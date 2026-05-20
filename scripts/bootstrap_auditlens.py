#!/usr/bin/env python3
"""Guided AuditLens installation and validation flow."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.product.bootstrap import (
    BootstrapError,
    BootstrapInputs,
    CANONICAL_TOPICS,
    ConfigLoadResult,
    DEFAULT_DASHBOARD_PORT,
    DEFAULT_LANDING_PORT,
    DEFAULT_MCP_PORT,
    DEFAULT_METRICS_PORT,
    SOURCE_AUDIT_TOPIC,
    backup_file_if_exists,
    check_local_prerequisites,
    docker_auth_headers,
    load_install_config_file,
    make_admin_password,
    make_api_token,
    mask_secret,
    render_env_file,
    render_k8s_configmap,
    render_k8s_namespace,
    render_k8s_pvc,
    render_k8s_secret,
    render_k8s_workloads,
    render_review_summary,
    render_secrets_env,
    render_token_json,
    run_checked,
    validate_destination_and_topics,
    validate_port_choices,
    validate_persistence_config,
    validate_schema_registry_access,
    validate_source_access,
    wait_for_http_json,
    wait_for_http_status,
    wait_for_topic_message,
    write_text_file,
)


# scripts/bootstrap_auditlens.py → parent (scripts/) → parent (repo root).
# .env, .secrets, and `docker compose -f docker-compose.prod.yml` all need
# the actual repo root, so this MUST resolve to the project directory.
REPO_ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────
# ANSI styling helpers. All check sys.stdout.isatty() so output stays
# clean when piped or running in CI (no escape codes leak into logs).
# Patterned after Vercel / Stripe CLI / Fly.io conventions: cyan for
# section headers + labels, dim for hints, green/yellow/red for state.
# ─────────────────────────────────────────────────────────────────────────
def _supports_color() -> bool:
    return sys.stdout.isatty()


def _wrap(code: str, text: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def cyan(text: str) -> str:    return _wrap("36", text)
def green(text: str) -> str:   return _wrap("32", text)
def yellow(text: str) -> str:  return _wrap("33", text)
def red(text: str) -> str:     return _wrap("31", text)
def bold(text: str) -> str:    return _wrap("1",  text)
def dim(text: str) -> str:     return _wrap("2",  text)


def link(url: str, label: str | None = None) -> str:
    """OSC 8 hyperlink — clickable in modern terminals (iTerm2, kitty,
    WezTerm, Windows Terminal, GNOME Terminal 3.26+). Falls back to plain
    text when stdout is not a tty so logs/CI stay readable."""
    text = label or url
    if not _supports_color():
        return text
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


# Per-credential URL hints. Used by prompt_text(url_hint=…) to print a
# clickable "Find it here" line under the field label so operators don't
# have to leave the terminal to look up Confluent Cloud paths.
URL_HINT_BOOTSTRAP        = "https://confluent.cloud (Cluster → Settings → Endpoints)"
URL_HINT_KAFKA_API_KEY    = "https://confluent.cloud (Cluster → API Keys)"
URL_HINT_CLOUD_API_KEY    = "https://confluent.cloud/settings/api-keys"
URL_HINT_SCHEMA_REGISTRY  = "https://confluent.cloud (Environment → Stream Governance API)"
URL_HINT_AUDIT_LOG_PAGE   = "https://confluent.cloud/settings/audit_logs/cli"


def ok_line(message: str) -> None:
    print(green(f"  ✅  {message}"))


def warn_line(message: str) -> None:
    print(yellow(f"  ⚠   {message}"))


def err_line(message: str) -> None:
    print(red(f"  ❌  {message}"))


def info_line(message: str) -> None:
    print(cyan(f"  ℹ   {message}"))


def skip_line(message: str) -> None:
    print(yellow(f"  ⏭   {message}"))


# ─────────────────────────────────────────────────────────────────────────
# Checkpoint state. After each phase passes we persist a small JSON file
# under $HOME so a failed install (Phase 3 timeout etc.) can resume on the
# next run instead of forcing the operator to re-enter source + dest creds.
# The file is chmod 600 because it stores raw API keys / secrets gathered
# during the wizard.
# ─────────────────────────────────────────────────────────────────────────
CHECKPOINT_PATH = Path.home() / ".auditlens_setup_checkpoint.json"
_CP_VERSION = "1"


def save_checkpoint(completed_phases: list, inputs) -> None:
    """Write progress after each phase passes. chmod 600."""
    d = {}
    if hasattr(inputs, "_asdict"):
        d = dict(inputs._asdict())
    elif hasattr(inputs, "__dict__"):
        d = vars(inputs).copy()
    data = {
        "version": _CP_VERSION,
        "completed_phases": sorted(set(completed_phases)),
        "inputs": d,
    }
    CHECKPOINT_PATH.write_text(json.dumps(data, indent=2))
    CHECKPOINT_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600


def load_checkpoint() -> dict | None:
    try:
        if not CHECKPOINT_PATH.exists():
            return None
        data = json.loads(CHECKPOINT_PATH.read_text())
        return data if data.get("version") == _CP_VERSION else None
    except Exception:
        return None


def delete_checkpoint() -> None:
    try:
        CHECKPOINT_PATH.unlink(missing_ok=True)
    except Exception:
        pass


_PHASE_LABELS = {
    0: "Local prerequisites",
    1: "Source cluster",
    2: "Destination cluster",
    3: "Schema Registry",
    4: "Product / API settings",
    5: "Persistence",
}


def _restore_inputs(inputs, saved: dict) -> None:
    """Copy saved field values back onto a fresh BootstrapInputs so skipped
    phases still have working credentials for later validation / config
    rendering. Unknown keys are ignored — the dataclass shape is the source
    of truth, not the checkpoint."""
    if not saved:
        return
    for key, value in saved.items():
        if hasattr(inputs, key):
            setattr(inputs, key, value)


# Phase headers map an internal phase number to a step counter so the
# operator sees consistent "N of 6" progress. Phase 7 (startup) renders
# as "Final step" — a deliberate label rather than a number.
_PHASE_TOTAL_STEPS = 6
_PHASE_STEP_INDEX = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6}


def print_phase_header(phase_num: int, title: str) -> None:
    step = _PHASE_STEP_INDEX.get(phase_num)
    if step is not None:
        filled = "■" * step + "□" * (_PHASE_TOTAL_STEPS - step)
        step_text = f"Step {step} of {_PHASE_TOTAL_STEPS}"
    else:
        filled = "■" * _PHASE_TOTAL_STEPS
        step_text = "Final step"
    bar_width = 60
    print()
    print(bold(cyan("━" * bar_width)))
    print(bold(cyan(f"  Phase {phase_num} — {title}")))
    print(bold(cyan("━" * bar_width)))
    print(dim(f"  [{filled}] {step_text}"))
    print()


def ensure_persistence_dir(inputs: BootstrapInputs) -> None:
    """Create the host directory backing inputs.persistence_db_path before
    the preflight docker run tries to open the file. On a fresh EC2 host
    /var/lib/auditlens does not exist; the bind-mount preflight inside the
    forwarder image then errors with `sqlite3.OperationalError: unable to
    open database file`. Best-effort: failures (no sudo, no write perm) are
    warned and ignored so the install still proceeds — docker compose
    itself creates the directory on first `up`.
    """
    if not inputs.persistence_enabled:
        return
    db_path = inputs.persistence_db_path or "/var/lib/auditlens/auditlens.db"
    target_dir = Path(db_path).parent
    if str(target_dir) in ("", "/") or target_dir.exists():
        return
    for cmd in (
        ["sudo", "mkdir", "-p", str(target_dir)],
        ["sudo", "chmod", "755", str(target_dir)],
    ):
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, timeout=10)
            if result.returncode != 0:
                warn_line(
                    f"Could not prepare {target_dir} (`{' '.join(cmd)}` exited {result.returncode}). "
                    "Docker compose will create it on first start."
                )
                return
        except Exception as exc:  # FileNotFoundError on no-sudo, etc.
            warn_line(
                f"Could not prepare {target_dir} ({exc.__class__.__name__}). "
                "Docker compose will create it on first start."
            )
            return


SOURCE_CLUSTER_HELP = """
Confluent Cloud audit-log source help

1. Log in:
   confluent login --save

2. Find the audit-log configuration:
   confluent audit-log describe

3. From that output, identify:
   - environment ID
   - cluster ID
   - service account ID
   - audit-log topic name

4. Select the audit-log environment and cluster if needed:
   confluent environment use <ENVIRONMENT_ID>
   confluent kafka cluster use <CLUSTER_ID>

5. Find or create a Kafka API key for that audit-log cluster:
   confluent api-key list --resource <CLUSTER_ID>
   confluent api-key create --service-account <SERVICE_ACCOUNT_ID> --resource <CLUSTER_ID>

