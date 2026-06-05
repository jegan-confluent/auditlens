#!/usr/bin/env python3
"""AuditLens diagnostic tool — basic pattern analysis + optional AI deep-dive.

Run modes:
  python3 scripts/diagnose.py            # basic + AI if a key is present
  python3 scripts/diagnose.py --basic    # basic only, skip AI even with a key
  python3 scripts/diagnose.py --ai       # require AI; error out if no key
  python3 scripts/diagnose.py --fix      # basic + AI + auto-apply fix commands

The script intentionally uses only the stdlib (no requests, no anthropic SDK)
so it works on a fresh clone before .venv is populated. urllib + json are
sufficient for every supported LLM provider.

LLM provider detection order:
  1. ANTHROPIC_API_KEY  (or secrets/anthropic_api_key.txt) → Claude Haiku 4.5
  2. OPENAI_API_KEY     (or secrets/openai_api_key.txt)    → gpt-4o-mini
  3. OPENAI_API_BASE + OPENAI_API_KEY (Ollama, Azure, etc) → LLM_MODEL or
                                                              gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ───── locations ─────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.prod.yml"

# Container names map to compose service names — we use container names for
# `docker logs` (works on a stopped container) and compose service names for
# `docker compose ps` (reports State even when the container is gone).
CONTAINERS = [
    "auditlens-postgres",
    "auditlens-api",
    "auditlens-forwarder",
    "auditlens-frontend",
    "auditlens-caddy",
]

# Compose-service name -> container name. Used to cross-reference the two
# data sources (docker compose ps reports services; docker logs needs the
# container name).
SERVICE_TO_CONTAINER = {
    "postgres": "auditlens-postgres",
    "api": "auditlens-api",
    "auditlens-forwarder": "auditlens-forwarder",
    "frontend": "auditlens-frontend",
    "caddy": "auditlens-caddy",
}


# ───── ANSI ──────────────────────────────────────────────────────────────────
def _ansi(code: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str: return _ansi("32", t)
def yellow(t: str) -> str: return _ansi("33", t)
def red(t: str) -> str:    return _ansi("31", t)
def cyan(t: str) -> str:   return _ansi("36", t)
def dim(t: str) -> str:    return _ansi("2",  t)
def bold(t: str) -> str:   return _ansi("1",  t)


# ───── subprocess helpers ────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """Run a subprocess, NEVER raise. Returns (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as exc:  # noqa: BLE001 — defensive
        return 1, "", f"{exc.__class__.__name__}: {exc}"


# ───── STEP 1: collect context ───────────────────────────────────────────────
def collect_context() -> dict[str, Any]:
    """Gather every input the diagnosis layers consume.

    Robust: each sub-collection is independent — a missing docker daemon
    yields a structured "(unavailable)" string per field instead of
    aborting the whole report.
    """
    ctx: dict[str, Any] = {
        "compose_ps": [],
        "logs": {},
        "env": "(.env not found)",
        "arch": "unknown",
        "docker": {},
    }

    # docker compose ps --format json — emits one JSON object per line.
    rc, out, err = _run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json"],
        timeout=20,
    )
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ctx["compose_ps"].append(json.loads(line))
            except json.JSONDecodeError:
                pass
    else:
        ctx["compose_ps_error"] = (err or "docker compose unreachable").strip()

    # docker logs per container, last 100 lines. stderr is merged into the
    # log capture because most containers (postgres, kafka, etc.) write
    # operational logs to stderr.
    for name in CONTAINERS:
        rc, out, err = _run(
            ["docker", "logs", name, "--tail", "100"],
            timeout=15,
        )
        if rc == 0:
            ctx["logs"][name] = (out + (err or "")).strip()
        else:
            ctx["logs"][name] = f"(unavailable: {err.strip() or 'no logs'})"

    # .env masked: every value gets ***MASKED***, comments + blank lines pass
    # through. The MASKED form is what's safe to send to an external LLM.
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        try:
            masked: list[str] = []
            for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    masked.append(raw)
                    continue
                if "=" in stripped:
                    key, _, _value = stripped.partition("=")
                    key = key.strip()
                    masked.append(f"{key}=***MASKED***")
                else:
                    masked.append(raw)
            ctx["env"] = "\n".join(masked)
        except OSError as exc:
            ctx["env"] = f"(.env read failed: {exc})"

    # uname -m
    rc, out, _ = _run(["uname", "-m"], timeout=5)
    if rc == 0:
        ctx["arch"] = out.strip()

    # docker info — extract the fields the LLM (and the operator) actually use.
    rc, out, _ = _run(["docker", "info", "--format", "{{json .}}"], timeout=10)
    if rc == 0:
        try:
            data = json.loads(out)
            mem_total = data.get("MemTotal")
            ctx["docker"] = {
                "MemTotalGB": round(mem_total / 1024**3, 1) if isinstance(mem_total, (int, float)) else None,
                "NCPU": data.get("NCPU"),
                "ServerVersion": data.get("ServerVersion"),
                "OperatingSystem": data.get("OperatingSystem"),
                "Architecture": data.get("Architecture"),
            }
        except json.JSONDecodeError:
            ctx["docker"] = {"raw": out[:500]}
    else:
        ctx["docker"] = {"error": "docker info unreachable"}

    return ctx


