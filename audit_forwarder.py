#!/usr/bin/env python3
"""
AuditLens foundation forwarder.

This forwarder:
1. Consumes events from Confluent Cloud audit log topic
2. Produces a raw replay envelope for forensic recovery
3. Normalizes and enriches events with centralized classification
4. Tracks events for anomaly detection
5. Records metrics for Prometheus exposition
6. Emits additive signal streams for denials and high-risk activity
7. Sends explainable operator alerts for high-risk events
"""

# Version - read from VERSION file for consistency across all modules
from pathlib import Path as _VersionPath
_version_file = _VersionPath(__file__).parent / "VERSION"
VERSION = _version_file.read_text().strip() if _version_file.exists() else "2.1.0"

import os
import sys
import traceback
import argparse
import signal
import ipaddress
import orjson
import logging
import time
import re
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, Future
import random
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
from dotenv import load_dotenv
from cachetools import TTLCache

try:
    import psutil as _psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False
from confluent_kafka import Consumer, Producer, KafkaError, TopicPartition
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.json_schema import JSONSerializer

# Import our intelligence modules
from src.metrics.audit_events import (
    audit_event_metrics,
    record_event_metrics,
    record_anomaly_metrics,
    record_routing_metrics,
    record_schema_registry_failure,
)
from src.classification import calculate_criticality, CriticalityLevel
from src.classification.methods import (
    CRITICAL_METHODS,
    HIGH_METHODS,
    READ_ONLY_METHODS,
    AUTHENTICATION_METHODS,
    AUTHORIZATION_CHECK_METHODS,
)
from src.anomaly import RateTracker, RateTrackerConfig
from src.routing import TopicRouter, RouterConfig, RoutingResult
from src.alerting import get_webhook_sender
from src.aggregation import DenialAggregator, AggregatorConfig
from src.identity import normalize_with_type
from src.product import (
    AuthConfig,
    Authenticator,
    PersistenceConfig,
    Role,
    SQLiteProductStore,
    heal_sqlite_on_startup,
)
from src.product.db_writer import AuditEventDbWriter
from src.product.event_normalization import (
    BULK_NOISE_METHODS,
    parse_event_timestamp,
    flatten_audit,
    _to_scalar,
    _extract_email,
    _extract_client_ip,
    _map_client_tool,
)
from src.product.event_intelligence import decision_snapshot
from src.product.actor_enrichment import get_actor_mapping_file, wait_for_iam_cache_ready
from src.notifications.notifier import AuditLensNotifier
from src.forwarder.utils import extract_from_crn, utc_now_iso
from src.forwarder.secrets_masking import mask_sensitive_text, mask_config_for_logging, _SENSITIVE_KEY_TOKENS
from src.forwarder.metrics import Metrics
import src.forwarder.health_server as _health_server_module
from src.forwarder.health_server import (
    start_metrics_server,
    MetricsHandler,
    AuditLensHealthServer,
    _parse_iso_to_utc,
    _compute_db_behind_seconds,
    _classify_db_writer_status,
    _is_replay_recommended,
    _build_db_writer_block,
    _request_filters,
    _request_actor,
    _normalize_json_keys,
)
from src.forwarder.config import (
    load_env,
    AUDIT_BOOTSTRAP, AUDIT_API_KEY, AUDIT_API_SECRET,
    DEST_BOOTSTRAP, DEST_API_KEY, DEST_API_SECRET,
    SCHEMA_REGISTRY_URL, SCHEMA_REGISTRY_KEY, SCHEMA_REGISTRY_SECRET,
    AUDIT_TOPIC, GROUP_ID, AUTO_OFFSET_RESET, METRICS_PORT,
    AUDIT_RAW_TOPIC, AUDIT_NORMALIZED_TOPIC, AUDIT_ENRICHED_TOPIC,
    AUDIT_SIGNALS_DENIALS_TOPIC, AUDIT_SIGNALS_HIGHRISK_TOPIC, AUDIT_ALERTS_TOPIC,
    ANOMALY_WINDOW_SECONDS, ANOMALY_AUTH_FAILURE_THRESHOLD, ANOMALY_ACTIVITY_SPIKE_THRESHOLD,
    ANOMALY_DELETION_THRESHOLD, ANOMALY_API_KEY_THRESHOLD,
    ENABLE_MULTI_TOPIC_ROUTING, ROUTER_DRY_RUN,
    DLQ_TOPIC, ENABLE_DLQ,
    ENABLE_DENIAL_AGGREGATION, ALERT_ON_HIGH_RISK,
    API_MAX_SEARCH_RESULTS, API_BUFFER_ENRICHED, API_BUFFER_SIGNALS,
    API_EXPORT_MAX_ROWS, API_EXPORT_MAX_HOURS,
    REPLAY_ENABLED, REPLAY_DEFAULT_HOURS, REPLAY_MAX_HOURS, REPLAY_PUBLISH_DERIVED_TOPICS,
    STORAGE_MONITOR_INTERVAL_SECONDS,
    CONSUMER_POLL_TIMEOUT_SECONDS, CONSUMER_EMPTY_POLL_SLEEP_SECONDS, CONSUMER_BATCH_SLEEP_SECONDS,
    KAFKA_RETRY_INITIAL_BACKOFF_SECONDS, KAFKA_RETRY_MAX_BACKOFF_SECONDS,
    KAFKA_DEGRADED_AFTER_ERRORS, KAFKA_ERROR_LOG_INTERVAL_SECONDS,
    ENABLE_DB_WRITER, DATABASE_URL,
    DB_WRITE_BATCH_SIZE, DB_WRITE_BACKOFF_MAX_SECONDS, DB_WRITE_FLUSH_INTERVAL_SECONDS,
    EVENT_RETENTION_DAYS, DB_RETENTION_CLEANUP_INTERVAL_SECONDS,
    ENABLE_NOISE_SHORT_CIRCUIT, NOISE_PERSIST_WAIT_TIMEOUT_SECONDS,
    AUTH_CONFIG, PERSISTENCE_CONFIG,
    BUILTIN_ALERT_METHODS, ENABLE_BUILTIN_ALERTS, LEGACY_WEBHOOK_ENABLED,
    HIGH_RISK_ALERT_METHODS, HIGH_RISK_SIGNAL_METHODS,
)

# ──────────── graceful shutdown handler ────────────
_shutdown_requested = False

