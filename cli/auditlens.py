#!/usr/bin/env python3
"""AuditLens CLI — single-file, no codebase import.

Speaks to a running AuditLens API (FastAPI behind Caddy at /api/*) over
HTTPS or HTTP. Config lives in ~/.auditlens.conf and/or env vars.
"""
from __future__ import annotations

import configparser
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import click
import httpx

CONFIG_PATH = Path.home() / ".auditlens.conf"
DEFAULT_URL = "http://localhost"
DEFAULT_PG_USER = "auditlens"
DEFAULT_PG_DB = "auditlens"
DEFAULT_COMPOSE = "~/AuditLens/docker-compose.prod.yml"

SIGNAL_CHOICES = ["action_required", "attention", "informational", "noise"]
WINDOW_CHOICES = ["5m", "15m", "30m", "1h", "2h", "4h", "12h", "24h", "7d", "30d"]


# ──────────── config / client helpers ────────────

def load_config() -> dict[str, str]:
    cfg: dict[str, str] = {
        "url": os.environ.get("AUDITLENS_URL", DEFAULT_URL),
        "pg_host": os.environ.get("AUDITLENS_PG_HOST", ""),
        "pg_user": os.environ.get("AUDITLENS_PG_USER", DEFAULT_PG_USER),
        "pg_db": os.environ.get("AUDITLENS_PG_DB", DEFAULT_PG_DB),
        "token": os.environ.get("AUDITLENS_TOKEN", ""),
        "compose_file": DEFAULT_COMPOSE,
    }
    if CONFIG_PATH.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_PATH)
        if parser.has_section("auditlens"):
            for k in cfg:
                if k in parser["auditlens"]:
                    cfg[k] = parser["auditlens"][k]
    return cfg


def save_config(updates: dict[str, str]) -> None:
    parser = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        parser.read(CONFIG_PATH)
    if not parser.has_section("auditlens"):
        parser.add_section("auditlens")
    for k, v in updates.items():
        if v is not None:
            parser.set("auditlens", k, str(v))
    with open(CONFIG_PATH, "w") as fh:
        parser.write(fh)
    os.chmod(CONFIG_PATH, 0o600)


def make_client(cfg: dict[str, str]) -> httpx.Client:
    headers = {}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    base = cfg["url"].rstrip("/")
    return httpx.Client(base_url=f"{base}/api", headers=headers, timeout=30.0)


# ──────────── formatting helpers ────────────

def encode_window(value: str) -> str:
    """Translate Nd → Nh for backend time_window regex ([1-9][0-9]*[mh]).

    The backend rejects 'Nd'; we do the same conversion the frontend does.
    """
    if not value:
        return value
    if value.endswith("d"):
        try:
            return f"{int(value[:-1]) * 24}h"
        except ValueError:
            pass
    return value


