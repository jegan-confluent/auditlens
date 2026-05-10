#!/usr/bin/env python3
"""Guided AuditLens installation and validation flow."""

from __future__ import annotations

import argparse
import getpass
import json
import shlex
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


REPO_ROOT = Path(__file__).resolve().parent.parent


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


def prompt_text(label: str, *, default: str | None = None, secret: bool = False, help_text: str | None = None, required: bool = True) -> str:
    if help_text:
        print(textwrap.fill(help_text, width=100))
    suffix = f" [{default}]" if default not in {None, ''} else ""
    while True:
        if secret:
            value = getpass.getpass(f"{label}{suffix}: ")
        else:
            value = input(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            value = default
        if value or not required:
            return value
        print("This field is required.")


def prompt_bool(label: str, default: bool = True, help_text: str | None = None) -> bool:
    if help_text:
        print(textwrap.fill(help_text, width=100))
    suffix = " [Y/n]" if default else " [y/N]"
    raw = input(f"{label}{suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def prompt_choice(label: str, choices: list[str], default: str, help_text: str | None = None) -> str:
    if help_text:
        print(textwrap.fill(help_text, width=100))
    rendered = "/".join(choices)
    while True:
        value = input(f"{label} ({rendered}) [{default}]: ").strip().lower() or default
        if value in choices:
            return value
        print(f"Choose one of: {', '.join(choices)}")


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
            "Installer helpers require local Python dependencies from requirements.txt. "
            "Install them first with `pip install -r requirements.txt`."
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

    print("\nLoaded config file.")
    if load_result.placeholder_fields:
        print("These fields still use placeholders and will be requested interactively:")
        for field_name in load_result.placeholder_fields:
            print(f"- {field_name}")
    if load_result.missing_required_fields:
        print("These required fields are missing and will be requested interactively:")
        for field_name in load_result.missing_required_fields:
            print(f"- {field_name}")

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

    return inputs, token_json


def collect_interactive_inputs() -> tuple[BootstrapInputs, str | None]:
    inputs = BootstrapInputs()

    print("\nPhase 0. Local prerequisites")
    check_local_prerequisites(REPO_ROOT)
    print("Local prerequisites validated.\n")

    inputs.deployment_mode = prompt_choice(
        "Deployment mode",
        ["docker", "kubernetes"],
        "docker",
        help_text="Choose Docker for local first-time installation. Use Kubernetes only if you already have kubectl access and image delivery handled.",
    )

    print("\nPhase 1. Source cluster walkthrough")
    if prompt_bool(
        "Need help finding your source audit-log cluster details",
        default=False,
        help_text="Shows the Confluent CLI commands that identify the audit-log topic, cluster, service account, and API key path.",
    ):
        print_source_cluster_help()

    inputs.source_display_name = prompt_text(
        "Source cluster display name",
        default="Confluent Cloud Audit Logs",
        help_text="Display-only label used in installer summaries. This is not a Confluent technical ID and is safe to leave as the default.",
    )
    inputs.audit_bootstrap = prompt_text(
        "Source bootstrap endpoint",
        help_text="Required technical value. Example: pkc-xxxxx.us-west-2.aws.confluent.cloud:9092. Get it from the Kafka cluster settings for the audit-log cluster. It does not come from `confluent audit-log describe`.",
    )
    inputs.audit_api_key = prompt_text(
        "Source Kafka API key",
        secret=True,
        help_text="Required secret. Use a Kafka API key scoped to the audit-log cluster. Use `confluent api-key list --resource <CLUSTER_ID>` or create one for the service account from audit-log config.",
    )
    inputs.audit_api_secret = prompt_text(
        "Source Kafka API secret",
        secret=True,
        help_text="Required secret for the source Kafka API key. It is kept masked and never echoed back.",
    )
    inputs.audit_topic = prompt_text(
        "Source audit topic",
        default=SOURCE_AUDIT_TOPIC,
        help_text="Required technical value. Use the topic name from `confluent audit-log describe`. Confluent Cloud audit logs usually use confluent-audit-log-events.",
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
    source_result = validate_source_access(inputs)
    print(f"Source validated: topic={source_result.topic}, partitions={source_result.partitions}, retained_events={'yes' if source_result.retained_messages_present else 'no'}")

    print("\nPhase 2. Destination cluster walkthrough")
    inputs.destination_display_name = prompt_text(
        "Destination cluster display name",
        default="AuditLens Internal Kafka",
        help_text="A friendly label for the Kafka cluster where AuditLens writes raw, enriched, signal, alert, and DLQ topics.",
    )
    inputs.dest_bootstrap = prompt_text(
        "Destination bootstrap endpoint",
        help_text="Required. Example: pkc-yyyyy.ap-south-1.aws.confluent.cloud:9092.",
    )
    inputs.dest_api_key = prompt_text(
        "Destination Kafka API key",
        secret=True,
        help_text="Required. Must allow metadata access and preferably topic creation for the canonical AuditLens topics.",
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
    print(f"Destination validated: {len(dest_result.verified_topics)} canonical topics ready.")

    print("\nPhase 3. Schema Registry walkthrough")
    inputs.schema_registry_enabled = prompt_bool(
        "Use Schema Registry",
        default=False,
        help_text="Enable this only if your deployment uses Schema Registry and you want the installer to validate it up front.",
    )
    if inputs.schema_registry_enabled:
        inputs.schema_registry_url = prompt_text(
            "Schema Registry URL",
            help_text="Example: https://psrc-xxxxx.us-west-2.aws.confluent.cloud",
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
        print(f"Schema Registry validated: subjects_checked={'yes' if sr_result.subjects_checked else 'no'}, subject_count={sr_result.subject_count}")
    else:
        print("Schema Registry skipped.")

    print("\nPhase 4. Product/API settings")
    inputs.api_auth_enabled = prompt_bool(
        "Enable API authentication",
        default=True,
        help_text="Recommended. The installer can generate a secure local admin token file for first-time use.",
    )
    token_json = None
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

    print("\nPhase 5. Persistence validation")
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
        inputs.persistence_db_path = prompt_text(
            "SQLite DB path",
            default="/var/lib/auditlens/auditlens.db",
            help_text="The default path is mounted into a Docker named volume or Kubernetes PVC.",
        )
    persistence_result = validate_persistence_config(inputs, REPO_ROOT)
    print(f"Persistence validated: {persistence_result.message}")

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


def validate_flow(inputs: BootstrapInputs) -> bool:
    return wait_for_topic_message(
        inputs.dest_bootstrap,
        inputs.dest_api_key,
        inputs.dest_api_secret,
        inputs.audit_enriched_topic,
        timeout_seconds=45.0,
    )


def print_final_summary(
    inputs: BootstrapInputs,
    source_validated: bool,
    destination_validated: bool,
    schema_registry_status: str,
    persistence_validated: bool,
    services_started: bool,
    flow_visible: bool,
) -> None:
    print("")
    print("AuditLens guided installation summary")
    print(f"- source cluster validated: {'yes' if source_validated else 'no'}")
    print(f"- destination cluster validated: {'yes' if destination_validated else 'no'}")
    print(f"- Schema Registry validated: {schema_registry_status}")
    print(f"- persistence validated: {'yes' if persistence_validated else 'no'}")
    print(f"- services started: {'yes' if services_started else 'no'}")
    print(f"- dashboard URL: http://localhost:{inputs.dashboard_port}")
    print(f"- metrics URL: http://localhost:{inputs.metrics_port}/metrics")
    print(f"- API health URL: http://localhost:{inputs.metrics_port}/api/v1/health")
    if inputs.api_auth_enabled and inputs.generated_admin_token:
        print(f"- bootstrap admin token: {mask_secret(inputs.generated_admin_token)}")
        print(f"- bootstrap admin token file: {REPO_ROOT / 'secrets' / 'auditlens-bootstrap-admin.token'}")
    print(f"- enriched output visible: {'yes' if flow_visible else 'not yet'}")
    print("")
    if not flow_visible:
        print("If no events appear yet:")
        print("- confirm the audit-log cluster is receiving new events")
        print("- confirm the source topic still has retained data inside the default seven-day window")
        print("- check firewall or private networking paths for source and destination Kafka")
        print(f"- inspect forwarder logs: docker compose logs -f auditlens-forwarder")
        return

    if services_started and inputs.deployment_mode == "docker":
        print("")
        print("╔══════════════════════════════════════════════╗")
        print("║                                              ║")
        print("║   ✅  AuditLens is ready.                   ║")
        print("║                                              ║")
        print("║   Open http://localhost:3000                 ║")
        print("║                                              ║")
        print("║   Useful commands:                           ║")
        print("║     make status   — check pipeline health   ║")
        print("║     make logs     — follow forwarder logs   ║")
        print("║     make stop     — stop all services       ║")
        print("║                                              ║")
        print("╚══════════════════════════════════════════════╝")
        print("")


def main() -> int:
    parser = argparse.ArgumentParser(description="AuditLens guided installer")
    parser.add_argument("--config-file", help="YAML or JSON file for template-driven installation")
    args = parser.parse_args()

    try:
        ensure_python_deps()
        check_local_prerequisites(REPO_ROOT)

        if args.config_file:
            load_result = load_install_config_file(Path(args.config_file))
            inputs, token_json = _prompt_for_missing_from_config(load_result.inputs, load_result)
        else:
            inputs, token_json = collect_interactive_inputs()

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
        persistence_result = validate_persistence_config(inputs, REPO_ROOT)

        source_validated = bool(source_result.readable)
        destination_validated = bool(dest_result.verified_topics)
        schema_registry_status = "skipped"
        persistence_validated = persistence_result.enabled or inputs.persistence_enabled is False

        if inputs.schema_registry_enabled:
            validate_schema_registry_access(inputs)
            schema_registry_status = "yes"

        print("\nMasked review before write")
        print(render_review_summary(inputs))
        if stdin_is_interactive() and not prompt_bool("Write config and continue to startup", default=True):
            raise BootstrapError("Installer stopped before writing config.")

        backups = write_local_config(inputs, token_json)
        if backups:
            print("Backed up prior local config:")
            for backup in backups:
                print(f"- {backup}")

        port_forward_processes: list[subprocess.Popen[str]] = []
        services_started = False
        try:
            print("\nPhase 7. Startup")
            if inputs.deployment_mode == "docker":
                deploy_docker()
            else:
                pf_forwarder, pf_dashboard = deploy_kubernetes(inputs, token_json)
                port_forward_processes.extend([pf_forwarder, pf_dashboard])
            services_started = True

            print("Waiting for forwarder, persistence, metrics, dashboard, and API health...")
            validate_runtime(inputs)
            flow_visible = validate_flow(inputs)
        finally:
            for proc in port_forward_processes:
                proc.terminate()

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
        print("")
        print("AuditLens installation failed")
        print(textwrap.fill(str(exc), width=100))
        return 1


if __name__ == "__main__":
    sys.exit(main())
