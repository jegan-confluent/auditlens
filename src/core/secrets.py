"""AWS Secrets Manager fetcher with env-var fallback.

Primary source: AWS Secrets Manager via boto3 when
AWS_SECRETS_MANAGER_ENABLED=true. Cached for 15 minutes in-process so
repeated lookups during a request don't hit ASM repeatedly.

Fallback: os.environ when ASM is disabled OR any boto3 call raises. The
fallback path logs WARNING (not ERROR) so local dev without AWS creds
still produces a clean log stream.

Public interface:

    from src.core.secrets import get_secret, get_secret_dict, validate_secrets

    confluent_key = get_secret("CONFLUENT_CLOUD_API_KEY")  # env-var name
    pg = get_secret_dict("auditlens/prod/postgres")        # whole secret
    missing = validate_secrets()                            # startup check

The "asm:<secret-name>#<key>" notation lets notifications.yml webhook
URLs point at ASM without restructuring the file. Example:

    webhook_url: "asm:auditlens/prod/notifications#slack_webhook"

is resolved at notifier load time via resolve_asm_reference().
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from cachetools import TTLCache


logger = logging.getLogger(__name__)


_CACHE_TTL_SECONDS = 15 * 60
_CACHE_MAXSIZE = 256
_secret_cache: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL_SECONDS)
_cache_lock = threading.Lock()

# Required secrets per environment. validate_secrets() returns the
# names that aren't reachable via ASM-or-env at startup. Tweak this set
# as the deployment matures — over-specifying it makes local dev
# painful, under-specifying it means a misconfigured prod silently
# starts and only fails on the first event.
_REQUIRED_AT_STARTUP: tuple[str, ...] = (
    "AUDIT_BOOTSTRAP",
    "AUDIT_API_KEY",
    "AUDIT_API_SECRET",
    "DEST_BOOTSTRAP",
    "DEST_API_KEY",
    "DEST_API_SECRET",
    "POSTGRES_PASSWORD",
)

_ASM_PREFIX = "asm:"


def _asm_enabled() -> bool:
    return os.environ.get("AWS_SECRETS_MANAGER_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _auditlens_env() -> str:
    return os.environ.get("AUDITLENS_ENV", "prod").strip() or "prod"


def _aws_region() -> str:
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "ap-southeast-1"
    )


def _new_client():
    """Build a Secrets Manager client. boto3 is an optional dependency at
    import time — if it's missing we silently fall back to env vars."""
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("boto3 not installed; secrets resolution will use env-var fallback only")
        return None
    return boto3.client("secretsmanager", region_name=_aws_region())


def _fetch_from_asm(secret_id: str) -> dict[str, Any] | None:
    """Return the parsed JSON body of an ASM secret, or None on any
    failure. Logs WARNING (not ERROR) on failure so the fallback path
    stays quiet under normal local-dev conditions."""
    client = _new_client()
    if client is None:
        return None
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except Exception as exc:
        logger.warning("Falling back to env for %s — ASM lookup failed: %s", secret_id, exc)
        return None
    secret_string = response.get("SecretString")
    if not secret_string:
        # Binary secrets aren't part of the AuditLens contract; treat as miss.
        return None
    try:
        parsed = json.loads(secret_string)
    except json.JSONDecodeError:
        # Single-string secrets are allowed too — surface them as {"value": ...}
        # so get_secret() with a key="value" hint works uniformly.
        return {"value": secret_string}
    if not isinstance(parsed, dict):
        return {"value": secret_string}
    return parsed


def _cached_get(secret_id: str) -> dict[str, Any] | None:
    with _cache_lock:
        if secret_id in _secret_cache:
            return _secret_cache[secret_id]
    value = _fetch_from_asm(secret_id)
    if value is not None:
        with _cache_lock:
            _secret_cache[secret_id] = value
    return value


def get_secret_dict(secret_id: str) -> dict[str, Any] | None:
    """Fetch a whole ASM secret as a dict.

    Returns None if AWS_SECRETS_MANAGER_ENABLED is off, boto3 is missing,
    or the secret can't be retrieved. Callers that need a single value
    should prefer get_secret() — it handles the env-var fallback too.
    """
    if not _asm_enabled():
        return None
    return _cached_get(secret_id)