def fmt_time_local(ts: str | None) -> str:
    """Parse ISO timestamp, return local-tz 'Jun 03 11:44'."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%b %d %H:%M")
    except Exception:
        return ts


def style_signal(signal: str | None) -> str:
    if not signal:
        return "—"
    if signal == "action_required":
        return click.style(signal, fg="red")
    if signal == "attention":
        return click.style(signal, fg="yellow")
    if signal == "informational":
        return click.style(signal, fg="green")
    if signal == "noise":
        return click.style(signal, dim=True)
    return signal


def truncate(s: Any, width: int) -> str:
    if s is None:
        return ""
    s = str(s)
    if len(s) > width:
        return s[: width - 1] + "…"
    return s


def render_table(rows: list[dict[str, str]], columns: list[tuple[str, str, int]]) -> None:
    """Render a fixed-width table. columns: [(key, label, width), ...]."""
    header = "  ".join(label.ljust(width) for _, label, width in columns)
    click.echo(click.style(header, bold=True))
    click.echo("  ".join("-" * width for _, _, width in columns))
    for row in rows:
        cells = []
        for key, _, width in columns:
            val = row.get(key, "")
            # ANSI colour codes inflate len() — measure stripped width.
            stripped = click.unstyle(val) if isinstance(val, str) else str(val)
            display = val if isinstance(val, str) else str(val)
            pad = " " * max(0, width - len(stripped))
            cells.append(display + pad)
        click.echo("  ".join(cells))


def http_error_exit(exc: Exception) -> NoReturn:
    click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
    sys.exit(1)


# ──────────── CLI ────────────

@click.group()
def cli() -> None:
    """AuditLens command-line interface."""


# ----- config -----

@cli.group()
def config() -> None:
    """Manage CLI configuration (~/.auditlens.conf)."""


@config.command("set")
@click.option("--url", help="Base URL of the AuditLens deployment (e.g. http://98.95.144.160).")
@click.option("--pg-host", help="Postgres host for direct queries (optional).")
@click.option("--pg-user", help="Postgres user (default: auditlens).")
@click.option("--pg-db", help="Postgres database (default: auditlens).")
@click.option("--token", help="Bearer token if API_AUTH_ENABLED=true.")
@click.option("--compose-file", help="Path to docker-compose.prod.yml on the deploy host.")
def config_set(
    url: str | None,
    pg_host: str | None,
    pg_user: str | None,
    pg_db: str | None,
    token: str | None,
    compose_file: str | None,
) -> None:
    """Persist CLI settings to ~/.auditlens.conf (chmod 600)."""
    updates = {
        "url": url,
        "pg_host": pg_host,
        "pg_user": pg_user,
        "pg_db": pg_db,
        "token": token,
        "compose_file": compose_file,
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        click.echo("No --options supplied. Nothing to write.")
        return
    save_config(updates)
    click.echo(f"Wrote {CONFIG_PATH}")
    for k, v in updates.items():
        if k == "token" and v:
            v = f"***{v[-4:]}"
        click.echo(f"  {k} = {v}")


@config.command("show")
def config_show() -> None:
    """Print resolved config (masks the token)."""
    cfg = load_config()
    for k, v in cfg.items():
        if k == "token" and v:
            v = f"***{v[-4:]}"
        click.echo(f"{k} = {v}")


# ----- events -----

@cli.group()
def events() -> None:
    """Browse, fetch, and export audit events."""


def _events_filter_params(
    signal: str | None, actor: str | None, since: str, limit: int
) -> dict[str, str]:
    params: dict[str, str] = {
        "limit": str(limit),
        "time_window": encode_window(since),
    }
    if signal:
        params["signal_type"] = signal
    if actor:
        params["actor"] = actor
    return params


@events.command("list")
@click.option("--signal", type=click.Choice(SIGNAL_CHOICES))
@click.option("--actor", help="Partial actor / email match (ILIKE on backend).")
@click.option("--since", default="24h", show_default=True, help="Time window (Nm/Nh/Nd).")
@click.option("--limit", default=20, type=click.IntRange(1, 200), show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Raw JSON output.")
def events_list(
    signal: str | None,
    actor: str | None,
    since: str,
    limit: int,
    json_output: bool,
) -> None:
    """List recent events as a coloured table."""
    cfg = load_config()
    with make_client(cfg) as client:
        try:
            r = client.get("/events", params=_events_filter_params(signal, actor, since, limit))
            r.raise_for_status()
        except httpx.HTTPError as exc:
            http_error_exit(exc)
        data = r.json()
    items = data.get("items", [])
    if json_output:
        click.echo(json.dumps(items, indent=2, default=str))
        return
    if not items:
        click.echo("No events matched.")
        return
    rows = []
    for it in items:
        rows.append(
            {
                "time": fmt_time_local(it.get("timestamp")),
                "actor": truncate(it.get("actor_display_name") or it.get("actor") or "—", 28),
                "action": truncate(it.get("action") or "—", 30),
                "signal": style_signal(it.get("signal_type")),
                "reason": truncate(it.get("decision_reason") or "—", 22),
                "risk": it.get("risk_level") or "—",
            }
        )
    render_table(
        rows,
        [
            ("time", "Time", 12),
            ("actor", "Actor", 28),
            ("action", "Action", 30),
            ("signal", "Signal", 16),
            ("reason", "Reason", 22),
            ("risk", "Risk", 10),
        ],
    )
    total = data.get("total")
    suffix = f" of {total}" if total is not None else ""
    click.echo(f"\nShowing {len(items)}{suffix} matching events.")


@events.command("get")
@click.argument("event_id", type=int)
def events_get(event_id: int) -> None:
    """Fetch a single event by integer ID and print every field."""
    cfg = load_config()
    with make_client(cfg) as client:
        try:
            r = client.get(f"/events/{event_id}")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            http_error_exit(exc)
        data = r.json()
    for key in sorted(data.keys()):
        val = data[key]
        if isinstance(val, (dict, list)):
            val = json.dumps(val, default=str)
        click.echo(f"{key}: {val}")


@events.command("export")
@click.option("--signal", type=click.Choice(SIGNAL_CHOICES))
@click.option("--actor")
@click.option("--since", default="24h", show_default=True)
@click.option("--limit", default=1000, type=click.IntRange(1, 50000), show_default=True)
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), default="csv", show_default=True)
@click.option("--out", type=click.Path(dir_okay=False, writable=True), default=None,
              help="Output file (default: stdout).")
def events_export(
    signal: str | None,
    actor: str | None,
    since: str,
    limit: int,
    fmt: str,
    out: str | None,
) -> None:
    """Stream events to CSV or JSON via /api/events/export."""
    cfg = load_config()
    params = _events_filter_params(signal, actor, since, limit)
    params["format"] = fmt
    with make_client(cfg) as client:
        try:
            with client.stream("GET", "/events/export", params=params) as r:
                r.raise_for_status()
                if out:
                    with open(out, "wb") as fh:
                        for chunk in r.iter_bytes():
                            fh.write(chunk)
                    click.echo(f"Wrote {out}", err=True)
                else:
                    for chunk in r.iter_bytes():
                        sys.stdout.buffer.write(chunk)
        except httpx.HTTPError as exc:
            http_error_exit(exc)


# ----- stats compare -----

@cli.group()
def stats() -> None:
    """Aggregate stats across periods."""


def _top(items: list[dict], key: str) -> str:
    if not items:
        return "—"
    first = items[0]
    name = first.get(key) or "—"
    count = first.get("count")
    return f"{name} ({count})" if count is not None else str(name)


@stats.command("compare")
@click.option("--period-a", default="24h", show_default=True)
@click.option("--period-b", default="7d", show_default=True)
def stats_compare(period_a: str, period_b: str) -> None:
    """Side-by-side stats for two time windows."""
    cfg = load_config()
    with make_client(cfg) as client:
        try:
            r = client.get(
                "/events/compare",
                params={"period_a": encode_window(period_a), "period_b": encode_window(period_b)},
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            http_error_exit(exc)
        data = r.json()
    a, b = data["period_a"], data["period_b"]

    def sig(p: dict, key: str) -> str:
        return str(p.get("by_signal_type", {}).get(key, 0))

    metrics = [
        ("Total events", str(a["total"]), str(b["total"])),
        ("Action required", sig(a, "action_required"), sig(b, "action_required")),
        ("Attention", sig(a, "attention"), sig(b, "attention")),
        ("Informational", sig(a, "informational"), sig(b, "informational")),
        ("Noise", sig(a, "noise"), sig(b, "noise")),
        ("Top actor", _top(a["top_actors"], "name"), _top(b["top_actors"], "name")),
        ("Top action", _top(a["top_methods"], "action"), _top(b["top_methods"], "action")),
    ]
    label_a = f"Period A ({period_a})"
    label_b = f"Period B ({period_b})"
    name_w = max(len("Metric"), max(len(m[0]) for m in metrics))
    col_w = max(len(label_a), len(label_b), max(len(m[1]) for m in metrics), max(len(m[2]) for m in metrics))
    click.echo(click.style(
        f"{'Metric'.ljust(name_w)}  {label_a.ljust(col_w)}  {label_b.ljust(col_w)}",
        bold=True,
    ))
    click.echo("  ".join(["-" * name_w, "-" * col_w, "-" * col_w]))
    for metric, va, vb in metrics:
        click.echo(f"{metric.ljust(name_w)}  {va.ljust(col_w)}  {vb.ljust(col_w)}")


# ----- pipeline -----

@cli.group()
def pipeline() -> None:
    """Inspect pipeline health and Postgres internals."""


@pipeline.command("status")
def pipeline_status() -> None:
    """API health + recent ingest rate + last-event freshness."""
    cfg = load_config()
    base = cfg["url"].rstrip("/")
    # /health is exposed at root (Caddy maps it directly); doesn't need /api.
    try:
        h = httpx.get(f"{base}/health", timeout=10.0)
        api_line = f"{h.status_code} {h.reason_phrase}"
    except httpx.HTTPError as exc:
        api_line = f"unreachable ({exc})"

    last_5 = last_60 = "—"
    last_ts = None
    with make_client(cfg) as client:
        try:
            r = client.get("/events/compare", params={"period_a": "5m", "period_b": "60m"})
            r.raise_for_status()
            comp = r.json()
            last_5 = str(comp["period_a"]["total"])
            last_60 = str(comp["period_b"]["total"])
        except httpx.HTTPError as exc:
            click.echo(click.style(f"  compare endpoint error: {exc}", fg="red"), err=True)

        try:
            r = client.get("/events", params={"limit": 1, "time_window": "24h"})
            r.raise_for_status()
            items = r.json().get("items", [])
            last_ts = items[0]["timestamp"] if items else None
        except httpx.HTTPError:
            pass

    click.echo(click.style("Pipeline status", bold=True))
    click.echo(f"  API health     : {api_line}")
    if last_ts:
        try:
            ts_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            now = datetime.now(ts_dt.tzinfo)
            mins_ago = int((now - ts_dt).total_seconds() // 60)
        except Exception:
            mins_ago = -1
        click.echo(f"  Last event     : {fmt_time_local(last_ts)} ({mins_ago} min ago)")
        if mins_ago > 30:
            click.echo(click.style(
                f"  WARNING        : pipeline silent for {mins_ago} minutes (threshold 30)",
                fg="red", bold=True,
            ))
    else:
        click.echo(click.style("  Last event     : none in last 24h", fg="red"))
    click.echo(f"  Events last 5m : {last_5}")
    click.echo(f"  Events last 1h : {last_60}")


@pipeline.command("indexes")
def pipeline_indexes() -> None:
    """List audit_events* indexes via `docker compose exec postgres psql`."""
    cfg = load_config()
    compose_file = os.path.expanduser(cfg.get("compose_file") or DEFAULT_COMPOSE)
    cmd = [
        "docker", "compose", "-f", compose_file, "exec", "-T", "postgres",
        "psql", "-U", cfg["pg_user"], "-d", cfg["pg_db"], "-c", r"\di audit_events*",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        click.echo(click.style("docker not on PATH (run from the deploy host).", fg="red"), err=True)
        sys.exit(1)
    if result.returncode != 0:
        click.echo(click.style(f"psql failed: {result.stderr.strip()}", fg="red"), err=True)
        sys.exit(1)
    rows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.startswith(" public"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 5:
            rows.append({"name": parts[1], "type": parts[2], "table": parts[4]})
    if not rows:
        click.echo("No audit_events* indexes found.")
        click.echo(result.stdout)
        return
    name_w = max(20, max(len(r["name"]) for r in rows))
    table_w = max(15, max(len(r["table"]) for r in rows))
    click.echo(click.style(
        f"{'Index name'.ljust(name_w)}  {'Type'.ljust(8)}  {'Table'.ljust(table_w)}", bold=True,
    ))
    click.echo("  ".join(["-" * name_w, "-" * 8, "-" * table_w]))
    for r_ in rows:
        click.echo(f"{r_['name'].ljust(name_w)}  {r_['type'].ljust(8)}  {r_['table'].ljust(table_w)}")


# ----- alerts -----

@cli.group()
def alerts() -> None:
    """Notification destination tools."""


@alerts.command("test")
def alerts_test() -> None:
    """Fire a real test notification to every enabled Slack/Teams destination."""
    cfg = load_config()
    with make_client(cfg) as client:
        try:
            r = client.post("/settings/notifications/test", json={})
        except httpx.HTTPError as exc:
            http_error_exit(exc)
    if r.status_code == 404:
        click.echo("not available (POST /api/settings/notifications/test missing on this build)")
        sys.exit(2)
    if r.status_code in (401, 403):
        click.echo(click.style(
            f"auth required ({r.status_code}) — run `auditlens config set --token <admin-bearer>`",
            fg="yellow",
        ))
        sys.exit(1)
    try:
        data = r.json()
    except Exception:
        click.echo(r.text)
        return
    sent = data.get("sent_count", 0)
    errors = data.get("error_count", 0)
    fg = "green" if errors == 0 and sent > 0 else ("yellow" if errors == 0 else "red")
    click.echo(click.style(f"sent={sent}  errors={errors}", fg=fg, bold=True))
    for r_ in data.get("results", []):
        ok = r_.get("success", False)
        marker = click.style("✓", fg="green") if ok else click.style("✗", fg="red")
        name = r_.get("name") or r_.get("destination") or "?"
        msg = r_.get("message") or r_.get("error") or ""
        click.echo(f"  {marker} {name}  {msg}")


# ──────────── doctor ────────────
# Severity levels for the doctor summary table + exit code derivation.
#   "ok"       → ✅ green   (exit 0)
#   "warning"  → ⚠️  yellow (exit 1)
#   "critical" → ❌ red     (exit 2)
#   "skipped"  → ⏭️  dim    (treated as ok for exit code; reachability check)
SEVERITY_RANK = {"ok": 0, "skipped": 0, "warning": 1, "critical": 2}

# Domain reachability target. Treated as best-effort: a missing DNS / non-2xx
# response only ever produces a "skipped" or "warning", never "critical".
REACHABILITY_DOMAIN = "auditlens.aws.cse.confluent.io"

# Env vars the doctor check verifies are non-empty in the deploy host's .env.
# Names match docker-compose.prod.yml's variable substitution surface. Note
# that the historical AUDIT_BOOTSTRAP_SERVERS / DEST_BOOTSTRAP_SERVERS names
# also accepted (in case an operator's .env predates the rename) — the check
# treats either form as "set".
REQUIRED_ENV_VARS = (
    ("AUDIT_BOOTSTRAP", ("AUDIT_BOOTSTRAP_SERVERS",)),
    ("AUDIT_TOPIC", ()),
    ("DEST_BOOTSTRAP", ("DEST_BOOTSTRAP_SERVERS",)),
    ("DATABASE_URL", ()),
    ("CORS_ORIGINS", ()),
    ("NEXT_PUBLIC_API_BASE_URL", ()),
)


def _doctor_compose_file(cfg: dict[str, str]) -> str:
    """Resolve the docker-compose.prod.yml path, expanding ``~``."""
    return os.path.expanduser(cfg.get("compose_file") or DEFAULT_COMPOSE)


def _safe_run(cmd: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    """subprocess.run that always returns a CompletedProcess. On failure
    populates returncode=-1 and stderr with the exception message so the
    caller can pattern-match without catching at every call site."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(cmd, -1, "", f"binary not found: {exc}")
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, -1, "", f"timeout after {exc.timeout}s")
    except Exception as exc:  # pragma: no cover - defensive
        return subprocess.CompletedProcess(cmd, -1, "", f"{type(exc).__name__}: {exc}")