def _signal_handler(sig, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    global _shutdown_requested
    sig_name = signal.Signals(sig).name
    # Use print since logger may not be initialized yet
    print(f"Received {sig_name}, initiating graceful shutdown...")
    _shutdown_requested = True

# Register signal handlers
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


# PRODUCT_MODE, ENABLE_SQLITE_HOT_CACHE, and _sqlite_hot_cache_enabled are computed
# locally so that importlib.reload(audit_forwarder) re-evaluates them from the current
# env — the tests in test_sqlite_hot_cache_guard.py rely on this reload behaviour.
PRODUCT_MODE = os.getenv("DATABASE_URL", "sqlite:////var/lib/auditlens/auditlens_api.db").startswith("postgresql")
ENABLE_SQLITE_HOT_CACHE = os.getenv("ENABLE_SQLITE_HOT_CACHE", "auto").strip().lower()


def _sqlite_hot_cache_enabled() -> bool:
    """Decide whether the legacy SQLite hot cache should run."""
    if ENABLE_SQLITE_HOT_CACHE in {"true", "1", "yes", "on"}:
        return True
    if ENABLE_SQLITE_HOT_CACHE in {"false", "0", "no", "off"}:
        return False
    return not PRODUCT_MODE


authenticator = Authenticator(AUTH_CONFIG)
product_store = None
db_writer = None
_db_init_next_attempt: float = 0.0
storage_monitor_stop = threading.Event()
storage_monitor_thread = None


# ──────────── noise persistence barrier ────────────
# When ENABLE_NOISE_SHORT_CIRCUIT is on, the consumer thread routes
# bulk-noise events directly to the bulk writer, bypassing the processor.
# Those events never reach a Kafka topic, so the only durable home is
# audit_events_noise. To preserve at-least-once: the processor MUST NOT
# commit a partition's offset past a short-circuited noise offset until
# the bulk writer has persisted it.
#
# The bulk writer publishes the highest offset persisted per (topic,
# partition) into _noise_persisted_offsets and notify_all() on the CV.
# The processor, after producer.flush(), waits on this CV until every
# (topic, partition) it short-circuited has caught up. On timeout the
# processor declines to commit, and the events will be re-consumed on
# restart — no silent loss.
_noise_persisted_offsets: dict[tuple[str, int], int] = {}
_noise_persisted_lock = threading.Lock()
_noise_persisted_cv = threading.Condition(_noise_persisted_lock)


def _record_noise_persisted(items: list) -> None:
    """Mark per-(topic, partition) max persisted offset for short-circuited
    noise events that were just successfully INSERTed into audit_events_noise.
    Wakes processor-thread waiters on the condition variable.
    """
    if not items:
        return
    updated = False
    with _noise_persisted_cv:
        for item in items:
            if not isinstance(item, dict) or not item.get("_short_circuit"):
                continue
            topic = item.get("_topic")
            partition = item.get("_partition")
            offset = item.get("_offset")
            if topic is None or partition is None or offset is None:
                continue
            key = (topic, partition)
            current = _noise_persisted_offsets.get(key, -1)
            if offset > current:
                _noise_persisted_offsets[key] = offset
                updated = True
        if updated:
            _noise_persisted_cv.notify_all()


def _await_noise_persisted(
    required: dict[tuple[str, int], int],
    *,
    timeout: float = NOISE_PERSIST_WAIT_TIMEOUT_SECONDS,
) -> bool:
    """Block until every (topic, partition) in ``required`` has been
    persisted up to (>=) its required offset. Returns True if all caught
    up; False on timeout. Empty ``required`` returns True immediately.
    """
    if not required:
        return True
    deadline = time.monotonic() + max(0.0, timeout)
    with _noise_persisted_cv:
        while True:
            if all(_noise_persisted_offsets.get(k, -1) >= v for k, v in required.items()):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _noise_persisted_cv.wait(remaining)


def _try_short_circuit_noise(msg) -> dict | None:
    """Decode a raw Kafka record and return the parsed dict iff it's a
    bulk-noise method. Returns None on any failure or non-noise event,
    so the caller falls back to the full processor path.

    Never raises — wrapped in try/except so a malformed payload at the
    consume point can never crash the consumer thread.
    """
    try:
        value = msg.value()
        if value is None:
            return None
        payload = orjson.loads(value)
        if not isinstance(payload, dict):
            return None
        method = ""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else None
        if data is not None:
            method = data.get("methodName") or ""
        if not method:
            method = payload.get("methodName") or payload.get("method") or ""
        if not isinstance(method, str) or not method:
            return None
        if method.lower() not in BULK_NOISE_METHODS:
            return None
        return payload
    except Exception:
        return None  # Any decode/shape error → full path

# ──────────── logging ────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()


# ─────────────────── DB-writer freshness helpers ───────────────────────
# These compute the /health db_writer block from in-memory metrics state
# (no DB queries — keeps /health <100ms). All return None / safe defaults
# on bad input so /health can never raise from them.

def _max_event_timestamp_iso(payloads: list[dict]) -> str | None:
    """Max event-time across a batch as ISO-8601 UTC, or None.

    Used by the writer threads to advance the `db_last_event_timestamp_iso`
    freshness mark after a successful INSERT — the highest event time in
    the batch is the most-recent event Postgres has actually seen.
    Wrapped in try/except: a single bad payload must not abort the
    timestamp computation for the rest of the batch.
    """
    if not payloads:
        return None
    latest: datetime | None = None
    for payload in payloads:
        try:
            ts = parse_event_timestamp(payload)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            if latest is None or ts > latest:
                latest = ts
        except Exception:
            continue
    if latest is None:
        return None
    return latest.isoformat().replace("+00:00", "Z")


def build_raw_event(event: dict, msg) -> dict:
    """Wrap source event for replay-safe raw topic production."""
    return {
        "schema_version": "audit.raw.v1",
        "ingested_at": utc_now_iso(),
        "source_topic": msg.topic(),
        "source_partition": msg.partition(),
        "source_offset": msg.offset(),
        "forwarder_version": VERSION,
        "raw_event": event,
    }


def build_normalized_event(flat: dict) -> dict:
    """Return normalized contract without enrichment-only fields."""
    normalized = dict(flat)
    for key in (
        "criticality",
        "classification_reason",
        "criticality_elevated",
        "method_category",
        "is_security_event",
        "is_signal_candidate",
        "signal_type",
        "is_deletion",
        "is_creation",
        "is_modification",
        "is_high_risk",
        "pipeline_stage",
        "event_contract_version",
        "schema_version",
    ):
        normalized.pop(key, None)
    normalized["schema_version"] = "audit.normalized.v1"
    normalized["pipeline_stage"] = "normalized"
    normalized["event_contract_version"] = "v1"
    return normalized


def build_enriched_event(flat: dict) -> dict:
    """Return enriched contract used by the dashboard and operator workflows."""
    enriched = dict(flat)
    enriched["schema_version"] = "audit.enriched.v1"
    enriched["pipeline_stage"] = "enriched"
    enriched["event_contract_version"] = "v1"
    enriched["is_high_risk"] = (
        enriched.get("criticality") == "CRITICAL" or
        enriched.get("methodName") in HIGH_RISK_SIGNAL_METHODS
    )
    return enriched


def should_emit_high_risk_alert(event: dict) -> bool:
    """Gate high-risk alerts to avoid flooding on every enriched record."""
    if not ALERT_ON_HIGH_RISK:
        return False
    criticality = event.get("criticality")
    method_name = event.get("methodName", "")
    if criticality == "CRITICAL":
        return True
    return criticality == "HIGH" and method_name in HIGH_RISK_ALERT_METHODS


def build_operator_alert(event: dict) -> dict:
    """Create a simple explainable operator alert record."""
    severity = event.get("criticality", "HIGH")
    principal = event.get("principal")
    resource = event.get("resourceName") or event.get("authzResourceName")
    method_name = event.get("methodName")
    return {
        "schema_version": "audit.alerts.v1",
        "alert_type": "high_risk_event",
        "severity": severity,
        "event_time": event.get("time") or utc_now_iso(),
        "principal": principal,
        "principal_normalized": event.get("principal_normalized"),
        "resource": resource,
        "method_name": method_name,
        "organization_id": event.get("organization_id"),
        "environment_id": event.get("environment_id"),
        "cluster_id": event.get("cluster_id"),
        "recommended_action": (
            "Validate whether this change was expected, confirm actor identity, "
            "and review surrounding audit activity in AuditLens."
        ),
        "confidence": "high" if severity == "CRITICAL" else "medium",
        "source_event_id": event.get("id"),
        "classification_reason": event.get("classification_reason"),
    }


def build_anomaly_alert(anomaly) -> dict:
    """Convert anomaly tracker output into an operator alert record."""
    principal = getattr(anomaly, "principal", None)
    source_ip = getattr(anomaly, "source_ip", None)
    anomaly_type = getattr(anomaly, "anomaly_type", None)
    anomaly_name = anomaly_type.value if anomaly_type else "anomaly"
    severity = getattr(anomaly, "severity", "MEDIUM")
    rate = getattr(anomaly, "rate", None)
    threshold = getattr(anomaly, "threshold", None)
    return {
        "schema_version": "audit.alerts.v1",
        "alert_type": anomaly_name,
        "severity": severity,
        "event_time": utc_now_iso(),
        "principal": principal,
        "principal_normalized": principal,
        "resource": None,
        "method_name": None,
        "recommended_action": (
            "Review recent audit activity for this principal, validate whether the "
            "behavior is expected, and investigate correlated failures or source IP changes."
        ),
        "confidence": "medium" if severity == "MEDIUM" else "high",
        "source_ip": source_ip,
        "observed_rate": rate,
        "threshold": threshold,
    }

metrics = Metrics()


def redact_value(name: str, value):
    if value is None:
        return None
    normalized = name.lower().replace("-", "_").replace(".", "_")
    if any(token in normalized for token in _SENSITIVE_KEY_TOKENS):
        return "***MASKED***"
    return value


def validate_startup_config() -> dict:
    """Validate canonical foundation configuration and return grouped metadata."""
    config_groups = {
        "source_audit_cluster": {
            "AUDIT_BOOTSTRAP": AUDIT_BOOTSTRAP,
            "AUDIT_API_KEY": AUDIT_API_KEY,
            "AUDIT_API_SECRET": AUDIT_API_SECRET,
            "AUDIT_TOPIC": AUDIT_TOPIC,
            "GROUP_ID": GROUP_ID,
            "AUTO_OFFSET_RESET": AUTO_OFFSET_RESET,
        },
        "internal_kafka_topics": {
            "DEST_BOOTSTRAP": DEST_BOOTSTRAP,
            "DEST_API_KEY": DEST_API_KEY,
            "DEST_API_SECRET": DEST_API_SECRET,
            "AUDIT_RAW_TOPIC": AUDIT_RAW_TOPIC,
            "AUDIT_NORMALIZED_TOPIC": AUDIT_NORMALIZED_TOPIC,
            "AUDIT_ENRICHED_TOPIC": AUDIT_ENRICHED_TOPIC,
            "AUDIT_SIGNALS_DENIALS_TOPIC": AUDIT_SIGNALS_DENIALS_TOPIC,
            "AUDIT_SIGNALS_HIGHRISK_TOPIC": AUDIT_SIGNALS_HIGHRISK_TOPIC,
            "AUDIT_ALERTS_TOPIC": AUDIT_ALERTS_TOPIC,
            "DLQ_TOPIC": DLQ_TOPIC,
        },
        "alerting": {
            "SLACK_WEBHOOK": os.getenv("SLACK_WEBHOOK"),
            "ALERT_ON_HIGH_RISK": str(ALERT_ON_HIGH_RISK).lower(),
            "ENABLE_DENIAL_AGGREGATION": str(ENABLE_DENIAL_AGGREGATION).lower(),
        },
        "dashboard_api": {
            "METRICS_PORT": str(METRICS_PORT),
            "API_MAX_SEARCH_RESULTS": str(API_MAX_SEARCH_RESULTS),
            "API_AUTH_ENABLED": str(AUTH_CONFIG.enabled).lower(),
            "API_EXPORT_MAX_ROWS": str(API_EXPORT_MAX_ROWS),
            "API_EXPORT_MAX_HOURS": str(API_EXPORT_MAX_HOURS),
        },
        "monitoring": {
            "SCHEMA_REGISTRY_URL": SCHEMA_REGISTRY_URL,
            "SCHEMA_REGISTRY_KEY": SCHEMA_REGISTRY_KEY,
            "SCHEMA_REGISTRY_SECRET": SCHEMA_REGISTRY_SECRET,
        },
        "persistence": {
            "PERSISTENCE_ENABLED": str(PERSISTENCE_CONFIG.enabled).lower(),
            "PERSISTENCE_BACKEND": PERSISTENCE_CONFIG.backend,
            "PERSISTENCE_DB_PATH": PERSISTENCE_CONFIG.db_path,
        },
        "feature_flags": {
            "ENABLE_LEGACY_MULTI_TOPIC_ROUTING": str(ENABLE_MULTI_TOPIC_ROUTING).lower(),
            "AUDIT_ROUTER_DRY_RUN": str(ROUTER_DRY_RUN).lower(),
        },
        "offset_recovery": {
            "OFFSET_MODEL": "consumer_group_only",
            "OFFSET_COMMIT_MODE": "after_persistence_and_kafka_flush",
            "DELIVERY_SEMANTICS": "at_least_once",
        },
    }

    missing_required = {
        "source_audit_cluster": [
            key for key in ("AUDIT_BOOTSTRAP", "AUDIT_API_KEY", "AUDIT_API_SECRET")
            if not config_groups["source_audit_cluster"].get(key)
        ],
        "internal_kafka_topics": [
            key for key in ("DEST_BOOTSTRAP", "DEST_API_KEY", "DEST_API_SECRET")
            if not config_groups["internal_kafka_topics"].get(key)
        ],
    }
    missing_required = {group: keys for group, keys in missing_required.items() if keys}

    topic_values = [
        AUDIT_RAW_TOPIC,
        AUDIT_NORMALIZED_TOPIC,
        AUDIT_ENRICHED_TOPIC,
        AUDIT_SIGNALS_DENIALS_TOPIC,
        AUDIT_SIGNALS_HIGHRISK_TOPIC,
        AUDIT_ALERTS_TOPIC,
        DLQ_TOPIC,
    ]
    duplicate_topics = sorted({topic for topic in topic_values if topic_values.count(topic) > 1})
    invalid_offset = AUTO_OFFSET_RESET not in {"latest", "earliest"}

    auth_missing = AUTH_CONFIG.enabled and not AUTH_CONFIG.tokens
    persistence_invalid = PERSISTENCE_CONFIG.enabled and PERSISTENCE_CONFIG.backend != "sqlite"

    summary = {
        "app_name": "AuditLens",
        "version": VERSION,
        "valid": not missing_required and not duplicate_topics and not invalid_offset and not auth_missing and not persistence_invalid,
        "missing_required": missing_required,
        "duplicate_topics": duplicate_topics,
        "invalid_values": (
            (["AUTO_OFFSET_RESET"] if invalid_offset else []) +
            (["API_AUTH_TOKENS_JSON/API_AUTH_TOKEN_FILE"] if auth_missing else []) +
            (["PERSISTENCE_BACKEND"] if persistence_invalid else [])
        ),
        "config_groups": {
            group: {key: redact_value(key, value) for key, value in values.items()}
            for group, values in config_groups.items()
        },
    }
    return summary


class ApiState:
    """Small in-memory cache for recent searchable foundation data."""

    def __init__(self):
        self._lock = threading.Lock()
        self.enriched_events = deque(maxlen=API_BUFFER_ENRICHED)
        self.high_risk_events = deque(maxlen=API_BUFFER_SIGNALS)
        self.denial_summaries = deque(maxlen=API_BUFFER_SIGNALS)
        self.alerts = deque(maxlen=API_BUFFER_SIGNALS)
        self.last_enriched_event_time = None
        self.last_enriched_ingest_at = None
        self.last_denial_flush_at = None
        self.coverage_note = (
            "API v1 serves recent in-memory investigation data from the running forwarder. "
            "Historical completeness depends on destination Kafka topics."
        )

    def record_enriched_event(self, event: dict):
        with self._lock:
            self.enriched_events.appendleft(event)
            self.last_enriched_event_time = event.get("time")
            self.last_enriched_ingest_at = utc_now_iso()
            if event.get("is_high_risk"):
                self.high_risk_events.appendleft(event)

    def record_denial_summary(self, summary: dict):
        with self._lock:
            self.denial_summaries.appendleft(summary)
            self.last_denial_flush_at = utc_now_iso()

    def record_alert(self, alert: dict):
        with self._lock:
            self.alerts.appendleft(alert)

    def snapshot(self):
        with self._lock:
            return {
                "enriched_events": list(self.enriched_events),
                "high_risk_events": list(self.high_risk_events),
                "denial_summaries": list(self.denial_summaries),
                "alerts": list(self.alerts),
                "last_enriched_event_time": self.last_enriched_event_time,
                "last_enriched_ingest_at": self.last_enriched_ingest_at,
                "last_denial_flush_at": self.last_denial_flush_at,
                "coverage_note": self.coverage_note,
            }


api_state = ApiState()


class ReplayState:
    """Single-instance replay status."""

    def __init__(self):
        self._lock = threading.Lock()
        self.in_progress = False
        self.source_mode = None
        self.window_mode = None
        self.hours = None
        self.publish_topics = False
        self.started_at = None
        self.completed_at = None
        self.last_success_at = None
        self.last_error = None
        self.processed_records = 0
        self.rebuilt_enriched = 0
        self.generated_signals = 0
        self.generated_alerts = 0

    def snapshot(self):
        with self._lock:
            return {
                "in_progress": self.in_progress,
                "source_mode": self.source_mode,
                "window_mode": self.window_mode,
                "hours": self.hours,
                "publish_topics": self.publish_topics,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "last_success_at": self.last_success_at,
                "last_error": self.last_error,
                "processed_records": self.processed_records,
                "rebuilt_enriched": self.rebuilt_enriched,
                "generated_signals": self.generated_signals,
                "generated_alerts": self.generated_alerts,
            }

    def start(self, source_mode: str, window_mode: str, hours: int | None, publish_topics: bool):
        with self._lock:
            if self.in_progress:
                raise RuntimeError("replay already in progress")
            self.in_progress = True
            self.source_mode = source_mode
            self.window_mode = window_mode
            self.hours = hours
            self.publish_topics = publish_topics
            self.started_at = utc_now_iso()
            self.completed_at = None
            self.last_error = None
            self.processed_records = 0
            self.rebuilt_enriched = 0
            self.generated_signals = 0
            self.generated_alerts = 0

    def progress(self, processed_delta: int = 0, rebuilt_delta: int = 0, signals_delta: int = 0, alerts_delta: int = 0):
        with self._lock:
            self.processed_records += processed_delta
            self.rebuilt_enriched += rebuilt_delta
            self.generated_signals += signals_delta
            self.generated_alerts += alerts_delta

    def finish(self, success: bool, error: str | None = None):
        with self._lock:
            self.in_progress = False
            self.completed_at = utc_now_iso()
            self.last_error = error
            if success:
                self.last_success_at = self.completed_at


replay_state = ReplayState()



def persist_safely(label: str, fn, *args, **kwargs) -> None:
    """Run a SQLite hot-cache write that must never block the consume path.

    Postgres is the durable source of truth (db_writer.write_batch). The
    in-process SQLite store is a query accelerator only — a failed write
    here is logged at WARN and dropped. Callers explicitly choose this
    helper for hot-path writes; durable writes still propagate exceptions.
    """
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("sqlite_write_failed label=%s error=%s", label, mask_sensitive_text(str(exc)))


def make_rdkafka_stats_callback(metrics_obj):
    """Build a librdkafka stats callback that updates per-partition lag.

    librdkafka emits a JSON stats blob every ``statistics.interval.ms``
    that includes ``consumer_lag`` per partition. Reading from that is
    free (no network), thread-safe (callback runs in a librdkafka
    background thread), and replaces the previous synchronous
    ``get_watermark_offsets`` polling that could stall the consume
    loop during cross-region latency spikes.

    Stats arrive as a JSON string; we parse and write into
    ``metrics_obj.partition_lag`` so existing /health and Prometheus
    surfaces see fresh numbers without code changes.
    """
    def _on_stats(stats_json_str: str) -> None:
        try:
            stats = orjson.loads(stats_json_str)
        except Exception as exc:
            logger.debug("rdkafka stats parse failed: %s", exc)
            return
        try:
            for topic_data in (stats.get("topics") or {}).values():
                for partition_id, partition_data in (topic_data.get("partitions") or {}).items():
                    try:
                        p_id = int(partition_id)
                    except (TypeError, ValueError):
                        continue
                    if p_id < 0:
                        # librdkafka uses negative ids for internal "partition -1" tombstones
                        continue
                    consumer_lag = partition_data.get("consumer_lag")
                    if consumer_lag is None or consumer_lag < 0:
                        continue
                    hi = partition_data.get("hi_offset")
                    pos = (hi - consumer_lag) if isinstance(hi, int) and hi >= 0 else (hi or 0)
                    metrics_obj.update_lag(p_id, pos, hi if isinstance(hi, int) else (pos + consumer_lag))
        except Exception as exc:
            logger.debug("rdkafka stats apply failed: %s", exc)

    return _on_stats

# ──────────── kafka configs ────────────
# Consumer tuning rationale:
# - fetch.min.bytes 64 KB: wait for real batches; saves request overhead.
# - fetch.wait.max.ms 500 ms: bound on how long the broker waits for those bytes.
# - fetch.max.bytes 50 MB: large enough for catchup scenarios over hot partitions.
# - max.partition.fetch.bytes 1 MB: per-partition cap; defaults are fine.
# - session.timeout.ms 45 s + heartbeat.interval.ms 15 s (1/3 of session): tolerate
#   slow PG writes without rebalancing while still detecting a hung consumer.
# - max.poll.interval.ms 5 min: only relevant for the high-level `subscribe`
#   model; we use confluent-kafka's lower-level consumer where librdkafka does
#   heartbeats internally, but we set it as a defence-in-depth limit.
# - group.instance.id: static membership — restarts don't trigger a full
#   rebalance, only a brief heartbeat gap.
# - queued.max.messages.kbytes 1 GB: large internal librdkafka buffer so the
#   consume thread keeps fetching while the processor is slow.
# - statistics.interval.ms 10 s: fires stats_cb (set in main()) so we read
#   per-partition lag from rdkafka stats instead of synchronous
#   get_watermark_offsets calls.
consumer_conf = {
    "bootstrap.servers":         AUDIT_BOOTSTRAP,
    "security.protocol":         "SASL_SSL",
    "sasl.mechanism":            "PLAIN",
    "sasl.username":             AUDIT_API_KEY,
    "sasl.password":             AUDIT_API_SECRET,
    "group.id":                  GROUP_ID,
    # Explicit offset commits after batch processing (at-least-once delivery)
    "enable.auto.commit":        False,
    "auto.offset.reset":         AUTO_OFFSET_RESET,
    "fetch.min.bytes":           int(os.getenv("KAFKA_FETCH_MIN_BYTES", str(64 * 1024))),
    "fetch.max.bytes":           int(os.getenv("KAFKA_FETCH_MAX_BYTES", str(50 * 1024 * 1024))),
    "fetch.wait.max.ms":         int(os.getenv("KAFKA_FETCH_MAX_WAIT_MS", os.getenv("KAFKA_FETCH_WAIT_MAX_MS", "500"))),
    "max.partition.fetch.bytes": int(os.getenv("KAFKA_MAX_PARTITION_FETCH_BYTES", str(1 * 1024 * 1024))),
    "queued.min.messages":       int(os.getenv("KAFKA_QUEUED_MIN_MESSAGES", "1000")),
    "queued.max.messages.kbytes": int(os.getenv("KAFKA_QUEUED_MAX_MESSAGES_KBYTES", str(1 * 1024 * 1024))),
    "session.timeout.ms":        int(os.getenv("KAFKA_SESSION_TIMEOUT_MS", "45000")),
    "heartbeat.interval.ms":     int(os.getenv("KAFKA_HEARTBEAT_INTERVAL_MS", "15000")),
    "max.poll.interval.ms":      int(os.getenv("KAFKA_MAX_POLL_INTERVAL_MS", "300000")),
    "socket.timeout.ms":         30000,
    "statistics.interval.ms":    int(os.getenv("KAFKA_STATS_INTERVAL_MS", "10000")),
}
_group_instance_id = os.getenv("KAFKA_GROUP_INSTANCE_ID", "").strip()
if _group_instance_id:
    # Static membership keeps the same partition assignment across restarts —
    # avoids a full rebalance storm when the forwarder cycles. Set to a
    # stable, unique-per-replica id (e.g. "auditlens-forwarder-1").
    consumer_conf["group.instance.id"] = _group_instance_id

producer_conf = {
    "bootstrap.servers":            DEST_BOOTSTRAP,
    "security.protocol":            "SASL_SSL",
    "sasl.mechanism":               "PLAIN",
    "sasl.username":                DEST_API_KEY,
    "sasl.password":                DEST_API_SECRET,
    "enable.idempotence":           True,               # Enable for exactly-once semantics
    "acks":                         "all",              # All replicas must ack (audit data = no loss)
    "retries":                      3,                  # Fewer retries
    "delivery.timeout.ms":          120000,             # 2 min timeout
    "linger.ms":                    10,                 # Batch for 10ms (was 20)
    "batch.size":                   int(os.getenv("KAFKA_PRODUCER_BATCH_SIZE", str(512 * 1024))),
    "batch.num.messages":           int(os.getenv("KAFKA_PRODUCER_BATCH_NUM_MESSAGES", "10000")),
    "queue.buffering.max.messages": int(os.getenv("KAFKA_PRODUCER_QUEUE_MAX_MESSAGES", "100000")),
    "queue.buffering.max.kbytes":   int(os.getenv("KAFKA_PRODUCER_QUEUE_MAX_KBYTES", str(64 * 1024))),
    "compression.type":             "lz4",              # LZ4 compression for speed
}

# ──────────── offset management ────────────
# NOTE: Offsets are now managed entirely by Kafka consumer groups.
# No file-based offset storage - enables horizontal scaling and crash recovery.
# After each batch is processed and produced, we call consumer.commit() explicitly.
# This is "at-least-once" delivery: commit AFTER successful produce.

# ──────────── delivery callback ────────────
delivery_errors = {"count": 0, "last_error": None}
_delivery_errors_lock = threading.Lock()
dlq_stats = {"sent": 0, "failed": 0, "enqueued": 0}
_dlq_stats_lock = threading.Lock()

# Wire module-level singletons into the health_server DI stubs so that tests
# patching forwarder.metrics / forwarder.api_state etc. see the same objects
# in health_server, and so MetricsHandler works before start_metrics_server()
# is called. replay_events is a function defined below; it's injected at the
# start_metrics_server() call site in main().
_health_server_module.metrics = metrics
_health_server_module.api_state = api_state
_health_server_module.replay_state = replay_state
_health_server_module.authenticator = authenticator
_health_server_module.delivery_errors = delivery_errors
_health_server_module.dlq_stats = dlq_stats
_health_server_module.validate_startup_config = validate_startup_config


def _dlq_delivery_callback(err, msg):
    with _dlq_stats_lock:
        if not err:
            dlq_stats["sent"] += 1
        else:
            dlq_stats["failed"] += 1


def delivery_callback(err, msg):
    """Track delivery errors."""
    if err:
        with _delivery_errors_lock:
            delivery_errors["count"] += 1
            # Always store the masked form so anything that subsequently reads
            # delivery_errors["last_error"] (the heartbeat log, the /health probe,
            # etc.) cannot inadvertently leak secrets.
            delivery_errors["last_error"] = mask_sensitive_text(str(err))
        metrics.record_delivery_failure(msg.topic() if msg else "unknown")
        if delivery_errors["count"] <= 10 or delivery_errors["count"] % 1000 == 0:
            logger.error(
                "Delivery failed (%d total): %s",
                delivery_errors["count"],
                mask_sensitive_text(str(err)),
            )
        metrics.record_error()
    else:
        metrics.record_delivery_success(msg.topic())

def send_to_dlq(producer, raw_value: bytes, error_msg: str, source_topic: str, partition: int, offset: int):
    """Send failed event to Dead Letter Queue with error metadata."""
    if not ENABLE_DLQ:
        return

    try:
        dlq_event = {
            "original_value": raw_value.decode('utf-8', errors='replace'),
            "error": error_msg,
            "source_topic": source_topic,
            "source_partition": partition,
            "source_offset": offset,
            "failed_at": utc_now_iso(),
            "forwarder_version": VERSION,
        }
        producer.produce(
            DLQ_TOPIC,
            key=f"{source_topic}-{partition}-{offset}".encode('utf-8'),
            value=orjson.dumps(dlq_event),
            callback=_dlq_delivery_callback,
        )
        with _dlq_stats_lock:
            dlq_stats["enqueued"] += 1
    except Exception as e:
        with _dlq_stats_lock:
            dlq_stats["failed"] += 1
        logger.warning("Failed to send to DLQ: %s", e)

# ──────────── safe produce helper ────────────
MAX_PRODUCE_RETRIES = 10


def safe_produce(p: Producer, topic: str, key: bytes, value: bytes):
    retries = 0
    event_fingerprint = key.decode("utf-8", errors="replace") if key else None
    while retries < MAX_PRODUCE_RETRIES:
        try:
            # drive I/O to free up buffer slots
            p.poll(0)
            metrics.record_delivery_attempt(topic)
            p.produce(topic, key=key, value=value, callback=delivery_callback)
            return True
        except BufferError:
            # buffer is full—wait briefly for background I/O
            retries += 1
            p.poll(0.1)
    metrics.record_produce_retry_exhausted()
    logger.critical(
        "Producer buffer exhausted after %d retries; routing to DLQ if enabled topic=%s event_fingerprint=%s",
        MAX_PRODUCE_RETRIES,
        topic,
        event_fingerprint or "unknown",
    )
    if ENABLE_DLQ and topic != DLQ_TOPIC:
        try:
            send_to_dlq(
                p,
                value,
                f"producer buffer exhausted after {MAX_PRODUCE_RETRIES} retries",
                topic,
                -1,
                -1,
            )
        except Exception as exc:
            logger.warning("Failed to route exhausted produce to DLQ: %s", exc)
    return False

# ──────────── partition assign callback ────────────
def on_assign(consumer, partitions):
    """Handle partition assignment - offsets managed by Kafka consumer groups."""
    metrics.record_rebalance()
    # Let Kafka consumer group handle offsets automatically
    # On first join: starts from auto.offset.reset (latest)
    # On rejoins: resumes from last committed offset
    for tp in partitions:
        try:
            low, high = consumer.get_watermark_offsets(tp, timeout=5.0)
            logger.info("Assigned partition %d: watermarks low=%d high=%d", tp.partition, low, high)
        except Exception as e:
            logger.warning("Could not get watermarks for partition %d: %s", tp.partition, e)
    logger.info("Assigned %d partitions: %s", len(partitions), [p.partition for p in partitions])


def on_revoke(consumer, partitions):
    """Track revocations during rebalances."""
    metrics.record_rebalance()
    logger.warning("Revoked %d partitions: %s", len(partitions), [p.partition for p in partitions])


def _handle_denial_summary_flush(alert) -> None:
    summary = alert.to_dict()
    api_state.record_denial_summary(summary)
    metrics.record_signal("denial_summary")
    if product_store:
        product_store.persist_denial_summary(summary)
        metrics.record_persistence_success(product_store.health())
        if summary.get("threshold_exceeded"):
            product_store.persist_alert(summary)
            metrics.record_persistence_success(product_store.health())


class _RecordMeta:
    """Minimal message metadata adapter used by replay and tests."""

    def __init__(self, topic_name: str, partition_id: int, offset_value: int):
        self._topic_name = topic_name
        self._partition_id = partition_id
        self._offset_value = offset_value

    def topic(self):
        return self._topic_name

    def partition(self):
        return self._partition_id

    def offset(self):
        return self._offset_value


class _NoOpProducer:
    """Producer stub used for replay rebuilds when topic publishing is disabled."""

    def produce(self, *args, **kwargs):
        callback = kwargs.get("callback")
        if callback:
            class _Msg:
                def topic(self_inner):
                    return kwargs.get("topic", "replay")
                def partition(self_inner):
                    return 0
                def offset(self_inner):
                    return 0
            callback(None, _Msg())

    def poll(self, timeout):
        return None

    def flush(self, timeout=0):
        return 0


class RuntimeBackoff:
    """Bound retry loops so DNS/Kafka failures do not hot-loop under Docker restart."""

    def __init__(
        self,
        initial: float = KAFKA_RETRY_INITIAL_BACKOFF_SECONDS,
        maximum: float = KAFKA_RETRY_MAX_BACKOFF_SECONDS,
        jitter_ratio: float = 0.20,
    ):
        self.initial = max(0.1, initial)
        self.maximum = max(self.initial, maximum)
        self.jitter_ratio = max(0.0, jitter_ratio)
        self.current = self.initial

    def reset(self) -> None:
        self.current = self.initial

    def next_delay(self) -> float:
        delay = self.current
        self.current = min(self.maximum, self.current * 2)
        if self.jitter_ratio <= 0:
            return delay
        jitter = delay * self.jitter_ratio
        return max(0.1, delay + random.uniform(-jitter, jitter))


def _sleep_with_shutdown(delay_seconds: float) -> None:
    deadline = time.time() + max(0.0, delay_seconds)
    while not _shutdown_requested and time.time() < deadline:
        time.sleep(min(0.5, max(0.0, deadline - time.time())))


def _should_log_repeated_error(state: dict, error_text: str) -> bool:
    now = time.time()
    if error_text != state.get("last_error") or now - state.get("last_log_at", 0) >= KAFKA_ERROR_LOG_INTERVAL_SECONDS:
        state["last_error"] = error_text
        state["last_log_at"] = now
        return True
    return False


def initialize_db_writer_if_enabled():
    global db_writer, _db_init_next_attempt
    if not ENABLE_DB_WRITER:
        metrics.set_db_writer_state("disabled")
        return None
    if db_writer is not None:
        return db_writer
    # Circuit breaker: if the last init attempt failed, wait before retrying
    # to avoid creating a new SQLAlchemy engine (and leaking a connection pool)
    # on every call during an extended DB outage.
    if time.monotonic() < _db_init_next_attempt:
        return None
    metrics.set_db_writer_state("retrying")
    try:
        db_writer = AuditEventDbWriter(
            DATABASE_URL,
            retention_days=EVENT_RETENTION_DAYS,
            retention_cleanup_interval_seconds=DB_RETENTION_CLEANUP_INTERVAL_SECONDS,
        )
        metrics.set_db_writer_state("connected")
        _db_init_next_attempt = 0.0  # reset — success
        logger.info("DB writer enabled: mode=%s", db_writer.mode)
        return db_writer
    except Exception as exc:
        masked = mask_sensitive_text(str(exc))
        # Exponential backoff — cap at 60s to avoid stalling too long
        _db_init_next_attempt = time.monotonic() + min(
            60.0, 2.0 ** min(metrics.db_write_consecutive_error_count, 6)
        )
        metrics.record_db_write_error(masked, 0)
        logger.warning(
            "DB writer init failed (retry in %.0fs): %s",
            _db_init_next_attempt - time.monotonic(),
            masked,
        )
        return None


def flush_db_writer_noise_batch(
    payloads: list[dict],
    backoff: RuntimeBackoff,
    log_state: dict,
    *,
    label: str = "bulk",
) -> bool:
    """Bulk-noise INSERT into audit_events_noise. Skips fingerprint /
    enrichment / catalog upsert. Writer signature mirrors
    flush_db_writer_batch so the writer-thread loop can dispatch on lane."""
    if not ENABLE_DB_WRITER or not payloads:
        return True
    try:
        writer = initialize_db_writer_if_enabled()
        if writer is None:
            return False
        result = writer.write_noise_batch(payloads)
        max_event_iso = _max_event_timestamp_iso(payloads)
        metrics.record_db_write_success(result.attempted, max_event_timestamp_iso=max_event_iso)
        backoff.reset()
        logger.info(
            "DB writer batch complete lane=%s table=audit_events_noise attempted=%d inserted=%d "
            "elapsed_ms=%.1f [normalize=%.0fms pg_insert=%.0fms]",
            label, result.attempted, result.inserted, result.elapsed_ms,
            getattr(result, "normalize_ms", 0.0),
            getattr(result, "pg_insert_ms", 0.0),
        )
        return True
    except Exception as exc:
        delay = backoff.next_delay()
        masked_exc = mask_sensitive_text(str(exc))
        metrics.record_db_write_error(masked_exc, len(payloads))
        metrics.set_db_writer_state("backoff")
        if _should_log_repeated_error(log_state, masked_exc):
            logger.warning("DB noise writer failed; backing off for %.1fs: %s", delay, masked_exc)
        _sleep_with_shutdown(delay)
        return False


def flush_db_writer_batch(
    payloads: list[dict],
    backoff: RuntimeBackoff,
    log_state: dict,
    *,
    defer_catalog: bool = False,
    catalog_target: "queue.Queue | None" = None,
    label: str = "",
) -> bool:
    if not ENABLE_DB_WRITER or not payloads:
        return True
    try:
        writer = initialize_db_writer_if_enabled()
        if writer is None:
            return False
        # Pass defer_catalog only when set so older test doubles whose
        # write_batch signature predates the kwarg keep working.
        if defer_catalog:
            result = writer.write_batch(payloads, defer_catalog=True)
        else:
            result = writer.write_batch(payloads)
        max_event_iso = _max_event_timestamp_iso(payloads)
        metrics.record_db_write_success(result.attempted, max_event_timestamp_iso=max_event_iso)
        cleanup = writer.cleanup_retention_if_due()
        if cleanup:
            metrics.record_db_retention_cleanup(cleanup)
        backoff.reset()
        logger.info(
            "DB writer batch complete%s attempted=%d inserted=%d elapsed_ms=%.1f "
            "[normalize=%.0fms pg_insert=%.0fms catalog_upsert=%.0fms]",
            f" lane={label}" if label else "",
            result.attempted,
            result.inserted,
            result.elapsed_ms,
            getattr(result, "normalize_ms", 0.0),
            getattr(result, "pg_insert_ms", 0.0),
            getattr(result, "catalog_upsert_ms", 0.0),
        )
        if defer_catalog and catalog_target is not None:
            for row in result.deferred_catalog_rows or []:
                try:
                    catalog_target.put_nowait(row)
                except queue.Full:
                    # Catalog rows are derived state — losing one here is
                    # harmless because the next event for the same resource
                    # will re-derive it. We just lose the last_seen_at update.
                    metrics.record_db_write_error("catalog_queue full", 0)
                    break
        return True
    except Exception as exc:
        delay = backoff.next_delay()
        masked_exc = mask_sensitive_text(str(exc))
        metrics.record_db_write_error(masked_exc, len(payloads))
        metrics.set_db_writer_state("backoff")
        metrics.set_consumer_state("degraded", delay)
        if _should_log_repeated_error(log_state, masked_exc):
            logger.warning("DB writer failed; backing off for %.1fs: %s", delay, masked_exc)
        _sleep_with_shutdown(delay)
        return False


def flush_db_writer_buffer(payloads: list[dict], backoff: RuntimeBackoff, log_state: dict, *, force: bool = False, executor: ThreadPoolExecutor | None = None) -> bool:
    """Flush the in-memory DB write buffer.

    Without an executor: chunk by DB_WRITE_BATCH_SIZE and write sequentially
    (the historical contract — preserved for any non-thread-pool callers).

    With an executor: when ``force=True`` and the buffer has more than one
    chunk, split it into chunks and submit each to the executor for parallel
    execution. Wait for all chunks. The wall-clock time of a buffer flush
    drops to roughly the time of the slowest chunk, which is the ceiling
    we hit at one writer per Postgres connection.
    """
    if not ENABLE_DB_WRITER or not payloads:
        return True
    batch_size = max(1, DB_WRITE_BATCH_SIZE)
    if executor is not None and force:
        # Parallel chunk size is configurable independently of the trigger
        # threshold — when the buffer arrives equal to DB_WRITE_BATCH_SIZE
        # we still want to split it across multiple workers. Falls back to
        # DB_WRITE_BATCH_SIZE if not set.
        parallel_chunk = max(1, int(os.getenv("DB_WRITE_PARALLEL_CHUNK_SIZE", str(batch_size))))
        if len(payloads) > parallel_chunk:
            chunks = [payloads[i:i + parallel_chunk] for i in range(0, len(payloads), parallel_chunk)]
            # Submit copies so the caller's payload mutation doesn't race the workers.
            futures = [
                executor.submit(
                    flush_db_writer_batch,
                    list(chunk),
                    RuntimeBackoff(maximum=DB_WRITE_BACKOFF_MAX_SECONDS),  # fresh per chunk
                    {},                                                      # fresh per chunk
                )
                for chunk in chunks
            ]
            all_ok = True
            for fut in futures:
                try:
                    ok = fut.result(timeout=180)
                except Exception as exc:
                    logger.warning("Parallel DB write chunk raised: %s", mask_sensitive_text(str(exc)))
                    ok = False
                all_ok = all_ok and ok
            if all_ok:
                del payloads[:]
            return all_ok
    while payloads and (force or len(payloads) >= batch_size):
        chunk = payloads[:batch_size]
        # Keep the in-memory buffer intact until the DB write returns success.
        # If the write fails, the same chunk must remain retryable on the next pass.
        if not flush_db_writer_batch(chunk, backoff, log_state):
            return False
        del payloads[:len(chunk)]
        if not force:
            break
    return True


def evaluate_batch_commit(flush_remaining: int, delivery_errors_before: int, delivery_errors_after: int, processing_failed: bool) -> tuple[bool, dict]:
    """Return whether offsets may be committed for a processed batch."""
    details = {
        "flush_remaining": flush_remaining,
        "delivery_errors_before": delivery_errors_before,
        "delivery_errors_after": delivery_errors_after,
        "processing_failed": processing_failed,
    }
    should_commit = flush_remaining == 0 and delivery_errors_after == delivery_errors_before and not processing_failed
    return should_commit, details


def initialize_product_store_or_exit() -> None:
    """Initialize durable product storage if enabled."""
    global product_store
    if not PERSISTENCE_CONFIG.enabled:
        return
    if product_store is not None:
        return
    if not _sqlite_hot_cache_enabled():
        # Postgres-backed deployments don't need the legacy SQLite hot
        # cache — Postgres IS the durable store. Leave product_store as
        # None; every call site already guards on `if product_store: …`,
        # so persistence calls become no-ops without raising. The
        # SQLiteProductStore class stays compiled for demo mode.
        if PRODUCT_MODE:
            logger.info("Storage mode: PRODUCT (Postgres only — SQLite hot cache disabled)")
        else:
            logger.info(
                "Storage mode: SQLite hot cache: DISABLED "
                "(ENABLE_SQLITE_HOT_CACHE=%s)",
                ENABLE_SQLITE_HOT_CACHE,
            )
        metrics.record_persistence_disabled()
        return
    try:
        # Heal the SQLite hot cache before opening the long-lived
        # connection. Either reclaims accumulated freelist pages via
        # incremental_vacuum, or — when the file was created with
        # auto_vacuum=NONE and so cannot reclaim in-place — deletes the
        # file so initialize() recreates it fresh with the correct
        # pragmas. Safe because Postgres is the durable source of truth.
        heal_sqlite_on_startup(PERSISTENCE_CONFIG.db_path)
        product_store = SQLiteProductStore(PERSISTENCE_CONFIG)
        product_store.initialize()
        product_store.enforce_storage_bounds(trigger="startup")
        metrics.record_persistence_success(product_store.health())
        metrics.set_restart_count(product_store.health().get("startup_count", 0))
        if PRODUCT_MODE:
            # Caller asked for hot cache + Postgres concurrently
            # (ENABLE_SQLITE_HOT_CACHE=true). Surface the choice clearly so
            # operators know they're paying for two stores.
            logger.info(
                "Storage mode: PRODUCT + SQLite hot cache (ENABLE_SQLITE_HOT_CACHE=true) — "
                "dual-write active"
            )
        else:
            logger.info("Storage mode: DEMO (SQLite hot cache active)")
        logger.info("Persistence initialized: backend=%s path=%s",
                    PERSISTENCE_CONFIG.backend, PERSISTENCE_CONFIG.db_path)
    except Exception as exc:
        masked_exc = mask_sensitive_text(str(exc))
        metrics.record_persistence_failure(masked_exc)
        logger.error("Persistence initialization failed: %s", masked_exc)
        sys.exit(1)


def run_storage_monitor_tick(trigger: str = "periodic") -> None:
    """Check bounded hot-cache state and rotate if storage exceeds the hard cap."""
    if not product_store:
        return
    try:
        status = product_store.enforce_storage_bounds(trigger=trigger)
        product_store.checkpoint_wal(mode="PASSIVE")
        metrics.record_persistence_success(product_store.health())
        storage_mode = status.get("storage_mode", "unknown")
        if storage_mode in {"warning", "critical", "emergency"} or status.get("storage_degraded"):
            logger.warning(
                "SQLite hot-cache monitor: trigger=%s storage_mode=%s storage_degraded=%s current_size=%s max_size=%s write_guard_active=%s",
                trigger,
                storage_mode,
                status.get("storage_degraded"),
                status.get("current_db_size"),
                status.get("max_db_size"),
                status.get("write_guard_active"),
            )
    except Exception as exc:
        metrics.record_persistence_failure(str(exc))
        logger.warning("SQLite hot-cache monitor failed: trigger=%s error=%s", trigger, exc)


def start_storage_monitor() -> None:
    """Start periodic storage enforcement without blocking the processing loop."""
    global storage_monitor_thread
    if not product_store or storage_monitor_thread is not None:
        return

    def _loop() -> None:
        while not storage_monitor_stop.wait(max(1, STORAGE_MONITOR_INTERVAL_SECONDS)):
            run_storage_monitor_tick(trigger="periodic")

    storage_monitor_thread = threading.Thread(target=_loop, name="auditlens-storage-monitor", daemon=True)
    storage_monitor_thread.start()
    logger.info("SQLite hot-cache monitor started: interval_seconds=%d", STORAGE_MONITOR_INTERVAL_SECONDS)


def recompute_enriched_event(event: dict) -> dict:
    """Re-run classification on an existing enriched/flat event."""
    updated = dict(event)
    classification_result = calculate_criticality(updated)
    updated["criticality"] = classification_result.criticality.value
    updated["classification_reason"] = classification_result.reason
    updated["criticality_elevated"] = classification_result.elevated
    updated["method_category"] = classification_result.method_category
    updated["is_security_event"] = classification_result.is_security_event
    updated["is_signal_candidate"] = classification_result.is_signal_candidate
    updated["signal_type"] = classification_result.signal_type
    method_name = updated.get("methodName", "") or ""
    _method_lower = method_name.lower()
    updated["is_deletion"] = "delete" in _method_lower
    updated["is_creation"] = "create" in _method_lower
    updated["is_modification"] = any(op in _method_lower for op in ("update", "alter"))
    updated["schema_version"] = "audit.enriched.v1"
    updated["pipeline_stage"] = "enriched"
    updated["event_contract_version"] = "v1"
    updated["is_high_risk"] = (
        updated.get("criticality") == "CRITICAL" or
        updated.get("methodName") in HIGH_RISK_SIGNAL_METHODS
    )
    return updated


def _persist_replay_artifacts(
    producer,
    enriched_event: dict,
    meta: _RecordMeta,
    signal_tracker: dict,
):
    event_key = enriched_event.get('id', '').encode('utf-8') if enriched_event.get('id') else None
    if product_store:
        product_store.persist_enriched_event(enriched_event, meta.topic(), meta.partition(), meta.offset())
        metrics.record_persistence_success(product_store.health())

    api_state.record_enriched_event(enriched_event)

    if enriched_event.get("is_high_risk"):
        if product_store:
            product_store.persist_high_risk_event(enriched_event, meta.partition(), meta.offset())
            metrics.record_persistence_success(product_store.health())
        signal_tracker["signals"] += 1
        metrics.record_signal("high_risk_replay")
        if REPLAY_PUBLISH_DERIVED_TOPICS and producer:
            safe_produce(producer, AUDIT_SIGNALS_HIGHRISK_TOPIC, event_key, orjson.dumps(enriched_event))

    if should_emit_high_risk_alert(enriched_event):
        operator_alert = build_operator_alert(enriched_event)
        if product_store:
            product_store.persist_alert(operator_alert)
            metrics.record_persistence_success(product_store.health())
        api_state.record_alert(operator_alert)
        signal_tracker["alerts"] += 1
        metrics.record_signal("operator_alert_replay")
        if REPLAY_PUBLISH_DERIVED_TOPICS and producer:
            safe_produce(producer, AUDIT_ALERTS_TOPIC, event_key, orjson.dumps(operator_alert))


def _handle_replay_denial_summary(alert, signal_tracker: dict):
    summary = alert.to_dict()
    api_state.record_denial_summary(summary)
    signal_tracker["signals"] += 1
    metrics.record_signal("denial_summary_replay")
    if product_store:
        product_store.persist_denial_summary(summary)
        metrics.record_persistence_success(product_store.health())
        if summary.get("threshold_exceeded"):
            product_store.persist_alert(summary)
            metrics.record_persistence_success(product_store.health())
            signal_tracker["alerts"] += 1


def replay_events(
    source_mode: str = "raw",
    hours: int | None = None,
    from_earliest: bool = False,
    publish_topics: bool = False,
) -> dict:
    """Replay Kafka events to rebuild persistence and product state."""
    if source_mode not in {"raw", "enriched"}:
        raise ValueError("source_mode must be 'raw' or 'enriched'")
    if hours is not None and hours <= 0:
        raise ValueError("hours must be positive")
    if hours is not None and hours > REPLAY_MAX_HOURS and not from_earliest:
        raise ValueError(f"hours exceeds REPLAY_MAX_HOURS={REPLAY_MAX_HOURS}")
    if not REPLAY_ENABLED:
        raise RuntimeError("replay is disabled")
    if not product_store:
        raise RuntimeError("persistence is required for replay rebuild")

    source_topic = AUDIT_RAW_TOPIC if source_mode == "raw" else AUDIT_ENRICHED_TOPIC
    window_mode = "earliest" if from_earliest else f"last_{hours or REPLAY_DEFAULT_HOURS}h"
    replay_state.start(source_mode, window_mode, hours, publish_topics)
    metrics.replay_started(source_mode, window_mode)
    product_store.set_runtime_meta("last_replay_requested_at", utc_now_iso())
    product_store.set_runtime_meta("replay_in_progress", "true")
    product_store.set_runtime_meta("replay_source_mode", source_mode)
    product_store.set_runtime_meta("replay_window_mode", window_mode)

    replay_consumer = Consumer({
        "bootstrap.servers": DEST_BOOTSTRAP,
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "PLAIN",
        "sasl.username": DEST_API_KEY,
        "sasl.password": DEST_API_SECRET,
        "group.id": f"auditlens-replay-{int(time.time())}",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    })
    replay_producer = Producer(producer_conf) if publish_topics else _NoOpProducer()
    anomaly_tracker = RateTracker(RateTrackerConfig(
        window_seconds=ANOMALY_WINDOW_SECONDS,
        auth_failure_threshold=ANOMALY_AUTH_FAILURE_THRESHOLD,
        activity_spike_threshold=ANOMALY_ACTIVITY_SPIKE_THRESHOLD,
        deletion_threshold=ANOMALY_DELETION_THRESHOLD,
        api_key_threshold=ANOMALY_API_KEY_THRESHOLD,
    ))
    aggregator = DenialAggregator(
        replay_producer,
        AggregatorConfig(
            window_seconds=max(1, AggregatorConfig.from_env().window_seconds),
            high_threshold=AggregatorConfig.from_env().high_threshold,
            signals_topic=AUDIT_SIGNALS_DENIALS_TOPIC,
            alerts_topic=AUDIT_ALERTS_TOPIC,
            enabled=True,
            dry_run=False,
        ),
        on_flush=lambda alert: _handle_replay_denial_summary(alert, replay_counts),
        webhook_sender=None,
    )

    replay_counts = {"processed": 0, "rebuilt": 0, "signals": 0, "alerts": 0}
    try:
        md = replay_consumer.list_topics(source_topic, timeout=10)
        if source_topic not in md.topics:
            raise RuntimeError(f"replay source topic missing: {source_topic}")
        partitions = sorted(md.topics[source_topic].partitions.keys())
        assignments = []
        if from_earliest:
            assignments = [TopicPartition(source_topic, partition, 0) for partition in partitions]
        else:
            replay_hours = hours or REPLAY_DEFAULT_HOURS
            ts_ms = int((time.time() - replay_hours * 3600) * 1000)
            requested = [TopicPartition(source_topic, partition, ts_ms) for partition in partitions]
            resolved = replay_consumer.offsets_for_times(requested, timeout=10)
            for tp in resolved:
                if tp.offset is None or tp.offset < 0:
                    tp.offset = 0
                assignments.append(tp)

        replay_consumer.assign(assignments)
        logger.info("Replay started: source=%s window=%s publish_topics=%s", source_mode, window_mode, publish_topics)

        empty_polls = 0
        while not _shutdown_requested:
            msg = replay_consumer.poll(timeout=1.0)
            if msg is None:
                empty_polls += 1
                if empty_polls >= 5:
                    break
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    empty_polls += 1
                    if empty_polls >= 5:
                        break
                    continue
                raise RuntimeError(str(msg.error()))
            empty_polls = 0
            payload = orjson.loads(msg.value())
            meta = _RecordMeta(msg.topic(), msg.partition(), msg.offset())
            if source_mode == "raw":
                base_event = payload.get("raw_event")
                if not base_event:
                    continue
                flat = flatten_audit(base_event)
                metrics.record_data_quality(flat, calculate_criticality(flat))
                enriched_event = build_enriched_event(flat)
            else:
                enriched_event = recompute_enriched_event(payload)

            _persist_replay_artifacts(replay_producer if publish_topics else None, enriched_event, meta, replay_counts)

            if aggregator.should_aggregate(enriched_event):
                aggregator.add_event(enriched_event)

            anomalies = anomaly_tracker.track_event(enriched_event)
            for anomaly in anomalies:
                if anomaly.anomaly_type.value in {"auth_failure_spike", "rapid_deletions", "api_key_abuse"}:
                    anomaly_alert = build_anomaly_alert(anomaly)
                    if product_store:
                        product_store.persist_alert(anomaly_alert)
                        metrics.record_persistence_success(product_store.health())
                    api_state.record_alert(anomaly_alert)
                    replay_counts["alerts"] += 1
                    metrics.record_signal(f"{anomaly.anomaly_type.value}_replay")
                    if publish_topics:
                        safe_produce(replay_producer, AUDIT_ALERTS_TOPIC, None, orjson.dumps(anomaly_alert))

            replay_counts["processed"] += 1
            replay_counts["rebuilt"] += 1
            replay_state.progress(processed_delta=1, rebuilt_delta=1)
            metrics.replay_progress(1)
            if replay_counts["processed"] % 1000 == 0:
                logger.info(
                    "Replay progress: processed=%d rebuilt=%d signals=%d alerts=%d",
                    replay_counts["processed"], replay_counts["rebuilt"],
                    replay_counts["signals"], replay_counts["alerts"],
                )

        aggregator.shutdown()
        if publish_topics and replay_producer:
            replay_producer.flush(timeout=30)
        replay_state.finish(True)
        metrics.replay_finished(True)
        product_store.set_runtime_meta("last_replay_completed_at", utc_now_iso())
        product_store.set_runtime_meta("last_replay_success_at", utc_now_iso())
        product_store.set_runtime_meta("replay_in_progress", "false")
        return {
            "status": "completed",
            "source_mode": source_mode,
            "window_mode": window_mode,
            "processed_records": replay_counts["processed"],
            "rebuilt_enriched": replay_counts["rebuilt"],
            "generated_signals": replay_counts["signals"],
            "generated_alerts": replay_counts["alerts"],
            "publish_topics": publish_topics,
        }
    except Exception as exc:
        replay_state.finish(False, str(exc))
        metrics.replay_finished(False, str(exc))
        product_store.set_runtime_meta("replay_in_progress", "false")
        product_store.set_runtime_meta("last_replay_error", str(exc))
        logger.exception("Replay failed: %s", exc)
        raise
    finally:
        replay_consumer.close()

# ──────────── main ────────────
_BACKFILL_BATCH_SIZE = 100
_BACKFILL_BATCH_SLEEP = 0.05  # seconds between batches — keeps row-lock windows short


def _backfill_batched(conn_factory, where_clause: str, set_clause: str, params: dict) -> int:
    """Batched UPDATE using CTE + FOR UPDATE SKIP LOCKED.

    Postgres does not support LIMIT inside UPDATE directly.  The CTE pattern
    selects a batch of row IDs (skipping any rows currently locked by the live
    DB writer) and then updates only those IDs.  Each batch is its own
    committed transaction so lock windows stay small.  Returns total rows
    updated.
    """
    from sqlalchemy import text as sa_text  # noqa: PLC0415
    batch_sql = sa_text(f"""
        WITH batch AS (
            SELECT id FROM audit_events
            WHERE {where_clause}
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        )
        UPDATE audit_events
        SET {set_clause}
        FROM batch
        WHERE audit_events.id = batch.id
    """)
    total = 0
    while True:
        with conn_factory() as conn:
            r = conn.execute(batch_sql, {**params, "limit": _BACKFILL_BATCH_SIZE})
            n = r.rowcount
        total += n
        if n < _BACKFILL_BATCH_SIZE:
            break
        time.sleep(_BACKFILL_BATCH_SLEEP)
    return total


def _run_startup_display_name_backfill() -> None:
    """One-time backfill of historical enrichment gaps — runs once in a daemon
    thread after startup so it never blocks the consume loop.

    Fixes three classes of stored display names that the enrichment chain
    writes incorrectly:
      1. Known actor IDs where display_name == actor (unenriched) — filled
         from the IAM cache once it is warm.
      2. JSON blobs stored as display names (Confluent internal events).
      3. Stored display names that still carry the "User:" prefix.

    Uses CTE + FOR UPDATE SKIP LOCKED batches so it never deadlocks the live
    DB writer — locked rows are skipped, not waited on.
    """
    if not ENABLE_DB_WRITER or db_writer is None:
        return
    if not PRODUCT_MODE:
        # SQLite-only demo mode — CTE/SUBSTRING is Postgres-specific; skip.
        return

    from src.product.actor_enrichment import _confluent_identity_enricher  # noqa: PLC0415

    try:
        # Wait up to 60 s for the IAM cache to warm before using it.
        wait_for_iam_cache_ready(timeout_seconds=60.0)
    except Exception:
        pass

    conn_factory = db_writer.engine.begin

    from sqlalchemy import text as sa_text  # noqa: PLC0415
    with conn_factory() as _check_conn:
        needs_work = _check_conn.execute(sa_text("""
            SELECT 1 FROM audit_events
            WHERE actor_confidence = 'low'
               OR actor_display_name LIKE '{%'
               OR actor_display_name LIKE 'User:u-%'
               OR actor_display_name LIKE 'User:sa-%'
            LIMIT 1
        """)).fetchone()
    if not needs_work:
        logger.info("Startup backfill: nothing to fix, skipping")
        return

    try:
        enricher = _confluent_identity_enricher()

        # Fix 1: backfill actors the IAM cache now knows about.
        if enricher is not None:
            identities = (
                list(enricher.get_all_service_accounts()) +
                list(enricher.get_all_users())
            )
            iam_total = 0
            for info in identities:
                actor_id = info.id
                display_name = info.display_name
                if not display_name or display_name == actor_id:
                    continue
                n = _backfill_batched(
                    conn_factory,
                    where_clause=(
                        "actor = :actor"
                        " AND (actor_display_name IS NULL"
                        "      OR actor_display_name = actor"
                        "      OR actor_display_name LIKE 'User:%'"
                        "      OR actor_display_name LIKE '{%')"
                    ),
                    set_clause="actor_display_name = :dn",
                    params={"dn": display_name, "actor": actor_id},
                )
                iam_total += n
            if iam_total:
                logger.info("Startup backfill: updated %d rows from IAM cache", iam_total)

        # Fix 2: normalize stored Confluent JSON blob display names.
        n2 = _backfill_batched(
            conn_factory,
            where_clause="actor_display_name LIKE '{%\"externalAccount\"%'",
            set_clause="actor_display_name = 'Confluent (internal)'",
            params={},
        )
        if n2:
            logger.info("Startup backfill: fixed %d Confluent JSON blob rows", n2)

        # Fix 3: strip stored 'User:' prefix (Postgres SUBSTRING syntax).
        n3 = _backfill_batched(
            conn_factory,
            where_clause=(
                "actor_display_name LIKE 'User:u-%'"
                " OR actor_display_name LIKE 'User:sa-%'"
            ),
            set_clause="actor_display_name = SUBSTRING(actor_display_name FROM 6)",
            params={},
        )
        if n3:
            logger.info("Startup backfill: stripped User: prefix from %d rows", n3)

        logger.info("Startup display name backfill complete")
    except Exception as exc:
        logger.warning("Startup display name backfill failed (non-fatal): %s", exc)


def main():
    global db_writer
    logger.info("=" * 70)
    logger.info("AuditLens Foundation Forwarder")
    logger.info(f"Version: {VERSION}")
    logger.info("Mode: Kafka-native foundation pipeline")
    logger.info("=" * 70)
    _mem_limit = os.getenv("MEMORY_LIMIT_MB", "unknown")
    logger.info("Starting PID=%d mem_limit=%sMB", os.getpid(), _mem_limit)
    logger.info(
        "No telemetry — audit data stays within this deployment. "
        "Outbound connections: Kafka bootstrap + (optional) Confluent IAM API + user-configured webhooks."
    )

    startup_config = validate_startup_config()
    if not startup_config["valid"]:
        logger.error("Startup validation failed: %s", mask_config_for_logging(startup_config))
        sys.exit(1)
    logger.info("Startup configuration validated successfully")

    initialize_product_store_or_exit()
    _health_server_module.product_store = product_store  # propagate to health server DI
    start_storage_monitor()
    if ENABLE_DB_WRITER:
        try:
            initialize_db_writer_if_enabled()
        except Exception as exc:
            db_writer = None
            masked_exc = mask_sensitive_text(str(exc))
            metrics.record_db_write_error(masked_exc, 0)
            logger.warning("DB writer enabled but initial connection failed; will retry in processing loop: %s", masked_exc)
        # Run once in background — never blocks startup, never raises.
        _backfill_thread = threading.Thread(
            target=_run_startup_display_name_backfill,
            name="auditlens-startup-dn-backfill",
            daemon=True,
        )
        _backfill_thread.start()
    else:
        metrics.set_db_writer_state("disabled")

    pattern_detector = None
    if ENABLE_DB_WRITER:
        try:
            from src.product.pattern_detector import PatternDetector
            pattern_detector = PatternDetector(DATABASE_URL)
            logger.info("PatternDetector initialized for recurring pattern detection")
        except Exception as exc:
            logger.warning(
                "PatternDetector init failed; pattern detection disabled: %s",
                mask_sensitive_text(str(exc)),
            )

    ip_baseline_tracker = None
    if ENABLE_DB_WRITER:
        try:
            from src.product.ip_baseline_tracker import IpBaselineTracker, _is_private_ip
            ip_baseline_tracker = IpBaselineTracker(DATABASE_URL)
            logger.info("IpBaselineTracker initialized for actor/IP baseline tracking")
        except Exception as exc:
            logger.warning(
                "IpBaselineTracker init failed; IP baseline tracking disabled: %s",
                mask_sensitive_text(str(exc)),
            )

    # 24h dedup cache for new-IP alerts: maps (actor, ip) → alert_sent_at epoch
    _IP_ALERT_DEDUP_WINDOW = 86400.0  # 24 hours
    _ip_alert_dedup: TTLCache = TTLCache(maxsize=50_000, ttl=_IP_ALERT_DEDUP_WINDOW)

    # Optional Schema Registry check
    if SCHEMA_REGISTRY_URL:
        logger.info("Schema Registry configured: %s", SCHEMA_REGISTRY_URL)
    else:
        logger.info("Schema Registry not configured (optional)")

    # Initialize anomaly detection.
    # Use from_env() so ANOMALY_WHITELIST_PRINCIPALS, ANOMALY_SPIKE_THRESHOLD,
    # and ANOMALY_DEDUP_WINDOW_SECONDS take effect at runtime. The legacy
    # module-level ANOMALY_ACTIVITY_SPIKE_THRESHOLD constant is honored by
    # from_env() as a fallback when ANOMALY_SPIKE_THRESHOLD is unset.
    anomaly_config = RateTrackerConfig.from_env()
    anomaly_tracker = RateTracker(anomaly_config)
    logger.info(
        "Anomaly detection initialized: window=%ds, auth_failure_threshold=%d, "
        "activity_spike_threshold=%d, dedup_window=%ds, whitelist_principals=%s",
        anomaly_config.window_seconds,
        anomaly_config.auth_failure_threshold,
        anomaly_config.activity_spike_threshold,
        anomaly_config.dedup_window_seconds,
        list(anomaly_config.whitelist_principals) or "<none>",
    )

    # Initialize webhook alerting
    webhook_sender = get_webhook_sender()
    if webhook_sender.enabled:
        logger.info("Webhook alerting enabled: %s", webhook_sender.config.webhook_type.value)
        if ENABLE_BUILTIN_ALERTS:
            logger.info("Built-in alert rules enabled: %d rules configured", len(BUILTIN_ALERT_METHODS))
            for method in list(BUILTIN_ALERT_METHODS.keys())[:5]:  # Show first 5
                logger.info("  - %s", method)
            if len(BUILTIN_ALERT_METHODS) > 5:
                logger.info("  - ... and %d more", len(BUILTIN_ALERT_METHODS) - 5)
        else:
            logger.info("Built-in alerts disabled (set SLACK_WEBHOOK to enable)")
    else:
        logger.info("Webhook alerting disabled (no configuration)")

    # Phase 5: actor_mappings.yml manual overrides — primed at startup so
    # the count appears in the boot log. The file is gracefully optional;
    # missing file means no overrides (logged below).
    try:
        mapping_file = get_actor_mapping_file()
        mapping_count = mapping_file.count()
        if mapping_count:
            logger.info(
                "Actor mappings: %d entries loaded from actor_mappings.yml",
                mapping_count,
            )
        else:
            logger.info(
                "Actor mappings: no actor_mappings.yml found — manual overrides disabled"
            )
    except Exception as exc:
        logger.warning("Actor mappings init failed (%s) — continuing", exc)

    # Bulk prefetch all IAM identities into the enrich_actor TTL cache so the
    # dashboard shows real display names immediately without waiting for the
    # 55-minute background refresh or individual per-event lookups.
    try:
        from src.product.actor_enrichment import _bulk_prefetch_identities  # noqa: PLC0415
        _prefetch_thread = threading.Thread(
            target=_bulk_prefetch_identities,
            args=(None,),  # None → uses EnrichmentConfig.from_env() internally
            daemon=True,
            name="iam-bulk-prefetch",
        )
        _prefetch_thread.start()
        logger.info("IAM bulk prefetch started in background")
    except Exception as _prefetch_exc:
        logger.warning("IAM bulk prefetch start failed: %s", _prefetch_exc)

    # Initialize the configurable notification layer (slack/teams/webhook).
    # Failure here must not crash the forwarder — the legacy SLACK_WEBHOOK
    # path stays available via ENABLE_LEGACY_SLACK_WEBHOOK=true.
    notifier: AuditLensNotifier | None = None
    try:
        notifier = AuditLensNotifier(
            config_path=os.getenv("NOTIFICATIONS_CONFIG", "notifications.yml")
        )
        if notifier.has_destinations():
            enabled_count = sum(1 for d in notifier._destinations if d.enabled)
            logger.info(
                "Notification layer: %d destinations loaded from notifications.yml",
                enabled_count,
            )
        else:
            logger.info("Notification layer: disabled (no notifications.yml found)")
    except Exception as exc:
        logger.warning(
            "Notification layer init failed (%s) — continuing without it", exc
        )
        notifier = None

    # Create clients. Hook the librdkafka stats callback so per-partition
    # consumer_lag flows in via stats.json, not synchronous watermark polls.
    consumer_conf_with_stats = dict(consumer_conf)
    consumer_conf_with_stats["stats_cb"] = make_rdkafka_stats_callback(metrics)
    consumer = Consumer(consumer_conf_with_stats)
    producer = Producer(producer_conf)

    # Start metrics server
    metrics_server = start_metrics_server(
        METRICS_PORT,
        metrics_obj=metrics,
        product_store_obj=product_store,
        api_state_obj=api_state,
        replay_state_obj=replay_state,
        authenticator_obj=authenticator,
        delivery_errors_dict=delivery_errors,
        dlq_stats_dict=dlq_stats,
        validate_startup_config_fn=validate_startup_config,
        replay_events_fn=replay_events,
    )

    # Connectivity checks use backoff so Docker restart policy does not create
    # a DNS/Kafka retry storm on laptops or customer demo machines.
    startup_backoff = RuntimeBackoff()
    startup_log_state = {}
    while not _shutdown_requested:
        try:
            metrics.set_consumer_state("retrying")
            md = consumer.list_topics(timeout=10.0)
            if AUDIT_TOPIC not in md.topics:
                raise RuntimeError(f"source topic missing: {AUDIT_TOPIC}")
            startup_backoff.reset()
            metrics.set_consumer_state("connected")
            logger.info("Connected to source; topic %s exists", AUDIT_TOPIC)
            break
        except Exception as e:
            delay = startup_backoff.next_delay()
            metrics.record_consumer_retry(str(e), delay)
            if _should_log_repeated_error(startup_log_state, str(e)):
                logger.warning(
                    "Source connectivity failed; retrying in %.1fs: %s",
                    delay,
                    e,
                )
            _sleep_with_shutdown(delay)
    if _shutdown_requested:
        return

    foundation_topics = {
        AUDIT_RAW_TOPIC,
        AUDIT_NORMALIZED_TOPIC,
        AUDIT_ENRICHED_TOPIC,
        AUDIT_SIGNALS_DENIALS_TOPIC,
        AUDIT_SIGNALS_HIGHRISK_TOPIC,
        AUDIT_ALERTS_TOPIC,
        DLQ_TOPIC,
    }

    # Initialize router if multi-topic routing is enabled
    topic_router = None
    if ENABLE_MULTI_TOPIC_ROUTING:
        router_config = RouterConfig.from_env()
        topic_router = TopicRouter(producer, router_config)
        logger.warning("Legacy criticality routing enabled: %s", topic_router.get_enabled_topic_names())

    # Initialize denial aggregator (aggregates auth denials into summary alerts)
    denial_aggregator = None
    if ENABLE_DENIAL_AGGREGATION:
        aggregator_config = AggregatorConfig.from_env()
        # Pass webhook_sender to send Slack alerts for HIGH aggregated alerts
        denial_aggregator = DenialAggregator(
            producer,
            aggregator_config,
            on_flush=lambda alert: _handle_denial_summary_flush(alert),
            webhook_sender=webhook_sender if webhook_sender.enabled else None
        )
        logger.info("Denial aggregation enabled: window=%ds, threshold=%d, signals_topic=%s, webhook=%s",
                    aggregator_config.window_seconds, aggregator_config.high_threshold,
                    aggregator_config.signals_topic, "enabled" if webhook_sender.enabled else "disabled")

    # Destination connectivity check
    startup_backoff.reset()
    startup_log_state = {}
    while not _shutdown_requested:
        try:
            metrics.set_consumer_state("retrying")
            md2 = producer.list_topics(timeout=10.0)

            if ENABLE_MULTI_TOPIC_ROUTING and topic_router:
                # Verify all destination topics exist
                if ROUTER_DRY_RUN:
                    logger.warning("Router in dry-run mode - skipping destination topic verification")
                else:
                    for dest_topic in topic_router.get_enabled_topic_names():
                        if dest_topic not in md2.topics:
                            raise RuntimeError(f"destination topic missing: {dest_topic}")
                        logger.info("Verified destination topic: %s", dest_topic)
            for dest_topic in sorted(foundation_topics):
                if dest_topic not in md2.topics:
                    raise RuntimeError(f"destination topic missing: {dest_topic}")
                logger.info("Verified foundation topic: %s", dest_topic)
            startup_backoff.reset()
            metrics.set_consumer_state("connected")
            break
        except Exception as e:
            delay = startup_backoff.next_delay()
            metrics.record_consumer_retry(str(e), delay)
            if _should_log_repeated_error(startup_log_state, str(e)):
                logger.warning(
                    "Destination connectivity failed; retrying in %.1fs: %s",
                    delay,
                    e,
                )
            _sleep_with_shutdown(delay)
    if _shutdown_requested:
        return

    # Schema Registry — optional Avro serialization for audit.enriched.v1.
    # Falls back to orjson JSON production transparently if SR is not configured
    # or if registration fails (e.g. network issues at startup).
    from src.product.schema_registry import (
        get_sr_client, register_schema, get_avro_serializer, project_enriched,
    )
    _sr_client = get_sr_client()
    _enriched_serializer = None
    _noise_serializer = None

    if _sr_client:
        try:
            _SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "src", "schema")
            register_schema(
                _sr_client,
                f"{AUDIT_ENRICHED_TOPIC}-value",
                os.path.join(_SCHEMA_DIR, "audit_enriched_v1.avsc"),
            )
            register_schema(
                _sr_client,
                "audit.noise.v1-value",
                os.path.join(_SCHEMA_DIR, "audit_noise_v1.avsc"),
            )
            _enriched_serializer = get_avro_serializer(
                _sr_client,
                os.path.join(_SCHEMA_DIR, "audit_enriched_v1.avsc"),
            )
            _noise_serializer = get_avro_serializer(
                _sr_client,
                os.path.join(_SCHEMA_DIR, "audit_noise_v1.avsc"),
            )
            logger.info(
                "Schema Registry configured — producing with Avro serialization"
            )
        except Exception as _sr_exc:
            logger.warning(
                "Schema Registry init failed (%s) — falling back to JSON production",
                _sr_exc,
            )
            record_schema_registry_failure()
            _sr_client = None
    else:
        logger.info("Schema Registry not configured - using JSON serialization without schema validation")

    # Subscribe to source topic - offsets are managed by Kafka consumer groups
    # On first join: starts from auto.offset.reset (latest)
    # On rejoins after crash: resumes from last committed offset
    consumer.subscribe([AUDIT_TOPIC], on_assign=on_assign, on_revoke=on_revoke)
    logger.info("Subscribed to %s with consumer group %s", AUDIT_TOPIC, GROUP_ID)

    # Per-partition lag is now sourced from the librdkafka stats_cb (see
    # make_rdkafka_stats_callback). No synchronous watermark polling.

    # Main processing loop
    BATCH_SIZE     = int(os.getenv("KAFKA_CONSUME_BATCH_SIZE", "100"))
    processed      = 0
    start_ts       = time.time()
    last_heartbeat = start_ts
    last_lag_ts    = start_ts
    last_iam_prefetch_ts = 0.0  # triggers immediately at first tick
    _IAM_PREFETCH_INTERVAL = 6 * 3600
    loop_backoff = RuntimeBackoff()
    loop_log_state = {}
    db_write_backoff = RuntimeBackoff(maximum=DB_WRITE_BACKOFF_MAX_SECONDS)
    db_write_log_state = {}
    db_last_flush_ts = time.monotonic()

    logger.info("Entering processing loop")

    # Thread-pool architecture with priority lanes:
    #   consumer thread → record_queue → processor thread → priority routing →
    #     critical/normal/bulk writer threads → audit_events INSERT
    #     catalog writer thread ← deferred catalog rows from each writer
    # Decoupling poll from process lets librdkafka keep heartbeating during
    # slow PG writes — broker no longer reaps us. Splitting writes by
    # criticality means destructive events land in PG within seconds even
    # when the bulk lane is digesting tens of thousands of authz checks.
    # Default 10000: previous default of 20 batches saturated within
    # seconds at any reasonable ingest rate, putting the consumer into
    # a continuous pause/resume backpressure loop. With BATCH_SIZE=100
    # this caps buffered events at ~1M (still bounded; per-lane queues
    # below provide the real shape).
    RECORD_QUEUE_SIZE = max(1, int(os.getenv("RECORD_QUEUE_SIZE", "10000")))
    record_queue: queue.Queue = queue.Queue(maxsize=RECORD_QUEUE_SIZE)
    metrics.record_queue_capacity = RECORD_QUEUE_SIZE
    consumer_log_state: dict = {}
    consumer_backoff = RuntimeBackoff()

    # Priority routing — only used when DB writer is enabled. Sized so the
    # critical lane stays small (drains fast), normal lane is moderate, and
    # bulk lane absorbs noise without blocking the producer.
    PRIORITY_QUEUES_ENABLED = ENABLE_DB_WRITER
    if PRIORITY_QUEUES_ENABLED:
        # ~1 KB per event in steady state: critical 500=0.5MB,
        # normal 5000=5MB, bulk 50000=50MB, catalog 10000=10MB.
        # WRITER_*_QUEUE_SIZE wins if set (spec-aligned name); we keep
        # PRIORITY_QUEUE_*_MAX as a legacy alias so existing deploys
        # don't need .env edits.
        def _queue_max(env_primary: str, env_legacy: str, default: int, floor: int) -> int:
            value = os.getenv(env_primary) or os.getenv(env_legacy) or str(default)
            return max(floor, int(value))
        critical_queue: queue.Queue = queue.Queue(
            maxsize=_queue_max("WRITER_CRITICAL_QUEUE_SIZE", "PRIORITY_QUEUE_CRITICAL_MAX", 500, 100)
        )
        normal_queue: queue.Queue = queue.Queue(
            maxsize=_queue_max("WRITER_NORMAL_QUEUE_SIZE", "PRIORITY_QUEUE_NORMAL_MAX", 5000, 500)
        )
        bulk_queue: queue.Queue = queue.Queue(
            maxsize=_queue_max("WRITER_BULK_QUEUE_SIZE", "PRIORITY_QUEUE_BULK_MAX", 50000, 5000)
        )
        catalog_queue: queue.Queue = queue.Queue(
            maxsize=_queue_max("WRITER_CATALOG_QUEUE_SIZE", "PRIORITY_QUEUE_CATALOG_MAX", 10000, 1000)
        )
    else:
        critical_queue = normal_queue = bulk_queue = catalog_queue = None

    def _route_to_queue(enriched_event: dict) -> None:
        """Fast routing — pick the priority lane based on methodName.

        Critical+High methods → critical_queue (small batches, < 0.1s wait).
        Read-only / authentication / authz checks → bulk_queue (huge batches).
        Everything else → normal_queue (medium batches).

        Sets ``_queue_lane`` on the event so the writer thread can pick
        the right INSERT path (audit_events vs audit_events_noise).
        """
        if not PRIORITY_QUEUES_ENABLED:
            return
        method = enriched_event.get("methodName") or enriched_event.get("method") or ""
        if enriched_event.get("validateOnly"):
            target, target_name = bulk_queue, "bulk"
        elif method in CRITICAL_METHODS or method in HIGH_METHODS:
            target, target_name = critical_queue, "critical"
        elif (
            method in READ_ONLY_METHODS
            or method in AUTHENTICATION_METHODS
            or method in AUTHORIZATION_CHECK_METHODS
        ):
            target, target_name = bulk_queue, "bulk"
        else:
            target, target_name = normal_queue, "normal"
        enriched_event["_queue_lane"] = target_name
        try:
            target.put_nowait(enriched_event)
        except queue.Full:
            # Block briefly to apply back-pressure to the processor thread.
            # If this saturates, the upstream record_queue fills and the
            # consumer thread pauses Kafka — the existing back-pressure path.
            try:
                target.put(enriched_event, timeout=5.0)
            except queue.Full:
                metrics.record_db_write_error(f"{target_name}_queue full", 1)
                logger.warning(
                    "priority queue %s full — dropping event method=%s",
                    target_name, method,
                )

    def _refresh_queue_depths() -> None:
        if not PRIORITY_QUEUES_ENABLED:
            return
        metrics.critical_queue_depth = critical_queue.qsize()
        metrics.normal_queue_depth = normal_queue.qsize()
        metrics.bulk_queue_depth = bulk_queue.qsize()
        metrics.catalog_queue_depth = catalog_queue.qsize()

    def _writer_loop(q: queue.Queue, batch_size: int, max_wait: float, lane: str, depth_attr: str) -> None:
        """Generic writer: drain ``q`` into Postgres in batches.

        Wait at most ``max_wait`` seconds for ``batch_size`` records. Critical
        writer wakes early to prioritise latency; bulk writer waits longer to
        prioritise throughput. Catalog upsert is deferred to the catalog
        writer so this hot path is dominated by audit_events INSERT only.
        """
        log_state: dict = {}
        backoff = RuntimeBackoff(maximum=DB_WRITE_BACKOFF_MAX_SECONDS)
        while True:
            batch: list[dict] = []
            deadline = time.monotonic() + max_wait
            while len(batch) < batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    record = q.get(timeout=min(remaining, 0.1))
                except queue.Empty:
                    if _shutdown_requested and q.empty():
                        break
                    continue
                batch.append(record)
            setattr(metrics, depth_attr, q.qsize())
            if batch:
                if lane == "bulk":
                    # Noise lane → audit_events_noise: minimal columns, no
                    # fingerprint, no catalog upsert. ~50x cheaper per row.
                    if flush_db_writer_noise_batch(batch, backoff, log_state, label=lane):
                        # Ack short-circuited noise offsets so the processor
                        # thread can include them in the next commit. Items
                        # without _short_circuit (those routed here from the
                        # processor's own _route_to_queue path) are skipped
                        # silently — their offsets ride on batch_max_offsets.
                        _record_noise_persisted(batch)
                else:
                    flush_db_writer_batch(
                        batch, backoff, log_state,
                        defer_catalog=True,
                        catalog_target=catalog_queue,
                        label=lane,
                    )
                setattr(metrics, depth_attr, q.qsize())
            if _shutdown_requested and q.empty() and not batch:
                return

    def _catalog_writer_loop() -> None:
        """Drain catalog_queue → resource_catalog upsert.

        Catalog rows describe the same resource on most events, so even a
        500-row batch typically collapses to a small number of distinct
        resource_ids. Running this off-thread cuts ~300ms from every
        audit_events INSERT batch on the critical / normal lanes.
        """
        log_state: dict = {}
        while True:
            try:
                first = catalog_queue.get(timeout=10.0)
            except queue.Empty:
                if _shutdown_requested and catalog_queue.empty():
                    return
                continue
            rows: list[dict] = [first]
            while len(rows) < 500:
                try:
                    rows.append(catalog_queue.get_nowait())
                except queue.Empty:
                    break
            metrics.catalog_queue_depth = catalog_queue.qsize()
            try:
                writer = initialize_db_writer_if_enabled()
                if writer is not None:
                    writer.upsert_catalog(rows)
            except Exception as exc:
                masked = mask_sensitive_text(str(exc))
                metrics.record_db_write_error(f"catalog upsert failed: {masked}", 0)
                if _should_log_repeated_error(log_state, masked):
                    logger.warning("catalog_upsert failed: %s", masked)

    short_circuit_active = ENABLE_NOISE_SHORT_CIRCUIT and PRIORITY_QUEUES_ENABLED

    def _split_noise(batch_local):
        """Split a Kafka consume() result into (non_noise_msgs, noise_offsets).

        Noise events are routed directly to bulk_queue (carrying their
        topic/partition/offset metadata) and never enter record_queue.
        Returns the messages the processor must still handle plus a per-
        (topic, partition) max-offset map so the processor can include
        those offsets in the commit set after the bulk writer persists them.

        When short_circuit_active is False, returns the original batch
        unchanged with an empty noise_offsets map (no behavior change).
        """
        if not short_circuit_active:
            return list(batch_local), {}
        non_noise: list = []
        noise_offsets: dict[tuple[str, int], int] = {}
        short_circuited = 0
        for msg in batch_local:
            if msg is None or msg.error():
                non_noise.append(msg)
                continue
            payload = _try_short_circuit_noise(msg)
            if payload is None:
                non_noise.append(msg)
                continue
            # Tag the payload with the offset metadata the bulk writer
            # uses to ack persistence. These underscore-prefixed keys are
            # ignored by minimal_normalize / write_noise_batch.
            payload["_short_circuit"] = True
            payload["_topic"] = msg.topic()
            payload["_partition"] = msg.partition()
            payload["_offset"] = msg.offset()
            try:
                bulk_queue.put(payload, timeout=5.0)
            except queue.Full:
                # Bulk lane is saturated; fall back to the full path so
                # the event still reaches durable storage. The
                # processor will route it to bulk_queue itself after
                # flatten_audit (slower, but correct).
                non_noise.append(msg)
                continue
            short_circuited += 1
            key = (msg.topic(), msg.partition())
            current = noise_offsets.get(key, -1)
            if msg.offset() > current:
                noise_offsets[key] = msg.offset()
        if short_circuited:
            metrics.record_noise_short_circuited(short_circuited)
        return non_noise, noise_offsets

    def _consume_thread() -> None:
        """Thread A: poll Kafka, short-circuit bulk noise, queue the rest."""
        paused = False
        while not _shutdown_requested:
            try:
                batch_local = consumer.consume(num_messages=BATCH_SIZE, timeout=CONSUMER_POLL_TIMEOUT_SECONDS)
            except Exception as exc:
                delay = consumer_backoff.next_delay()
                masked = mask_sensitive_text(str(exc))
                metrics.record_consumer_retry(masked, delay)
                if _should_log_repeated_error(consumer_log_state, masked):
                    logger.warning("Kafka consume failed; backing off for %.1fs: %s", delay, masked)
                _sleep_with_shutdown(delay)
                continue
            consumer_backoff.reset()
            if not batch_local:
                metrics.record_poll(0)
                # Drive heartbeats even on idle polls — librdkafka piggy-backs them.
                consumer.poll(0)
                if CONSUMER_EMPTY_POLL_SLEEP_SECONDS > 0:
                    _sleep_with_shutdown(CONSUMER_EMPTY_POLL_SLEEP_SECONDS)
                continue
            non_noise_msgs, noise_offsets = _split_noise(batch_local)
            envelope = (non_noise_msgs, noise_offsets)
            try:
                record_queue.put(envelope, timeout=5.0)
                metrics.record_queue_depth = record_queue.qsize()
            except queue.Full:
                if not paused:
                    try:
                        consumer.pause(consumer.assignment())
                        paused = True
                        logger.warning(
                            "record_queue full (%d/%d) — pausing consumer for backpressure",
                            record_queue.qsize(), RECORD_QUEUE_SIZE,
                        )
                    except Exception as exc:
                        logger.warning("consumer.pause failed: %s", exc)
                while record_queue.qsize() > RECORD_QUEUE_SIZE // 2 and not _shutdown_requested:
                    consumer.poll(0)
                    _sleep_with_shutdown(0.1)
                if paused:
                    try:
                        consumer.resume(consumer.assignment())
                    except Exception as exc:
                        logger.warning("consumer.resume failed: %s", exc)
                    paused = False
                    logger.info(
                        "record_queue drained (%d/%d) — resuming consumer",
                        record_queue.qsize(), RECORD_QUEUE_SIZE,
                    )
                try:
                    record_queue.put(envelope, timeout=30.0)
                    metrics.record_queue_depth = record_queue.qsize()
                except queue.Full:
                    logger.error(
                        "record_queue still full after backpressure — dropping batch of %d",
                        len(non_noise_msgs),
                    )
                    metrics.record_error()
        # Sentinel so the processor exits its loop after the last real batch.
        try:
            record_queue.put(None, timeout=10.0)
        except queue.Full:
            logger.warning("Failed to enqueue shutdown sentinel; processor may rely on shutdown flag")

    def _process_thread() -> None:
        """Thread B: pop batches and run the full per-event pipeline."""
        nonlocal processed, last_heartbeat, last_lag_ts, db_last_flush_ts
        while True:
            try:
                envelope = record_queue.get(timeout=1.0)
            except queue.Empty:
                if _shutdown_requested and record_queue.empty():
                    break
                # Still run the maintenance ticks even when idle.
                now = time.time()
                _run_periodic_maintenance(now)
                continue
            metrics.record_queue_depth = record_queue.qsize()
            if envelope is None:
                # Shutdown sentinel from consumer thread.
                break
            # Consumer thread now sends an envelope: (non_noise_msgs,
            # noise_offsets). The noise_offsets dict carries the offsets
            # of events the consumer short-circuited directly to bulk_queue
            # — we must wait for the bulk writer to persist them before we
            # commit those offsets. A bare list (legacy / defensive)
            # unpacks to an empty noise_offsets map.
            if isinstance(envelope, tuple) and len(envelope) == 2:
                batch, noise_offsets = envelope
            else:
                batch, noise_offsets = envelope, {}
            loop_backoff.reset()
            batch_had_processing_failure = False
            batch_delivery_errors_before = delivery_errors["count"]
            # Track high-water-mark offset per (topic, partition) so we can
            # explicitly commit once at end of batch. With the consumer thread
            # split off, librdkafka's auto-offset-store does not propagate
            # reliably to the commit thread; explicit offsets are mandatory.
            batch_max_offsets: dict[tuple[str, int], int] = {}
            # Record in metrics
            batch_size = len([m for m in batch if m and not m.error()])
            metrics.record_poll(batch_size)
            if batch_size > 0:
                metrics.record_processed(batch_size)

            # Cache health result for this batch — avoids per-event SQLite COUNT(*)
            _ps_health = product_store.health() if product_store else None

            for msg in batch:
                if msg is None or msg.error():
                    if msg and msg.error().code() != KafkaError._PARTITION_EOF:
                        delay = loop_backoff.next_delay()
                        masked_err = mask_sensitive_text(str(msg.error()))
                        metrics.record_consumer_retry(masked_err, delay)
                        if _should_log_repeated_error(loop_log_state, masked_err):
                            logger.error("Consume error; backing off for %.1fs: %s", delay, masked_err)
                        _sleep_with_shutdown(delay)
                        batch_had_processing_failure = True
                    continue
                try:
                    evt = orjson.loads(msg.value())
                    safe_produce(producer, AUDIT_RAW_TOPIC, None, orjson.dumps(build_raw_event(evt, msg)))

                    flat = flatten_audit(evt)
                    metrics.record_data_quality(flat, calculate_criticality(flat))
                    normalized_event = build_normalized_event(flat)
                    enriched_event = build_enriched_event(flat)
                    event_key = enriched_event.get('id', '').encode('utf-8') if enriched_event.get('id') else None

                    if product_store:
                        persist_safely(
                            "enriched_event",
                            product_store.persist_enriched_event,
                            enriched_event, msg.topic(), msg.partition(), msg.offset(),
                        )
                        if _ps_health:
                            metrics.record_persistence_success(_ps_health)
                    if ENABLE_DB_WRITER:
                        # Route into the priority lane based on methodName
                        # (critical / normal / bulk). Writer threads drain
                        # each queue into Postgres asynchronously; we no
                        # longer block this batch on the DB write. Events
                        # remain durable in the audit Kafka topics, so a
                        # crash between offset-commit and async-write is
                        # recoverable via replay.
                        _route_to_queue(enriched_event)

                    if pattern_detector is not None:
                        _method = str(enriched_event.get("methodName", "")).lower()
                        if _method not in BULK_NOISE_METHODS:
                            pattern_detector.record(enriched_event)

                    if ip_baseline_tracker is not None:
                        _ip_actor = str(
                            enriched_event.get("actor")
                            or enriched_event.get("principal")
                            or ""
                        ).strip()
                        _ip_src = str(enriched_event.get("clientIp") or enriched_event.get("source_ip") or "").strip()
                        if _ip_actor and _ip_src:
                            _ip_is_new = ip_baseline_tracker.record(_ip_actor, _ip_src)
                            if _ip_is_new and notifier is not None and notifier.has_destinations():
                                try:
                                    _mapping = get_actor_mapping_file()
                                    _trusted = _mapping.get_trusted_ips(_ip_actor)
                                    _alert_on_new = _mapping.alert_on_new_ip(_ip_actor)
                                    _whitelisted = (
                                        _ip_actor in anomaly_config.whitelist_principals
                                    )
                                    _is_private = _is_private_ip(_ip_src)
                                    _dedup_key = (_ip_actor, _ip_src)
                                    _now_ts = time.time()
                                    _last_alerted = _ip_alert_dedup.get(_dedup_key, 0.0)
                                    _dedup_ok = (_now_ts - _last_alerted) >= _IP_ALERT_DEDUP_WINDOW
                                    _in_trusted = any(
                                        ipaddress.ip_address(_ip_src)
                                        in ipaddress.ip_network(cidr, strict=False)
                                        for cidr in _trusted
                                        if cidr
                                    ) if _trusted else False
                                    _should_alert = (
                                        not _whitelisted
                                        and not _in_trusted
                                        and _dedup_ok
                                        and (_alert_on_new or _trusted or not _is_private)
                                    )
                                    if _should_alert:
                                        _ip_alert_dedup[_dedup_key] = _now_ts
                                        _ip_alert = {
                                            **enriched_event,
                                            "signal_type": "action_required",
                                            "alert_type": "new_ip_detected",
                                            "severity": "HIGH",
                                            "recommended_action": (
                                                f"Verify whether {_ip_actor} legitimately accessed from {_ip_src}. "
                                                "If unexpected, rotate credentials and investigate recent activity."
                                            ),
                                        }
                                        notifier.notify(_ip_alert)
                                        logger.warning(
                                            "New IP alert: actor=%s ip=%s (first time seen)",
                                            _ip_actor,
                                            _ip_src,
                                        )
                                except Exception as _ip_exc:
                                    logger.warning("IP alert dispatch failed: %s", _ip_exc)

                    safe_produce(producer, AUDIT_NORMALIZED_TOPIC, event_key, orjson.dumps(normalized_event))
                    if _enriched_serializer:
                        from confluent_kafka.serialization import SerializationContext, MessageField  # noqa: PLC0415
                        _enriched_value = _enriched_serializer(
                            project_enriched(enriched_event),
                            SerializationContext(AUDIT_ENRICHED_TOPIC, MessageField.VALUE),
                        )
                    else:
                        _enriched_value = orjson.dumps(enriched_event)
                    safe_produce(producer, AUDIT_ENRICHED_TOPIC, event_key, _enriched_value)
                    api_state.record_enriched_event(enriched_event)
                    metrics.record_processed(0, enriched_event.get("time"))
                    record_event_metrics(enriched_event)
                    record_routing_metrics(AUDIT_ENRICHED_TOPIC, False)

                    # Track event for anomaly detection
                    anomalies = anomaly_tracker.track_event(enriched_event)
                    for anomaly in anomalies:
                        record_anomaly_metrics(anomaly.anomaly_type.value)
                        logger.warning(
                            "ANOMALY DETECTED: %s - %s (principal=%s, source_ip=%s, rate=%.1f, threshold=%d)",
                            anomaly.severity,
                            anomaly.anomaly_type.value,
                            anomaly.principal,
                            anomaly.source_ip,
                            anomaly.rate,
                            anomaly.threshold,
                        )
                        if anomaly.anomaly_type.value in {"auth_failure_spike", "rapid_deletions", "api_key_abuse"}:
                            anomaly_alert = build_anomaly_alert(anomaly)
                            safe_produce(
                                producer,
                                AUDIT_ALERTS_TOPIC,
                                None,
                                orjson.dumps(anomaly_alert),
                            )
                            api_state.record_alert(anomaly_alert)
                            metrics.record_signal(anomaly.anomaly_type.value)
                            if product_store:
                                persist_safely("anomaly_alert", product_store.persist_alert, anomaly_alert)
                                if _ps_health:
                                    metrics.record_persistence_success(_ps_health)

                    # Configurable notification layer (slack/teams/webhook)
                    # — runs before the legacy webhook so dedup keys are
                    # owned by the notifier. Skip noise events and skip
                    # entirely if no destinations are configured.
                    if notifier is not None and notifier.has_destinations():
                        try:
                            notify_payload = {
                                **enriched_event,
                                **decision_snapshot(enriched_event),
                            }
                            if notify_payload.get("signal_type") != "noise":
                                notifier.notify(notify_payload)
                        except Exception as exc:
                            logger.warning("notifier dispatch failed: %s", exc)

                    # Legacy SLACK_WEBHOOK path. Auto-disabled once the
                    # notifier owns destinations; flip ENABLE_LEGACY_SLACK_WEBHOOK
                    # to true to force-fire, false to fully suppress.
                    fire_legacy = False
                    if LEGACY_WEBHOOK_ENABLED == "true":
                        fire_legacy = True
                    elif LEGACY_WEBHOOK_ENABLED == "auto":
                        fire_legacy = not (
                            notifier is not None and notifier.has_destinations()
                        )

                    if fire_legacy and webhook_sender.enabled and ENABLE_BUILTIN_ALERTS:
                        method_name = enriched_event.get('methodName', '')

                        # Check if this method triggers a built-in alert
                        if method_name in BUILTIN_ALERT_METHODS:
                            alert_config = BUILTIN_ALERT_METHODS[method_name]
                            logger.info("Built-in alert triggered: %s - %s",
                                       method_name, alert_config['message'])
                            webhook_sender.send_critical_event_alert(enriched_event)
                        # Also send alert for any CRITICAL event not in built-in rules
                        elif enriched_event.get('criticality') == 'CRITICAL':
                            webhook_sender.send_critical_event_alert(enriched_event)

                    if denial_aggregator and denial_aggregator.should_aggregate(enriched_event):
                        denial_aggregator.add_event(enriched_event)

                    if enriched_event.get("is_high_risk"):
                        if product_store:
                            persist_safely(
                                "high_risk_event",
                                product_store.persist_high_risk_event,
                                enriched_event, msg.partition(), msg.offset(),
                            )
                            if _ps_health:
                                metrics.record_persistence_success(_ps_health)
                        safe_produce(
                            producer,
                            AUDIT_SIGNALS_HIGHRISK_TOPIC,
                            event_key,
                            orjson.dumps(enriched_event),
                        )
                        metrics.record_signal("high_risk")
                        record_routing_metrics(AUDIT_SIGNALS_HIGHRISK_TOPIC, False)

                    if should_emit_high_risk_alert(enriched_event):
                        operator_alert = build_operator_alert(enriched_event)
                        safe_produce(
                            producer,
                            AUDIT_ALERTS_TOPIC,
                            event_key,
                            orjson.dumps(operator_alert),
                        )
                        api_state.record_alert(operator_alert)
                        metrics.record_signal("operator_alert")
                        if product_store:
                            persist_safely("operator_alert", product_store.persist_alert, operator_alert)
                            if _ps_health:
                                metrics.record_persistence_success(_ps_health)

                    if ENABLE_MULTI_TOPIC_ROUTING and topic_router:
                        _rt_result = topic_router.route_event(enriched_event)
                        if _rt_result == RoutingResult.ERROR:
                            logger.error(
                                "topic_router.route_event failed for method=%s — sending to DLQ",
                                enriched_event.get("methodName", "unknown"),
                            )
                            send_to_dlq(
                                producer,
                                msg.value(),
                                "topic_router.route_event returned ERROR",
                                msg.topic(),
                                msg.partition(),
                                msg.offset(),
                            )

                    # Track this message's offset for the end-of-batch commit.
                    key = (msg.topic(), msg.partition())
                    if msg.offset() > batch_max_offsets.get(key, -1):
                        batch_max_offsets[key] = msg.offset()
                except orjson.JSONDecodeError as ex:
                    batch_had_processing_failure = True
                    metrics.record_parse_error()
                    logger.exception("Parse failure: %s", ex)
                    send_to_dlq(
                        producer,
                        msg.value(),
                        str(ex),
                        msg.topic(),
                        msg.partition(),
                        msg.offset()
                    )
                except Exception as ex:
                    batch_had_processing_failure = True
                    metrics.record_error()
                    if product_store:
                        metrics.record_persistence_failure(str(ex))
                    logger.exception("Process failure: %s", ex)
                    # Send failed event to DLQ for later reprocessing
                    send_to_dlq(
                        producer,
                        msg.value(),
                        str(ex),
                        msg.topic(),
                        msg.partition(),
                        msg.offset()
                    )

            # End-of-batch DB write is now async — events were routed into
            # priority lanes earlier in this batch. The producer flush below
            # is what gates offset commit; PG durability is rebuilt from
            # Kafka topics on replay if a writer thread crashes.
            db_last_flush_ts = time.monotonic()

            # Flush producer to ensure ALL messages are delivered before committing offsets
            # This is critical for at-least-once delivery guarantee
            remaining = producer.flush(timeout=30)
            _refresh_queue_depths()

            should_commit, commit_details = evaluate_batch_commit(
                remaining,
                batch_delivery_errors_before,
                delivery_errors["count"],
                batch_had_processing_failure,
            )

            # Merge offsets from noise events the consumer short-circuited.
            # These never reached a Kafka topic, so the only at-least-once
            # gate is "the bulk writer has actually INSERTed them". We block
            # here until that's true — and refuse to commit on timeout so a
            # restart will replay any unpersisted noise.
            noise_persisted_ok = True
            if noise_offsets:
                noise_persisted_ok = _await_noise_persisted(noise_offsets)
                if not noise_persisted_ok:
                    metrics.record_noise_persist_wait_timeout()
                    logger.warning(
                        "Noise persistence wait timed out after %.1fs — declining commit; "
                        "%d short-circuited events across %d partitions will replay on restart",
                        NOISE_PERSIST_WAIT_TIMEOUT_SECONDS,
                        sum(1 for _ in noise_offsets),
                        len(noise_offsets),
                    )

            if not should_commit or not noise_persisted_ok:
                # Some messages failed to deliver, or short-circuited noise
                # didn't land in PG in time. Either way: do NOT commit
                # offsets — restart will replay everything in this batch.
                if not should_commit:
                    logger.error("Batch not committed: %s", commit_details)
                metrics.record_commit_failure()
            else:
                # Combine processor and short-circuit offsets into a single
                # per-partition high-watermark for the commit.
                merged_offsets = dict(batch_max_offsets)
                for key, offset in noise_offsets.items():
                    if offset > merged_offsets.get(key, -1):
                        merged_offsets[key] = offset

                if not merged_offsets:
                    # No successfully-processed messages in this batch (everything
                    # was a parse error / consume error). Nothing to commit.
                    metrics.record_commit_success()
                else:
                    # All messages delivered (and any short-circuited noise
                    # is durable). Build explicit TopicPartitions:
                    # librdkafka's auto-offset-store is unreliable when
                    # consume() and commit() run in different threads.
                    # Commit offset = max processed + 1 per partition.
                    offsets_to_commit = [
                        TopicPartition(t, p, offset + 1)
                        for (t, p), offset in merged_offsets.items()
                    ]
                    try:
                        consumer.commit(offsets=offsets_to_commit, asynchronous=False)
                        metrics.record_commit_success()
                        logger.debug(
                            "Batch committed: %d events across %d partitions (noise offsets included)",
                            batch_size, len(offsets_to_commit),
                        )
                    except Exception as e:
                        logger.error("Failed to commit offsets: %s", e)
                        metrics.record_commit_failure()

            processed += batch_size
            if processed >= 1000 and processed % 1000 < batch_size:
                elapsed = time.time() - start_ts
                logger.info("Processed %d msgs in %.1f s (%.1f msg/s)",
                            processed, elapsed, processed / elapsed)
            if CONSUMER_BATCH_SLEEP_SECONDS > 0:
                _sleep_with_shutdown(CONSUMER_BATCH_SLEEP_SECONDS)

            now = time.time()
            _run_periodic_maintenance(now)

    def _run_periodic_maintenance(now: float) -> None:
        """Heartbeat + 60 s tick. Runs from the processor thread (or its idle
        path when the queue is empty) so we don't need a third thread."""
        nonlocal last_heartbeat, last_lag_ts, last_iam_prefetch_ts
        if now - last_heartbeat >= 30:
            _refresh_queue_depths()
            _mem_mb_part = ""
            if _PSUTIL_AVAILABLE:
                try:
                    _mem_mb = _psutil.Process().memory_info().rss / 1024 / 1024
                    _mem_mb_part = f" memory_mb={_mem_mb:.0f}"
                except Exception:
                    pass
            logger.info(
                "Forwarder is alive at %s. Processed: %d, Errors: %d, Delivery failures: %d, "
                "DLQ: %d sent/%d failed, queue=%d/%d, lanes critical=%d normal=%d bulk=%d catalog=%d%s",
                time.ctime(), metrics.processed_total, metrics.error_count, delivery_errors["count"],
                dlq_stats["sent"], dlq_stats["failed"],
                record_queue.qsize(), RECORD_QUEUE_SIZE,
                metrics.critical_queue_depth, metrics.normal_queue_depth,
                metrics.bulk_queue_depth, metrics.catalog_queue_depth,
                _mem_mb_part,
            )
            if delivery_errors["last_error"]:
                logger.info(
                    "Last delivery error: %s",
                    mask_sensitive_text(delivery_errors["last_error"]),
                )
            if ENABLE_MULTI_TOPIC_ROUTING and topic_router:
                stats = topic_router.get_stats()
                if stats.get('low_dropped', 0) > 0:
                    logger.info(
                        "Routing stats - LOW dropped: %d (%.1f%% of total), CRITICAL: %d, "
                        "HIGH: %d, MEDIUM: %d, LOW routed: %d",
                        stats['low_dropped'],
                        stats['low_dropped'] / max(stats['total_events'], 1) * 100,
                        stats['critical_routed'], stats['high_routed'],
                        stats['medium_routed'], stats['low_routed'],
                    )
            if denial_aggregator:
                agg_stats = denial_aggregator.get_stats()
                if agg_stats.get('events_aggregated', 0) > 0:
                    logger.info(
                        "Aggregator stats - aggregated: %d, alerts: %d (HIGH: %d, MEDIUM: %d), pending: %d",
                        agg_stats['events_aggregated'], agg_stats['alerts_produced'],
                        agg_stats['high_alerts'], agg_stats['medium_alerts'],
                        agg_stats['pending_denials'],
                    )
            last_heartbeat = now

        if now - last_lag_ts >= 60:
            anomaly_tracker.cleanup()
            tracker_stats = anomaly_tracker.get_stats()
            logger.debug(
                "Rate tracker cleanup: %d principals, %d IPs tracked",
                tracker_stats.get('tracked_principals', 0),
                tracker_stats.get('tracked_ips', 0),
            )
            try:
                summary = anomaly_tracker.flush_suppression_summary()
                for anomaly_type, principal, count in summary:
                    logger.info(
                        "%s: %s suppressed %d repeats in last %ds",
                        principal or "<unknown>", anomaly_type, count,
                        anomaly_tracker.config.dedup_window_seconds,
                    )
            except AttributeError:
                pass  # older RateTracker without the helper
            if product_store:
                try:
                    product_store.cleanup_expired()
                    product_store.checkpoint_wal(mode="PASSIVE")
                    metrics.record_persistence_success(product_store.health())
                except Exception as exc:
                    metrics.record_persistence_failure(str(exc))
                    logger.warning("Persistence maintenance failed: %s", exc)
            last_lag_ts = now

        if now - last_iam_prefetch_ts > _IAM_PREFETCH_INTERVAL:
            try:
                from src.product.actor_enrichment import _bulk_prefetch_identities  # noqa: PLC0415
                threading.Thread(
                    target=_bulk_prefetch_identities,
                    args=(None,),
                    daemon=True,
                    name="iam-bulk-refresh",
                ).start()
            except Exception as _iam_exc:
                logger.warning("IAM bulk refresh start failed: %s", _iam_exc)
            last_iam_prefetch_ts = now

    consumer_thread = threading.Thread(target=_consume_thread, name="kafka-consumer")
    processor_thread = threading.Thread(target=_process_thread, name="event-processor")
    consumer_thread.start()
    processor_thread.start()

    writer_threads: list[threading.Thread] = []
    if PRIORITY_QUEUES_ENABLED:
        # Three writer lanes — sized so the critical lane drains in seconds
        # (small batches, no wait), the bulk lane absorbs noise efficiently
        # (large batches, multi-second wait), and the normal lane sits in
        # between. Per-lane tuning is exposed via env vars but the defaults
        # match the freshness SLA documented in docs/RETENTION_POLICY.md.
        critical_writer = threading.Thread(
            target=_writer_loop,
            args=(
                critical_queue,
                max(1, int(os.getenv("WRITER_CRITICAL_BATCH", "25"))),
                max(0.05, float(os.getenv("WRITER_CRITICAL_WAIT", "0.1"))),
                "critical",
                "critical_queue_depth",
            ),
            name="writer-critical",
            daemon=False,
        )
        normal_writer = threading.Thread(
            target=_writer_loop,
            args=(
                normal_queue,
                max(1, int(os.getenv("WRITER_NORMAL_BATCH", "200"))),
                max(0.1, float(os.getenv("WRITER_NORMAL_WAIT", "1.0"))),
                "normal",
                "normal_queue_depth",
            ),
            name="writer-normal",
            daemon=False,
        )
        bulk_writer = threading.Thread(
            target=_writer_loop,
            args=(
                bulk_queue,
                max(1, int(os.getenv("WRITER_BULK_BATCH", "1000"))),
                max(0.5, float(os.getenv("WRITER_BULK_WAIT", "5.0"))),
                "bulk",
                "bulk_queue_depth",
            ),
            name="writer-bulk",
            daemon=False,
        )
        catalog_writer = threading.Thread(
            target=_catalog_writer_loop,
            name="writer-catalog",
            daemon=False,
        )
        for t in (critical_writer, normal_writer, bulk_writer, catalog_writer):
            t.start()
            writer_threads.append(t)

    logger.info(
        "Thread pool started: 1 consumer, 1 processor, %d priority writers (record_queue capacity=%d)",
        len(writer_threads), RECORD_QUEUE_SIZE,
    )
    if short_circuit_active:
        logger.info(
            "Noise short-circuit: ENABLED — bulk noise bypasses processor thread "
            "(persist barrier %.0fs, methods=%d)",
            NOISE_PERSIST_WAIT_TIMEOUT_SECONDS,
            len(BULK_NOISE_METHODS),
        )
    else:
        reason = (
            "ENABLE_NOISE_SHORT_CIRCUIT=false"
            if not ENABLE_NOISE_SHORT_CIRCUIT
            else "DB writer disabled"
        )
        logger.info("Noise short-circuit: DISABLED (%s)", reason)

    try:
        # Main thread blocks here until shutdown is requested. The actual
        # work happens in consumer_thread + processor_thread.
        while not _shutdown_requested:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Interrupted by user (KeyboardInterrupt)")
    finally:
        logger.info("Shutting down gracefully...")

        # Wait for the consumer thread to drain its current poll and signal
        # the processor via the queue sentinel.
        consumer_thread.join(timeout=30)
        if consumer_thread.is_alive():
            logger.warning("kafka-consumer thread did not exit within 30s")
        # Wait for the processor to drain in-flight DB writes.
        processor_thread.join(timeout=120)
        processor_still_alive = processor_thread.is_alive()
        if processor_still_alive:
            logger.warning("event-processor thread did not exit within 120s")
        # Drain priority writer threads. Each writer flushes any partial
        # batch it has buffered before exiting (loop checks _shutdown_requested
        # after every batch). Critical drains first because its queue is
        # smallest and we want destructive events landed before exit.
        for t in writer_threads:
            t.join(timeout=120)
            if t.is_alive():
                logger.warning("%s did not exit within 120s", t.name)

        # Shutdown denial aggregator FIRST (flushes pending alerts before producer)
        if denial_aggregator:
            denial_aggregator.shutdown()

        # Stop metrics server
        if metrics_server:
            metrics_server.shutdown()
        storage_monitor_stop.set()
        if storage_monitor_thread:
            storage_monitor_thread.join(timeout=5)

        # Flush producer. The processor thread has already committed offsets
        # for every batch it finished, so shutdown commit is purely defensive
        # — typically there is nothing left in librdkafka's offset store at
        # this point and commit() will return _NO_OFFSET (harmless).
        remaining = producer.flush(timeout=30)
        if remaining > 0:
            logger.warning("Could not flush %d messages during shutdown", remaining)
        else:
            if processor_still_alive:
                logger.info("Skipping shutdown commit — processor thread still alive and will commit its own offsets")
            else:
                try:
                    consumer.commit(asynchronous=False)
                    metrics.record_commit_success()
                    logger.info("Final offset commit successful")
                except Exception as e:
                    msg_str = str(e)
                    if "No offset stored" in msg_str or "_NO_OFFSET" in msg_str:
                        logger.info("No pending offsets to commit at shutdown (processor already committed)")
                    else:
                        logger.error("Failed to commit offsets during shutdown: %s", e)
                        metrics.record_commit_failure()

        consumer.close()
        logger.info("Shutdown complete")


