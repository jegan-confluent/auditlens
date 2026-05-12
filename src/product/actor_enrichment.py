import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.identity.enricher import IdentityEnricher as ConfluentIdentityEnricher

logger = logging.getLogger("auditlens.product.actor_enrichment")

ACTOR_TYPES = {"user", "service_account", "api_key", "unknown"}
ACTOR_SOURCES = {"manual", "manual_mapping", "confluent_api", "metrics", "audit_event", "fallback"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
UNKNOWN_DISPLAY_LABELS = {"unknown actor", "unknown user", "unknown service account", "unknown principal"}
PRINCIPAL_PREFIXES = ("user:", "u-", "sa-", "api-key-", "apikey", "pool-", "org-", "lkc-", "env-")
_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, str | None]]] = {}


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default)) or default))
    except ValueError:
        return default


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
    metrics_enabled: bool
    metrics_source: str
    metrics_cache_ttl_seconds: int
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
        api_key = os.getenv("CONFLUENT_CLOUD_API_KEY") or os.getenv("CONFLUENT_API_KEY")
        api_secret = os.getenv("CONFLUENT_CLOUD_API_SECRET") or os.getenv("CONFLUENT_API_SECRET")
        return cls(
            enabled=os.getenv("IAM_ENRICHMENT_ENABLED", "false").lower() == "true",
            sources=sources or ("manual",),
            cache_ttl_seconds=_env_int("IAM_ENRICHMENT_CACHE_TTL_SECONDS", 3600),
            mapping_file=os.getenv("IAM_MAPPING_FILE", "data/iam_mapping.json"),
            metrics_enabled=os.getenv("METRICS_ENRICHMENT_ENABLED", "false").lower() == "true",
            metrics_source=os.getenv("METRICS_ENRICHMENT_SOURCE", "correlation").strip() or "correlation",
            metrics_cache_ttl_seconds=_env_int("METRICS_ENRICHMENT_CACHE_TTL_SECONDS", 3600),
            confluent_api_configured=bool(api_key and api_secret),
            confluent_api_key=api_key,
            confluent_api_secret=api_secret,
            confluent_api_base_url=os.getenv("CONFLUENT_API_BASE_URL", "https://api.confluent.cloud").rstrip("/"),
        )


def _normalize_identity(raw_id: str, value: Any, *, source: str, default_confidence: str = "high") -> dict[str, str]:
    if isinstance(value, str):
        value = {"display_name": value}
    if not isinstance(value, dict):
        return {}
    actor_type = _as_text(value.get("actor_type") or value.get("type") or infer_actor_type(raw_id))
    if actor_type not in ACTOR_TYPES:
        actor_type = "unknown"
    display_name = _as_text(value.get("display_name") or value.get("name") or value.get("label") or value.get("email"))
    if display_name.startswith(("{", "[")):
        display_name = ""
    output = {
        "actor_id": actor_raw_id(_as_text(value.get("actor_id") or value.get("id") or raw_id)),
        "actor_display_name": display_name,
        "actor_email": _as_text(value.get("email") or value.get("actor_email")),
        "actor_type": actor_type,
        "actor_source": source,
        "actor_confidence": _as_text(value.get("actor_confidence") or value.get("confidence") or default_confidence),
    }
    if output["actor_confidence"] not in CONFIDENCE_LEVELS:
        output["actor_confidence"] = "medium"
    if source == "metrics" and output["actor_confidence"] == "high":
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
            # Identity-mapping file present but unreadable. Fall back to env-var
            # mapping, but record the failure so a misconfigured mount does not
            # silently strip enrichment.
            logger.debug(
                "identity mapping file %s could not be read; falling back to env",
                file_path,
                exc_info=True,
            )
    raw = os.getenv("ACTOR_IDENTITY_MAP_JSON", "").strip()
    if raw:
        output.update(_parse_identity_map(raw, source="manual"))
    return output


def _metrics_identity_map() -> dict[str, dict[str, str]]:
    raw = os.getenv("IAM_METRICS_IDENTITY_MAP_JSON", "").strip()
    if not raw:
        raw = os.getenv("METRICS_CORRELATION_MAP_JSON", "").strip()
    return _parse_identity_map(raw, source="metrics") if raw else {}