def _parse_env_file(path: str) -> dict[str, str]:
    """Lightweight .env parser — keys may be quoted, values may contain `=`.
    Returns {} if the file is unreadable. Doesn't honour `export` prefixes
    or shell escapes; matches what docker compose actually reads."""
    out: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    out[key] = value
    except OSError:
        return {}
    return out


def _docker_compose_ps(compose_file: str) -> list[dict[str, str]]:
    """Return one row per service from `docker compose ps`. Tries JSON
    output first; falls back to parsing the human-readable table when the
    installed docker compose doesn't support --format json."""
    proc = _safe_run(
        ["docker", "compose", "-f", compose_file, "ps", "--format", "json"],
    )
    if proc.returncode != 0:
        return []
    rows: list[dict[str, str]] = []
    out = proc.stdout.strip()
    if not out:
        return []
    # New docker compose: NDJSON (one object per line)
    if out.startswith("{"):
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
    # Older docker compose: JSON array
    try:
        parsed = json.loads(out)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return rows


def _docker_service_status(row: dict[str, str]) -> tuple[str, str, str]:
    """Pull (service_name, state, health) out of a compose-ps row tolerant
    to the slightly different key shapes between compose versions."""
    name = row.get("Service") or row.get("Name") or "?"
    state = (row.get("State") or row.get("Status") or "").lower()
    health = (row.get("Health") or "").lower()
    if not health and "(" in (row.get("Status") or ""):
        # Older format embeds "(healthy)" inside the Status string.
        status = row.get("Status", "")
        if "(healthy)" in status:
            health = "healthy"
        elif "(unhealthy)" in status:
            health = "unhealthy"
        elif "(starting)" in status:
            health = "starting"
    return name, state, health


