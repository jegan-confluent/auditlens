import json
import os
import re
import time
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ACTOR_TYPES = {"user", "service_account", "api_key", "unknown"}
ACTOR_SOURCES = {"manual", "confluent_api", "metrics", "audit_event", "fallback"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, str | None]]] = {}


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def actor_raw_id(value: str) -> str:
    text = _as_text(value)
    if text.startswith("User:"):
        text = text.split(":", 1)[1].strip()
    return text


def infer_actor_type(raw_id: str, fallback: str = "") -> str:
    raw = actor_raw_id(raw_id)
    lowered = raw.lower()
    fallback_text = fallback.lower()
    if lowered.startswith("api-key-") or lowered.startswith("apikey") or "api key" in fallback_text:
        return "api_key"
    if lowered.startswith("sa-") or "service" in fallback_text:
        return "service_account"
    if lowered.startswith("u-") or lowered.startswith("user:") or "@" in raw or "user" in fallback_text:
        return "user"
    return "unknown"


@dataclass(frozen=True)
class EnrichmentConfig:
    enabled: bool
    sources: tuple[str, ...]
    cache_ttl_seconds: int
    mapping_file: str
    confluent_api_configured: bool
    confluent_api_key: str | None = None
    confluent_api_secret: str | None = None
    confluent_api_base_url: str = "https://api.confluent.cloud"

    @classmethod
    def from_env(cls) -> "EnrichmentConfig":
        sources = tuple(
            source.strip()
            for source in os.getenv("IAM_ENRICHMENT_SOURCE", "manual,confluent_api,metrics").split(",")
            if source.strip()
        )
        ttl = int(os.getenv("IAM_ENRICHMENT_CACHE_TTL_SECONDS", "3600") or "3600")
        api_key = os.getenv("CONFLUENT_CLOUD_API_KEY") or os.getenv("CONFLUENT_API_KEY")
        api_secret = os.getenv("CONFLUENT_CLOUD_API_SECRET") or os.getenv("CONFLUENT_API_SECRET")
        return cls(
            enabled=os.getenv("IAM_ENRICHMENT_ENABLED", "false").lower() == "true",
            sources=sources or ("manual",),
            cache_ttl_seconds=max(1, ttl),
            mapping_file=os.getenv("IAM_MAPPING_FILE", "data/iam_mapping.json"),
            confluent_api_configured=bool(api_key and api_secret),
            confluent_api_key=api_key,
            confluent_api_secret=api_secret,
            confluent_api_base_url=os.getenv("CONFLUENT_API_BASE_URL", "https://api.confluent.cloud").rstrip("/"),
        )


def _normalize_identity(raw_id: str, value: Any, *, source: str) -> dict[str, str]:
    if isinstance(value, str):
        value = {"display_name": value}
    if not isinstance(value, dict):
        return {}
    actor_type = _as_text(value.get("actor_type") or value.get("type") or infer_actor_type(raw_id))
    if actor_type not in ACTOR_TYPES:
        actor_type = "unknown"
    display_name = _as_text(value.get("display_name") or value.get("name") or value.get("label") or value.get("email"))
    output = {
        "actor_id": actor_raw_id(_as_text(value.get("actor_id") or value.get("id") or raw_id)),
        "actor_display_name": display_name,
        "actor_email": _as_text(value.get("email") or value.get("actor_email")),
        "actor_type": actor_type,
        "actor_source": source,
        "actor_confidence": _as_text(value.get("actor_confidence") or value.get("confidence") or "high"),
    }
    if output["actor_confidence"] not in CONFIDENCE_LEVELS:
        output["actor_confidence"] = "medium"
    return {key: val for key, val in output.items() if val}