def run_cli(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="AuditLens foundation runtime")
    subparsers = parser.add_subparsers(dest="command")

    replay_parser = subparsers.add_parser("replay", help="Rebuild durable state from Kafka")
    replay_parser.add_argument("--source-mode", choices=["raw", "enriched"], default="raw")
    replay_parser.add_argument("--hours", type=int, default=None, help="Replay last N hours")
    replay_parser.add_argument("--from-earliest", action="store_true", help="Replay from earliest offset")
    replay_parser.add_argument("--publish-topics", action="store_true", help="Republish rebuilt signals/alerts to Kafka topics")

    args = parser.parse_args(argv)
    if args.command != "replay":
        try:
            main()
        except Exception as e:
            logging.critical(
                "FORWARDER CRASHED: %s\n%s",
                e, traceback.format_exc()
            )
            raise
        return 0

    startup_config = validate_startup_config()
    if not startup_config["valid"]:
        logger.error("Startup validation failed: %s", mask_config_for_logging(startup_config))
        return 1
    initialize_product_store_or_exit()
    result = replay_events(
        source_mode=args.source_mode,
        hours=args.hours,
        from_earliest=args.from_earliest,
        publish_topics=args.publish_topics,
    )
    logger.info("Replay completed: %s", result)
    return 0

if __name__ == "__main__":
    sys.exit(run_cli())