def _tail_logs(compose_file: str, service: str, lines: int = 20) -> list[str]:
    proc = _safe_run(
        ["docker", "compose", "-f", compose_file, "logs", "--tail", str(lines), service],
        timeout=15,
    )
    if proc.returncode != 0:
        return [f"(could not read logs: {proc.stderr.strip()[:120]})"]
    return [line for line in proc.stdout.splitlines() if line.strip()][-5:]


def _doctor_status_marker(severity: str) -> str:
    if severity == "ok":
        return click.style("✅", fg="green")
    if severity == "warning":
        return click.style("⚠️ ", fg="yellow")
    if severity == "critical":
        return click.style("❌", fg="red")
    return click.style("⏭️ ", dim=True)


# ──────────── per-service deep probes ────────────
# SERVICE_PROBES is the doctor's view of every service that ships in
# docker-compose.prod.yml. Each entry says: which container holds it,
# which port to hit, and which probe strategy to use. Ports are an
# overridable default — _parse_compose_ports() reads the live compose
# file at runtime and replaces these when it can.
#
# probe_strategy:
#   "http"           — urllib.request GET (or method=…); checks status
#                      code and optionally a top-level JSON key.
#   "tcp_connect"    — socket.create_connection only. Cheapest probe; use
#                      it for services where opening the port without
#                      authentication is enough proof of life.
#   "process_alive"  — docker compose exec <svc> pgrep -f <pattern>.
#                      Required for stdio MCP / any service that has no
#                      HTTP endpoint to probe.
SERVICE_PROBES: dict[str, dict[str, Any]] = {
    "api": {
        "container_name": "auditlens-api",
        "host_port": 8080,
        "probe_strategy": "http",
        "probe_path": "/health",
        "expect_status": 200,
        "expect_json_key": "status",
        "timeout": 5,
    },
    "frontend": {
        "container_name": "auditlens-frontend",
        "host_port": 3000,
        "probe_strategy": "http",
        # Matches the compose healthcheck (Next.js root may redirect).
        "probe_path": "/dashboard",
        "expect_status": 200,
        "timeout": 5,
    },
    "auditlens-forwarder": {
        "container_name": "auditlens-forwarder",
        "host_port": 8003,
        "probe_strategy": "http",
        "probe_path": "/health",
        "expect_status": 200,
        "expect_json_key": "status",
        "timeout": 5,
        # When the probe returns JSON, doctor also surfaces last_event age.
        "include_last_event": True,
    },
    "mcp-server": {
        "container_name": "audit-mcp-server",
        "host_port": 8089,
        # MCP speaks JSON-RPC over stdin/stdout — there is no HTTP endpoint.
        # The compose healthcheck (curl :8089/health) is misconfigured for
        # this transport and will always fail; doctor flags the mismatch
        # explicitly when the container reports unhealthy.
        "probe_strategy": "process_alive",
        "process_pattern": "server.py",
        "transport": "stdio",
        "timeout": 5,
    },
    "postgres": {
        "container_name": "auditlens-postgres",
        "host_port": 5432,
        # pg_isready needs the right auth context; a TCP connect plus the
        # downstream Postgres-rows check together prove the database path
        # without doctor having to know the password.
        "probe_strategy": "tcp_connect",
        "timeout": 3,
    },
    "prometheus": {
        "container_name": "audit-prometheus",
        "host_port": 9090,
        "probe_strategy": "http",
        "probe_path": "/-/healthy",
        "expect_status": 200,
        "timeout": 5,
    },
    "grafana": {
        "container_name": "audit-grafana",
        "host_port": 3001,
        "probe_strategy": "http",
        "probe_path": "/api/health",
        "expect_status": 200,
        "timeout": 5,
    },
    "alertmanager": {
        "container_name": "audit-alertmanager",
        "host_port": 9093,
        "probe_strategy": "http",
        "probe_path": "/-/healthy",
        "expect_status": 200,
        "timeout": 5,
        "no_compose_healthcheck": True,
    },
    "postgres-exporter": {
        "container_name": "auditlens-postgres-exporter",
        "host_port": 9187,
        "probe_strategy": "http",
        "probe_path": "/metrics",
        "expect_status": 200,
        "timeout": 5,
        "no_compose_healthcheck": True,
    },
    "caddy": {
        "container_name": "auditlens-caddy",
        "host_port": 80,
        "probe_strategy": "http",
        "probe_path": "/health",
        "expect_status": 200,
        "timeout": 5,
    },
}


def _http_probe(
    host: str,
    port: int,
    path: str,
    *,
    method: str = "GET",
    expect_status: int = 200,
    expect_json_key: str | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """stdlib-only HTTP probe. Returns
        {ok, status_code, response_ms, detail, body}
    The body is parsed JSON when the response looks JSON-shaped, else None."""
    import urllib.request as _ur
    import urllib.error as _ue
    url = f"http://{host}:{port}{path}"
    req = _ur.Request(url, method=method)
    start = time.perf_counter()
    try:
        with _ur.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            status = resp.status
            # 64 KB is enough for any reasonable health JSON; reading
            # too little (8 KB) silently failed JSON parsing on the
            # forwarder's verbose /health body which carries queue
            # depths + last_event + per-partition lag.
            raw = resp.read(65536)
    except _ue.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        ok = (exc.code == expect_status)
        return {
            "ok": ok,
            "status_code": exc.code,
            "response_ms": elapsed_ms,
            "detail": f"HTTP {exc.code} {elapsed_ms}ms",
            "body": None,
        }
    except _ue.URLError as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        reason = getattr(exc, "reason", exc)
        return {
            "ok": False,
            "status_code": None,
            "response_ms": elapsed_ms,
            "detail": f"connect refused: {reason}",
            "body": None,
        }
    except Exception as exc:  # pragma: no cover - defensive
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": False,
            "status_code": None,
            "response_ms": elapsed_ms,
            "detail": f"{type(exc).__name__}: {exc}",
            "body": None,
        }

    body: Any = None
    if raw and raw.lstrip()[:1] in (b"{", b"["):
        try:
            body = json.loads(raw)
        except Exception:
            body = None

    if status != expect_status:
        return {
            "ok": False, "status_code": status, "response_ms": elapsed_ms,
            "detail": f"HTTP {status} (expected {expect_status})", "body": body,
        }
    if expect_json_key:
        if not isinstance(body, dict) or expect_json_key not in body:
            return {
                "ok": False, "status_code": status, "response_ms": elapsed_ms,
                "detail": f"HTTP {status} {elapsed_ms}ms — JSON missing key '{expect_json_key}'",
                "body": body,
            }
    return {
        "ok": True, "status_code": status, "response_ms": elapsed_ms,
        "detail": f"HTTP {status} {elapsed_ms}ms", "body": body,
    }