def _parse_identity_map(raw: str, *, source: str) -> dict[str, dict[str, str]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    output: dict[str, dict[str, str]] = {}
    for key, value in parsed.items():
        raw_key = actor_raw_id(str(key))
        identity = _normalize_identity(raw_key, value, source=source)
        if identity:
            output[raw_key] = identity
    return output


@lru_cache(maxsize=1)
def _identity_map() -> dict[str, dict[str, str]]:
    config = EnrichmentConfig.from_env()
    output: dict[str, dict[str, str]] = {}
    file_path = Path(config.mapping_file)
    if file_path.exists():
        try:
            output.update(_parse_identity_map(file_path.read_text(encoding="utf-8"), source="manual"))
        except OSError:
            pass
    raw = os.getenv("ACTOR_IDENTITY_MAP_JSON", "").strip()
    if raw:
        output.update(_parse_identity_map(raw, source="manual"))
    return output


def _metrics_identity_map() -> dict[str, dict[str, str]]:
    raw = os.getenv("IAM_METRICS_IDENTITY_MAP_JSON", "").strip()
    return _parse_identity_map(raw, source="metrics") if raw else {}


def _lookup_confluent_principal(raw: str, config: EnrichmentConfig) -> dict[str, str] | None:
    if not config.enabled or not config.confluent_api_configured:
        return None
    if not raw or not config.confluent_api_key or not config.confluent_api_secret:
        return None
    if raw.startswith("sa-"):
        paths = (f"/iam/v2/service-accounts/{raw}",)
    elif raw.startswith("u-"):
        paths = (f"/iam/v2/users/{raw}",)
    else:
        return None
    token = base64.b64encode(f"{config.confluent_api_key}:{config.confluent_api_secret}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    for path in paths:
        request = Request(f"{config.confluent_api_base_url}{path}", headers=headers)
        try:
            with urlopen(request, timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        display_name = _as_text(payload.get("display_name") or payload.get("displayName") or payload.get("full_name") or payload.get("name"))
        email = _as_text(payload.get("email"))
        actor_type = "service_account" if raw.startswith("sa-") else "user"
        return {
            "actor_id": raw,
            "actor_display_name": display_name or email or raw,
            "actor_email": email,
            "actor_type": actor_type,
            "actor_source": "confluent_api",
            "actor_confidence": "high" if display_name or email else "medium",
        }
    return None


def _lookup_metrics_identity(raw: str, config: EnrichmentConfig) -> dict[str, str] | None:
    if "metrics" not in config.sources:
        return None
    return _metrics_identity_map().get(raw)


def _fallback_identity(raw: str, subject_type: str = "") -> dict[str, str | None]:
    actor_type = infer_actor_type(raw, subject_type)
    if actor_type == "service_account":
        display_name = "Unknown service account"
    elif actor_type == "user":
        display_name = "Unknown user"
    elif actor_type == "api_key":
        display_name = "Unknown API key"
    else:
        display_name = raw or "Unknown actor"
    return {
        "actor_id": raw or None,
        "actor_display_name": display_name,
        "actor_email": None,
        "actor_type": actor_type,
        "actor_source": "fallback" if raw else "audit_event",
        "actor_confidence": "low" if raw else "medium",
    }


def enrich_actor(actor: str, subject: str = "", subject_type: str = "") -> dict[str, str | None]:
    config = EnrichmentConfig.from_env()
    raw = actor_raw_id(subject or actor)
    if not raw or raw.lower() == "unknown actor":
        raw = actor_raw_id(actor)
    cache_key = (raw, subject, subject_type)
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached and now - cached[0] < config.cache_ttl_seconds:
        return cached[1]

    identity: dict[str, str] | None = None
    try:
        if "manual" in config.sources:
            identity = _identity_map().get(raw)
        if identity is None and "confluent_api" in config.sources:
            identity = _lookup_confluent_principal(raw, config)
        if identity is None:
            identity = _lookup_metrics_identity(raw, config)
    except Exception:
        identity = None

    if identity:
        result: dict[str, str | None] = {
            "actor_id": identity.get("actor_id") or raw or None,
            "actor_display_name": identity.get("actor_display_name") or identity.get("display_name") or raw or "Unknown actor",
            "actor_email": identity.get("actor_email") or identity.get("email") or None,
            "actor_type": identity.get("actor_type") or identity.get("type") or infer_actor_type(raw, subject_type),
            "actor_raw_id": raw or None,
            "actor_source": identity.get("actor_source") or "manual",
            "actor_confidence": identity.get("actor_confidence") or "high",
            "actor_enriched_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        result = {
            **_fallback_identity(raw, subject_type),
            "actor_raw_id": raw or None,
            "actor_enriched_at": datetime.now(timezone.utc).isoformat(),
        }

    _CACHE[cache_key] = (now, result)
    return result


def clear_actor_enrichment_cache() -> None:
    _CACHE.clear()
    _identity_map.cache_clear()


def looks_like_ip(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip()
    ipv4 = re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text)
    if ipv4:
        return all(0 <= int(part) <= 255 for part in text.split("."))
    return bool(re.fullmatch(r"[0-9a-fA-F:]{3,}", text) and ":" in text)