@lru_cache(maxsize=1)
def _confluent_identity_enricher() -> ConfluentIdentityEnricher | None:
    config = EnrichmentConfig.from_env()
    if not config.enabled or not config.confluent_api_configured:
        return None
    if not config.confluent_api_key or not config.confluent_api_secret:
        return None
    enricher = ConfluentIdentityEnricher(
        api_key=config.confluent_api_key,
        api_secret=config.confluent_api_secret,
        cache_ttl=config.cache_ttl_seconds,
    )
    # Background-refresh the IAM cache so the consume loop never pays the
    # 6-8 s cost of the initial 11-page load on the hot path. The first
    # refresh runs inside the daemon thread; resolve() returns raw_id
    # until it completes.
    enricher.start_background_refresh()
    return enricher


def _looks_like_raw_principal(value: str) -> bool:
    text = actor_raw_id(value).strip().lower()
    if not text or text in UNKNOWN_DISPLAY_LABELS:
        return False
    if "@" in text:
        return False
    return text.startswith(PRINCIPAL_PREFIXES)


def _audit_event_identity(raw: str, subject_type: str = "", display_candidate: str = "") -> dict[str, str | None] | None:
    candidate = _as_text(display_candidate).strip()
    if not candidate or candidate.lower() in UNKNOWN_DISPLAY_LABELS:
        return None
    if _looks_like_raw_principal(candidate):
        return None
    if subject_type in ACTOR_TYPES and subject_type != "unknown":
        actor_type = subject_type
    elif "@" in candidate or " " in candidate:
        actor_type = "user"
    else:
        actor_type = infer_actor_type(raw or candidate, subject_type)
    return {
        "actor_id": raw or None,
        "actor_display_name": candidate,
        "actor_email": candidate if "@" in candidate else None,
        "actor_type": actor_type,
        "actor_source": "audit_event",
        "actor_confidence": "medium",
    }


def _lookup_confluent_principal(raw: str, config: EnrichmentConfig) -> dict[str, str] | None:
    if not raw or not config.enabled or not config.confluent_api_configured:
        return None
    if "confluent_api" not in config.sources:
        return None
    if not raw.startswith(("sa-", "u-")):
        return None
    enricher = _confluent_identity_enricher()
    if enricher is None:
        return None
    try:
        info = enricher.resolve(raw)
    except Exception:
        return None
    display_name = _as_text(getattr(info, "display_name", ""))
    email = _as_text(getattr(info, "email", ""))
    identity_id = _as_text(getattr(info, "id", raw)) or raw
    if not display_name or (display_name == identity_id and not email):
        return None
    actor_type = "service_account" if raw.startswith("sa-") else "user"
    return {
        "actor_id": raw,
        "actor_display_name": display_name or email or raw,
        "actor_email": email,
        "actor_type": actor_type,
        "actor_source": "confluent_api",
        "actor_confidence": "high" if display_name != identity_id or email else "medium",
    }


def _lookup_metrics_identity(raw: str, config: EnrichmentConfig) -> dict[str, str] | None:
    if not raw or not config.metrics_enabled:
        return None
    if "metrics" not in config.sources and config.metrics_source not in {"correlation", "labels", "manual"}:
        return None
    identity = _metrics_identity_map().get(raw)
    if identity is None:
        return None
    if identity.get("actor_source") != "metrics":
        identity = {**identity, "actor_source": "metrics"}
    confidence = _as_text(identity.get("actor_confidence") or identity.get("confidence") or "low")
    if confidence not in {"low", "medium"}:
        confidence = "medium" if identity.get("actor_display_name") or identity.get("actor_email") else "low"
    return {
        **identity,
        "actor_id": identity.get("actor_id") or raw,
        "actor_display_name": identity.get("actor_display_name") or identity.get("display_name") or identity.get("name") or identity.get("email") or raw,
        "actor_email": identity.get("actor_email") or identity.get("email") or None,
        "actor_type": identity.get("actor_type") or identity.get("type") or infer_actor_type(raw),
        "actor_source": "metrics",
        "actor_confidence": confidence if confidence in {"low", "medium"} else "low",
    }


def _normalize_raw_actor(actor: str, subject: str = "") -> str:
    raw = actor_raw_id(subject or actor)
    if raw.lower() in UNKNOWN_DISPLAY_LABELS:
        raw = actor_raw_id(actor)
    if raw.lower() in UNKNOWN_DISPLAY_LABELS:
        return ""
    return raw