def _tcp_probe(host: str, port: int, *, timeout: float = 3.0) -> dict[str, Any]:
    """stdlib-only TCP connect probe. Returns {ok, response_ms, detail}."""
    import socket as _sock
    start = time.perf_counter()
    try:
        with _sock.create_connection((host, port), timeout=timeout):
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return {
                "ok": True, "response_ms": elapsed_ms,
                "detail": f"TCP open {elapsed_ms}ms",
            }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": False, "response_ms": elapsed_ms,
            "detail": f"TCP probe failed: {type(exc).__name__}",
        }


def _process_probe(container_name: str) -> dict[str, Any]:
    """Check the container's PID 1 is alive via `docker inspect`.

    Earlier versions used `docker compose exec <svc> pgrep -f <pattern>`
    but `pgrep` is not present in python-slim base images (the mcp-server
    image), nor in any minimal/distroless image. `docker inspect` reads
    the container state without entering the container, so it works
    regardless of what tools were baked in. A container with
    State.Status=="running" has, by Docker's own definition, a live
    PID 1 — for the stdio MCP server that IS the python server.py
    process."""
    proc = _safe_run(
        ["docker", "inspect", container_name,
         "--format", "{{.State.Status}}|{{.State.Pid}}|{{.Path}} {{join .Args \" \"}}"],
        timeout=5,
    )
    if proc.returncode != 0:
        return {"ok": False, "pid": None,
                "detail": f"inspect failed: {(proc.stderr or '').strip()[:80]}"}
    parts = proc.stdout.strip().split("|")
    if len(parts) < 3:
        return {"ok": False, "pid": None, "detail": "inspect malformed"}
    status = parts[0].strip().lower()
    try:
        pid = int(parts[1].strip())
    except ValueError:
        pid = 0
    cmdline = parts[2].strip()
    if status == "running" and pid > 0:
        return {"ok": True, "pid": str(pid),
                "detail": f"pid {pid} running ({cmdline[:60]})"}
    return {"ok": False, "pid": str(pid),
            "detail": f"status={status} pid={pid}"}


def _restart_loop_probe(container_name: str) -> dict[str, Any]:
    """Read RestartCount + last ExitCode from `docker inspect`. Categorises:

      restarts > 5  + exit=0   → critical (clean-exit loop, e.g. missing
                                  entrypoint — the mcp-server bug pattern)
      restarts > 5  + exit!=0  → critical (crash loop)
      0 < restarts ≤ 5         → warning  (recent recovery)
      restarts == 0            → ok
    """
    proc = _safe_run(
        ["docker", "inspect", container_name,
         "--format", "{{.RestartCount}}|{{.State.ExitCode}}|{{.State.Status}}"],
        timeout=5,
    )
    if proc.returncode != 0:
        return {"ok": False, "severity": "warning", "detail": "inspect failed",
                "restart_count": -1}
    parts = proc.stdout.strip().split("|")
    if len(parts) < 3:
        return {"ok": False, "severity": "warning", "detail": "inspect malformed",
                "restart_count": -1}
    try:
        restart_count = int(parts[0])
        exit_code = int(parts[1])
    except ValueError:
        return {"ok": False, "severity": "warning", "detail": "inspect non-numeric",
                "restart_count": -1}
    if restart_count > 5:
        if exit_code == 0:
            return {"ok": False, "severity": "critical",
                    "detail": f"{restart_count} restarts (clean-exit loop)",
                    "restart_count": restart_count}
        return {"ok": False, "severity": "critical",
                "detail": f"{restart_count} restarts (crash loop, exit {exit_code})",
                "restart_count": restart_count}
    if restart_count > 0:
        return {"ok": False, "severity": "warning",
                "detail": f"{restart_count} recent restarts",
                "restart_count": restart_count}
    return {"ok": True, "severity": "ok", "detail": "0 restarts",
            "restart_count": 0}


