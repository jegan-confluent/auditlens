"""Tests for src/core/secrets.py — Phase 6 of the AWS Secrets Manager
migration. All boto3 calls are mocked; no real AWS traffic."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from src.core import secrets as secrets_mod
from src.core.secrets import (
    clear_cache,
    get_secret,
    get_secret_dict,
    resolve_asm_reference,
    validate_secrets,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts with an empty TTL cache."""
    clear_cache()
    yield
    clear_cache()


# ─────────────────────────────────────────────────────────────────────────
# Env-var fallback path (AWS_SECRETS_MANAGER_ENABLED unset / false)
# ─────────────────────────────────────────────────────────────────────────


def test_get_secret_falls_back_to_env_when_asm_disabled(monkeypatch):
    """With AWS_SECRETS_MANAGER_ENABLED=false the env var wins
    immediately — no boto3 client should be constructed."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "false")
    monkeypatch.setenv("CONFLUENT_CLOUD_API_KEY", "k-from-env")
    with patch.object(secrets_mod, "_new_client") as mock_new_client:
        assert get_secret("CONFLUENT_CLOUD_API_KEY") == "k-from-env"
        mock_new_client.assert_not_called()


def test_get_secret_returns_none_when_neither_path_supplies(monkeypatch):
    """Missing in env AND ASM disabled → None (logs WARNING, no raise)."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "false")
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
    assert get_secret("DEFINITELY_NOT_SET") is None


def test_get_secret_does_not_raise_on_missing(monkeypatch):
    """Even with ASM enabled and a misconfigured boto3 client, missing
    secrets surface as None — never a raise."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "true")
    monkeypatch.delenv("UNKNOWN_SECRET", raising=False)
    with patch.object(secrets_mod, "_new_client") as mock_new_client:
        client = MagicMock()
        client.get_secret_value.side_effect = RuntimeError("ASM unreachable")
        mock_new_client.return_value = client
        assert get_secret("UNKNOWN_SECRET") is None


# ─────────────────────────────────────────────────────────────────────────
# ASM-primary path
# ─────────────────────────────────────────────────────────────────────────


def test_get_secret_pulls_from_asm_when_enabled(monkeypatch):
    """With ASM enabled, the routing table maps CONFLUENT_CLOUD_API_KEY
    to auditlens/{env}/confluent#cloud_api_key — and the mocked client
    returns the JSON body containing that field."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "true")
    monkeypatch.setenv("AUDITLENS_ENV", "prod")
    monkeypatch.setenv("CONFLUENT_CLOUD_API_KEY", "k-from-env-should-not-win")
    payload = {
        "cloud_api_key": "k-from-asm",
        "cloud_api_secret": "s-from-asm",
    }
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": json.dumps(payload)}
    with patch.object(secrets_mod, "_new_client", return_value=client):
        assert get_secret("CONFLUENT_CLOUD_API_KEY") == "k-from-asm"


def test_get_secret_cached_after_first_call(monkeypatch):
    """The TTL cache must save the boto3 round-trip on the second call."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "true")
    monkeypatch.setenv("AUDITLENS_ENV", "prod")
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({"cloud_api_key": "k1"}),
    }
    with patch.object(secrets_mod, "_new_client", return_value=client):
        # First call — boto3 hit
        assert get_secret("CONFLUENT_CLOUD_API_KEY") == "k1"
        # Second call — must NOT re-hit boto3
        assert get_secret("CONFLUENT_CLOUD_API_KEY") == "k1"
    assert client.get_secret_value.call_count == 1


def test_get_secret_falls_back_to_env_on_asm_error(monkeypatch):
    """If boto3 raises on get_secret_value, log WARNING (not ERROR) and
    fall back to the env-var. Production-critical: a transient ASM
    outage must not take the forwarder down. We assert against the
    module logger directly so test ordering / caplog propagation can't
    swallow the call."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "true")
    monkeypatch.setenv("CONFLUENT_CLOUD_API_KEY", "env-fallback")
    client = MagicMock()
    client.get_secret_value.side_effect = Exception("ASM 503")
    with patch.object(secrets_mod, "_new_client", return_value=client), \
            patch.object(secrets_mod.logger, "warning") as warn_mock:
        value = get_secret("CONFLUENT_CLOUD_API_KEY")
    assert value == "env-fallback"
    # Two warnings expected: the ASM-failure line, and possibly a
    # validate_secrets line if any other test mutated env. The
    # ASM-failure message starts with "Falling back".
    fallback_calls = [
        call for call in warn_mock.call_args_list
        if call.args and isinstance(call.args[0], str) and "Falling back" in call.args[0]
    ]
    assert fallback_calls, f"expected a 'Falling back' WARNING, got {warn_mock.call_args_list}"