class ActorMappingFile:
    """Optional manual override for principal-ID → display-name resolution.

    Reads a YAML file on construction, then re-reads on mtime change so
    operators can edit `actor_mappings.yml` without restarting services.

    Schema — string format (backward compatible):
        mappings:
          sa-xxxx: "Datadog Monitor"
          u-xxxxx: "Former Employee - John"

    Schema — dict format (extended):
        mappings:
          sa-xxxx:
            display_name: "Datadog Monitor"
            trusted_ips: ["10.0.0.0/8", "34.238.241.0/24"]
            alert_on_new_ip: true
            team: "Platform"
            k8s_namespace: "monitoring"
            k8s_deployment: "datadog-agent"

    Thread-safe reads. Never raises — bad YAML logs WARNING and returns
    empty mappings, so callers can treat `get(...) is None` as "no
    override" without paranoid try/except blocks.
    """

    def __init__(self, path: str = "actor_mappings.yml") -> None:
        self._path = path
        self._mappings: dict[str, str] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._mtime: float = 0.0
        self._lock = threading.Lock()
        self._load()

    def get(self, principal_id: str) -> str | None:
        if not principal_id:
            return None
        self._reload_if_changed()
        with self._lock:
            return self._mappings.get(principal_id)

    def get_trusted_ips(self, principal_id: str) -> list[str]:
        """Return the list of trusted IP CIDRs for principal_id (empty if none)."""
        if not principal_id:
            return []
        self._reload_if_changed()
        with self._lock:
            meta = self._metadata.get(principal_id, {})
        raw = meta.get("trusted_ips") or []
        return [str(ip) for ip in raw] if isinstance(raw, list) else []

    def alert_on_new_ip(self, principal_id: str) -> bool:
        """Return True if new-IP alerts are enabled for principal_id."""
        if not principal_id:
            return False
        self._reload_if_changed()
        with self._lock:
            meta = self._metadata.get(principal_id, {})
        return bool(meta.get("alert_on_new_ip", False))

    def get_metadata(self, principal_id: str) -> dict[str, Any]:
        """Return the full metadata dict for principal_id (empty dict if none)."""
        if not principal_id:
            return {}
        self._reload_if_changed()
        with self._lock:
            return dict(self._metadata.get(principal_id, {}))

    def count(self) -> int:
        with self._lock:
            return len(self._mappings)

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            with self._lock:
                self._mappings = {}
                self._metadata = {}
                self._mtime = 0.0
            return
        try:
            mtime = os.path.getmtime(self._path)
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
        except (yaml.YAMLError, OSError) as exc:
            logger.warning(
                "actor_mappings.yml load failed (%s) — manual overrides disabled",
                exc,
            )
            with self._lock:
                self._mappings = {}
                self._metadata = {}
                self._mtime = 0.0
            return

        mappings: dict[str, str] = {}
        metadata: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict):
            entries = raw.get("mappings") or {}
            if isinstance(entries, dict):
                for key, value in entries.items():
                    if not isinstance(key, str):
                        continue
                    key_clean = key.strip()
                    if not key_clean:
                        continue
                    if isinstance(value, str):
                        # Legacy string format
                        value_clean = value.strip()
                        if value_clean:
                            mappings[key_clean] = value_clean
                    elif isinstance(value, dict):
                        # Extended dict format
                        display = _as_text(value.get("display_name") or "").strip()
                        if display:
                            mappings[key_clean] = display
                        meta: dict[str, Any] = {}
                        if "trusted_ips" in value:
                            meta["trusted_ips"] = value["trusted_ips"]
                        if "alert_on_new_ip" in value:
                            meta["alert_on_new_ip"] = bool(value["alert_on_new_ip"])
                        for field in ("team", "k8s_namespace", "k8s_deployment"):
                            if field in value:
                                meta[field] = _as_text(value[field])
                        if meta:
                            metadata[key_clean] = meta
            elif entries:
                logger.warning(
                    "actor_mappings.yml: 'mappings' must be a mapping — ignoring",
                )
        with self._lock:
            self._mappings = mappings
            self._metadata = metadata
            self._mtime = mtime

    def _reload_if_changed(self) -> None:
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            # File may have been deleted; clear in-memory copy on next miss.
            with self._lock:
                if self._mtime != 0.0:
                    self._mappings = {}
                    self._metadata = {}
                    self._mtime = 0.0
            return
        if mtime != self._mtime:
            self._load()