Field mapping:
- source.audit_topic -> topic name from `confluent audit-log describe`
- source.bootstrap -> Kafka bootstrap endpoint from the audit-log cluster settings, not audit-log describe
- source.api_key / source.api_secret -> Kafka API key and secret for the audit-log cluster
- source.display_name -> display-only label; safe to leave as default

Manual read test:
  confluent kafka topic consume --from-beginning <AUDIT_LOG_TOPIC>
"""


def print_source_cluster_help() -> None:
    print(textwrap.dedent(SOURCE_CLUSTER_HELP).strip())


def prompt_text(
    label: str,
    *,
    default: str | None = None,
    secret: bool = False,
    help_text: str | None = None,
    required: bool = True,
    url_hint: str | None = None,
) -> str:
    """Visual style: cyan label on its own line, dim wrapped help under it,
    optional clickable URL hint line, then a `→` prompt. Preserves the
    existing default + required + secret semantics — purely a presentation
    change.
    """
    print()
    print(cyan(f"  {label}"))
    if help_text:
        for line in textwrap.fill(help_text, width=88).splitlines():
            print(dim(f"    {line}"))
    if url_hint:
        print(dim(f"    Find it: {link(url_hint, url_hint)}"))
    suffix = f" [{default}]" if default not in {None, ""} else ""
    prompt_str = f"  → {suffix.strip()} " if suffix else "  → "
    while True:
        if secret:
            value = getpass.getpass(prompt_str)
        else:
            value = input(prompt_str).strip()
        if not value and default is not None:
            value = default
        if value or not required:
            return value
        err_line("This field is required.")


def prompt_bool(label: str, default: bool = True, help_text: str | None = None) -> bool:
    print()
    print(cyan(f"  {label}"))
    if help_text:
        for line in textwrap.fill(help_text, width=88).splitlines():
            print(dim(f"    {line}"))
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"  → {suffix} ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def prompt_choice(label: str, choices: list[str], default: str, help_text: str | None = None) -> str:
    print()
    print(cyan(f"  {label}"))
    if help_text:
        for line in textwrap.fill(help_text, width=88).splitlines():
            print(dim(f"    {line}"))
    rendered = "/".join(choices)
    while True:
        value = input(f"  → ({rendered}) [{default}] ").strip().lower() or default
        if value in choices:
            return value
        err_line(f"Choose one of: {', '.join(choices)}")


def prompt_int(label: str, default: int, help_text: str | None = None) -> int:
    while True:
        raw = prompt_text(label, default=str(default), help_text=help_text)
        try:
            return int(raw)
        except ValueError:
            print("Enter a numeric value.")


def ensure_python_deps() -> None:
    try:
        import confluent_kafka  # noqa: F401
        import yaml  # noqa: F401
    except Exception as exc:
        raise BootstrapError(
            "Installer helpers require local Python dependencies from requirements-setup.txt. "
            "Install them first with `pip install -r requirements-setup.txt`."
        ) from exc


def stdin_is_interactive() -> bool:
    return sys.stdin.isatty()


def prompt_missing_text(current: str, label: str, *, default: str | None = None, secret: bool = False, help_text: str | None = None, required: bool = True) -> str:
    if current:
        return current
    return prompt_text(label, default=default, secret=secret, help_text=help_text, required=required)


def prompt_missing_choice(current: str, label: str, choices: list[str], default: str, help_text: str | None = None) -> str:
    if current:
        return current
    return prompt_choice(label, choices, default, help_text=help_text)


def prompt_missing_int(current: int, label: str, default: int, help_text: str | None = None) -> int:
    if current not in {0, None}:
        return current
    return prompt_int(label, default, help_text=help_text)


def _validate_cc_credentials(api_key: str, api_secret: str, timeout_seconds: float = 10.0) -> int:
    """Probe GET /org/v2/environments. Returns the HTTP status code on a
    completed request (200 on success, 401/403/etc. on failure), or 0 on
    network / parse failure. The caller dispatches on the code to surface
    a specific error message (auth vs. permissions vs. transient)."""
    import base64
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError

    auth = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    try:
        req = Request("https://api.confluent.cloud/org/v2/environments", headers=headers)
        with urlopen(req, timeout=timeout_seconds) as resp:
            return resp.status
    except HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def _fetch_environments(
    api_key: str, api_secret: str, timeout_seconds: float = 10.0,
) -> tuple[int, list[dict] | None]:
    """GET /org/v2/environments → list of {id, display_name}.

    Returns (status_code, envs | None). HTTP / network failure surfaces
    via the status code (0 on transport error). Pagination across very
    large orgs is not handled — the eligible-cluster listing is purely
    informational, so showing the first page is fine."""
    import base64
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError

    auth = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    try:
        req = Request("https://api.confluent.cloud/org/v2/environments", headers=headers)
        with urlopen(req, timeout=timeout_seconds) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, None
    except Exception:
        return 0, None

    if status != 200:
        return status, None
    envs: list[dict] = []
    for item in (data.get("data") or []):
        envs.append({
            "id": (item.get("id") or "").strip(),
            "display_name": (item.get("display_name") or "").strip(),
        })
    return status, envs


def _fetch_clusters_for_env(
    api_key: str, api_secret: str, env_id: str, timeout_seconds: float = 10.0,
) -> list[dict]:
    """GET /cmk/v2/clusters?environment=<env_id> → list of clusters.

    Returns [{id, display_name, type, bootstrap}, ...] or an empty list
    on any failure. The cluster listing is informational only, so a
    per-env failure should just skip that env without blocking Phase 1.
    Bootstrap servers are stripped of the SASL_SSL:// scheme prefix so
    the display matches the form the operator pastes into .env."""
    import base64
    from urllib.request import Request, urlopen
    from urllib.parse import quote
    from urllib.error import HTTPError

    auth = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    url = f"https://api.confluent.cloud/cmk/v2/clusters?environment={quote(env_id)}"
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout_seconds) as resp:
            if resp.status != 200:
                return []
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError:
        return []
    except Exception:
        return []

    clusters: list[dict] = []
    for item in (data.get("data") or []):
        spec = item.get("spec") or {}
        config = spec.get("config") or {}
        kind = (config.get("kind") or "").strip()
        bootstrap = (spec.get("kafka_bootstrap_endpoint") or "").strip()
        if "://" in bootstrap:
            bootstrap = bootstrap.split("://", 1)[1]
        clusters.append({
            "id": (item.get("id") or "").strip(),
            "display_name": (spec.get("display_name") or "").strip(),
            "type": kind,
            "bootstrap": bootstrap,
        })
    return clusters


def _show_audit_log_directions() -> None:
    """STEP 1 of Phase 1: directions banner pointing the operator at the
    Confluent Cloud audit-logs CLI page where the bootstrap endpoint,
    cluster id, environment id, and topic name are all surfaced together.

    The audit-log cluster is system-managed and cannot be reliably
    discovered via the public REST API, so the wizard sends the operator
    to the UI for the authoritative values."""
    bar = "━" * 60
    print()
    print(bold(cyan(bar)))
    print(bold(cyan("  Finding your Audit Log cluster")))
    print(bold(cyan(bar)))
    print()
    print("  Open this URL to find your audit log cluster details:")
    print(f"  → {link(URL_HINT_AUDIT_LOG_PAGE)}")
    print()
    print("  You will see:")
    print(dim("    Cluster    : lkc-xxxxx"))
    print(dim("    Environment: env-xxxxx"))
    print(dim("    Topic      : confluent-audit-log-events"))
    print(dim("    Bootstrap  : pkc-xxxxx.region.aws.confluent.cloud:9092"))
    print()
    print("  Copy the bootstrap endpoint and create an API key when prompted below.")
    print()


def _show_eligible_clusters_for_reference(inputs: BootstrapInputs) -> None:
    """STEP 2 of Phase 1: optional informational listing.

    Prompts for a Cloud-scoped CC API key (key + secret). When provided
    and valid, hits /org/v2/environments and /cmk/v2/clusters to display
    the org's Standard/Dedicated clusters as reference — these are the
    candidates eligible to back an audit-log cluster. The listing is
    NOT a picker: the audit-log cluster bootstrap is separate from all
    of these and must be sourced from the audit_logs/cli page.

    Skip / invalid / transport failure all fall through silently to the
    manual prompts so a missing or weak Cloud API key never blocks the
    install. Cloud credentials are only persisted to inputs once the
    envs call succeeds, so partial attempts leave no stray creds in
    inputs (and therefore none in .secrets)."""
    api_key = inputs.cloud_api_key
    api_secret = inputs.cloud_api_secret
    if not api_key:
        api_key = prompt_text(
            "Confluent Cloud API key (optional — to show your eligible clusters)",
            secret=True,
            required=False,
            help_text=(
                "Cloud-scoped key from https://confluent.cloud/settings/api-keys. "
                "Used only to display eligible clusters for reference. "
                "Press Enter to skip."
            ),
            url_hint=URL_HINT_CLOUD_API_KEY,
        )
    if api_key and not api_secret:
        api_secret = prompt_text(
            "Confluent Cloud API secret",
            secret=True,
            required=False,
        )
    if not (api_key and api_secret):
        return

    val_status = _validate_cc_credentials(api_key, api_secret)
    if val_status != 200:
        # Silent skip — informational listing only, the manual prompts
        # below still let the operator complete Phase 1.
        return

    env_status, envs = _fetch_environments(api_key, api_secret)
    if env_status != 200 or not envs:
        return

    # Persist the validated cloud creds so resume + render_secrets reuse
    # them, but only after the envs call has actually succeeded.
    inputs.cloud_api_key = api_key
    inputs.cloud_api_secret = api_secret

    eligible_rows: list[tuple[str, str, str, str, str]] = []
    basic_excluded = 0
    for env in envs:
        env_id = env["id"]
        env_name = env["display_name"]
        for cluster in _fetch_clusters_for_env(api_key, api_secret, env_id):
            kind = cluster["type"]
            if kind.lower() == "basic":
                basic_excluded += 1
                continue
            eligible_rows.append((
                env_id, env_name, cluster["display_name"], kind, cluster["bootstrap"],
            ))

    if not eligible_rows:
        if basic_excluded:
            print()
            info_line(
                f"({basic_excluded} Basic clusters excluded — audit logs not supported)"
            )
        return

    # Width-align env-id / cluster-name / type for a readable column layout.
    env_width  = max(len(f"{r[0]} / {r[1]}") for r in eligible_rows)
    name_width = max(len(r[2]) for r in eligible_rows)
    print()
    info_line("Clusters eligible for audit logs in your org:")
    for env_id, env_name, name, kind, bootstrap in eligible_rows:
        env_label = f"{env_id} / {env_name}".ljust(env_width)
        n_label   = name.ljust(name_width)
        k_label   = f"[{kind}]"
        print(dim(f"     {env_label}   {n_label}  {k_label} — {bootstrap}"))
    if basic_excluded:
        print(dim(
            f"     ({basic_excluded} Basic clusters excluded — "
            "audit logs not supported)"
        ))
    print()
    info_line("Your audit log cluster bootstrap is separate from these.")
    print(dim(f"     Find it at: {link(URL_HINT_AUDIT_LOG_PAGE)}"))
    print()


def _prompt_for_missing_from_config(inputs: BootstrapInputs, load_result: ConfigLoadResult) -> tuple[BootstrapInputs, str | None]:
    if load_result.placeholder_fields and not stdin_is_interactive():
        raise BootstrapError(
            "The config file still contains placeholder values for: "
            + ", ".join(load_result.placeholder_fields)
        )
    if load_result.missing_required_fields and not stdin_is_interactive():
        raise BootstrapError(
            "The config file is missing required values for: "
            + ", ".join(load_result.missing_required_fields)
        )

    print()
    info_line("Loaded config file.")
    if load_result.placeholder_fields:
        warn_line("These fields still use placeholders and will be requested interactively:")
        for field_name in load_result.placeholder_fields:
            print(dim(f"      • {field_name}"))
    if load_result.missing_required_fields:
        warn_line("These required fields are missing and will be requested interactively:")
        for field_name in load_result.missing_required_fields:
            print(dim(f"      • {field_name}"))

    token_json = None

    inputs.source_display_name = prompt_missing_text(
        inputs.source_display_name,
        "Source cluster display name",
        default="Confluent Cloud Audit Logs",
    )
    inputs.audit_bootstrap = prompt_missing_text(
        inputs.audit_bootstrap,
        "Source bootstrap endpoint",
        help_text="Required. Example: pkc-xxxxx.us-west-2.aws.confluent.cloud:9092.",
    )
    inputs.audit_api_key = prompt_missing_text(
        inputs.audit_api_key,
        "Source Kafka API key",
        secret=True,
    )
    inputs.audit_api_secret = prompt_missing_text(
        inputs.audit_api_secret,
        "Source Kafka API secret",
        secret=True,
    )

    inputs.destination_display_name = prompt_missing_text(
        inputs.destination_display_name,
        "Destination cluster display name",
        default="AuditLens Internal Kafka",
    )
    inputs.dest_bootstrap = prompt_missing_text(
        inputs.dest_bootstrap,
        "Destination bootstrap endpoint",
    )
    inputs.dest_api_key = prompt_missing_text(
        inputs.dest_api_key,
        "Destination Kafka API key",
        secret=True,
    )
    inputs.dest_api_secret = prompt_missing_text(
        inputs.dest_api_secret,
        "Destination Kafka API secret",
        secret=True,
    )

    if inputs.schema_registry_enabled:
        inputs.schema_registry_url = prompt_missing_text(inputs.schema_registry_url, "Schema Registry URL")
        inputs.schema_registry_api_key = prompt_missing_text(inputs.schema_registry_api_key, "Schema Registry API key", secret=True)
        inputs.schema_registry_api_secret = prompt_missing_text(inputs.schema_registry_api_secret, "Schema Registry API secret", secret=True)

    if inputs.api_auth_enabled:
        if inputs.api_token_mode == "generate":
            if not inputs.generated_admin_token:
                generated_token, entries = make_api_token()
                inputs.generated_admin_token = generated_token
                token_json = render_token_json(entries)
        elif inputs.api_token_mode == "existing":
            token_file = Path(inputs.api_auth_token_file or prompt_text("Existing API token file path", default=str(REPO_ROOT / "secrets" / "auditlens-api-tokens.json")))
            if not token_file.exists():
                raise BootstrapError(f"API token file does not exist: {token_file}")
            token_json = token_file.read_text(encoding="utf-8")
            payload = json.loads(token_json)
            if not isinstance(payload, list) or not payload or "token" not in payload[0]:
                raise BootstrapError("Existing API token file must contain a non-empty list of token objects.")
            inputs.generated_admin_token = payload[0]["token"]
            inputs.api_auth_token_file = "/run/secrets/auditlens-api-tokens.json"

    # docker-compose.prod.yml requires POSTGRES_PASSWORD and
    # GRAFANA_ADMIN_PASSWORD; auto-generate them the same way the API auth
    # token is generated. Skip if a checkpoint already restored a value so
    # the same password survives across resumes.
    if not inputs.postgres_password:
        inputs.postgres_password = make_admin_password()
    if not inputs.grafana_admin_password:
        inputs.grafana_admin_password = make_admin_password()

    return inputs, token_json


def _reconstruct_token_json_on_resume(inputs: BootstrapInputs) -> str | None:
    """When phase 4 was already completed and the operator is resuming, the
    in-memory token_json has been lost (it was never persisted). Rebuild it
    from inputs so write_local_config still writes
    secrets/auditlens-api-tokens.json. Only "generate" mode is fully
    reconstructable from the checkpoint alone; "existing" mode returns None
    and falls back to the file that should already be on disk."""
    if not inputs.api_auth_enabled or not inputs.generated_admin_token:
        return None
    if inputs.api_token_mode != "generate":
        return None
    entries = [{
        "token": inputs.generated_admin_token,
        "actor_id": "auditlens-bootstrap-admin",
        "role": "admin",
        "organizations": ["*"],
        "environments": ["*"],
        "clusters": ["*"],
    }]
    return render_token_json(entries)


def collect_interactive_inputs(
    completed: list[int] | None = None,
    saved: dict | None = None,
) -> tuple[BootstrapInputs, str | None]:
    inputs = BootstrapInputs()
    _restore_inputs(inputs, saved or {})
    if completed is None:
        completed = []
    token_json: str | None = None

    # docker-compose.prod.yml requires POSTGRES_PASSWORD and
    # GRAFANA_ADMIN_PASSWORD; generate ONCE at the top of the wizard so the
    # values are included in every phase's save_checkpoint snapshot. On
    # resume, _restore_inputs has already restored them from the checkpoint,
    # so `if not …` is false and we don't regenerate — preserving the
    # password baked into the postgres data volume from the first attempt.
    if not inputs.postgres_password:
        inputs.postgres_password = make_admin_password()
    if not inputs.grafana_admin_password:
        inputs.grafana_admin_password = make_admin_password()

    # ── Phase 0 ─────────────────────────────────────────────────────────
    if 0 in completed:
        skip_line(f"Phase 0 ({_PHASE_LABELS[0]}) already done — skipping.")
    else:
        print_phase_header(0, "Local prerequisites")
        check_local_prerequisites(REPO_ROOT)
        ok_line("Local prerequisites validated.")
        print()

        # Kubernetes path is currently vestigial (no dashboard/Dockerfile, no
        # api/postgres/frontend/caddy in the rendered manifests, no registry
        # push for real clusters). Restrict the interactive prompt to docker
        # so operators don't burn five phases of prompts before hitting a
        # crash. A separate guard in main() catches the same case for
        # --config-file mode and exits cleanly with a doc pointer.
        inputs.deployment_mode = prompt_choice(
            "Deployment mode",
            ["docker"],
            "docker",
            help_text="Docker is the only supported mode in this release. Kubernetes support is on the roadmap (manual install: deploy/kubernetes/README.md).",
        )
        completed.append(0)
        save_checkpoint(completed, inputs)
        ok_line("Progress saved.")

    # ── Phase 1 ─────────────────────────────────────────────────────────
    if 1 in completed:
        skip_line(f"Phase 1 ({_PHASE_LABELS[1]}) already done — skipping.")
    else:
        print_phase_header(1, "Source cluster walkthrough")
        if prompt_bool(
            "Need help finding your source audit-log cluster details",
            default=False,
            help_text="Shows the Confluent CLI commands that identify the audit-log topic, cluster, service account, and API key path.",
        ):
            print_source_cluster_help()

        # STEP 1 — directions banner.
        # The audit-log cluster is system-managed and cannot be
        # auto-discovered via the public REST API, so point the operator
        # at the audit_logs/cli page where the bootstrap, cluster id,
        # env id, and topic name are all shown together.
        _show_audit_log_directions()

        # STEP 2 — optional reference listing of eligible (Standard /
        # Dedicated) clusters in the operator's org. This is NOT a picker
        # — the audit-log cluster bootstrap is separate from all of them.
        # The function handles its own skip/failure case silently so a
        # missing or weak Cloud API key never blocks the install.
        _show_eligible_clusters_for_reference(inputs)

        # STEP 3 — manual source-cluster prompts.
        inputs.source_display_name = prompt_text(
            "Source cluster display name",
            default="Confluent Cloud Audit Logs",
            help_text="Display-only label used in installer summaries. This is not a Confluent technical ID and is safe to leave as the default.",
        )
        inputs.audit_bootstrap = prompt_text(
            "Source bootstrap endpoint",
            help_text=(
                f"From {URL_HINT_AUDIT_LOG_PAGE}. "
                "Example: pkc-xxxxx.us-west-2.aws.confluent.cloud:9092."
            ),
            url_hint=URL_HINT_AUDIT_LOG_PAGE,
        )
        inputs.audit_api_key = prompt_text(
            "Audit log Kafka API key",
            secret=True,
            help_text=(
                "Scoped to the audit log cluster only. "
                "Create one on the audit logs page or via "
                "`confluent api-key create --service-account <sa-id> --resource <cluster-id>`."
            ),
            url_hint=URL_HINT_KAFKA_API_KEY,
        )
        inputs.audit_api_secret = prompt_text(
            "Audit log Kafka API secret",
            secret=True,
            help_text="Required secret for the audit log Kafka API key. Kept masked and never echoed back.",
        )
        inputs.audit_topic = prompt_text(
            "Source audit topic",
            default=SOURCE_AUDIT_TOPIC,
            help_text="Confluent Cloud audit logs use confluent-audit-log-events by default.",
        )
        inputs.group_id = prompt_text(
            "Consumer group",
            default="auditlens-forwarder-v1",
            help_text="Required. This controls Kafka-managed offsets for the forwarder.",
        )
        inputs.auto_offset_reset = prompt_choice(
            "Offset reset policy",
            ["earliest", "latest"],
            "earliest",
            help_text="Use earliest for first-time installs if you want to inspect retained audit history. Use latest if you only want new events.",
        )

        # STEP 4 — existing source validation (unchanged).
        source_result = validate_source_access(inputs)
        ok_line(
            f"Source validated — topic={source_result.topic}, partitions={source_result.partitions}, "
            f"retained_events={'yes' if source_result.retained_messages_present else 'no'}"
        )
        completed.append(1)
        save_checkpoint(completed, inputs)
        ok_line("Progress saved.")

    # ── Phase 2 ─────────────────────────────────────────────────────────
    if 2 in completed:
        skip_line(f"Phase 2 ({_PHASE_LABELS[2]}) already done — skipping.")
    else:
        print_phase_header(2, "Destination cluster walkthrough")
        inputs.destination_display_name = prompt_text(
            "Destination cluster display name",
            default="AuditLens Internal Kafka",
            help_text="A friendly label for the Kafka cluster where AuditLens writes raw, enriched, signal, alert, and DLQ topics.",
        )
        inputs.dest_bootstrap = prompt_text(
            "Destination bootstrap endpoint",
            help_text="Example: pkc-yyyyy.ap-south-1.aws.confluent.cloud:9092.",
            url_hint=URL_HINT_BOOTSTRAP,
        )
        inputs.dest_api_key = prompt_text(
            "Destination Kafka API key",
            secret=True,
            help_text="Must allow metadata access and preferably topic creation for the canonical AuditLens topics.",
            url_hint=URL_HINT_KAFKA_API_KEY,
        )
        inputs.dest_api_secret = prompt_text(
            "Destination Kafka API secret",
            secret=True,
            help_text="Required. Kept masked and never echoed back.",
        )
        inputs.topics_exist = prompt_bool(
            "Do the canonical destination topics already exist",
            default=False,
            help_text="If you answer no, the installer will try to create the canonical topics: "
                      + ", ".join(CANONICAL_TOPICS),
        )
        dest_result = validate_destination_and_topics(inputs, create_missing_topics=not inputs.topics_exist)
        ok_line(f"Destination validated — {len(dest_result.verified_topics)} canonical topics ready.")
        completed.append(2)
        save_checkpoint(completed, inputs)
        ok_line("Progress saved.")

    # ── Phase 3 ─────────────────────────────────────────────────────────
    if 3 in completed:
        skip_line(f"Phase 3 ({_PHASE_LABELS[3]}) already done — skipping.")
    else:
        print_phase_header(3, "Schema Registry walkthrough")
        inputs.schema_registry_enabled = prompt_bool(
            "Use Schema Registry",
            default=False,
            help_text="Enable this only if your deployment uses Schema Registry and you want the installer to validate it up front.",
        )
        if inputs.schema_registry_enabled:
            inputs.schema_registry_url = prompt_text(
                "Schema Registry URL",
                help_text="Example: https://psrc-xxxxx.us-west-2.aws.confluent.cloud",
                url_hint=URL_HINT_SCHEMA_REGISTRY,
            )
            inputs.schema_registry_api_key = prompt_text(
                "Schema Registry API key",
                secret=True,
                help_text="Required only when Schema Registry is enabled.",
            )
            inputs.schema_registry_api_secret = prompt_text(
                "Schema Registry API secret",
                secret=True,
                help_text="Required only when Schema Registry is enabled.",
            )
            sr_result = validate_schema_registry_access(inputs)
            ok_line(
                f"Schema Registry validated — subjects_checked="
                f"{'yes' if sr_result.subjects_checked else 'no'}, subject_count={sr_result.subject_count}"
            )
        else:
            skip_line("Schema Registry skipped.")
        completed.append(3)
        save_checkpoint(completed, inputs)
        ok_line("Progress saved.")

    # ── Phase 4 ─────────────────────────────────────────────────────────
    if 4 in completed:
        skip_line(f"Phase 4 ({_PHASE_LABELS[4]}) already done — skipping.")
        token_json = _reconstruct_token_json_on_resume(inputs)
    else:
        print_phase_header(4, "Product / API settings")
        inputs.api_auth_enabled = prompt_bool(
            "Enable API authentication",
            default=True,
            help_text="Recommended. The installer can generate a secure local admin token file for first-time use.",
        )
        if inputs.api_auth_enabled:
            inputs.api_token_mode = prompt_choice(
                "API auth token mode",
                ["generate", "existing"],
                "generate",
                help_text="Choose generate for a local first-use token, or existing to point at a prepared token JSON file.",
            )
            if inputs.api_token_mode == "generate":
                generated_token, entries = make_api_token()
                inputs.generated_admin_token = generated_token
                token_json = render_token_json(entries)
            else:
                existing_token_path = Path(prompt_text(
                    "Existing API token file path",
                    default=str(REPO_ROOT / "secrets" / "auditlens-api-tokens.json"),
                    help_text="Path to a JSON file containing API auth token records.",
                ))
                if not existing_token_path.exists():
                    raise BootstrapError(f"Token file does not exist: {existing_token_path}")
                token_json = existing_token_path.read_text(encoding="utf-8")
                payload = json.loads(token_json)
                if not isinstance(payload, list) or not payload or "token" not in payload[0]:
                    raise BootstrapError("Existing API token file must contain a non-empty list of token objects.")
                inputs.generated_admin_token = payload[0]["token"]
            inputs.api_auth_token_file = "/run/secrets/auditlens-api-tokens.json"
        else:
            inputs.api_token_mode = "disabled"
            inputs.generated_admin_token = ""

        inputs.dashboard_port = prompt_int(
            "Dashboard port",
            DEFAULT_DASHBOARD_PORT,
            help_text="Local browser port for Streamlit. Default 8503.",
        )
        inputs.metrics_port = prompt_int(
            "Metrics/API port",
            DEFAULT_METRICS_PORT,
            help_text="Local forwarder health, metrics, and API port. Default 8003.",
        )
        inputs.mcp_port = prompt_int(
            "MCP port",
            DEFAULT_MCP_PORT,
            help_text="Reserved for the optional future MCP profile. Keep it free even if you do not enable that profile now.",
        )
        inputs.landing_port = prompt_int(
            "Landing page port",
            DEFAULT_LANDING_PORT,
            help_text="Local single-entry AuditLens landing page port. Default 8088.",
        )
        validate_port_choices(
            inputs.metrics_port,
            inputs.dashboard_port,
            inputs.mcp_port,
            inputs.landing_port,
            allowed_in_use_ports=existing_auditlens_bound_ports(inputs),
        )

        inputs.alerting_webhook = prompt_text(
            "Optional generic alerting webhook",
            required=False,
            help_text="Optional. Basic format validation only. Leave blank to skip.",
        )
        inputs.slack_webhook = prompt_text(
            "Optional Slack webhook",
            required=False,
            help_text="Optional. Basic format validation only. Leave blank to skip.",
        )
        if inputs.alerting_webhook and not inputs.alerting_webhook.startswith(("http://", "https://")):
            raise BootstrapError("Alerting webhook must start with http:// or https://")
        if inputs.slack_webhook and not inputs.slack_webhook.startswith("https://"):
            raise BootstrapError("Slack webhook must start with https://")
        completed.append(4)
        save_checkpoint(completed, inputs)
        ok_line("Progress saved.")

    # ── Phase 5 ─────────────────────────────────────────────────────────
    if 5 in completed:
        skip_line(f"Phase 5 ({_PHASE_LABELS[5]}) already done — skipping.")
    else:
        print_phase_header(5, "Persistence validation")
        inputs.persistence_enabled = prompt_bool(
            "Enable persistence",
            default=True,
            help_text="Recommended. Persistence backs API search/export and replay-aware runtime state.",
        )
        if inputs.persistence_enabled:
            inputs.persistence_backend = prompt_choice(
                "Persistence backend",
                ["sqlite"],
                "sqlite",
                help_text="The current supported backend is sqlite.",
            )
            # Path depends on deployment mode because docker bind-mounts
            # ./data/forwarder as /app/data while k8s mounts the PVC at
            # /var/lib/auditlens. Suggesting the wrong default puts the DB
            # file on a tmpfs / unmounted path inside the container.
            default_db_path = (
                "/app/data/auditlens.db"
                if inputs.deployment_mode == "docker"
                else "/var/lib/auditlens/auditlens.db"
            )
            inputs.persistence_db_path = prompt_text(
                "SQLite DB path",
                default=default_db_path,
                help_text=(
                    "Docker bind-mounts ./data/forwarder as /app/data; "
                    "Kubernetes mounts a PVC at /var/lib/auditlens. The "
                    "default matches the deployment mode you picked."
                ),
            )
        # Prepare the host directory backing persistence_db_path so the
        # validate_persistence_config docker run does not fail with
        # `unable to open database file` on a fresh host. Best-effort.
        ensure_persistence_dir(inputs)
        try:
            persistence_result = validate_persistence_config(inputs, REPO_ROOT)
            ok_line(f"Persistence validated — {persistence_result.message}")
        except BootstrapError as exc:
            # Preflight is informational. Compose will create the bind-mount
            # path on first `up`, so a preflight miss is not fatal here.
            warn_line(
                f"Persistence preflight skipped: {exc}. "
                "Compose will create the host directory on first start."
            )
        completed.append(5)
        save_checkpoint(completed, inputs)
        ok_line("Progress saved.")

    # Postgres / Grafana passwords are generated at the top of this function
    # so every save_checkpoint above persists them; resumes restore the same
    # value and keep postgres-volume auth working.

    return inputs, token_json


def write_local_config(inputs: BootstrapInputs, token_json: str | None) -> list[Path]:
    env_path = REPO_ROOT / ".env"
    secrets_env_path = REPO_ROOT / ".secrets"
    token_file_path = REPO_ROOT / "secrets" / "auditlens-api-tokens.json"
    admin_token_path = REPO_ROOT / "secrets" / "auditlens-bootstrap-admin.token"

    backups: list[Path] = []
    for path in [env_path, secrets_env_path, token_file_path, admin_token_path]:
        backup = backup_file_if_exists(path)
        if backup:
            backups.append(backup)

    write_text_file(env_path, render_env_file(inputs), mode=0o600)
    write_text_file(secrets_env_path, render_secrets_env(inputs), mode=0o600)
    if token_json:
        write_text_file(token_file_path, token_json, mode=0o600)
    if inputs.generated_admin_token:
        write_text_file(admin_token_path, inputs.generated_admin_token + "\n", mode=0o600)
    return backups


def _ensure_host_directories() -> None:
    """Pre-create bind-mount host directories before `docker compose up`.
    When compose first sees a missing bind-mount source path, it creates the
    directory as root — that breaks the forwarder which runs as uid 1000
    and can't write into a root-owned /app/data on fresh EC2 hosts.

    forwarder bind-mounts ./data/forwarder as /app/data and ./secrets as
    /run/secrets. ./data/postgres and ./data/grafana are pre-created
    defensively in case future compose changes bind-mount them.

    Chown to the *current* user (typically uid 1000 on Amazon Linux
    ec2-user). On macOS this is a no-op for ownership purposes — Docker
    Desktop maps host ↔ container uid transparently.
    """
    paths = [
        REPO_ROOT / "data" / "forwarder",
        REPO_ROOT / "data" / "postgres",
        REPO_ROOT / "data" / "grafana",
        REPO_ROOT / "secrets",
    ]
    uid = os.geteuid()
    gid = os.getegid()
    for path in paths:
        os.makedirs(path, exist_ok=True)
        try:
            os.chown(path, uid, gid)
        except (PermissionError, OSError) as exc:
            # Best-effort: a directory we don't own (e.g. left by a prior
            # root-owned compose run) will refuse the chown — log but
            # continue. The operator can `sudo chown -R $USER:$USER data/`
            # manually if compose still complains about permissions.
            warn_line(f"Could not chown {path} ({exc.__class__.__name__}). Continuing.")

    # Named volume used by the api container at /var/lib/auditlens. Docker
    # creates new named volumes root-owned, which means the api process
    # (uid 1000) can't write to /var/lib/auditlens on first boot. Pre-create
    # the volume and chown it before `docker compose up` runs. Silent on
    # success; warns (does not exit) on failure so the wizard still gives
    # the api container a chance to come up.
    _ensure_named_volume_perms(
        volume_name="auditlens_auditlens_data",
        mount_path="/var/lib/auditlens",
        uid_gid="1000:1000",
        mode="755",
    )

    # Docker secrets backing the postgres + grafana _FILE indirections in
    # compose. The wizard prefers the EXISTING password value from .env so
    # a deploy with a pre-baked postgres data volume keeps authenticating
    # correctly. Only when .env is empty (fresh install) do we generate a
    # 32-char alphanumeric value.
    _ensure_secret_file(
        REPO_ROOT / "secrets" / "postgres_password.txt",
        env_var="POSTGRES_PASSWORD",
        label="Postgres password",
    )
    _ensure_secret_file(
        REPO_ROOT / "secrets" / "grafana_admin_password.txt",
        env_var="GRAFANA_ADMIN_PASSWORD",
        label="Grafana password",
    )


def _ensure_secret_file(path: Path, *, env_var: str, label: str) -> None:
    """Backfill a Docker-secret file from .env, or generate fresh.

    Priority order:
      1. If the file already exists and is non-empty → keep it (idempotent).
      2. Else if .env has a non-empty value for env_var → write that.
      3. Else generate a 32-char alphanumeric value and write it.

    chmod 600 in all cases. Failures are warn-not-fatal so a chmod
    refusal on macOS (where the file may have been created by Docker
    Desktop as a different uid) doesn't break the wizard."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text().strip():
        return
    value = _read_env_value(REPO_ROOT / ".env", env_var) or make_admin_password()
    try:
        path.write_text(value + "\n")
        path.chmod(0o600)
        ok_line(f"Generated {label} → secrets/{path.name}")
    except OSError as exc:
        warn_line(f"Could not write {path} ({exc.__class__.__name__}). Continuing.")