def test_get_secret_dict_returns_none_when_asm_disabled(monkeypatch):
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "false")
    assert get_secret_dict("auditlens/prod/postgres") is None


def test_get_secret_dict_returns_parsed_json_when_enabled(monkeypatch):
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "true")
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({"password": "p", "user": "u"})
    }
    with patch.object(secrets_mod, "_new_client", return_value=client):
        result = get_secret_dict("auditlens/prod/postgres")
    assert result == {"password": "p", "user": "u"}


# ─────────────────────────────────────────────────────────────────────────
# validate_secrets()
# ─────────────────────────────────────────────────────────────────────────


def test_validate_secrets_returns_empty_when_all_present(monkeypatch):
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "false")
    for name in (
        "AUDIT_BOOTSTRAP",
        "AUDIT_API_KEY",
        "AUDIT_API_SECRET",
        "DEST_BOOTSTRAP",
        "DEST_API_KEY",
        "DEST_API_SECRET",
        "POSTGRES_PASSWORD",
    ):
        monkeypatch.setenv(name, "value")
    assert validate_secrets() == []


def test_validate_secrets_returns_missing_names(monkeypatch):
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "false")
    for name in ("AUDIT_BOOTSTRAP", "AUDIT_API_KEY"):
        monkeypatch.setenv(name, "value")
    for name in (
        "AUDIT_API_SECRET",
        "DEST_BOOTSTRAP",
        "DEST_API_KEY",
        "DEST_API_SECRET",
        "POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    missing = validate_secrets()
    assert set(missing) == {
        "AUDIT_API_SECRET",
        "DEST_BOOTSTRAP",
        "DEST_API_KEY",
        "DEST_API_SECRET",
        "POSTGRES_PASSWORD",
    }


def test_validate_secrets_accepts_custom_required_list(monkeypatch):
    """Each subsystem (forwarder vs API) can validate only its own
    required set rather than the global default."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "false")
    monkeypatch.setenv("CUSTOM_REQUIRED_X", "v")
    monkeypatch.delenv("CUSTOM_REQUIRED_Y", raising=False)
    missing = validate_secrets(required=("CUSTOM_REQUIRED_X", "CUSTOM_REQUIRED_Y"))
    assert missing == ["CUSTOM_REQUIRED_Y"]


# ─────────────────────────────────────────────────────────────────────────
# "asm:" prefix resolution (used by notifier for notifications.yml)
# ─────────────────────────────────────────────────────────────────────────


def test_asm_prefix_in_notifications_resolves_via_get_secret(monkeypatch):
    """A webhook_url of "asm:auditlens/prod/notifications#slack_webhook"
    must resolve to the value stored under the slack_webhook key of the
    ASM secret. End-to-end exercise of the notifier integration point."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "true")
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({
            "slack_webhook": "https://hooks.slack.com/services/REAL/URL",
        })
    }
    with patch.object(secrets_mod, "_new_client", return_value=client):
        resolved = resolve_asm_reference(
            "asm:auditlens/prod/notifications#slack_webhook"
        )
    assert resolved == "https://hooks.slack.com/services/REAL/URL"


def test_asm_prefix_falls_back_to_original_on_failure(monkeypatch):
    """If ASM is down (or the secret/key doesn't exist), resolve_asm_reference
    returns the original placeholder so the notifier's existing
    "_is_placeholder_url" check can silently drop the destination.
    Logger inspected directly to be robust to caplog propagation."""
    monkeypatch.setenv("AWS_SECRETS_MANAGER_ENABLED", "true")
    client = MagicMock()
    client.get_secret_value.side_effect = Exception("ASM unavailable")
    placeholder = "asm:auditlens/prod/notifications#slack_webhook"
    with patch.object(secrets_mod, "_new_client", return_value=client), \
            patch.object(secrets_mod.logger, "warning") as warn_mock:
        resolved = resolve_asm_reference(placeholder)
    assert resolved == placeholder
    unresolved_calls = [
        call for call in warn_mock.call_args_list
        if call.args and isinstance(call.args[0], str) and "could not be resolved" in call.args[0]
    ]
    assert unresolved_calls, f"expected 'could not be resolved' WARNING; got {warn_mock.call_args_list}"


def test_resolve_asm_reference_passes_through_non_asm_values():
    """Plain webhook URLs (no asm: prefix) must pass through verbatim
    — the notifier still sees the literal URL the operator typed in."""
    assert resolve_asm_reference("https://hooks.slack.com/T1") == "https://hooks.slack.com/T1"
    assert resolve_asm_reference("") == ""
