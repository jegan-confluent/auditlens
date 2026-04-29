from pathlib import Path

import http.client
import json
import socket
import textwrap
from urllib.error import URLError

import pytest

import scripts.bootstrap_auditlens as bootstrap_installer
from scripts.bootstrap_auditlens import SOURCE_CLUSTER_HELP
from src.product.bootstrap import (
    BootstrapError,
    BootstrapInputs,
    DOCKER_PERSISTENCE_VOLUME,
    HealthCheckResult,
    backup_file_if_exists,
    load_install_config_file,
    make_api_token,
    mask_secret,
    render_review_summary,
    render_env_file,
    render_k8s_secret,
    validate_bootstrap_format,
    validate_persistence_config,
    wait_for_http_json,
)


def _inputs() -> BootstrapInputs:
    return BootstrapInputs(
        audit_bootstrap="pkc-audit.us-west-2.aws.confluent.cloud:9092",
        audit_api_key="audit-key",
        audit_api_secret="audit-secret",
        dest_bootstrap="pkc-dest.us-west-2.aws.confluent.cloud:9092",
        dest_api_key="dest-key",
        dest_api_secret="dest-secret",
        deployment_mode="docker",
        api_auth_enabled=True,
        api_token_mode="generate",
    )


def test_mask_secret_masks_middle():
    assert mask_secret("abcdef123456") == "abcd...3456"
    assert mask_secret("short") == "****"


def test_make_api_token_generates_admin_scope():
    token, entries = make_api_token()
    assert len(token) == 40
    assert entries[0]["role"] == "admin"
    assert entries[0]["organizations"] == ["*"]


def test_render_env_file_sets_first_run_defaults():
    env_text = render_env_file(_inputs())
    assert "AUDIT_TOPIC=confluent-audit-log-events" in env_text
    assert "AUTO_OFFSET_RESET=earliest" in env_text
    assert "AUDIT_ENRICHED_TOPIC=audit.enriched.v1" in env_text
    assert "API_AUTH_ENABLED=true" in env_text
    assert "LANDING_PORT=8088" in env_text
    assert "DASHBOARD_PORT=8503" in env_text
    assert "MCP_PORT=8080" in env_text


def test_render_k8s_secret_includes_token_json():
    token_json = json.dumps([{"token": "abc", "actor_id": "admin", "role": "admin"}])
    rendered = render_k8s_secret(_inputs(), token_json)
    assert "name: auditlens-secrets" in rendered
    assert "API_AUTH_TOKENS_JSON" in rendered
    assert "AUDIT_BOOTSTRAP" in rendered


def test_validate_bootstrap_format_parses_host_and_port():
    host, port = validate_bootstrap_format("pkc-audit.us-west-2.aws.confluent.cloud:9092")
    assert host == "pkc-audit.us-west-2.aws.confluent.cloud"
    assert port == 9092


def test_render_review_summary_masks_secrets():
    summary = render_review_summary(_inputs())
    assert "audit-key" not in summary
    assert "audit-secret" not in summary
    assert "dest-key" not in summary
    assert "dest-secret" not in summary
    assert "audi...cret" in summary
    assert "****" in summary


def test_backup_file_if_exists_moves_existing_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n", encoding="utf-8")
    backup = backup_file_if_exists(path)
    assert backup is not None
    assert backup.exists()
    assert not path.exists()


def test_load_install_config_file_reads_yaml_and_coerces_values(tmp_path):
    config_path = tmp_path / "install.local.yaml"
    config_path.write_text(textwrap.dedent("""
        deployment_mode: docker
        source:
          display_name: Confluent Cloud Audit Logs
          bootstrap: pkc-audit.us-west-2.aws.confluent.cloud:9092
          api_key: audit-key
          api_secret: audit-secret
          audit_topic: confluent-audit-log-events
          group_id: auditlens-forwarder-v1
          auto_offset_reset: earliest
        destination:
          display_name: AuditLens Destination Cluster
          bootstrap: pkc-dest.us-west-2.aws.confluent.cloud:9092
          api_key: dest-key
          api_secret: dest-secret
          topics_exist: true
        schema_registry:
          enabled: false
        product:
          api_auth_enabled: true
          api_token_mode: generate
          dashboard_port: 8504
          metrics_port: 8004
          mcp_port: 8081
          landing_port: 8089
        persistence:
          enabled: true
          backend: sqlite
          db_path: /var/lib/auditlens/auditlens.db
    """).strip() + "\n", encoding="utf-8")

    result = load_install_config_file(config_path)

    assert result.inputs.audit_bootstrap == "pkc-audit.us-west-2.aws.confluent.cloud:9092"
    assert result.inputs.dest_bootstrap == "pkc-dest.us-west-2.aws.confluent.cloud:9092"
    assert result.inputs.topics_exist is True
    assert result.inputs.api_auth_enabled is True
    assert result.inputs.persistence_enabled is True
    assert result.inputs.metrics_port == 8004
    assert result.inputs.landing_port == 8089
    assert result.missing_required_fields == []
    assert result.placeholder_fields == []