def _read_env_value(env_path: Path, key: str) -> str | None:
    """Return the value of ``key`` from an existing .env file, or None.

    Tolerates the usual .env quirks: missing file, comments, blank lines,
    quoted values. Does NOT use python-dotenv to avoid pulling in another
    dependency for one lookup."""
    if not env_path.exists():
        return None
    try:
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, val = line.partition("=")
            if name.strip() == key:
                val = val.strip().strip('"').strip("'")
                return val or None
    except OSError:
        return None
    return None


def _ensure_named_volume_perms(
    *, volume_name: str, mount_path: str, uid_gid: str, mode: str,
) -> None:
    """Create the named docker volume if missing, then chown + chmod its
    backing directory by running a throwaway alpine container with the
    volume mounted. Equivalent to the manual recovery command we used to
    print as a warning — just done automatically up-front. Failures here
    are non-fatal: compose will still try to start the container, and if
    the volume is already correctly owned the chown is idempotent."""
    # `docker volume create` is idempotent — exits 0 whether the volume
    # already existed or was just created. capture_output=True so we don't
    # leak noise into the wizard's own progress lines.
    subprocess.run(
        ["docker", "volume", "create", volume_name],
        capture_output=True, check=False, timeout=15,
    )
    chown_cmd = f"chown -R {uid_gid} {mount_path} && chmod {mode} {mount_path}"
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{volume_name}:{mount_path}",
                "alpine",
                "sh", "-c", chown_cmd,
            ],
            capture_output=True, check=False, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        warn_line(
            f"Could not set permissions on volume {volume_name} "
            f"({exc.__class__.__name__}) — startup may fail. "
            f"Manual fix: docker run --rm -v {volume_name}:{mount_path} alpine sh -c '{chown_cmd}'"
        )
        return
    if result.returncode != 0:
        warn_line(
            f"Could not set permissions on volume {volume_name} — startup may fail. "
            f"Manual fix: docker run --rm -v {volume_name}:{mount_path} alpine sh -c '{chown_cmd}'"
        )