# ───── STEP 2: basic pattern matching ────────────────────────────────────────
# Each entry: regex matched against a service's logs. service=None means any
# service. fix is a list of shell commands shown to the operator.
PATTERNS: list[dict[str, Any]] = [
    {
        "name": "postgres_hostname_dns",
        "regex": r"\[Errno -2\]\s*Name or service not known|could not translate host name",
        "service": None,
        "message": "Postgres hostname is wrong in DATABASE_URL (DNS lookup failed).",
        "fix": [
            "# Check DATABASE_URL in .env uses '@postgres:5432' (compose service name)",
            "grep ^DATABASE_URL .env",
            "make repair",
        ],
        "confidence": "high",
    },
    {
        "name": "persistence_backend_invalid",
        "regex": r'(?i)invalid_values.*PERSISTENCE_BACKEND|PERSISTENCE_BACKEND.*invalid',
        "service": "auditlens-forwarder",
        "message": "Forwarder rejects PERSISTENCE_BACKEND value (must be postgres).",
        "fix": [
            "# Set PERSISTENCE_BACKEND=postgres in .env",
            "sed -i.bak 's/^PERSISTENCE_BACKEND=.*/PERSISTENCE_BACKEND=postgres/' .env",
            "docker compose -f docker-compose.prod.yml restart auditlens-forwarder",
        ],
        "confidence": "high",
    },
    {
        "name": "alembic_migration_failure",
        "regex": r"(?i)alembic.*(?:ERROR|failed)|Migration failed|target database is not up to date|FAILED:.*alembic",
        "service": "auditlens-api",
        "message": "Alembic migration failed inside the api container.",
        "fix": [
            "make repair",
        ],
        "confidence": "high",
    },
    {
        "name": "postgres_auth_failure",
        "regex": r"(?i)password authentication failed|FATAL:\s*password authentication",
        "service": None,
        "message": "POSTGRES_PASSWORD mismatch between .env and secrets/postgres_password.txt.",
        "fix": [
            "make repair",
        ],
        "confidence": "high",
    },
    {
        "name": "postgres_connection_refused",
        "regex": r"(?i)Connection refused.*:\s*5432|could not connect to server.*postgres",
        "service": None,
        "message": "Postgres is not accepting connections.",
        "fix": [
            "docker compose -f docker-compose.prod.yml up -d postgres",
            "docker logs auditlens-postgres --tail=20",
        ],
        "confidence": "high",
    },
    {
        "name": "token_file_missing",
        "regex": r"(?i)FileNotFoundError.*auditlens-api-tokens|API_AUTH_TOKEN_FILE.*not.*found|Could not parse.*token file",
        "service": "auditlens-api",
        "message": "API auth token file missing inside the api container — likely the ./secrets:/run/secrets:ro mount is missing.",
        "fix": [
            "# Confirm the api service has the secrets bind mount:",
            "grep -A 12 'api:' docker-compose.prod.yml | grep 'secrets:/run/secrets'",
            "make repair",
        ],
        "confidence": "high",
    },
    {
        "name": "kafka_auth_failure",
        "regex": r"(?i)Authentication failed.*SASL|SaslAuthenticationException|invalid_credentials",
        "service": "auditlens-forwarder",
        "message": "Kafka SASL authentication failed — check AUDIT_API_KEY / DEST_API_KEY in .secrets.",
        "fix": [
            "# Inspect the masked creds — fix and rerun:",
            "grep -E 'AUDIT_API_KEY|DEST_API_KEY' .secrets",
            "docker compose -f docker-compose.prod.yml restart auditlens-forwarder",
        ],
        "confidence": "medium",
    },
    {
        "name": "kafka_bootstrap_dns",
        "regex": r"(?i)bootstrap.*Name or service not known|resolve.*kafka.*bootstrap",
        "service": "auditlens-forwarder",
        "message": "Kafka bootstrap endpoint DNS lookup failed — check AUDIT_BOOTSTRAP / DEST_BOOTSTRAP in .env.",
        "fix": [
            "grep -E 'AUDIT_BOOTSTRAP|DEST_BOOTSTRAP' .env",
        ],
        "confidence": "medium",
    },
    {
        "name": "frontend_build_failure",
        "regex": r"(?i)Error: Cannot find module|next: command not found|TypeError.*at Module",
        "service": "auditlens-frontend",
        "message": "Frontend Next.js build / runtime failure.",
        "fix": [
            "docker compose -f docker-compose.prod.yml build --no-cache frontend",
            "docker compose -f docker-compose.prod.yml up -d frontend",
        ],
        "confidence": "medium",
    },
    {
        "name": "caddy_upstream_missing",
        "regex": r"(?i)dial tcp.*: connect: connection refused.*(api|frontend|forwarder)|no such host.*(api|frontend|forwarder)",
        "service": "auditlens-caddy",
        "message": "Caddy can't reach an upstream — api/frontend/forwarder is down or out of network.",
        "fix": [
            "make status",
            "docker compose -f docker-compose.prod.yml ps",
        ],
        "confidence": "medium",
    },
    # ── Patterns added after the initial diagnose ship — each one encodes
    # a real failure mode we hit during 2026-05 iteration and fixed in
    # a follow-up commit. The signatures match the exact wording the
    # offending process logged so a stale install upgrading from the
    # broken state will surface the diagnosis without an LLM call.
    {
        "name": "alembic_autocommit_block_assert",
        # Migrations 0004 / 0005 / 0006 / 0016 / 0019 / 0025 used
        # CONCURRENTLY inside autocommit_block(); env.py runs them under
        # a single context.begin_transaction() and Alembic's
        # autocommit_block then asserts on the missing outer txn.
        "regex": r"(?i)autocommit_block|assert self\._transaction is not None|alembic.*assertionerror",
        "service": "auditlens-api",
        "message": "Alembic migration uses CONCURRENTLY inside autocommit_block — incompatible with env.py's transactional runner.",
        "fix": [
            "# The migrations have been patched on main; pull + redeploy:",
            "make repair",
        ],
        "confidence": "high",
    },
    {
        "name": "pydantic_forwardref_openapi",
        # The /openapi.json 500 we saw on the onboarding routes — Pydantic
        # 2.11 + FastAPI 0.115 + `from __future__ import annotations`
        # leaves the body model as an unresolved ForwardRef and the
        # OpenAPI schema builder explodes.
        "regex": r"(?i)PydanticUserError.*ForwardRef|TypeAdapter\[.*ForwardRef.*Query",
        "service": "auditlens-api",
        "message": "Pydantic schema generation failed — a route uses `from __future__ import annotations` and a BaseModel body whose ForwardRef can't be resolved.",
        "fix": [
            "# Drop `from __future__ import annotations` from the offending route file",
            "# OR rewrite the body parameter with Annotated[Model, Body()] AFTER removing the future import.",
            "docker compose -f docker-compose.prod.yml build api",
            "docker compose -f docker-compose.prod.yml up -d --force-recreate api",
        ],
        "confidence": "high",
    },
    {
        "name": "forwarder_ready_missing",
        # /ready was missing from the forwarder's BaseHTTPRequestHandler
        # until we added it as a /health alias. The dashboard probe at
        # /api/ready hits the API container (not this one), so the
        # forwarder 404 only shows up for operators curling :8003 by hand.
        "regex": r"(?i)8003/ready.*\b404\b|GET /ready.*\b404\b",
        "service": None,  # match in any log
        "message": "Forwarder /ready endpoint missing — older health_server.py only registered /health and /api/v1/health.",
        "fix": [
            "make repair",
            "# Verify after restart:",
            "curl -s -o /dev/null -w '%{http_code}\\n' http://localhost:8003/ready",
        ],
        "confidence": "medium",
    },
    {
        "name": "frontend_api_rewrite_missing",
        # The dashboard 404 cascade when the operator opens
        # http://localhost:3000/dashboard directly (skipping Caddy).
        # Without next.config.ts rewrites every /api/* fetch resolves
        # to Next.js itself and 404s.
        "regex": r"(?i)GET /api/.*\b404\b|/api/(events|summary|system|ready|patterns|filters).*\b404\b",
        "service": "auditlens-frontend",
        "message": "Frontend serving /api/* itself instead of proxying — next.config.ts is missing the /api/:path* rewrite.",
        "fix": [
            "# Confirm rewrites() is present in frontend/next.config.ts",
            "grep -A 4 'async rewrites' frontend/next.config.ts",
            "docker compose -f docker-compose.prod.yml build frontend",
            "docker compose -f docker-compose.prod.yml up -d --force-recreate frontend",
        ],
        "confidence": "medium",
    },
    {
        "name": "auth_config_token_file_missing",
        # AuthConfig.from_env() raises FileNotFoundError when
        # API_AUTH_TOKEN_FILE doesn't exist inside the api container —
        # most commonly because ./secrets:/run/secrets:ro wasn't mounted
        # on the api service. Different symptom from `token_file_missing`
        # above (that one fires at startup, this one mid-request).
        "regex": r"(?i)AuthConfig.*from_env|API_AUTH_TOKEN_FILE.*(not.found|missing)|FileNotFoundError.*run/secrets",
        "service": "auditlens-api",
        "message": "API auth gate cannot load tokens — secrets volume not mounted on api service or token file absent.",
        "fix": [
            "# Confirm the api service has the secrets bind mount:",
            "grep -A 12 '^  api:' docker-compose.prod.yml | grep 'secrets:/run/secrets'",
            "make repair",
        ],
        "confidence": "high",
    },
]