def test_load_install_config_file_rejects_placeholders(tmp_path):
    config_path = tmp_path / "install.local.yaml"
    config_path.write_text(textwrap.dedent("""
        deployment_mode: docker
        source:
          bootstrap: REPLACE_ME
          api_key: REPLACE_ME
          api_secret: REPLACE_ME
        destination:
          bootstrap: pkc-dest.us-west-2.aws.confluent.cloud:9092
          api_key: dest-key
          api_secret: dest-secret
    """).strip() + "\n", encoding="utf-8")

    result = load_install_config_file(config_path)

    assert result.inputs.audit_bootstrap == ""
    assert result.placeholder_fields == [
        "source.api_key",
        "source.api_secret",
        "source.bootstrap",
    ]


def test_load_install_config_file_tracks_missing_required_fields(tmp_path):
    config_path = tmp_path / "install.local.yaml"
    config_path.write_text(textwrap.dedent("""
        deployment_mode: docker
        source:
          bootstrap: pkc-audit.us-west-2.aws.confluent.cloud:9092
          api_key: audit-key
        destination:
          bootstrap: pkc-dest.us-west-2.aws.confluent.cloud:9092
          api_key: dest-key
    """).strip() + "\n", encoding="utf-8")

    result = load_install_config_file(config_path)

    assert result.missing_required_fields == [
        "destination.api_secret",
        "source.api_secret",
    ]


def test_load_install_config_file_rejects_bad_boolean(tmp_path):
    config_path = tmp_path / "install.local.yaml"
    config_path.write_text(textwrap.dedent("""
        deployment_mode: docker
        source:
          bootstrap: pkc-audit.us-west-2.aws.confluent.cloud:9092
          api_key: audit-key
          api_secret: audit-secret
        destination:
          bootstrap: pkc-dest.us-west-2.aws.confluent.cloud:9092
          api_key: dest-key
          api_secret: dest-secret
          topics_exist: maybe
    """).strip() + "\n", encoding="utf-8")

    with pytest.raises(BootstrapError, match="destination.topics_exist"):
        load_install_config_file(config_path)


def test_gitignore_covers_local_install_files():
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
    content = gitignore.read_text(encoding="utf-8")
    assert "install.local.yaml" in content
    assert "install.*.local.yaml" in content
    assert "*.install.local.yaml" in content


def test_source_cluster_help_maps_cli_values_without_secrets():
    assert "confluent audit-log describe" in SOURCE_CLUSTER_HELP
    assert "confluent api-key create --service-account <SERVICE_ACCOUNT_ID> --resource <CLUSTER_ID>" in SOURCE_CLUSTER_HELP
    assert "source.audit_topic" in SOURCE_CLUSTER_HELP
    assert "source.bootstrap" in SOURCE_CLUSTER_HELP
    assert "not audit-log describe" in SOURCE_CLUSTER_HELP
    assert "api_secret: " not in SOURCE_CLUSTER_HELP


def test_persistence_preflight_fixes_volume_permissions_once(monkeypatch, tmp_path, capsys):
    calls: list[list[str]] = []

    def fake_run_checked(command, cwd=None, redacted=None):
        calls.append(command)
        if command[:3] == ["docker", "volume", "create"]:
            return None
        if "python:3.11-slim" in command and sum("python:3.11-slim" in call for call in calls) == 1:
            raise BootstrapError("Command failed: docker run persistence preflight\nPermission denied")
        return None

    monkeypatch.setattr("src.product.bootstrap.run_checked", fake_run_checked)

    result = validate_persistence_config(_inputs(), tmp_path)
    output = capsys.readouterr().out

    assert result.docker_volume_writable is True
    assert "Detected volume permission issue. Attempting automatic fix..." in output
    assert "Persistence volume permissions fixed successfully." in output
    assert calls[0] == ["docker", "volume", "create", DOCKER_PERSISTENCE_VOLUME]
    assert any("alpine" in call for call in calls)
    assert sum("python:3.11-slim" in call for call in calls) == 2


def test_persistence_preflight_fails_cleanly_after_fix_retry(monkeypatch, tmp_path):
    def fake_run_checked(command, cwd=None, redacted=None):
        if command[:3] == ["docker", "volume", "create"] or "alpine" in command:
            return None
        raise BootstrapError("Command failed: docker run persistence preflight\nPermission denied")

    monkeypatch.setattr("src.product.bootstrap.run_checked", fake_run_checked)

    with pytest.raises(BootstrapError, match="Persistence validation failed after automatic fix"):
        validate_persistence_config(_inputs(), tmp_path)