def deploy_docker() -> None:
    run_checked(["docker", "compose", "up", "-d", "--build"], cwd=REPO_ROOT, redacted="docker compose up -d --build")


def _parse_port(output: str) -> int | None:
    value = output.strip()
    if not value or ":" not in value:
        return None
    try:
        return int(value.rsplit(":", 1)[1])
    except ValueError:
        return None


def existing_auditlens_bound_ports(inputs: BootstrapInputs) -> set[int]:
    if inputs.deployment_mode != "docker":
        return set()

    service_targets = [
        ("auditlens-forwarder", inputs.metrics_port),
        ("dashboard", 8501),
        ("landing", inputs.landing_port),
    ]
    ports: set[int] = set()
    for service, target_port in service_targets:
        try:
            result = run_checked(
                ["docker", "compose", "port", service, str(target_port)],
                cwd=REPO_ROOT,
                redacted=f"docker compose port {service}",
            )
        except BootstrapError:
            continue
        port = _parse_port(result.stdout)
        if port:
            ports.add(port)
    return ports


def shutil_which(binary: str) -> str | None:
    return subprocess.run(["bash", "-lc", f"command -v {shlex.quote(binary)}"], text=True, capture_output=True).stdout.strip() or None


def kubectl_current_context() -> str:
    try:
        return run_checked(["kubectl", "config", "current-context"]).stdout.strip()
    except BootstrapError:
        return ""