@lru_cache(maxsize=1)
def _actor_mapping_file() -> ActorMappingFile:
    return ActorMappingFile(
        path=os.getenv("ACTOR_MAPPINGS_FILE", "actor_mappings.yml"),
    )


def get_actor_mapping_file() -> ActorMappingFile:
    """Public accessor used by audit_forwarder.py and the backfill job."""
    return _actor_mapping_file()


def wait_for_iam_cache_ready(timeout_seconds: float = 30.0) -> bool:
    """Block until the Confluent IAM cache has completed its first refresh.

    Returns True when the cache is ready or no enricher is configured
    (nothing to wait for); False on timeout. Used by the actor backfill
    job so it doesn't run against a half-warm cache.
    """
    enricher = _confluent_identity_enricher()
    if enricher is None:
        return True
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        if getattr(enricher, "_last_refresh_at", None) is not None:
            return True
        time.sleep(0.5)
    return getattr(enricher, "_last_refresh_at", None) is not None


def _lookup_actor_mapping_override(raw: str, subject_type: str = "") -> dict[str, str] | None:
    if not raw:
        return None
    override = _actor_mapping_file().get(raw)
    if not override:
        return None
    return {
        "actor_id": raw,
        "actor_display_name": override,
        "actor_email": None,
        "actor_type": infer_actor_type(raw, subject_type),
        "actor_source": "manual_mapping",
        "actor_confidence": "high",
    }


def _fallback_identity(raw: str, subject_type: str = "") -> dict[str, str | None]:
    actor_type = infer_actor_type(raw, subject_type)
    # Phase 5: never substitute a "Unknown X" placeholder for the display
    # name — it collapses different unresolved IDs into the same label and
    # hides the raw u-/sa- ID operators need to investigate. Surface the
    # raw ID instead; if there's no raw ID either, return an empty string
    # so downstream consumers can render an explicit blank.
    return {
        "actor_id": raw or None,
        "actor_display_name": raw,
        "actor_email": None,
        "actor_type": actor_type,
        "actor_source": "fallback",
        "actor_confidence": "low" if raw else "medium",
    }


def enrich_actor(actor: str, subject: str = "", subject_type: str = "") -> dict[str, str | None]:
    config = EnrichmentConfig.from_env()
    raw = _normalize_raw_actor(actor, subject)
    cache_key = (raw, subject, subject_type)
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached and now - cached[0] < config.cache_ttl_seconds:
        return cached[1]

    identity: dict[str, str] | None = None
    try:
        # Phase 5: actor_mappings.yml takes priority over every other
        # resolution path so operators can override deleted/cryptic SAs
        # without editing Python or restarting services.
        identity = _lookup_actor_mapping_override(raw, subject_type)
        if identity is None and "manual" in config.sources:
            identity = _identity_map().get(raw)
        if identity is None and "confluent_api" in config.sources:
            identity = _lookup_confluent_principal(raw, config)
        if identity is None:
            identity = _audit_event_identity(raw, subject_type, actor or subject)
        if identity is None:
            identity = _lookup_metrics_identity(raw, config)
    except Exception:
        identity = None

    if identity:
        result: dict[str, str | None] = {
            "actor_id": identity.get("actor_id") or raw or None,
            "actor_display_name": identity.get("actor_display_name") or identity.get("display_name") or raw,
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

    # Normalize actor_display_name at the cache boundary — single gate for
    # all resolution paths so nothing malformed ever reaches the DB.
    dn = result.get("actor_display_name") or ""
    if dn.startswith("{"):
        # JSON blob (e.g. Confluent internal service account subject).
        dn = "Confluent (internal)" if "Confluent" in dn else (raw or "")
    if dn.startswith("User:"):
        dn = dn[5:]
    result["actor_display_name"] = dn or None

    _CACHE[cache_key] = (now, result)
    return result


def clear_actor_enrichment_cache() -> None:
    _CACHE.clear()
    _identity_map.cache_clear()
    _confluent_identity_enricher.cache_clear()
    _actor_mapping_file.cache_clear()


def looks_like_ip(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip()
    ipv4 = re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", text)
    if ipv4:
        return all(0 <= int(part) <= 255 for part in text.split("."))
    return bool(re.fullmatch(r"[0-9a-fA-F:]{3,}", text) and ":" in text)