def test_persistence_preflight_does_not_fix_non_permission_failure(monkeypatch, tmp_path, capsys):
    calls: list[list[str]] = []

    def fake_run_checked(command, cwd=None, redacted=None):
        calls.append(command)
        if command[:3] == ["docker", "volume", "create"]:
            return None
        raise BootstrapError("Command failed: docker run persistence preflight\nimage pull failed")

    monkeypatch.setattr("src.product.bootstrap.run_checked", fake_run_checked)

    with pytest.raises(BootstrapError, match="image pull failed"):
        validate_persistence_config(_inputs(), tmp_path)

    assert "Detected volume permission issue" not in capsys.readouterr().out
    assert not any("alpine" in call for call in calls)


class _FakeHttpResponse:
    status = 200

    def __init__(self, body: bytes = b'{"status":"ok"}'):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_wait_for_http_json_retries_connection_reset_then_succeeds(monkeypatch):
    attempts = iter([
        ConnectionResetError(54, "Connection reset by peer"),
        _FakeHttpResponse(),
    ])

    def fake_urlopen(request, timeout):
        item = next(attempts)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr("src.product.bootstrap.urlopen", fake_urlopen)
    monkeypatch.setattr("src.product.bootstrap.time.sleep", lambda _seconds: None)

    result = wait_for_http_json("http://localhost:8003/health", timeout_seconds=5.0)

    assert result.status_code == 200
    assert result.payload == {"status": "ok"}


def test_wait_for_http_json_retries_connection_refused_then_succeeds(monkeypatch):
    attempts = iter([
        URLError(ConnectionRefusedError(61, "Connection refused")),
        _FakeHttpResponse(),
    ])

    def fake_urlopen(request, timeout):
        item = next(attempts)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr("src.product.bootstrap.urlopen", fake_urlopen)
    monkeypatch.setattr("src.product.bootstrap.time.sleep", lambda _seconds: None)

    result = wait_for_http_json("http://localhost:8003/health", timeout_seconds=5.0)

    assert result.payload["status"] == "ok"


def test_wait_for_http_json_timeout_reports_last_transient_error(monkeypatch):
    times = iter([0.0, 0.5, 1.5])

    def fake_urlopen(request, timeout):
        raise http.client.RemoteDisconnected("remote closed connection")

    monkeypatch.setattr("src.product.bootstrap.time.time", lambda: next(times))
    monkeypatch.setattr("src.product.bootstrap.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("src.product.bootstrap.urlopen", fake_urlopen)

    with pytest.raises(BootstrapError) as exc_info:
        wait_for_http_json("http://localhost:8003/health", timeout_seconds=1.0)

    message = str(exc_info.value)
    assert "Timed out waiting for forwarder health endpoint on http://localhost:8003/health" in message
    assert "RemoteDisconnected" in message
    assert "Traceback" not in message


def test_wait_for_http_json_retries_socket_timeout_then_succeeds(monkeypatch):
    attempts = iter([
        socket.timeout("timed out"),
        _FakeHttpResponse(),
    ])

    def fake_urlopen(request, timeout):
        item = next(attempts)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr("src.product.bootstrap.urlopen", fake_urlopen)
    monkeypatch.setattr("src.product.bootstrap.time.sleep", lambda _seconds: None)

    result = wait_for_http_json("http://localhost:8003/health", timeout_seconds=5.0)

    assert result.payload == {"status": "ok"}


def test_validate_runtime_accepts_forwarder_healthy_component_status(monkeypatch):
    calls: list[str] = []

    def fake_wait_for_http_json(url, timeout_seconds=60.0, headers=None):
        calls.append(url)
        if url.endswith(":8003/health"):
            return HealthCheckResult(
                status_code=200,
                payload={"recovery": {"replay_in_progress": False}},
            )
        return HealthCheckResult(
            status_code=200,
            payload={"components": [{"name": "persistence", "status": "healthy"}]},
        )

    monkeypatch.setattr(bootstrap_installer, "wait_for_http_json", fake_wait_for_http_json)
    monkeypatch.setattr(bootstrap_installer, "wait_for_http_status", lambda *args, **kwargs: 200)

    probe_health, api_health = bootstrap_installer.validate_runtime(_inputs())

    assert probe_health["recovery"]["replay_in_progress"] is False
    assert api_health["components"][0]["status"] == "healthy"
    assert calls == [
        "http://localhost:8003/health",
        "http://localhost:8003/api/v1/health",
    ]