def get_secret(name: str, *, fallback_env: str | None = None) -> str | None:
    """Resolve a single secret value.

    Resolution order:
      1. AWS Secrets Manager (if AWS_SECRETS_MANAGER_ENABLED=true) under
         the auditlens/{env}/{group} naming convention. `name` is
         interpreted as one of:
           - "auditlens/prod/postgres#password" (explicit secret#key)
           - "asm:auditlens/prod/postgres#password" (asm:-prefixed form)
           - "CONFLUENT_CLOUD_API_KEY" (env-var name; mapped to a group)
      2. os.environ[name] OR os.environ[fallback_env] when ASM lookup
         returns None.

    Returns the resolved string, or None when neither path supplies a value.
    """
    if name.startswith(_ASM_PREFIX):
        name = name[len(_ASM_PREFIX):]
    if "#" in name:
        secret_id, key = name.split("#", 1)
        if _asm_enabled():
            payload = _cached_get(secret_id)
            if payload is not None and key in payload:
                value = payload[key]
                if value is not None and value != "":
                    return str(value)
        # Explicit secret#key form has no clean env-var fallback —
        # callers should set fallback_env if they want one.
        return os.environ.get(fallback_env or "") or None

    # Plain env-var-name form. Try ASM groups first (best-effort lookup
    # across known groups), then fall back to os.environ.
    env_value = os.environ.get(name)
    if _asm_enabled():
        group, key = _env_name_to_asm(name)
        if group:
            payload = _cached_get(f"auditlens/{_auditlens_env()}/{group}")
            if payload is not None and key in payload:
                value = payload[key]
                if value is not None and value != "":
                    return str(value)
    return env_value or None


# ---------------------------------------------------------------------
# Static env-var → (group, key) routing table. Keys without an entry here
# fall through to plain os.environ — that covers MEDIUM/LOW config that
# was deliberately left out of ASM.
# ---------------------------------------------------------------------
_ENV_TO_ASM: dict[str, tuple[str, str]] = {
    "AUDIT_BOOTSTRAP": ("confluent", "audit_bootstrap"),
    "AUDIT_API_KEY": ("confluent", "cloud_api_key"),
    "AUDIT_API_SECRET": ("confluent", "cloud_api_secret"),
    "DEST_BOOTSTRAP": ("confluent", "dest_bootstrap"),
    "DEST_API_KEY": ("confluent", "cloud_api_key"),
    "DEST_API_SECRET": ("confluent", "cloud_api_secret"),
    "CONFLUENT_CLOUD_API_KEY": ("confluent", "cloud_api_key"),
    "CONFLUENT_CLOUD_API_SECRET": ("confluent", "cloud_api_secret"),
    "CONFLUENT_API_KEY": ("confluent", "api_key"),
    "CONFLUENT_API_SECRET": ("confluent", "api_secret"),
    "POSTGRES_PASSWORD": ("postgres", "password"),
    "SCHEMA_REGISTRY_URL": ("sr", "url"),
    "SCHEMA_REGISTRY_API_KEY": ("sr", "api_key"),
    "SCHEMA_REGISTRY_API_SECRET": ("sr", "api_secret"),
    "SLACK_WEBHOOK": ("notifications", "legacy_slack_webhook"),
    "MCP_AUTH_TOKEN": ("misc", "mcp_auth_token"),
    "GRAFANA_ADMIN_PASSWORD": ("misc", "grafana_admin_password"),
    "STREAMLIT_PASSWORD": ("misc", "streamlit_password"),
    "SETTINGS_ENCRYPTION_KEY": ("misc", "settings_encryption_key"),
    "AWS_ACCESS_KEY_ID": ("misc", "aws_access_key_id"),
    "AWS_SECRET_ACCESS_KEY": ("misc", "aws_secret_access_key"),
}


def _env_name_to_asm(name: str) -> tuple[str | None, str]:
    """Translate an env-var name to (group, key). When the name isn't in
    the routing table, return (None, name) so callers fall back to env."""
    pair = _ENV_TO_ASM.get(name)
    if pair is None:
        return None, name
    return pair


def resolve_asm_reference(value: str) -> str:
    """If `value` starts with `asm:`, resolve it via get_secret; otherwise
    return `value` unchanged. Used by the notifier to let
    notifications.yml webhook URLs point at ASM without restructuring
    the file. On resolution failure, returns the original asm: string
    so the placeholder safety net in notifier._parse_destination skips
    the destination instead of leaking a half-baked URL."""
    if not isinstance(value, str) or not value.startswith(_ASM_PREFIX):
        return value
    resolved = get_secret(value)
    if resolved is None:
        logger.warning(
            "ASM reference %s could not be resolved — leaving the placeholder in place",
            value,
        )
        return value
    return resolved


def validate_secrets(
    required: tuple[str, ...] | None = None,
) -> list[str]:
    """Return the names of required secrets that resolved to None.

    Called at forwarder + API startup. Does NOT raise — startup code
    decides whether a missing secret is fatal (forwarder needs Kafka
    creds; API doesn't need DEST_*). Each missing name is logged at
    WARNING level so an operator can grep for the first failure.
    """
    names = required if required is not None else _REQUIRED_AT_STARTUP
    missing: list[str] = []
    for name in names:
        if not get_secret(name):
            logger.warning("Required secret missing: %s", name)
            missing.append(name)
    if not missing:
        logger.info("All %d required secrets resolved", len(names))
    return missing


def clear_cache() -> None:
    """Empty the TTL cache. Used by tests; production callers don't need
    this because the 15-minute TTL is short enough for rotation."""
    with _cache_lock:
        _secret_cache.clear()