def basic_diagnose(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Run regex pattern matching over the collected logs + compose state.

    Returns a list of issue dicts: {name, service, message, fix:[..],
    confidence:str}. Duplicates per (name, service) are squashed.
    """
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    # 1. Container not running detection from compose_ps.
    states = {
        (p.get("Service") or "").strip(): (p.get("State") or "").strip()
        for p in ctx.get("compose_ps", [])
        if isinstance(p, dict)
    }
    for svc_key, container in SERVICE_TO_CONTAINER.items():
        state = states.get(svc_key, "")
        if not state:
            # Not in compose ps — never started OR removed.
            issues.append({
                "name": "service_missing",
                "service": container,
                "message": f"{container} is not in the compose project — never started.",
                "fix": [
                    f"docker compose -f docker-compose.prod.yml up -d {svc_key}",
                ],
                "confidence": "high",
            })
        elif state.lower() not in {"running", "healthy"}:
            issues.append({
                "name": "service_unhealthy",
                "service": container,
                "message": f"{container} is in state '{state}'.",
                "fix": [
                    f"docker logs {container} --tail=30",
                    f"docker compose -f docker-compose.prod.yml up -d {svc_key}",
                ],
                "confidence": "high",
            })

    # 2. Regex pattern scan over each service's logs.
    for container, logs in ctx.get("logs", {}).items():
        if not isinstance(logs, str) or logs.startswith("(unavailable"):
            continue
        for pat in PATTERNS:
            if pat["service"] is not None and pat["service"] != container:
                continue
            if not re.search(pat["regex"], logs):
                continue
            key = (pat["name"], container)
            if key in seen:
                continue
            seen.add(key)
            issues.append({
                "name": pat["name"],
                "service": container,
                "message": pat["message"],
                "fix": list(pat["fix"]),
                "confidence": pat["confidence"],
            })

    return issues


# ───── basic report rendering ────────────────────────────────────────────────
def render_basic_report(ctx: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    line = "─" * 60
    print()
    print(bold(cyan("┌" + line + "┐")))
    print(bold(cyan("│" + "  AuditLens Diagnostic Report".ljust(60) + "│")))
    print(bold(cyan("├" + line + "┤")))

    # Service status row block
    print(bold(cyan("│" + "  SERVICE STATUS".ljust(60) + "│")))
    states = {
        (p.get("Service") or "").strip(): (p.get("State") or "").strip()
        for p in ctx.get("compose_ps", [])
        if isinstance(p, dict)
    }
    for svc_key, container in SERVICE_TO_CONTAINER.items():
        state = states.get(svc_key, "missing")
        icon = "✅" if state.lower() in {"running", "healthy"} else "❌"
        colour = green if icon == "✅" else red
        row = f"  {icon} {container.ljust(22)} — {state}"
        # ljust 60 includes the leading "  " already
        print(bold(cyan("│")) + colour(row.ljust(60)) + bold(cyan("│")))

    print(bold(cyan("├" + line + "┤")))

    # Issues block
    print(bold(cyan("│" + "  DETECTED ISSUES".ljust(60) + "│")))
    if not issues:
        ok = "  ✅ All services appear healthy. No issues detected."
        print(bold(cyan("│")) + green(ok.ljust(60)) + bold(cyan("│")))
        hint = "     If you see problems, try: python3 scripts/diagnose.py --ai"
        print(bold(cyan("│")) + dim(hint.ljust(60)) + bold(cyan("│")))
    else:
        for idx, issue in enumerate(issues, 1):
            header = f"  ❌ [{issue['service'].replace('auditlens-', '')}] {issue['message']}"
            for wrapped in textwrap.wrap(header, width=58, subsequent_indent="     "):
                print(bold(cyan("│")) + red(wrapped.ljust(60)) + bold(cyan("│")))
            for cmd in issue["fix"]:
                fix_line = f"     Fix: {cmd}" if not cmd.lstrip().startswith("#") else f"     {cmd}"
                for wrapped in textwrap.wrap(fix_line, width=58, subsequent_indent="          "):
                    print(bold(cyan("│")) + dim(wrapped.ljust(60)) + bold(cyan("│")))
            if idx < len(issues):
                print(bold(cyan("│" + " " * 60 + "│")))

    print(bold(cyan("├" + line + "┤")))

    # Confidence row
    overall_confidence = "high" if issues and all(i["confidence"] == "high" for i in issues) else (
        "medium" if issues else "n/a"
    )
    conf_row = f"  CONFIDENCE: {overall_confidence}"
    print(bold(cyan("│")) + cyan(conf_row.ljust(60)) + bold(cyan("│")))

    print(bold(cyan("└" + line + "┘")))
    print()


# ───── STEP 3: AI provider discovery + call ──────────────────────────────────
def _read_secret_file(name: str) -> str:
    """Read a secrets/<name>.txt file if present. Returns trimmed contents."""
    path = REPO_ROOT / "secrets" / name
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _smart_default_model_for_openai_compatible(base_url: str) -> str:
    """Pick a sensible default model based on the OPENAI_API_BASE hostname.

    OpenAI-compatible APIs expose wildly different model rosters. Anthropic
    has one default; OpenAI has one default; but any third-party endpoint
    needs a model name that actually exists on THAT endpoint. The heuristic
    below covers the three most common cases (OpenRouter, Azure, Ollama).
    Operators on anything else should set LLM_MODEL explicitly — the
    override path always wins.
    """
    base_lower = base_url.lower()
    if "openrouter.ai" in base_lower:
        # Cheapest reliable model on OpenRouter (~$0.075/M input tokens).
        # `google/gemini-flash-1.5` was previously listed but OpenRouter
        # deprecated the slug and now 404s — the supported successor is
        # `google/gemini-2.0-flash-001`, which retains the free-tier
        # credit window for new accounts.
        return "google/gemini-2.0-flash-001"
    if "localhost" in base_lower or "127.0.0.1" in base_lower or "ollama" in base_lower:
        # Ollama's default tag once `ollama pull llama3` has run.
        return "llama3"
    if "azure.com" in base_lower:
        # Azure OpenAI uses deployment-name routing; the operator must
        # provide their own deployment name, but gpt-4o-mini is the
        # most common name they'll have created.
        return "gpt-4o-mini"
    return "gpt-4o-mini"


def detect_llm_provider() -> dict[str, str] | None:
    """Return the first provider config found (env vars > secrets/ files).

    Provider dict keys:
      provider       — "anthropic" | "openai" | "gemini" (the protocol)
      display_name   — human-readable label for the welcome line
      flavor         — sub-variant of the protocol (vanilla | openrouter |
                       ollama | azure | custom); used for error formatting
      api_key, base_url, model

    LLM_MODEL env var ALWAYS overrides the default model regardless of
    provider, so operators can pin a specific model without changing
    provider-selection logic.
    """
    explicit_model = os.environ.get("LLM_MODEL") or ""

    # 1. Anthropic — preferred when a key is present. Claude Haiku 4.5
    #    is the cheapest first-party Anthropic model that handles this
    #    diagnostic prompt cleanly.
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or _read_secret_file("anthropic_api_key.txt")
    if anthropic_key:
        return {
            "provider": "anthropic",
            "display_name": "Anthropic Claude",
            "flavor": "anthropic",
            "api_key": anthropic_key,
            "base_url": "https://api.anthropic.com",
            "model": explicit_model or "claude-haiku-4-5-20251001",
        }

    # 2. OpenAI-compatible (any vendor on the chat/completions wire
    #    protocol). The OPENAI_API_BASE override is what distinguishes
    #    OpenRouter, Ollama, Azure, vLLM, LiteLLM, etc.
    openai_key = os.environ.get("OPENAI_API_KEY") or _read_secret_file("openai_api_key.txt")
    openai_base_raw = os.environ.get("OPENAI_API_BASE", "").strip()
    if openai_key and openai_base_raw:
        base_url = openai_base_raw.rstrip("/")
        base_lower = base_url.lower()
        if "openrouter.ai" in base_lower:
            flavor = "openrouter"
            display_name = "OpenRouter"
        elif "localhost" in base_lower or "127.0.0.1" in base_lower or "ollama" in base_lower:
            flavor = "ollama"
            display_name = "Ollama (local)"
        elif "azure.com" in base_lower:
            flavor = "azure"
            display_name = "Azure OpenAI"
        else:
            flavor = "custom"
            display_name = f"OpenAI-compatible ({base_url})"
        return {
            "provider": "openai",
            "display_name": display_name,
            "flavor": flavor,
            "api_key": openai_key,
            "base_url": base_url,
            "model": explicit_model or _smart_default_model_for_openai_compatible(base_url),
        }

    # 3. Vanilla OpenAI — no custom base, plain api.openai.com.
    if openai_key:
        return {
            "provider": "openai",
            "display_name": "OpenAI",
            "flavor": "openai",
            "api_key": openai_key,
            "base_url": "https://api.openai.com",
            "model": explicit_model or "gpt-4o-mini",
        }

    # 4. Google Gemini — generateContent endpoint, free tier available.
    gemini_key = os.environ.get("GEMINI_API_KEY") or _read_secret_file("gemini_api_key.txt")
    if gemini_key:
        return {
            "provider": "gemini",
            "display_name": "Google Gemini",
            "flavor": "gemini",
            "api_key": gemini_key,
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": explicit_model or "gemini-1.5-flash",
        }
    return None


SYSTEM_PROMPT = (
    "You are an expert AuditLens deployment engineer.\n"
    "AuditLens runs on Docker Compose with: postgres (database),\n"
    "api (FastAPI backend), forwarder (Kafka consumer),\n"
    "frontend (Next.js), caddy (reverse proxy).\n"
    "\n"
    "You will be given real logs and service status from a live deployment.\n"
    "YOUR RULES:\n"
    "1. ONLY diagnose problems you can see explicit evidence for in the logs.\n"
    "2. For every claim in DIAGNOSIS and ROOT CAUSE, you MUST quote the\n"
    "   exact log line that proves it (e.g. 'as shown by: <log line>').\n"
    "3. If logs show no errors and all services are running, you MUST respond:\n"
    "   DIAGNOSIS: All services are healthy — no issues detected.\n"
    "   ROOT CAUSE: N/A\n"
    "   FIX: No action required.\n"
    "   PREVENTION: N/A\n"
    "4. NEVER invent problems not present in the logs.\n"
    "5. NEVER suggest generic fixes like 'docker compose down/up'\n"
    "   unless you can cite a specific error that requires it.\n"
    "\n"
    "Respond in this exact format:\n"
    "DIAGNOSIS: <one sentence, cite log evidence>\n"
    "ROOT CAUSE: <one sentence, cite log evidence>\n"
    "FIX:\n"
    "<exact bash commands, one per line — or 'No action required'>\n"
    "PREVENTION: <one sentence>\n"
    "EVIDENCE:\n"
    "<paste the 1-3 specific log lines that led to your diagnosis>"
)


def _truncate(s: str, n: int = 4000) -> str:
    """Keep prompt small — we send last N chars of each log block to the LLM."""
    if len(s) <= n:
        return s
    return "…(truncated)…\n" + s[-n:]


def build_ai_user_message(ctx: dict[str, Any], basic_issues: list[dict[str, Any]]) -> str:
    """Compact, structured context for the LLM."""
    parts: list[str] = []
    parts.append(f"Architecture: {ctx.get('arch', 'unknown')}")
    parts.append(f"Docker: {json.dumps(ctx.get('docker', {}))}")
    if ctx.get("compose_ps"):
        ps_brief = [
            {"Service": p.get("Service"), "State": p.get("State"), "Health": p.get("Health"), "Status": p.get("Status")}
            for p in ctx["compose_ps"] if isinstance(p, dict)
        ]
        parts.append(f"compose ps: {json.dumps(ps_brief)}")
    else:
        parts.append(f"compose ps error: {ctx.get('compose_ps_error', 'unknown')}")
    if basic_issues:
        parts.append("Basic pattern matches: " + json.dumps([
            {"name": i["name"], "service": i["service"], "message": i["message"]}
            for i in basic_issues
        ]))
    parts.append(".env (masked):\n" + _truncate(str(ctx.get("env", "")), 2000))
    for name, log in ctx.get("logs", {}).items():
        parts.append(f"=== {name} logs (last 100 lines) ===\n{_truncate(str(log), 3000)}")
    return "\n\n".join(parts)


def call_anthropic(cfg: dict[str, str], user_message: str) -> str:
    """POST /v1/messages. Raises on non-2xx for the caller to catch."""
    payload = {
        "model": cfg["model"],
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }
    req = Request(
        f"{cfg['base_url']}/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": cfg["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    # Anthropic returns { content: [{ type: "text", text: "..." }, ...] }
    text_blocks = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks).strip()


def call_openai(cfg: dict[str, str], user_message: str) -> str:
    """POST /chat/completions on the configured base. Covers OpenAI,
    OpenRouter, Ollama, Azure OpenAI, vLLM, LiteLLM — any endpoint that
    speaks the OpenAI chat-completions wire protocol.

    The base URL convention is the part before "/chat/completions".
    OpenAI uses "/v1" as the version segment; OpenRouter uses "/api/v1";
    Azure uses "/openai/deployments/<name>". Operators bake the right
    suffix into OPENAI_API_BASE.
    """
    payload = {
        "model": cfg["model"],
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
    }
    base = cfg["base_url"].rstrip("/")
    # Vanilla openai.com needs the /v1 segment that OpenRouter / Ollama /
    # Azure / LiteLLM already include in their OPENAI_API_BASE.
    if base.endswith("api.openai.com"):
        url = f"{base}/v1/chat/completions"
    else:
        url = f"{base}/chat/completions"
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"].strip()


def call_gemini(cfg: dict[str, str], user_message: str) -> str:
    """POST :generateContent on Google Generative Language v1beta.

    Gemini does NOT speak the OpenAI chat-completions protocol. The auth
    is a `?key=…` query string (not a header), and the body uses
    `system_instruction` + `contents`.
    """
    url = (
        f"{cfg['base_url'].rstrip('/')}/models/{cfg['model']}:generateContent"
        f"?key={cfg['api_key']}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"maxOutputTokens": 1024},
    }
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    # Gemini returns { candidates: [{ content: { parts: [{ text: "..." }] } }] }
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()


def _provider_error_hint(cfg: dict[str, str], status_code: int) -> str:
    """Map (provider, status) → an actionable one-liner for the operator.

    We don't try to enumerate every error — just the half-dozen that
    show up in real life. Anything we don't recognise falls through to a
    generic "request failed" and the response body is printed below it
    by the caller.
    """
    flavor = cfg.get("flavor", "")
    provider = cfg.get("provider", "")
    if status_code == 401:
        if provider == "anthropic":
            return "Invalid ANTHROPIC_API_KEY"
        if provider == "gemini":
            return "Invalid GEMINI_API_KEY"
        if flavor == "openrouter":
            return "Invalid OpenRouter API key — generate one at openrouter.ai/keys"
        return "Invalid OPENAI_API_KEY"
    if status_code == 402:
        if flavor == "openrouter":
            return "OpenRouter credits exhausted — add credits at openrouter.ai/credits"
        return "Payment required — check the provider billing page"
    if status_code == 403:
        return f"{cfg.get('display_name', 'Provider')} refused the request (403) — check API-key scope / org access"
    if status_code == 404 and flavor == "ollama":
        return f"Model '{cfg.get('model')}' not pulled — run: ollama pull {cfg.get('model')}"
    if status_code == 429:
        return f"{cfg.get('display_name', 'Provider')} rate-limited — try again in a minute"
    if status_code >= 500:
        return f"{cfg.get('display_name', 'Provider')} upstream error ({status_code}) — usually transient"
    return f"{cfg.get('display_name', 'Provider')} returned HTTP {status_code}"


def run_ai(cfg: dict[str, str], ctx: dict[str, Any], basic_issues: list[dict[str, Any]]) -> str | None:
    """Send context to the LLM, return its reply or None on failure.

    Failures (HTTP, transport, timeout, malformed JSON) are caught,
    surfaced with a provider-specific hint, and return None — the
    caller falls back to the basic report and exits 0. Never crashes.
    """
    msg = build_ai_user_message(ctx, basic_issues)
    print(cyan(f"ℹ  AI diagnosis via {cfg.get('display_name', cfg['provider'])} ({cfg['model']})…"))
    try:
        if cfg["provider"] == "anthropic":
            return call_anthropic(cfg, msg)
        if cfg["provider"] == "gemini":
            return call_gemini(cfg, msg)
        return call_openai(cfg, msg)
    except HTTPError as exc:
        hint = _provider_error_hint(cfg, exc.code)
        try:
            error_body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            error_body = ""
        print(red(f"   AI request failed: {hint}"))
        if error_body:
            print(dim(f"   {error_body}"))
        return None
    except URLError as exc:
        # Wraps socket.timeout / ConnectionRefused / DNS errors.
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            print(red(
                f"   LLM API timed out — falling back to basic diagnosis"
            ))
        else:
            display = cfg.get("display_name", cfg.get("provider", "provider"))
            print(red(f"   {display} unreachable: {reason}"))
        return None
    except (TimeoutError, socket.timeout):
        # Some Python builds raise TimeoutError directly instead of via URLError.
        print(red("   LLM API timed out — falling back to basic diagnosis"))
        return None
    except (json.JSONDecodeError, KeyError) as exc:
        print(red(f"   AI returned malformed response ({exc.__class__.__name__})"))
        return None
    except Exception as exc:  # noqa: BLE001 — never crash on AI failure
        print(red(f"   AI request error: {exc.__class__.__name__}: {exc}"))
        return None


# ───── AI report rendering + fix extraction ──────────────────────────────────
def parse_fix_commands(ai_text: str) -> list[str]:
    """Pull the FIX: block out of the LLM's response.

    The expected format is:
      FIX:
      <command>
      <command>
      PREVENTION: …

    Lines beginning with #, ```, or text up to the next ALL_CAPS_LABEL: are
    ignored / terminate the block. Empty lines are skipped.
    """
    lines = ai_text.splitlines()
    out: list[str] = []
    in_fix = False
    label_re = re.compile(r"^[A-Z][A-Z_ ]+:")
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("FIX:"):
            in_fix = True
            continue
        if not in_fix:
            continue
        if label_re.match(line):
            # Hit the next section (PREVENTION, etc.) — stop.
            break
        if line.startswith("```"):
            continue
        if line.startswith("#"):
            continue
        out.append(line)
    return out


def render_ai_report(ai_text: str) -> None:
    print()
    print(bold(cyan("┌" + "─" * 60 + "┐")))
    print(bold(cyan("│  AI Deep Diagnosis".ljust(61)) + "│"))
    print(bold(cyan("├" + "─" * 60 + "┤")))
    for raw in ai_text.splitlines():
        for wrapped in textwrap.wrap(raw, width=58) or [""]:
            content = ("  " + wrapped).ljust(60)
            print(bold(cyan("│")) + content + bold(cyan("│")))
    print(bold(cyan("└" + "─" * 60 + "┘")))
    print()


def apply_fix(commands: list[str], *, force: bool) -> int:
    """Run each command sequentially. Returns # failed."""
    if not commands:
        print(yellow("  (no fix commands detected in AI response)"))
        return 0
    if not force:
        print()
        print(cyan("  Proposed fix commands:"))
        for cmd in commands:
            print(dim(f"    $ {cmd}"))
        try:
            ans = input("  Auto-apply? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in {"y", "yes"}:
            print(cyan("  Skipped. Copy the commands above to apply manually."))
            return 0
    failures = 0
    for cmd in commands:
        print()
        print(cyan(f"  $ {cmd}"))
        rc, out, err = _run(["bash", "-lc", cmd], timeout=300)
        out_text = (out + err).strip()
        if out_text:
            for line in out_text.splitlines()[:20]:
                print(dim(f"    {line}"))
        if rc == 0:
            print(green(f"  ✅ exit 0"))
        else:
            print(red(f"  ❌ exit {rc}"))
            failures += 1
    return failures


# ───── ingest health (60s sliding sample) ───────────────────────────────────
FORWARDER_HEALTH_URL_DEFAULT = "http://localhost:8003/health"
INGEST_SAMPLE_SECONDS = 60


def _fetch_forwarder_health(url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    """Single /health probe. Returns the parsed JSON or None on any failure.

    Never raises — caller distinguishes "unreachable" from "live" purely by
    the None / dict return. JSON parse failures are also collapsed to None
    so a partial response cannot break the rate calculation downstream.
    """
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError, socket.timeout):
        return None


def _read_env_value(name: str, default: str = "") -> str:
    """Read a single value from REPO_ROOT/.env without sourcing it.

    Returns `default` when .env is absent or the key is missing. Strips
    surrounding quotes so `KEY="value"` and `KEY=value` both work.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return default
    try:
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


def _ingest_status_icon(level: str) -> str:
    return {"ok": green("✓"), "warn": yellow("⚠"), "bad": red("❌")}.get(level, dim("—"))


def _classify_bottleneck(
    rate: float,
    lag_delta: int,
    iam_hit_rate: float | None,
    db_write_p95_ms: float | None,
    ceiling_msgs_per_sec: float | None,
    iam_enrichment_enabled: bool,
) -> tuple[str, str]:
    """Decide the single most-actionable bottleneck label + recommendation.

    Order matters — first match wins. Positive case first so a healthy
    forwarder isn't mis-labelled by a coincidental config ceiling.
    """
    healthy_threshold = 200.0
    if rate >= healthy_threshold and lag_delta <= 0:
        return (
            "HEALTHY",
            "Ingest is healthy — no action needed.",
        )

    # Forwarder keeping up but topic producing faster than ingest.
    if lag_delta > 0 and rate > 100.0:
        return (
            "KAFKA",
            "Forwarder healthy but topic publishing faster than ingest. "
            "Consider a second forwarder instance.",
        )

    slow = rate < 50.0
    if not slow:
        return ("UNKNOWN", "Share output of: docker compose logs auditlens-forwarder --tail=50")

    # Slow AND configured ceiling is the obvious culprit. Check this first
    # because it's the cheapest fix and rules out config before we point
    # the operator at IAM or DB.
    if ceiling_msgs_per_sec is not None and ceiling_msgs_per_sec < 100.0:
        return (
            "CONFIG",
            "Increase KAFKA_CONSUME_BATCH_SIZE=500 and "
            "CONSUMER_BATCH_SLEEP_SECONDS=0.05 in .env for catch-up mode.",
        )

    # IAM rule: rate < 50 AND (iam_hit_rate < 50% OR iam field missing).
    # Field is currently always missing (no /health instrumentation), so
    # this fires whenever IAM is enabled and we're slow.
    iam_field_missing = iam_hit_rate is None
    iam_below_threshold = iam_hit_rate is not None and iam_hit_rate < 50.0
    if iam_enrichment_enabled and (iam_below_threshold or iam_field_missing):
        return (
            "IAM_ENRICHMENT",
            "Add IAM_ENRICHMENT_ENABLED=false to .env and restart forwarder "
            "for catch-up. Re-enable once lag clears.",
        )

    if db_write_p95_ms is not None and db_write_p95_ms > 500.0:
        return (
            "DB_WRITE",
            "Check Postgres I/O: docker compose exec postgres psql "
            "-U auditlens -c 'SELECT * FROM pg_stat_bgwriter;'",
        )

    return ("UNKNOWN", "Share output of: docker compose logs auditlens-forwarder --tail=50")


def diagnose_ingest(url: str = FORWARDER_HEALTH_URL_DEFAULT) -> int:
    """Sample the forwarder /health endpoint twice 60s apart and classify
    the bottleneck from the delta. Returns process exit code.

    Returns 0 on a successful sample (regardless of whether the diagnosis
    flagged a problem) and 2 when the forwarder is unreachable — the
    operator can't get a diagnosis if the data plane is offline.
    """
    print()
    print(cyan("→ Forwarder ingest diagnostic"))
    print(dim(f"   Probing {url}"))
    first = _fetch_forwarder_health(url)
    if first is None:
        print(red("  ❌ Forwarder not reachable — is it running? Try: docker compose ps"))
        return 2

    # 60-second sample window with a tick every 5s so the operator can
    # confirm the script is alive (no progress feedback during a silent
    # 60s wait reads as "hung").
    print(dim(f"   Sampling forwarder for {INGEST_SAMPLE_SECONDS}s..."))
    tick = 5
    elapsed = 0
    while elapsed < INGEST_SAMPLE_SECONDS:
        time.sleep(min(tick, INGEST_SAMPLE_SECONDS - elapsed))
        elapsed += tick
        if elapsed <= INGEST_SAMPLE_SECONDS:
            print(dim(f"   …{elapsed}/{INGEST_SAMPLE_SECONDS}s"))

    second = _fetch_forwarder_health(url)
    if second is None:
        print(red("  ❌ Forwarder went away mid-sample — likely crashed during the 60s window."))
        return 2

    # Extract counters from both samples. Default to 0 so a missing field
    # (older forwarder build) computes as 0 instead of raising.
    # processed_total counts signal events that the processor thread
    # routed into audit_events; noise_short_circuited_total counts bulk
    # noise events the consumer thread routed straight to audit_events_noise
    # without ever entering the processor. Both lanes consume Kafka
    # offsets; total = signal + noise is the real ingest rate.
    processed_a = int(first.get("processed_total") or 0)
    processed_b = int(second.get("processed_total") or 0)
    noise_a = int(first.get("noise_short_circuited_total") or 0)
    noise_b = int(second.get("noise_short_circuited_total") or 0)
    lag_a = int(first.get("consumer_lag") or 0)
    lag_b = int(second.get("consumer_lag") or 0)

    signal_rate = max(0.0, (processed_b - processed_a) / float(INGEST_SAMPLE_SECONDS))
    noise_rate = max(0.0, (noise_b - noise_a) / float(INGEST_SAMPLE_SECONDS))
    total_rate = signal_rate + noise_rate
    lag_delta = lag_b - lag_a

    queues_b = second.get("queues") or {}
    bulk_q = int(queues_b.get("bulk") or 0)
    record_q = int(second.get("record_queue_depth") or 0)
    bulk_q_cap = 50000
    record_q_cap = 10000

    # 60s rolling-window stats added by src/product/{actor_enrichment,db_writer}.py.
    # Both forwarder builds since 2026-06 emit these; older builds return
    # None (or omit the field entirely) and the classifier degrades to
    # "field missing" handling — same behaviour as the rate-only path.
    iam_hit_rate_val = second.get("iam_cache_hit_rate")
    iam_hit_rate = (
        float(iam_hit_rate_val)
        if isinstance(iam_hit_rate_val, (int, float))
        else None
    )
    db_p95_val = second.get("db_write_p95_ms")
    db_p95 = (
        float(db_p95_val)
        if isinstance(db_p95_val, (int, float))
        else None
    )

    # Compute the .env-derived theoretical ceiling.
    try:
        batch_size = int(_read_env_value("KAFKA_CONSUME_BATCH_SIZE", "100"))
    except ValueError:
        batch_size = 100
    try:
        sleep_s = float(_read_env_value("CONSUMER_BATCH_SLEEP_SECONDS", "0.25"))
    except ValueError:
        sleep_s = 0.25
    ceiling = batch_size / sleep_s if sleep_s > 0 else None

    iam_env = _read_env_value("IAM_ENRICHMENT_ENABLED", "true").strip().lower()
    iam_enabled = iam_env != "false"

    # ── Per-row severity classification ─────────────────────────────────
    # Thresholds operate on TOTAL rate — signal alone underestimates real
    # ingest by ~5x (noise lane carries the bulk of audit volume). Signal
    # gets a looser threshold so a normal "low signal / high noise" steady
    # state doesn't flag as bad.
    total_level = "ok" if total_rate >= 200 else ("warn" if total_rate >= 50 else "bad")
    signal_level = "ok" if signal_rate >= 5 else ("warn" if signal_rate >= 1 else "bad")
    noise_level = "ok"  # Always green — noise is informational, never a fault signal.
    if lag_delta <= 0:
        lag_level = "ok"
    elif lag_delta < 1000:
        lag_level = "warn"
    else:
        lag_level = "bad"
    db_level = "—"
    if db_p95 is not None:
        db_level = "ok" if db_p95 <= 200 else ("warn" if db_p95 <= 500 else "bad")
    bulk_pct = bulk_q / bulk_q_cap if bulk_q_cap else 0
    bulk_level = "ok" if bulk_pct < 0.5 else ("warn" if bulk_pct < 0.9 else "bad")
    record_pct = record_q / record_q_cap if record_q_cap else 0
    record_level = "ok" if record_pct < 0.5 else ("warn" if record_pct < 0.9 else "bad")
    iam_level = "—"
    if iam_hit_rate is not None:
        iam_level = "ok" if iam_hit_rate >= 80 else ("warn" if iam_hit_rate >= 50 else "bad")

    # Bottleneck classifier consumes TOTAL rate — signal alone misleadingly
    # flags a healthy "low signal / high noise" stack as IAM-bound.
    label, action = _classify_bottleneck(
        rate=total_rate,
        lag_delta=lag_delta,
        iam_hit_rate=iam_hit_rate,
        db_write_p95_ms=db_p95,
        ceiling_msgs_per_sec=ceiling,
        iam_enrichment_enabled=iam_enabled,
    )

    # ── Render ──────────────────────────────────────────────────────────
    def _row(label_text: str, value_text: str, level: str) -> None:
        icon = _ingest_status_icon(level) if level != "—" else dim("—")
        print(f"  {label_text:<26} {value_text:<14} [{icon}]")

    def _fmt_signed(n: int) -> str:
        sign = "+" if n > 0 else ("" if n == 0 else "")
        return f"{sign}{n:,}"

    print()
    print(cyan("Forwarder ingest health (60s sample)"))
    print(cyan("─" * 60))
    _row("Signal rate (60s):", f"{signal_rate:.1f} msg/s", signal_level)
    _row("Noise rate (60s):", f"{noise_rate:.1f} msg/s", noise_level)
    _row("Total rate (60s):", f"{total_rate:.1f} msg/s", total_level)
    _row("Lag trend (Δ60s):", f"{_fmt_signed(lag_delta)} msgs", lag_level)
    _row("DB write p95:", "—" if db_p95 is None else f"{db_p95:.0f} ms", db_level)
    _row("bulk_queue depth:", f"{bulk_q} / {bulk_q_cap}", bulk_level)
    _row("record_queue depth:", f"{record_q} / {record_q_cap}", record_level)
    _row(
        "IAM cache hit rate:",
        "—" if iam_hit_rate is None else f"{iam_hit_rate:.0f}%",
        iam_level,
    )
    print(cyan("─" * 60))

    bottleneck_colour = {
        "HEALTHY": green,
        "KAFKA": yellow,
        "CONFIG": yellow,
        "IAM_ENRICHMENT": red,
        "DB_WRITE": red,
        "UNKNOWN": dim,
    }.get(label, dim)
    print(f"  Active bottleneck:         {bottleneck_colour(label)}")
    print(f"  Recommended action:        {action}")
    print()

    # Surface the inputs the classifier used so an operator who disagrees
    # can audit the decision. Dim so they don't compete with the main row.
    print(dim(
        f"   inputs: total_rate={total_rate:.1f} signal_rate={signal_rate:.1f} "
        f"noise_rate={noise_rate:.1f} lag_delta={lag_delta} "
        f"ceiling={'n/a' if ceiling is None else f'{ceiling:.0f}'} "
        f"iam_enabled={iam_enabled} batch_size={batch_size} "
        f"sleep_s={sleep_s}"
    ))
    print()
    return 0


# ───── main ──────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="AuditLens diagnostic — basic + optional AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "LLM keys: ANTHROPIC_API_KEY, OPENAI_API_KEY (+ optional "
            "OPENAI_API_BASE for OpenRouter/Ollama/Azure), GEMINI_API_KEY. "
            "Set LLM_MODEL to pin a specific model regardless of provider. "
            "Keys can also live in secrets/<provider>_api_key.txt."
        ),
    )
    parser.add_argument("--basic", action="store_true", help="basic only, skip AI even with a key")
    parser.add_argument("--ai", action="store_true", help="force AI; error if no key")
    parser.add_argument("--fix", action="store_true", help="basic + AI + auto-apply commands without confirmation")
    parser.add_argument(
        "--ingest-only",
        action="store_true",
        help="run only the 60-second ingest sample (rate + lag trend + bottleneck) and exit",
    )
    args = parser.parse_args()

    if args.ingest_only:
        return diagnose_ingest()

    if args.basic and args.ai:
        print(red("--basic and --ai are mutually exclusive."))
        return 2

    print(cyan("→ Collecting diagnostic context…"))
    ctx = collect_context()
    issues = basic_diagnose(ctx)
    render_basic_report(ctx, issues)

    if args.basic:
        return 0

    # Early exit: healthy stack + no explicit AI request. Saves the API
    # round-trip AND avoids the class of hallucination where an LLM
    # given a clean log will invent a problem to look useful. Operators
    # who explicitly want a deep read on a quiet stack still get it via
    # `make diagnose-ai` (which passes --ai → ai_explicit=True below).
    ai_explicit = args.ai or args.fix
    if not issues and not ai_explicit:
        print(cyan("ℹ  All services healthy — skipping AI diagnosis (no issues to analyze)."))
        print(dim("     Run 'make diagnose-ai' to force AI analysis."))
        return 0

    provider = detect_llm_provider()
    if not provider:
        # Shared help block so --ai and the default (no flag) path show
        # the same actionable list. The default path treats no-key as
        # "you didn't ask for AI" and exits 0; --ai/--fix treats it as
        # "you explicitly asked, here's why we can't deliver" and exits 2.
        header = "AI mode requested but no LLM API key found." if (args.ai or args.fix) \
                 else "No LLM key found — skipping AI diagnosis."
        print(red(f"  ❌ {header}") if (args.ai or args.fix) else dim(f"  {header}"))
        print(dim("     To enable AI diagnosis, set one of:"))
        print(dim("       ANTHROPIC_API_KEY  → Anthropic Claude (recommended)"))
        print(dim("       OPENAI_API_KEY     → OpenAI GPT"))
        print(dim("       OPENAI_API_KEY + OPENAI_API_BASE=https://openrouter.ai/api/v1"))
        print(dim("                          → OpenRouter (100+ models, free tier available)"))
        print(dim("       GEMINI_API_KEY     → Google Gemini (free tier available)"))
        print(dim("       OPENAI_API_KEY + OPENAI_API_BASE=http://localhost:11434/v1"))
        print(dim("                          → Ollama (fully local, free)"))
        print(dim("     Cheapest cloud option: OpenRouter google/gemini-2.0-flash-001 at ~$0.00007/diagnosis"))
        print(dim("     Keys can also live in secrets/<provider>_api_key.txt files."))
        return 2 if (args.ai or args.fix) else 0

    ai_text = run_ai(provider, ctx, issues)
    if not ai_text:
        print(yellow("  AI diagnosis unavailable — falling back to basic report above."))
        return 0
    render_ai_report(ai_text)

    if args.fix:
        commands = parse_fix_commands(ai_text)
        failures = apply_fix(commands, force=True)
        return 1 if failures else 0

    # Default: prompt to auto-apply if commands exist.
    commands = parse_fix_commands(ai_text)
    if commands:
        apply_fix(commands, force=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