def build_k8s_images(inputs: BootstrapInputs) -> None:
    run_checked(["docker", "build", "-t", inputs.forwarder_image, "."], cwd=REPO_ROOT, redacted="docker build forwarder image")
    run_checked(["docker", "build", "-t", inputs.dashboard_image, "."], cwd=REPO_ROOT / "dashboard", redacted="docker build dashboard image")

    kind_path = shutil_which("kind")
    minikube_path = shutil_which("minikube")
    current_context = kubectl_current_context()
    if kind_path and current_context.startswith("kind-"):
        run_checked(["kind", "load", "docker-image", inputs.forwarder_image])
        run_checked(["kind", "load", "docker-image", inputs.dashboard_image])
    elif minikube_path and "minikube" in current_context:
        run_checked(["minikube", "image", "load", inputs.forwarder_image])
        run_checked(["minikube", "image", "load", inputs.dashboard_image])


def deploy_kubernetes(inputs: BootstrapInputs, token_json: str | None) -> tuple[subprocess.Popen[str], subprocess.Popen[str]]:
    if not shutil_which("kubectl"):
        raise BootstrapError("kubectl is required for Kubernetes install mode.")

    build_k8s_images(inputs)

    generated_dir = REPO_ROOT / "deploy" / "kubernetes" / "generated"
    write_text_file(generated_dir / "namespace.yaml", render_k8s_namespace(inputs), mode=0o600)
    write_text_file(generated_dir / "configmap.yaml", render_k8s_configmap(inputs), mode=0o600)
    write_text_file(generated_dir / "secret.yaml", render_k8s_secret(inputs, token_json), mode=0o600)
    write_text_file(generated_dir / "pvc.yaml", render_k8s_pvc(inputs), mode=0o600)
    write_text_file(generated_dir / "workloads.yaml", render_k8s_workloads(inputs), mode=0o600)

    for filename in ["namespace.yaml", "configmap.yaml", "secret.yaml", "pvc.yaml", "workloads.yaml"]:
        run_checked(["kubectl", "apply", "-f", str(generated_dir / filename)], cwd=REPO_ROOT, redacted=f"kubectl apply {filename}")

    run_checked(["kubectl", "rollout", "status", "deployment/auditlens-forwarder", "-n", inputs.namespace, "--timeout=180s"], cwd=REPO_ROOT)
    run_checked(["kubectl", "rollout", "status", "deployment/auditlens-dashboard", "-n", inputs.namespace, "--timeout=180s"], cwd=REPO_ROOT)

    forwarder_pf = subprocess.Popen(
        ["kubectl", "port-forward", "-n", inputs.namespace, "svc/auditlens-forwarder", f"{inputs.metrics_port}:{inputs.metrics_port}"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    dashboard_pf = subprocess.Popen(
        ["kubectl", "port-forward", "-n", inputs.namespace, "svc/auditlens-dashboard", f"{inputs.dashboard_port}:8501"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    time.sleep(5)
    return forwarder_pf, dashboard_pf


def validate_runtime(inputs: BootstrapInputs) -> tuple[dict, dict]:
    probe_health = wait_for_http_json(f"http://localhost:{inputs.metrics_port}/health", timeout_seconds=90.0)
    headers = docker_auth_headers(inputs.generated_admin_token) if inputs.api_auth_enabled else {}
    api_health = wait_for_http_json(f"http://localhost:{inputs.metrics_port}/api/v1/health", timeout_seconds=90.0, headers=headers)

    if not probe_health.payload.get("recovery"):
        raise BootstrapError("/health did not expose recovery status after startup.")
    if probe_health.payload["recovery"].get("replay_in_progress"):
        raise BootstrapError("Replay is unexpectedly running immediately after install.")
    persistence_component = next((c for c in api_health.payload.get("components", []) if c.get("name") == "persistence"), None)
    if not persistence_component or persistence_component.get("status") not in {"healthy", "ok", "degraded"}:
        raise BootstrapError("Forwarder started, but persistence did not report a healthy startup state.")

    wait_for_http_status(f"http://localhost:{inputs.dashboard_port}", timeout_seconds=90.0)
    wait_for_http_status(f"http://localhost:{inputs.metrics_port}/metrics", timeout_seconds=30.0)
    if inputs.deployment_mode == "docker":
        wait_for_http_status(f"http://localhost:{inputs.landing_port}", timeout_seconds=30.0)
    return probe_health.payload, api_health.payload


def _wait_for_http_with_progress(
    url: str,
    timeout_seconds: float,
    *,
    headers: dict[str, str] | None = None,
    expect_json: bool = False,
    progress_interval_seconds: float = 10.0,
) -> tuple[int, dict | None]:
    """Like wait_for_http_status / wait_for_http_json from bootstrap.py but
    prints a friendly `Still waiting... (Ns elapsed)` line every
    progress_interval_seconds so the operator doesn't think Phase 7 is
    frozen. Returns (status_code, payload | None); raises BootstrapError on
    timeout. Progress prints are throttled — never faster than the
    interval, even when the inner HTTP request returns quickly."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    start = time.time()
    deadline = start + timeout_seconds
    next_progress = start + progress_interval_seconds
    last_error = "unknown error"
    while time.time() < deadline:
        try:
            req = Request(url, headers=headers or {})
            with urlopen(req, timeout=5.0) as resp:
                if expect_json:
                    body = resp.read().decode("utf-8")
                    return resp.status, json.loads(body) if body else {}
                return resp.status, None
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except URLError as exc:
            last_error = f"URLError: {exc.reason}"
        except Exception as exc:  # noqa: BLE001 — best-effort polling
            last_error = f"{exc.__class__.__name__}: {exc}"
        now = time.time()
        if now >= next_progress:
            elapsed = int(now - start)
            info_line(f"Still waiting... ({elapsed}s elapsed)")
            next_progress = now + progress_interval_seconds
        time.sleep(1.0)
    raise BootstrapError(
        f"Timed out waiting for {url} after {int(time.time() - start)}s. "
        f"Last observed: {last_error}"
    )


def _validate_runtime_with_progress(inputs: BootstrapInputs) -> None:
    """Progress-aware health checks for the docker deployment. Hits each
    service on its direct host-bound port (compose maps 8080/3000 to
    127.0.0.1 explicitly so the wizard doesn't depend on caddy being up
    yet). The legacy Streamlit (8503) and landing-page (8088) checks were
    dropped because those containers no longer exist in
    docker-compose.prod.yml."""
    metrics_port = inputs.metrics_port

    info_line("Waiting for forwarder health endpoint...")
    _, probe_health = _wait_for_http_with_progress(
        f"http://localhost:{metrics_port}/health",
        timeout_seconds=90.0,
        expect_json=True,
    )
    if not probe_health or not probe_health.get("recovery"):
        raise BootstrapError("/health did not expose recovery status after startup.")
    if probe_health["recovery"].get("replay_in_progress"):
        raise BootstrapError("Replay is unexpectedly running immediately after install.")

    info_line("Waiting for forwarder metrics endpoint...")
    _wait_for_http_with_progress(
        f"http://localhost:{metrics_port}/metrics",
        timeout_seconds=30.0,
    )

    info_line("Waiting for API health endpoint (http://localhost:8080/health)...")
    _wait_for_http_with_progress(
        "http://localhost:8080/health",
        timeout_seconds=90.0,
    )

    info_line("Waiting for frontend (http://localhost:3000)...")
    _wait_for_http_with_progress(
        "http://localhost:3000",
        timeout_seconds=90.0,
    )


def validate_flow(inputs: BootstrapInputs) -> bool:
    return wait_for_topic_message(
        inputs.dest_bootstrap,
        inputs.dest_api_key,
        inputs.dest_api_secret,
        inputs.audit_enriched_topic,
        timeout_seconds=45.0,
    )


def get_ec2_public_ip(timeout_seconds: float = 1.5) -> str | None:
    """Fetch the EC2 public IPv4 from the IMDS endpoint. Tries IMDSv2 first
    (Amazon Linux 2023 + most modern AMIs default to IMDSv2-required which
    returns 401 to bare GETs); falls back to IMDSv1 for older instances.
    Returns None on any failure — non-EC2 hosts time out quickly and the
    caller silently falls back to its localhost default."""
    from urllib.request import Request, urlopen
    try:
        # IMDSv2: PUT a short-TTL token, then GET with the X-aws header.
        token: str | None = None
        try:
            token_req = Request(
                "http://169.254.169.254/latest/api/token",
                method="PUT",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            )
            with urlopen(token_req, timeout=timeout_seconds) as token_resp:
                token = token_resp.read().decode("ascii").strip()
        except Exception:
            token = None  # token endpoint refused — try v1 path below.

        headers: dict[str, str] = {}
        if token:
            headers["X-aws-ec2-metadata-token"] = token
        ip_req = Request(
            "http://169.254.169.254/latest/meta-data/public-ipv4",
            headers=headers,
        )
        with urlopen(ip_req, timeout=timeout_seconds) as resp:
            ip = resp.read().decode("ascii").strip()
            return ip or None
    except Exception:
        return None


def print_service_status_panel(inputs: BootstrapInputs) -> None:
    """Service status + quick-link panel printed after Phase 7 health
    checks pass. localhost links are useful when port-forwarding from the
    operator's laptop; the EC2 public-IP links are useful when ./setup ran
    directly on the instance and the operator is hitting it from elsewhere.
    On non-EC2 hosts the IMDS call times out and we fall back to localhost.
    """
    metrics_port = inputs.metrics_port
    public_ip = get_ec2_public_ip() or "localhost"

    print()
    print(bold(cyan("  SERVICE STATUS")))
    status_rows = [
        ("Forwarder", f"http://localhost:{metrics_port}/health"),
        ("API",       "http://localhost:8080/health"),
        ("Frontend",  "http://localhost:3000"),
    ]
    for label, url in status_rows:
        print(green(f"  ✅ {label.ljust(13)} — healthy  ({url})"))

    print()
    print(bold(cyan("  QUICK LINKS")))
    quick_rows = [
        ("🔍", "Frontend", f"http://{public_ip}:3000"),
        ("📡", "API",      f"http://{public_ip}:8080"),
        ("📊", "Metrics",  f"http://{public_ip}:{metrics_port}/metrics"),
    ]
    for icon, label, url in quick_rows:
        print(f"  {icon} {label.ljust(13)} : {link(url)}")
    print()


def _row(label: str, value: str, width: int = 41) -> str:
    """Render `│  label:    value <padding>│` so the box right edge lines up
    regardless of value length. Width is the inner box width (chars between
    the two `│`)."""
    raw = f"  {label}:".ljust(11) + value
    if len(raw) > width:
        raw = raw[: width - 1] + "…"
    return bold(cyan("│")) + raw.ljust(width) + bold(cyan("│"))


def print_final_summary(
    inputs: BootstrapInputs,
    source_validated: bool,
    destination_validated: bool,
    schema_registry_status: str,
    persistence_validated: bool,
    services_started: bool,
    flow_visible: bool,
) -> None:
    # ── Top: ready-to-launch box with the five operator-relevant facts ──
    print()
    inner_width = 41
    print(bold(cyan("┌" + "─" * inner_width + "┐")))
    title = "  AuditLens is ready to launch"
    print(bold(cyan("│")) + title.ljust(inner_width) + bold(cyan("│")))
    print(bold(cyan("├" + "─" * inner_width + "┤")))
    print(_row("Source",  inputs.source_display_name or "(unset)", inner_width))
    print(_row("Dest",    inputs.destination_display_name or "(unset)", inner_width))
    print(_row("Auth",    "enabled" if inputs.api_auth_enabled else "disabled", inner_width))
    storage_label = inputs.persistence_backend if inputs.persistence_enabled else "off"
    print(_row("Storage", storage_label or "(unset)", inner_width))
    print(_row("SR",      schema_registry_status, inner_width))
    print(bold(cyan("└" + "─" * inner_width + "┘")))
    print()

    # ── Validation roll-up ──
    def _state(ok: bool, label: str) -> None:
        (ok_line if ok else warn_line)(label)
    _state(source_validated,      "Source cluster validated")
    _state(destination_validated, "Destination cluster validated")
    if schema_registry_status == "yes":
        ok_line("Schema Registry validated")
    elif schema_registry_status == "skipped":
        skip_line("Schema Registry skipped")
    else:
        warn_line(f"Schema Registry: {schema_registry_status}")
    _state(persistence_validated, "Persistence validated")
    _state(services_started,      "Services started")
    if flow_visible:
        ok_line("Enriched output flowing")
    else:
        warn_line("Enriched output not yet visible — see troubleshooting below")
    print()

    # ── Access URLs ──
    # Match the SERVICE STATUS panel above: forwarder /metrics on 8003,
    # api /health on 8080, frontend on 3000. Dashboard:8503 (Streamlit)
    # and Landing:8088 are gone — those containers were removed from
    # docker-compose.prod.yml, so don't print dead links.
    if services_started and inputs.deployment_mode == "docker":
        frontend_url = "http://localhost:3000"
        api_url      = "http://localhost:8080/health"
        metrics_url  = f"http://localhost:{inputs.metrics_port}/metrics"
        print(bold(green("  AuditLens is running!")))
        print()
        print(f"  Frontend:  {link(frontend_url)}")
        print(f"  API:       {link(api_url)}")
        print(f"  Metrics:   {link(metrics_url)}")
        print()
        if inputs.api_auth_enabled and inputs.generated_admin_token:
            token_file = REPO_ROOT / "secrets" / "auditlens-bootstrap-admin.token"
            info_line(f"Bootstrap admin token: {mask_secret(inputs.generated_admin_token)}")
            info_line(f"Token file: {token_file}")
            print()
        print(dim("  To stop:    docker compose -f docker-compose.prod.yml down"))
        print(dim("  To restart: docker compose -f docker-compose.prod.yml up -d"))
        print(dim("  Logs:       docker logs auditlens-forwarder --tail=50 -f"))
        print(dim("  Status:     make status"))
        print()

    # ── Troubleshooting hints when nothing flowed yet ──
    if not flow_visible:
        print(yellow("  If no events appear yet:"))
        print(dim("    • confirm the audit-log cluster is receiving new events"))
        print(dim("    • confirm the source topic still has retained data inside the 7-day window"))
        print(dim("    • check firewall / private networking for source and destination Kafka"))
        print(dim("    • inspect forwarder logs: docker compose logs -f auditlens-forwarder"))
        print()


def _show_resume_prompt(cp: dict) -> list[int]:
    """Render the resume / start-fresh prompt for a checkpoint that already
    exists on disk. Returns the list of completed phase numbers to honour on
    this run (empty list if the operator chose to start fresh)."""
    completed_phases = list(cp.get("completed_phases", []))
    remaining = [p for p in [0, 1, 2, 3, 4, 5] if p not in completed_phases]
    next_label = _PHASE_LABELS.get(remaining[0], "Startup") if remaining else "Startup"

    print()
    print(bold(cyan("⚡  Previous setup found (was interrupted).")))
    done_label = ", ".join(_PHASE_LABELS[p] for p in completed_phases) or "none"
    print(f"   Already done : {done_label}")
    print(f"   Will resume  : {next_label}")
    print()
    ans = input("   Resume where you left off? [Y/n] ").strip().lower()
    if ans in ("", "y", "yes"):
        ok_line("Resuming — skipping completed phases…")
        return completed_phases
    ans2 = input("   Start fresh? Clears saved progress. [y/N] ").strip().lower()
    if ans2 in ("y", "yes"):
        delete_checkpoint()
        warn_line("Checkpoint cleared. Starting fresh.")
        return []
    print("Exiting.")
    sys.exit(0)


def _show_skip_setup_banner() -> None:
    """Print the one-shot 'edit .env yourself and skip the wizard' banner,
    then block on input() so the operator can read it. Ctrl-C / EOF exits
    cleanly rather than dropping into the wizard."""
    bar = "━" * 60
    print()
    print(bold(cyan(bar)))
    print(bold(cyan("  ⚡  Already know your cluster details? Skip the wizard.")))
    print(bold(cyan(bar)))
    print()
    print("    Edit .env directly and start with one command:")
    print()
    print(bold("      docker compose -f docker-compose.prod.yml up -d"))
    print()
    print("    Minimum .env fields needed:")
    print()
    print(dim("      # ── Source cluster (Confluent Cloud audit-log) ──────────"))
    print("      AUDIT_BOOTSTRAP=pkc-xxxxx.us-west-2.aws.confluent.cloud:9092")
    print("      AUDIT_API_KEY=ABCDE12345ABCDE")
    print("      AUDIT_API_SECRET=your+source+api+secret")
    print()
    print(dim("      # ── Destination cluster (AuditLens internal) ────────────"))
    print("      DEST_BOOTSTRAP=pkc-yyyyy.us-east-2.aws.confluent.cloud:9092")
    print("      DEST_API_KEY=FGHIJ67890FGHIJ")
    print("      DEST_API_SECRET=your+dest+api+secret")
    print()
    print("    Where to find these:")
    print(f"      Bootstrap endpoint : {link('https://confluent.cloud', 'Confluent Cloud')} → Cluster → Settings → Endpoints")
    print(f"      API keys           : {link('https://confluent.cloud', 'Confluent Cloud')} → Cluster → API Keys → + Add key")
    print()
    print(dim("    Press Enter to run the wizard, or Ctrl-C to quit."))
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print()
        print("Exiting setup.")
        sys.exit(0)


def main() -> int:
    parser = argparse.ArgumentParser(description="AuditLens guided installer")
    parser.add_argument("--config-file", help="YAML or JSON file for template-driven installation")
    args = parser.parse_args()

    completed: list[int] = []
    saved_inputs: dict = {}

    # Resume + skip-setup UX is interactive-only. Config-file mode is
    # template-driven (no operator at the keyboard) so we skip both.
    if not args.config_file and stdin_is_interactive():
        cp = load_checkpoint()
        if cp:
            completed = _show_resume_prompt(cp)
            saved_inputs = cp.get("inputs", {}) if completed else {}

        # The "edit .env yourself" hint only makes sense on a clean start.
        # Resuming operators have already started the wizard once.
        if not completed:
            _show_skip_setup_banner()

    try:
        ensure_python_deps()
        check_local_prerequisites(REPO_ROOT)

        if args.config_file:
            load_result = load_install_config_file(Path(args.config_file))
            inputs, token_json = _prompt_for_missing_from_config(load_result.inputs, load_result)
        else:
            inputs, token_json = collect_interactive_inputs(completed, saved_inputs)

        # Kubernetes deployment is unsupported in this release. The interactive
        # prompt no longer offers it, but config-file mode and any restored
        # checkpoint can still set deployment_mode="kubernetes". Catch that
        # here and exit cleanly before the wizard burns time on validation
        # that would crash at Phase 7 (no dashboard/Dockerfile, no full stack
        # in the rendered K8s manifests, no registry push for real clusters).
        if inputs.deployment_mode == "kubernetes":
            print()
            print(bold(yellow(
                "  ⚠️  Kubernetes deployment is not yet supported in this version of the setup wizard."
            )))
            print()
            print("      The Docker deployment path is fully tested and production-ready.")
            print("      Kubernetes support is on the roadmap.")
            print()
            print(f"      To deploy on Kubernetes manually, see: {link('deploy/kubernetes/README.md')}")
            print()
            sys.exit(0)

        validate_port_choices(
            inputs.metrics_port,
            inputs.dashboard_port,
            inputs.mcp_port,
            inputs.landing_port,
            allowed_in_use_ports=existing_auditlens_bound_ports(inputs),
        )
        source_result = validate_source_access(inputs)
        if not source_result.retained_messages_present:
            raise BootstrapError(
                "Source Kafka auth succeeded, but no retained audit events were found on the source topic. "
                "Likely causes: seven-day retention window already passed, or the audit-log cluster has not emitted events yet."
            )
        dest_result = validate_destination_and_topics(inputs, create_missing_topics=not inputs.topics_exist)
        ensure_persistence_dir(inputs)
        try:
            persistence_result = validate_persistence_config(inputs, REPO_ROOT)
            persistence_validated = (
                persistence_result.enabled or inputs.persistence_enabled is False
            )
        except BootstrapError as exc:
            warn_line(
                f"Persistence preflight skipped: {exc}. "
                "Compose will create the host directory on first start."
            )
            persistence_validated = inputs.persistence_enabled is False

        source_validated = bool(source_result.readable)
        destination_validated = bool(dest_result.verified_topics)
        schema_registry_status = "skipped"

        if inputs.schema_registry_enabled:
            validate_schema_registry_access(inputs)
            schema_registry_status = "yes"

        print()
        print(bold(cyan("  Masked review before write")))
        print(dim(render_review_summary(inputs)))
        if stdin_is_interactive() and not prompt_bool("Write config and continue to startup", default=True):
            raise BootstrapError("Installer stopped before writing config.")

        # Refuse to clobber a working .env with empty credentials.
        # write_local_config renames the existing .env to .env.backup.<ts>
        # then writes a fresh one — if any of these are empty here, the new
        # file would have empty AUDIT_BOOTSTRAP / DEST_BOOTSTRAP lines and
        # docker compose would start with a broken config. Fail loud while
        # the on-disk .env is still intact.
        _required_for_env = [
            ("audit_bootstrap", "Source bootstrap endpoint"),
            ("audit_api_key", "Source Kafka API key"),
            ("dest_bootstrap", "Destination bootstrap endpoint"),
            ("dest_api_key", "Destination Kafka API key"),
        ]
        _missing = [label for attr, label in _required_for_env if not getattr(inputs, attr, "")]
        if _missing:
            raise BootstrapError(
                "Refusing to write .env — required credentials are empty: "
                + ", ".join(_missing)
                + ". The current .env on disk has NOT been touched. "
                "Re-run ./setup and supply every credential."
            )

        backups = write_local_config(inputs, token_json)
        if backups:
            info_line("Backed up prior local config:")
            for backup in backups:
                print(dim(f"      • {backup}"))

        port_forward_processes: list[subprocess.Popen[str]] = []
        services_started = False
        try:
            print_phase_header(7, "Startup")
            if inputs.deployment_mode == "docker":
                _ensure_host_directories()
                info_line("Starting containers...")
                deploy_docker()
            else:
                pf_forwarder, pf_dashboard = deploy_kubernetes(inputs, token_json)
                port_forward_processes.extend([pf_forwarder, pf_dashboard])
            services_started = True

            if inputs.deployment_mode == "docker":
                _validate_runtime_with_progress(inputs)
            else:
                # Kubernetes path keeps the existing in-cluster health
                # contract; port-forwards above expose the same forwarder
                # endpoints validate_runtime expects.
                info_line("Waiting for forwarder, persistence, metrics, dashboard, and API health…")
                validate_runtime(inputs)
            flow_visible = validate_flow(inputs)
        finally:
            for proc in port_forward_processes:
                proc.terminate()

        # Health checks passed — show the service status + quick-link panel
        # before the legacy "ready to launch" summary.
        print_service_status_panel(inputs)

        # Compose up + runtime validation made it here — clear the checkpoint
        # so the next invocation starts fresh rather than offering to resume
        # a successful install.
        delete_checkpoint()

        print_final_summary(
            inputs,
            source_validated=source_validated,
            destination_validated=destination_validated,
            schema_registry_status=schema_registry_status,
            persistence_validated=persistence_validated,
            services_started=services_started,
            flow_visible=flow_visible,
        )
        return 0 if flow_visible else 2
    except BootstrapError as exc:
        print()
        print(bold(red("  ❌  AuditLens installation failed")))
        for line in textwrap.fill(str(exc), width=88).splitlines():
            print(red(f"      {line}"))
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