def _parse_compose_ports(compose_file: str) -> dict[str, int]:
    """Best-effort: pull the host-side port for each service from
    docker-compose.prod.yml. Returns {service_name: host_port}. Substitutes
    `${VAR:-default}` patterns. Silently returns {} on parse failure — the
    SERVICE_PROBES defaults always win as the fallback."""
    try:
        with open(compose_file, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return {}
    import re as _re
    out: dict[str, int] = {}
    parts = _re.split(r"^  ([a-z][a-z0-9-]*):\s*$", content, flags=_re.M)
    # parts = [pre, name1, body1, name2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        name = parts[i]
        body = parts[i + 1]
        ports_block = _re.search(r"ports:\s*\n((?:\s{6,}-.*\n)+)", body)
        if not ports_block:
            continue
        for line in ports_block.group(1).splitlines():
            m = _re.search(r'"\s*(?:[\d.]+:)?([^":\s]+):([^":\s]+)\s*"', line)
            if not m:
                continue
            host_part = m.group(1).strip()
            sub = _re.search(r"\$\{[^:}]+:-([^}]+)\}", host_part)
            if sub:
                host_part = sub.group(1)
            try:
                out[name] = int(host_part)
                break
            except ValueError:
                continue
    return out


def _format_last_event_age(body: Any) -> str:
    """Pull last_event timestamp out of /health body and render Nm ago."""
    if not isinstance(body, dict):
        return ""
    last_event = body.get("last_event") or body.get("last_event_timestamp")
    if not isinstance(last_event, str) or not last_event:
        return ""
    try:
        ts = datetime.fromisoformat(last_event.replace("Z", "+00:00"))
        age_min = int((datetime.now(ts.tzinfo) - ts).total_seconds() // 60)
        return f"last event {age_min}m ago"
    except Exception:
        return ""


def _doctor_check_docker_services(
    compose_file: str, results: list[dict[str, str]]
) -> None:
    click.echo(click.style("→ Docker services (deep probe)", bold=True))
    if not os.path.exists(compose_file):
        click.echo(f"  compose file not found: {compose_file}")
        results.append({
            "component": "Docker compose",
            "severity": "critical",
            "probe": "—",
            "detail": f"missing {compose_file}",
        })
        return

    rows = _docker_compose_ps(compose_file)
    if not rows:
        click.echo("  docker compose ps returned no rows (daemon not running?)")
        results.append({
            "component": "Docker daemon",
            "severity": "critical",
            "probe": "—",
            "detail": "no containers reported",
        })
        return

    parsed_ports = _parse_compose_ports(compose_file)
    by_service: dict[str, tuple[dict[str, str], str, str]] = {}
    for row in rows:
        name, state, health = _docker_service_status(row)
        by_service[name] = (row, state, health)

    name_w = max(len(s) for s in SERVICE_PROBES)

    for service, spec in SERVICE_PROBES.items():
        row_data = by_service.get(service)
        if row_data is None:
            click.echo(f"  {_doctor_status_marker('warning')} "
                       f"{service.ljust(name_w)} not deployed")
            results.append({
                "component": f"Docker: {service}",
                "severity": "warning",
                "probe": "—",
                "detail": "not in `docker compose ps`",
            })
            continue
        _row, state, health = row_data
        container_name = spec.get("container_name", service)

        # 1. Restart-loop probe (independent of the deep probe).
        rl = _restart_loop_probe(container_name)
        restart_severity = rl.get("severity", "ok")
        restart_detail = rl.get("detail", "—")

        # 2. Docker state.
        if state != "running":
            severity = "critical"
            probe_text = "—"
            detail_text = f"state={state or 'unknown'}"
            click.echo(f"  {_doctor_status_marker(severity)} "
                       f"{service.ljust(name_w)} {state or 'down':<8} | {probe_text:<32} | {restart_detail}")
            if state in ("exited", "stopped", "dead"):
                for line in _tail_logs(compose_file, service):
                    click.echo(f"      {line[:160]}")
            results.append({
                "component": f"Docker: {service}",
                "severity": severity,
                "probe": probe_text,
                "detail": f"{detail_text} | {restart_detail}",
            })
            continue

        # 3. Per-service deep probe.
        strategy = spec.get("probe_strategy", "http")
        port = parsed_ports.get(service) or spec.get("host_port") or 0
        probe_text = "—"
        probe_severity = "ok"
        notes: list[str] = []

        try:
            if strategy == "http":
                p = _http_probe(
                    "127.0.0.1", int(port), spec.get("probe_path", "/"),
                    method=spec.get("method", "GET"),
                    expect_status=spec.get("expect_status", 200),
                    expect_json_key=spec.get("expect_json_key"),
                    timeout=spec.get("timeout", 5),
                )
                probe_text = p["detail"]
                probe_severity = "ok" if p["ok"] else "critical"
                if spec.get("include_last_event"):
                    age = _format_last_event_age(p.get("body"))
                    if age:
                        notes.append(age)
            elif strategy == "tcp_connect":
                p = _tcp_probe("127.0.0.1", int(port),
                               timeout=spec.get("timeout", 3))
                probe_text = p["detail"]
                probe_severity = "ok" if p["ok"] else "critical"
            elif strategy == "process_alive":
                p = _process_probe(container_name)
                probe_text = f"stdio/no-HTTP ({p['detail']})"
                probe_severity = "ok" if p["ok"] else "critical"
                # When the compose-level HTTP healthcheck reports unhealthy
                # against a stdio server, surface the configuration mismatch
                # rather than silently letting it look like a real failure.
                if health in ("unhealthy", "starting"):
                    notes.append(
                        "compose HTTP healthcheck mismatched stdio transport — "
                        "fix: change compose to pgrep")
                    if probe_severity == "ok":
                        probe_severity = "warning"
            else:
                probe_text = f"strategy={strategy}"
                probe_severity = "warning"
        except Exception as exc:  # pragma: no cover - defensive
            probe_text = f"probe crashed: {type(exc).__name__}"
            probe_severity = "warning"

        # 4. Services that ship without a compose-level healthcheck are
        #    flagged so operators know which signals are deliberately
        #    missing from `docker compose ps`.
        if spec.get("no_compose_healthcheck"):
            notes.append("no healthcheck in compose")
            if probe_severity == "ok":
                probe_severity = "warning"

        worst = max(
            (restart_severity, probe_severity),
            key=lambda s: SEVERITY_RANK.get(s, 0),
        )
        click.echo(
            f"  {_doctor_status_marker(worst)} {service.ljust(name_w)} "
            f"{state:<8} | {probe_text:<40} | {restart_detail}"
        )
        for note in notes:
            click.echo(f"           └─ {note}")

        detail_parts = [probe_text, restart_detail] + notes
        results.append({
            "component": f"Docker: {service}",
            "severity": worst,
            "probe": probe_text,
            "detail": " | ".join(detail_parts),
        })


def _doctor_check_forwarder(
    cfg: dict[str, str], results: list[dict[str, str]]
) -> None:
    click.echo(click.style("→ Forwarder connectivity", bold=True))
    base = cfg["url"].rstrip("/")
    # The forwarder /health is on :8003 directly, not behind Caddy.
    # Try the configured host (operator may have port-forwarded) first,
    # then fall back to localhost:8003 for the in-container case.
    forwarder_url_candidates = []
    host = base.split("://", 1)[-1].split(":")[0].split("/")[0]
    if host and host not in ("localhost", "127.0.0.1"):
        forwarder_url_candidates.append(f"http://{host}:8003/health")
    forwarder_url_candidates.append("http://localhost:8003/health")

    last_err: str | None = None
    response_text: str | None = None
    for url in forwarder_url_candidates:
        try:
            r = httpx.get(url, timeout=5.0)
            response_text = f"HTTP {r.status_code} ({url})"
            if r.status_code < 500:
                body: dict[str, Any] = {}
                try:
                    body = r.json()
                except Exception:
                    body = {}
                last_event = body.get("last_event") or body.get("last_event_timestamp")
                age_min: int | None = None
                if isinstance(last_event, str):
                    try:
                        ts = datetime.fromisoformat(last_event.replace("Z", "+00:00"))
                        age_min = int(
                            (datetime.now(ts.tzinfo) - ts).total_seconds() // 60
                        )
                    except Exception:
                        age_min = None
                if r.status_code >= 400:
                    severity = "critical"
                    detail = response_text
                elif age_min is not None and age_min > 30:
                    severity = "warning"
                    detail = f"last event {age_min} min ago"
                else:
                    severity = "ok"
                    detail = f"healthy ({url})"
                    if age_min is not None:
                        detail = f"last event {age_min} min ago"
                click.echo(f"  {_doctor_status_marker(severity)} {detail}")
                results.append({
                    "component": "Forwarder connectivity",
                    "severity": severity,
                    "detail": detail,
                })
                return
        except httpx.HTTPError as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            continue

    detail = f"unreachable ({last_err or 'unknown'})"
    click.echo(f"  {_doctor_status_marker('critical')} {detail}")
    results.append({"component": "Forwarder connectivity", "severity": "critical", "detail": detail})


def _doctor_check_api(cfg: dict[str, str], results: list[dict[str, str]]) -> None:
    click.echo(click.style("→ API health", bold=True))
    base = cfg["url"].rstrip("/")
    # /health is exposed at the root (Caddy maps it directly).
    start = time.perf_counter()
    try:
        r = httpx.get(f"{base}/health", timeout=10.0)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
    except httpx.HTTPError as exc:
        detail = f"unreachable ({type(exc).__name__}: {exc})"
        click.echo(f"  {_doctor_status_marker('critical')} {detail}")
        results.append({"component": "API health", "severity": "critical", "detail": detail})
        return
    if r.status_code >= 400:
        detail = f"HTTP {r.status_code} ({elapsed_ms}ms)"
        click.echo(f"  {_doctor_status_marker('critical')} {detail}")
        results.append({"component": "API health", "severity": "critical", "detail": detail})
        return
    severity = "warning" if elapsed_ms > 2000 else "ok"
    detail = f"{elapsed_ms}ms"
    if severity == "warning":
        detail = f"slow ({elapsed_ms}ms)"
    click.echo(f"  {_doctor_status_marker(severity)} /health {detail}")
    results.append({"component": "API health", "severity": severity, "detail": detail})

    # Smoke test /api/events to make sure the database path is working
    # end-to-end (not just the lightweight /health check).
    with make_client(cfg) as client:
        try:
            r = client.get("/events", params={"limit": 1, "time_window": "24h"})
            if r.status_code >= 500:
                detail = f"/api/events {r.status_code}"
                click.echo(f"  {_doctor_status_marker('critical')} {detail}")
                results.append({
                    "component": "API /events smoke",
                    "severity": "critical",
                    "detail": detail,
                })
            else:
                items = r.json().get("items") if r.headers.get("content-type", "").startswith("application/json") else None
                detail = f"OK ({len(items)} item(s) returned)" if isinstance(items, list) else f"HTTP {r.status_code}"
                click.echo(f"  {_doctor_status_marker('ok')} /api/events {detail}")
                results.append({
                    "component": "API /events smoke",
                    "severity": "ok",
                    "detail": detail,
                })
        except httpx.HTTPError as exc:
            detail = f"smoke failed: {exc}"
            click.echo(f"  {_doctor_status_marker('warning')} {detail}")
            results.append({
                "component": "API /events smoke",
                "severity": "warning",
                "detail": detail,
            })


def _doctor_check_postgres(
    cfg: dict[str, str], compose_file: str, results: list[dict[str, str]]
) -> None:
    click.echo(click.style("→ Postgres connectivity", bold=True))
    if not os.path.exists(compose_file):
        click.echo("  skipping — compose file not available")
        results.append({"component": "Postgres rows", "severity": "skipped", "detail": "no compose file"})
        return
    pg_user = cfg.get("pg_user") or DEFAULT_PG_USER
    pg_db = cfg.get("pg_db") or DEFAULT_PG_DB
    query = (
        "SELECT 'signal' AS tbl, COUNT(*) FROM audit_events "
        "UNION ALL "
        "SELECT 'noise', COUNT(*) FROM audit_events_noise "
        "UNION ALL "
        "SELECT 'recent_1h', COUNT(*) FROM audit_events "
        "WHERE timestamp >= NOW() - INTERVAL '1 hour';"
    )
    cmd = [
        "docker", "compose", "-f", compose_file, "exec", "-T", "postgres",
        "psql", "-U", pg_user, "-d", pg_db, "-At", "-F", "|", "-c", query,
    ]
    proc = _safe_run(cmd, timeout=30)
    if proc.returncode != 0:
        detail = f"psql failed: {(proc.stderr or proc.stdout).strip()[:140]}"
        click.echo(f"  {_doctor_status_marker('critical')} {detail}")
        results.append({"component": "Postgres rows", "severity": "critical", "detail": detail})
        return
    counts: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        label, _, n = line.partition("|")
        try:
            counts[label.strip()] = int(n.strip())
        except ValueError:
            continue
    sig = counts.get("signal", 0)
    noi = counts.get("noise", 0)
    last_hour = counts.get("recent_1h", 0)
    click.echo(f"  {_doctor_status_marker('ok')} signal rows  : {sig:,}")
    click.echo(f"  {_doctor_status_marker('ok')} noise rows   : {noi:,}")
    severity = "warning" if last_hour == 0 else "ok"
    line = f"last hour    : {last_hour:,} events"
    if severity == "warning":
        line += "  (possible pipeline stall)"
    click.echo(f"  {_doctor_status_marker(severity)} {line}")
    results.append({
        "component": "Postgres rows",
        "severity": "ok",
        "detail": f"{sig:,} signal + {noi:,} noise",
    })
    results.append({
        "component": "Pipeline freshness",
        "severity": severity,
        "detail": f"{last_hour:,} events in last hour",
    })


def _doctor_check_dead_tuples(
    cfg: dict[str, str], compose_file: str, results: list[dict[str, str]]
) -> None:
    click.echo(click.style("→ Dead-tuple bloat", bold=True))
    if not os.path.exists(compose_file):
        click.echo("  skipping — no compose file")
        results.append({"component": "Dead-tuple bloat", "severity": "skipped", "detail": "no compose file"})
        return
    pg_user = cfg.get("pg_user") or DEFAULT_PG_USER
    pg_db = cfg.get("pg_db") or DEFAULT_PG_DB
    query = (
        "SELECT relname, n_dead_tup, n_live_tup "
        "FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 5;"
    )
    cmd = [
        "docker", "compose", "-f", compose_file, "exec", "-T", "postgres",
        "psql", "-U", pg_user, "-d", pg_db, "-At", "-F", "|", "-c", query,
    ]
    proc = _safe_run(cmd, timeout=30)
    if proc.returncode != 0:
        detail = f"psql failed: {(proc.stderr or proc.stdout).strip()[:140]}"
        click.echo(f"  {_doctor_status_marker('warning')} {detail}")
        results.append({"component": "Dead-tuple bloat", "severity": "warning", "detail": detail})
        return
    worst_severity = "ok"
    worst_detail = "no tables over threshold"
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        relname = parts[0]
        try:
            dead = int(parts[1])
            live = int(parts[2])
        except ValueError:
            continue
        severity = "warning" if dead > 100_000 else "ok"
        marker = _doctor_status_marker(severity)
        click.echo(f"  {marker} {relname.ljust(36)} dead={dead:>10,} live={live:>10,}")
        if severity == "warning" and worst_severity != "warning":
            worst_severity = "warning"
            worst_detail = f"{relname} has {dead:,} dead tuples"
    results.append({
        "component": "Dead-tuple bloat",
        "severity": worst_severity,
        "detail": worst_detail,
    })


def _doctor_check_config_vars(
    compose_file: str, results: list[dict[str, str]]
) -> None:
    click.echo(click.style("→ Config sanity", bold=True))
    env_path = os.path.join(os.path.dirname(compose_file), ".env")
    env = _parse_env_file(env_path)
    if not env:
        detail = f"no .env at {env_path}"
        click.echo(f"  {_doctor_status_marker('warning')} {detail}")
        results.append({"component": "Config vars", "severity": "warning", "detail": detail})
        return

    missing: list[str] = []
    for primary, aliases in REQUIRED_ENV_VARS:
        if (env.get(primary) or "").strip():
            click.echo(f"  {_doctor_status_marker('ok')} {primary}")
            continue
        alias_hit = next((a for a in aliases if (env.get(a) or "").strip()), None)
        if alias_hit:
            click.echo(f"  {_doctor_status_marker('ok')} {primary} (via {alias_hit})")
            continue
        click.echo(f"  {_doctor_status_marker('critical')} {primary} missing")
        missing.append(primary)

    # Reachability-domain ↔ CORS check (best effort).
    cors_origins = env.get("CORS_ORIGINS", "")
    if REACHABILITY_DOMAIN and REACHABILITY_DOMAIN not in cors_origins:
        click.echo(
            f"  {_doctor_status_marker('warning')} "
            f"CORS_ORIGINS does not include https://{REACHABILITY_DOMAIN}"
        )
        results.append({
            "component": "Config: CORS_ORIGINS",
            "severity": "warning",
            "detail": f"missing {REACHABILITY_DOMAIN}",
        })

    api_base = env.get("NEXT_PUBLIC_API_BASE_URL", "")
    if api_base and not api_base.rstrip("/").endswith("/api"):
        click.echo(
            f"  {_doctor_status_marker('warning')} "
            f"NEXT_PUBLIC_API_BASE_URL={api_base!r} does not end with /api"
        )
        results.append({
            "component": "Config: NEXT_PUBLIC_API_BASE_URL",
            "severity": "warning",
            "detail": f"value {api_base!r}",
        })

    if missing:
        results.append({
            "component": "Config vars",
            "severity": "critical",
            "detail": f"missing: {', '.join(missing)}",
        })
    else:
        results.append({"component": "Config vars", "severity": "ok", "detail": "all required vars set"})


def _doctor_check_domain(results: list[dict[str, str]]) -> None:
    click.echo(click.style("→ Domain reachability", bold=True))
    if not REACHABILITY_DOMAIN:
        click.echo("  skipping — no domain configured")
        results.append({"component": "Domain reachability", "severity": "skipped", "detail": "no domain"})
        return
    start = time.perf_counter()
    try:
        r = httpx.get(f"https://{REACHABILITY_DOMAIN}/health", timeout=5.0)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
    except httpx.HTTPError as exc:
        detail = f"unreachable ({type(exc).__name__})"
        click.echo(f"  {_doctor_status_marker('skipped')} {detail}")
        results.append({"component": "Domain reachability", "severity": "skipped", "detail": detail})
        return
    severity = "ok" if 200 <= r.status_code < 400 else "warning"
    detail = f"HTTP {r.status_code} ({elapsed_ms}ms)"
    click.echo(f"  {_doctor_status_marker(severity)} {detail}")
    results.append({"component": "Domain reachability", "severity": severity, "detail": detail})


def _doctor_print_summary(results: list[dict[str, str]]) -> int:
    click.echo()
    click.echo(click.style("Summary", bold=True))
    name_w = max(28, max((len(r["component"]) for r in results), default=10))
    status_w = 12
    probe_w = max(20, max((len(r.get("probe", "—")) for r in results), default=10))
    click.echo(
        f"{'Component'.ljust(name_w)}  {'Status'.ljust(status_w)}  "
        f"{'Probe'.ljust(probe_w)}  Detail"
    )
    click.echo("─" * (name_w + status_w + probe_w + 40))
    for r in results:
        sev = r.get("severity", "ok")
        label = {
            "ok": click.style("✅ ok", fg="green"),
            "warning": click.style("⚠️  warn", fg="yellow"),
            "critical": click.style("❌ critical", fg="red"),
            "skipped": click.style("⏭️  skipped", dim=True),
        }.get(sev, sev)
        probe = (r.get("probe") or "—")
        click.echo(
            f"{r['component'].ljust(name_w)}  {label.ljust(status_w)}  "
            f"{probe.ljust(probe_w)}  {r.get('detail', '')}"
        )

    worst = max((SEVERITY_RANK.get(r.get("severity", "ok"), 0) for r in results), default=0)
    if worst >= 2:
        return 2
    if worst >= 1:
        return 1
    return 0


@cli.command("doctor")
def doctor() -> None:
    """End-to-end deployment health check (Docker + API + Postgres + config).

    Each check runs independently and prints inline status; a final summary
    table aggregates everything. Exit code: 0 = all green, 1 = any warning,
    2 = any critical failure. Safe to run in cron / CI.
    """
    cfg = load_config()
    compose_file = _doctor_compose_file(cfg)
    click.echo(click.style(f"AuditLens doctor — {cfg['url']}", bold=True))
    click.echo(f"Compose file: {compose_file}")
    click.echo()

    results: list[dict[str, str]] = []

    # Each check is wrapped — one failure must never crash the run.
    for label, fn in (
        ("docker_services", lambda: _doctor_check_docker_services(compose_file, results)),
        ("forwarder", lambda: _doctor_check_forwarder(cfg, results)),
        ("api", lambda: _doctor_check_api(cfg, results)),
        ("postgres", lambda: _doctor_check_postgres(cfg, compose_file, results)),
        ("dead_tuples", lambda: _doctor_check_dead_tuples(cfg, compose_file, results)),
        ("config_vars", lambda: _doctor_check_config_vars(compose_file, results)),
        ("domain", lambda: _doctor_check_domain(results)),
    ):
        try:
            fn()
        except Exception as exc:  # pragma: no cover - defensive
            detail = f"{type(exc).__name__}: {exc}"
            click.echo(click.style(f"  ! check {label!r} crashed: {detail}", fg="red"))
            results.append({"component": label, "severity": "warning", "detail": detail})
        click.echo()

    code = _doctor_print_summary(results)
    sys.exit(code)


if __name__ == "__main__":
    cli()
