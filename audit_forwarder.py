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
import argparse
import signal
import orjson
import logging
import time
import re
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, Future
import csv
import random
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import deque
from pathlib import Path
from io import StringIO
from urllib.parse import parse_qs, urlparse
from dotenv import load_dotenv
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
from src.routing import TopicRouter, RouterConfig
from src.alerting import get_webhook_sender
from src.aggregation import DenialAggregator, AggregatorConfig
from src.identity import normalize_with_type
from src.product import (
    AuthConfig,
    Authenticator,
    PersistenceConfig,
    Role,
    SQLiteProductStore,
)
from src.product.db_writer import AuditEventDbWriter

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


def extract_from_crn(crn, field):
    """Extract field from CRN string."""
    if not crn:
        return None
    match = re.search(f'{field}=([^/]+)', str(crn))
    return match.group(1) if match else None

# ──────────── secrets masking for safe logging ────────────
# Single source of truth for "is this field name sensitive?". Lower-case tokens
# that we expect after normalising - and . to _. New tokens: every commonly-used
# OAuth / IAM / API field that previously slipped past the redactor.
_SENSITIVE_KEY_TOKENS: tuple[str, ...] = (
    "password",
    "passphrase",
    "passwd",
    "secret",            # covers client_secret, api_secret, etc.
    "api_key",
    "apikey",
    "x_api_key",
    "token",             # covers access_token / refresh_token / id_token / bearer token
    "bearer",
    "credential",
    "authorization",
    "cookie",
    "private_key",
    "client_id",         # principal-style identifier; treat as sensitive in logs
)


def _key_is_sensitive(name: str) -> bool:
    normalized = name.lower().replace("-", "_").replace(".", "_")
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


# Build a separator-tolerant regex alternation for the sensitive tokens above.
# The `_` placeholders inside multi-word tokens become ``[_.\-]?`` so we match
# ``api_key``, ``api.key``, ``api-key``, and ``apikey`` against the same token.
def _token_pattern(token: str) -> str:
    escaped = re.escape(token)
    return escaped.replace(r"\_", r"[_.\-]?").replace(r"_", r"[_.\-]?")


_TOKEN_ALT = "|".join(_token_pattern(t) for t in _SENSITIVE_KEY_TOKENS)


def mask_config_for_logging(config: dict) -> dict:
    """
    Return config dict with secrets masked for safe logging.

    Use this when logging any configuration that might contain sensitive values.
    Masks: passwords, secrets, API keys, tokens, credentials, OAuth fields,
    cookies, and authorization headers.
    """
    masked = {}
    for k, v in config.items():
        if _key_is_sensitive(str(k)):
            masked[k] = '***MASKED***'
        else:
            masked[k] = v
    return masked


# Pre-compiled regexes for masking secrets out of a free-form *string*
# (Kafka error messages, exception strings, librdkafka diagnostics, etc.).
# We scrub two shapes:
#   1. ``key=value`` / ``key: value`` / ``key:"value"`` where the key matches a
#      sensitive token. Mask the value.
#   2. ``Bearer <token>`` / ``Basic <token>`` Authorization-header fragments.
# Order matters: Bearer/Basic Authorization fragments are scrubbed *before* the
# generic key=value pass so that ``Authorization: Bearer <token>`` becomes
# ``Authorization: Bearer ***MASKED***`` rather than the key=value pattern
# eating ``Bearer`` as the value of the ``Authorization:`` field and leaving
# the actual token unmasked at the tail.
_TEXT_MASK_PATTERNS = [
    re.compile(r"\b(?P<scheme>Bearer|Basic)\s+(?P<value>[A-Za-z0-9_\-\.=+/]{6,})", flags=re.IGNORECASE),
    re.compile(
        r"(?P<key>[A-Za-z0-9_.\-]*?(?:" + _TOKEN_ALT + r")[A-Za-z0-9_.\-]*?)"
        r"(?P<sep>\s*[:=]\s*)"
        r"(?P<quote>[\"']?)"
        r"(?P<value>[^\s\"'&,;]+)"
        r"(?P=quote)",
        flags=re.IGNORECASE,
    ),
]


def mask_sensitive_text(text: str | None) -> str | None:
    """
    Scrub secret-shaped substrings out of a free-form string.

    ``mask_config_for_logging`` works on dicts where keys carry the metadata
    needed for redaction. For raw error messages and exception strings we have
    no key to inspect, so we walk a curated set of regexes that catch the most
    common ``key=value`` / Authorization-header shapes.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    masked = text
    for pattern in _TEXT_MASK_PATTERNS:
        masked = pattern.sub(
            lambda match: (
                f"{match.group('scheme')} ***MASKED***"
                if "scheme" in match.groupdict() and match.group("scheme")
                else f"{match.group('key')}{match.group('sep')}{match.group('quote') or ''}***MASKED***{match.group('quote') or ''}"
            ),
            masked,
        )
    return masked


# ──────────── environment loader ────────────
def load_env():
    # Load .env file
    env_path = Path('.env')
    if not env_path.exists():
        alt = Path('..') / '.env'
        if alt.exists():
            env_path = alt
    if env_path.exists():
        load_dotenv(env_path)

    # Load .secrets file (contains sensitive credentials)
    secrets_path = Path('.secrets')
    if not secrets_path.exists():
        alt = Path('..') / '.secrets'
        if alt.exists():
            secrets_path = alt
    if secrets_path.exists():
        load_dotenv(secrets_path)
load_env()

# ──────────── environment variables ────────────
AUDIT_BOOTSTRAP        = os.getenv("AUDIT_BOOTSTRAP")
AUDIT_API_KEY          = os.getenv("AUDIT_API_KEY")
AUDIT_API_SECRET       = os.getenv("AUDIT_API_SECRET")
DEST_BOOTSTRAP         = os.getenv("DEST_BOOTSTRAP")
DEST_API_KEY           = os.getenv("DEST_API_KEY")
DEST_API_SECRET        = os.getenv("DEST_API_SECRET")
SCHEMA_REGISTRY_URL    = os.getenv("SCHEMA_REGISTRY_URL")
SCHEMA_REGISTRY_KEY    = os.getenv("SCHEMA_REGISTRY_KEY")
SCHEMA_REGISTRY_SECRET = os.getenv("SCHEMA_REGISTRY_SECRET")
AUDIT_TOPIC            = os.getenv("AUDIT_TOPIC", "confluent-audit-log-events")
# Consumer group - offsets are managed by Kafka consumer groups (not files)
GROUP_ID               = os.getenv("GROUP_ID", "auditlens-forwarder-v1")
AUTO_OFFSET_RESET      = os.getenv("AUTO_OFFSET_RESET", "latest")
METRICS_PORT           = int(os.getenv("METRICS_PORT", "8003"))

# Canonical product topics
AUDIT_RAW_TOPIC = os.getenv("AUDIT_RAW_TOPIC", "audit.raw.v1")
AUDIT_NORMALIZED_TOPIC = os.getenv("AUDIT_NORMALIZED_TOPIC", "audit.normalized.v1")
AUDIT_ENRICHED_TOPIC = os.getenv("AUDIT_ENRICHED_TOPIC", "audit.enriched.v1")
AUDIT_SIGNALS_DENIALS_TOPIC = os.getenv("AUDIT_SIGNALS_DENIALS_TOPIC", "audit.signals.denials.v1")
AUDIT_SIGNALS_HIGHRISK_TOPIC = os.getenv("AUDIT_SIGNALS_HIGHRISK_TOPIC", "audit.signals.highrisk.v1")
AUDIT_ALERTS_TOPIC = os.getenv("AUDIT_ALERTS_TOPIC", "audit.alerts.v1")

# Anomaly detection configuration
ANOMALY_WINDOW_SECONDS = int(os.getenv("ANOMALY_WINDOW_SECONDS", "60"))
ANOMALY_AUTH_FAILURE_THRESHOLD = int(os.getenv("ANOMALY_AUTH_FAILURE_THRESHOLD", "10"))
ANOMALY_ACTIVITY_SPIKE_THRESHOLD = int(os.getenv("ANOMALY_ACTIVITY_SPIKE_THRESHOLD", "100"))
ANOMALY_DELETION_THRESHOLD = int(os.getenv("ANOMALY_DELETION_THRESHOLD", "5"))
ANOMALY_API_KEY_THRESHOLD = int(os.getenv("ANOMALY_API_KEY_THRESHOLD", "10"))

# Legacy routing configuration - kept only for compatibility testing
ENABLE_MULTI_TOPIC_ROUTING = os.getenv("ENABLE_LEGACY_MULTI_TOPIC_ROUTING", "false").lower() == "true"
ROUTER_DRY_RUN = os.getenv("AUDIT_ROUTER_DRY_RUN", "false").lower() == "true"

# Dead Letter Queue - for events that fail processing
DLQ_TOPIC = os.getenv("DLQ_TOPIC", "audit.dlq.v1")
ENABLE_DLQ = os.getenv("ENABLE_DLQ", "true").lower() == "true"

# Denial aggregation - aggregate auth denials into summary alerts
ENABLE_DENIAL_AGGREGATION = os.getenv("ENABLE_DENIAL_AGGREGATION", "true").lower() == "true"
ALERT_ON_HIGH_RISK = os.getenv("ALERT_ON_HIGH_RISK", "true").lower() == "true"
API_MAX_SEARCH_RESULTS = int(os.getenv("API_MAX_SEARCH_RESULTS", "500"))
API_BUFFER_ENRICHED = int(os.getenv("API_BUFFER_ENRICHED", "5000"))
API_BUFFER_SIGNALS = int(os.getenv("API_BUFFER_SIGNALS", "1000"))
API_EXPORT_MAX_ROWS = int(os.getenv("API_EXPORT_MAX_ROWS", "5000"))
API_EXPORT_MAX_HOURS = int(os.getenv("API_EXPORT_MAX_HOURS", "168"))
REPLAY_ENABLED = os.getenv("REPLAY_ENABLED", "true").lower() == "true"
REPLAY_DEFAULT_HOURS = int(os.getenv("REPLAY_DEFAULT_HOURS", "24"))
REPLAY_MAX_HOURS = int(os.getenv("REPLAY_MAX_HOURS", "720"))
REPLAY_PUBLISH_DERIVED_TOPICS = os.getenv("REPLAY_PUBLISH_DERIVED_TOPICS", "false").lower() == "true"
STORAGE_MONITOR_INTERVAL_SECONDS = int(os.getenv("STORAGE_MONITOR_INTERVAL_SECONDS", "60"))
CONSUMER_POLL_TIMEOUT_SECONDS = float(os.getenv("CONSUMER_POLL_TIMEOUT_SECONDS", "2.0"))
CONSUMER_EMPTY_POLL_SLEEP_SECONDS = float(os.getenv("CONSUMER_EMPTY_POLL_SLEEP_SECONDS", "0.25"))
CONSUMER_BATCH_SLEEP_SECONDS = float(os.getenv("CONSUMER_BATCH_SLEEP_SECONDS", "0.25"))
KAFKA_RETRY_INITIAL_BACKOFF_SECONDS = float(os.getenv("KAFKA_RETRY_INITIAL_BACKOFF_SECONDS", "1.0"))
KAFKA_RETRY_MAX_BACKOFF_SECONDS = float(os.getenv("KAFKA_RETRY_MAX_BACKOFF_SECONDS", "60.0"))
KAFKA_DEGRADED_AFTER_ERRORS = int(os.getenv("KAFKA_DEGRADED_AFTER_ERRORS", "5"))
KAFKA_ERROR_LOG_INTERVAL_SECONDS = float(os.getenv("KAFKA_ERROR_LOG_INTERVAL_SECONDS", "30.0"))
ENABLE_DB_WRITER = os.getenv("ENABLE_DB_WRITER", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////var/lib/auditlens/auditlens_api.db")
DB_WRITE_BATCH_SIZE = int(os.getenv("DB_WRITE_BATCH_SIZE", "100"))
DB_WRITE_BACKOFF_MAX_SECONDS = float(os.getenv("DB_WRITE_BACKOFF_MAX_SECONDS", "60.0"))
DB_WRITE_FLUSH_INTERVAL_SECONDS = float(os.getenv("DB_WRITE_FLUSH_INTERVAL_SECONDS", "2.0"))
EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "7"))
DB_RETENTION_CLEANUP_INTERVAL_SECONDS = float(os.getenv("DB_RETENTION_CLEANUP_INTERVAL_SECONDS", "3600.0"))

AUTH_CONFIG = AuthConfig.from_env()
authenticator = Authenticator(AUTH_CONFIG)
PERSISTENCE_CONFIG = PersistenceConfig.from_env()
product_store = None
db_writer = None
storage_monitor_stop = threading.Event()
storage_monitor_thread = None

# Built-in alert rules (auto-enabled if SLACK_WEBHOOK is set)
# These are critical events that should trigger immediate alerts
BUILTIN_ALERT_METHODS = {
    # Infrastructure deletion - CRITICAL
    'DeleteKafkaCluster': {'severity': 'CRITICAL', 'message': '🚨 CRITICAL: Kafka cluster deleted'},
    'DeleteEnvironment': {'severity': 'CRITICAL', 'message': '🚨 CRITICAL: Environment deleted'},
    'DeleteOrganization': {'severity': 'CRITICAL', 'message': '🚨 CRITICAL: Organization deleted'},

    # Topic/data deletion - CRITICAL
    'kafka.DeleteTopics': {'severity': 'CRITICAL', 'message': '🚨 CRITICAL: Kafka topics deleted'},
    'kafka.DeleteRecords': {'severity': 'CRITICAL', 'message': '🚨 CRITICAL: Kafka records deleted'},

    # Security configuration changes - HIGH
    'kafka.CreateAcls': {'severity': 'HIGH', 'message': '⚠️ HIGH: ACLs created'},
    'kafka.DeleteAcls': {'severity': 'HIGH', 'message': '⚠️ HIGH: ACLs deleted'},
    'CreateApiKey': {'severity': 'HIGH', 'message': '🔑 HIGH: API key created'},
    'DeleteApiKey': {'severity': 'HIGH', 'message': '🔑 HIGH: API key deleted'},

    # Service account changes - HIGH
    'DeleteServiceAccount': {'severity': 'HIGH', 'message': '⚠️ HIGH: Service account deleted'},
    'CreateServiceAccount': {'severity': 'MEDIUM', 'message': 'ℹ️ MEDIUM: Service account created'},
}

# Enable built-in alerts if SLACK_WEBHOOK is configured
ENABLE_BUILTIN_ALERTS = os.getenv("SLACK_WEBHOOK", "") != ""

# ──────────── logging ────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()


HIGH_RISK_ALERT_METHODS = {
    "kafka.DeleteTopics",
    "kafka.DeleteRecords",
    "kafka.CreateAcls",
    "kafka.DeleteAcls",
    "CreateApiKey",
    "DeleteApiKey",
    "DeleteServiceAccount",
    "CreateRoleBinding",
    "DeleteRoleBinding",
}

HIGH_RISK_SIGNAL_METHODS = HIGH_RISK_ALERT_METHODS | {
    "DeleteKafkaCluster",
    "DeleteEnvironment",
    "DeleteWorkspace",
    "DeleteConnector",
}


def utc_now_iso() -> str:
    """Return RFC3339 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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

# ──────────── metrics tracking ────────────
class Metrics:
    def __init__(self):
        self.start_time = time.time()
        self.processed_total = 0
        self.error_count = 0
        self.last_process_time = time.time()
        self.partition_lag = {}
        # Set by the consumer thread on every poll cycle so /health can show
        # whether the processor is keeping up with fetched batches.
        self.record_queue_depth = 0
        self.record_queue_capacity = 0
        # Priority-queue depths (between processor and async DB writers).
        # Updated by writer threads + by the processor on enqueue. Surfaced
        # via /health so operators can see which lane is backing up.
        self.critical_queue_depth = 0
        self.normal_queue_depth = 0
        self.bulk_queue_depth = 0
        self.catalog_queue_depth = 0
        self.last_ingested_event_time = None
        self.last_committed_at = None
        self.offset_commits_total = 0
        self.offset_commit_failures_total = 0
        self.rebalance_count = 0
        self.restart_count = 0
        self.parse_error_count = 0
        self.persistence_write_failures = 0
        self.persistence_write_success_total = 0
        self.api_auth_failures_total = 0
        self.export_requests_total = 0
        self.export_denied_total = 0
        self.replay_runs_total = 0
        self.replay_failures_total = 0
        self.replay_in_progress = False
        self.replay_last_started_at = None
        self.replay_last_completed_at = None
        self.replay_last_success_at = None
        self.replay_last_error = None
        self.replay_records_processed_total = 0
        self.replay_source_mode = None
        self.replay_window = None
        self.poll_count = 0
        self.empty_poll_count = 0
        self.records_consumed_total = 0
        self.retry_count = 0
        self.consecutive_error_count = 0
        self.last_error = None
        self.last_error_at = None
        self.last_successful_poll = None
        self.backoff_seconds = 0.0
        self.consumer_state = "starting"
        self.db_write_success_total = 0
        self.db_write_error_total = 0
        self.db_write_batch_size = 0
        self.db_last_successful_write = None
        self.db_writer_state = "disabled"
        self.db_last_error = None
        self.db_last_cleanup_at = None
        self.db_last_cleanup_deleted_count = 0
        self.produce_retry_exhausted_total = 0
        self.delivery_attempts_by_topic = {}
        self.delivery_success_by_topic = {}
        self.delivery_failures_by_topic = {}
        self.signal_counts = {}
        self.data_quality = {
            "missing_principal_total": 0,
            "missing_resource_total": 0,
            "unknown_method_total": 0,
            "classification_fallback_total": 0,
            "suppressed_authz_noise_total": 0,
        }
        self.persistence_status = {
            "enabled": PERSISTENCE_CONFIG.enabled,
            "healthy": False,
            "backend": PERSISTENCE_CONFIG.backend,
            "last_write_at": None,
            "db_path": PERSISTENCE_CONFIG.db_path,
            "db_file_bytes": 0,
            "wal_file_bytes": 0,
            "current_db_size": 0,
            "max_db_size": PERSISTENCE_CONFIG.db_max_bytes,
            "free_disk_bytes": 0,
            "db_max_bytes": PERSISTENCE_CONFIG.db_max_bytes,
            "wal_max_bytes": PERSISTENCE_CONFIG.wal_max_bytes,
            "storage_mode": "normal",
            "free_disk_warning_bytes": PERSISTENCE_CONFIG.free_disk_warning_bytes,
            "free_disk_critical_bytes": PERSISTENCE_CONFIG.free_disk_critical_bytes,
            "storage_status": "ok",
            "storage_reasons": [],
            "data_retention_mode": "bounded_hot_cache",
            "hot_cache_retention_hours": PERSISTENCE_CONFIG.rotation_retention_hours,
            "archive_enabled": False,
            "data_loss_possible": True,
            "write_guard_active": False,
            "storage_degraded": False,
            "last_cleanup_at": None,
            "last_cleanup_deleted_rows": 0,
            "last_cleanup_time_deleted_rows": 0,
            "last_cleanup_size_deleted_rows": 0,
            "last_cleanup_strategy": "none",
            "cleanup_status": "not_run",
            "cleanup_last_error": None,
            "size_cleanup_status": "not_run",
            "size_cleanup_last_error": None,
            "size_cleanup_pressure_bytes": 0,
            "size_cleanup_target_bytes": int(PERSISTENCE_CONFIG.db_max_bytes * PERSISTENCE_CONFIG.adaptive_retention_target_ratio),
            "sqlite_page_size": 0,
            "sqlite_freelist_pages": 0,
            "sqlite_reclaimable_bytes": 0,
            "last_vacuum_at": None,
            "last_vacuum_status": "not_run",
            "last_vacuum_error": None,
            "rotation_in_progress": False,
            "last_rotation_time": None,
            "rows_copied": 0,
            "rotation_duration_ms": 0,
            "rotation_total": 0,
            "rotation_status": "not_run",
            "rotation_last_error": None,
            "rotation_trigger": None,
            "last_rotation_failure_time": None,
            "storage_write_dropped_total": 0,
            "adaptive_retention_min_hours": PERSISTENCE_CONFIG.adaptive_retention_min_hours,
            "adaptive_retention_max_batches": PERSISTENCE_CONFIG.adaptive_retention_max_batches,
            "size_cleanup_complete": True,
            "effective_retention_hours": {
                "enriched_events": PERSISTENCE_CONFIG.enriched_retention_days * 24,
                "high_risk_events": PERSISTENCE_CONFIG.signals_retention_days * 24,
                "denial_summaries": PERSISTENCE_CONFIG.signals_retention_days * 24,
                "alerts": PERSISTENCE_CONFIG.alerts_retention_days * 24,
                "api_audit_log": PERSISTENCE_CONFIG.audit_retention_days * 24,
            },
            "last_checkpoint_at": None,
            "last_checkpoint_mode": None,
            "last_checkpoint_status": "not_run",
            "last_checkpoint_busy": 0,
            "last_checkpoint_log_frames": 0,
            "last_checkpoint_checkpointed_frames": 0,
            "last_checkpoint_error": None,
        }
        self.lock = threading.Lock()
    
    def record_processed(self, count, event_time=None):
        with self.lock:
            self.processed_total += count
            self.last_process_time = time.time()
            if event_time:
                self.last_ingested_event_time = event_time

    def record_poll(self, record_count: int = 0):
        with self.lock:
            self.poll_count += 1
            if record_count <= 0:
                self.empty_poll_count += 1
            else:
                self.records_consumed_total += record_count
                self.last_successful_poll = utc_now_iso()
                self.consecutive_error_count = 0
                self.backoff_seconds = 0.0
                self.consumer_state = "connected"

    def record_consumer_retry(self, error: str, backoff_seconds: float):
        with self.lock:
            self.retry_count += 1
            self.consecutive_error_count += 1
            self.error_count += 1
            self.last_error = error
            self.last_error_at = utc_now_iso()
            self.backoff_seconds = backoff_seconds
            self.consumer_state = (
                "degraded"
                if self.consecutive_error_count >= KAFKA_DEGRADED_AFTER_ERRORS
                else "backoff"
            )

    def set_consumer_state(self, state: str, backoff_seconds: float = 0.0):
        with self.lock:
            self.consumer_state = state
            self.backoff_seconds = backoff_seconds

    def record_db_write_success(self, batch_size: int):
        with self.lock:
            self.db_write_success_total += 1
            self.db_write_batch_size = batch_size
            self.db_last_successful_write = utc_now_iso()
            self.db_writer_state = "connected"
            self.db_last_error = None

    def record_db_write_error(self, error: str, batch_size: int = 0):
        with self.lock:
            self.db_write_error_total += 1
            self.error_count += 1
            self.db_write_batch_size = batch_size
            self.db_writer_state = "degraded"
            self.db_last_error = error

    def record_db_retention_cleanup(self, cleanup: dict):
        with self.lock:
            self.db_last_cleanup_at = cleanup.get("last_cleanup_at")
            self.db_last_cleanup_deleted_count = int(cleanup.get("deleted_count") or 0)

    def set_db_writer_state(self, state: str):
        with self.lock:
            self.db_writer_state = state
    
    def record_error(self):
        with self.lock:
            self.error_count += 1

    def record_parse_error(self):
        with self.lock:
            self.parse_error_count += 1
            self.error_count += 1

    def record_commit_success(self):
        with self.lock:
            self.offset_commits_total += 1
            self.last_committed_at = utc_now_iso()

    def record_commit_failure(self):
        with self.lock:
            self.offset_commit_failures_total += 1
            self.error_count += 1

    def record_rebalance(self):
        with self.lock:
            self.rebalance_count += 1

    def set_restart_count(self, count: int):
        with self.lock:
            self.restart_count = count

    def record_persistence_success(self, status: dict):
        with self.lock:
            self.persistence_write_success_total += 1
            self.persistence_status.update(status)

    def record_persistence_failure(self, error: str):
        with self.lock:
            self.persistence_write_failures += 1
            self.error_count += 1
            self.persistence_status["healthy"] = False
            self.persistence_status["last_error"] = error

    def record_delivery_attempt(self, topic: str):
        with self.lock:
            self.delivery_attempts_by_topic[topic] = self.delivery_attempts_by_topic.get(topic, 0) + 1

    def record_delivery_success(self, topic: str):
        with self.lock:
            self.delivery_success_by_topic[topic] = self.delivery_success_by_topic.get(topic, 0) + 1

    def record_delivery_failure(self, topic: str):
        with self.lock:
            self.delivery_failures_by_topic[topic] = self.delivery_failures_by_topic.get(topic, 0) + 1

    def record_produce_retry_exhausted(self):
        with self.lock:
            self.produce_retry_exhausted_total += 1

    def record_signal(self, signal_type: str):
        with self.lock:
            self.signal_counts[signal_type] = self.signal_counts.get(signal_type, 0) + 1

    def record_api_auth_failure(self):
        with self.lock:
            self.api_auth_failures_total += 1

    def record_export_request(self):
        with self.lock:
            self.export_requests_total += 1

    def record_export_denied(self):
        with self.lock:
            self.export_denied_total += 1

    def replay_started(self, source_mode: str, window: str):
        with self.lock:
            self.replay_runs_total += 1
            self.replay_in_progress = True
            self.replay_last_started_at = utc_now_iso()
            self.replay_source_mode = source_mode
            self.replay_window = window
            self.replay_last_error = None

    def replay_progress(self, processed_delta: int = 0):
        with self.lock:
            self.replay_records_processed_total += processed_delta

    def replay_finished(self, success: bool, error: str | None = None):
        with self.lock:
            self.replay_in_progress = False
            self.replay_last_completed_at = utc_now_iso()
            self.replay_last_error = error
            if success:
                self.replay_last_success_at = self.replay_last_completed_at
            else:
                self.replay_failures_total += 1

    def record_data_quality(self, flat: dict, classification_result):
        with self.lock:
            if not flat.get("principal_normalized"):
                self.data_quality["missing_principal_total"] += 1
            if not (flat.get("resourceName") or flat.get("authzResourceName")):
                self.data_quality["missing_resource_total"] += 1
            if classification_result.method_category == "unknown":
                self.data_quality["unknown_method_total"] += 1
            if str(classification_result.reason).startswith("Unclassified method"):
                self.data_quality["classification_fallback_total"] += 1
            method = flat.get("methodName") or ""
            if method.endswith(".Authorize") and flat.get("granted") is True:
                self.data_quality["suppressed_authz_noise_total"] += 1
    
    def update_lag(self, partition, position, high):
        with self.lock:
            self.partition_lag[partition] = high - position
    
    def get_metrics(self):
        with self.lock:
            uptime = time.time() - self.start_time
            idle_time = time.time() - self.last_process_time
            total_lag = sum(self.partition_lag.values()) if self.partition_lag else 0
            
            return {
                "uptime_seconds": uptime,
                "processed_messages_total": self.processed_total,
                "processing_rate_per_second": self.processed_total / uptime if uptime > 0 else 0,
                "error_count": self.error_count,
                "idle_seconds": idle_time,
                "consumer_lag_total": total_lag,
                "consumer_lag_by_partition": self.partition_lag,
                "record_queue_depth": int(self.record_queue_depth),
                "record_queue_capacity": int(self.record_queue_capacity),
                "priority_queue_depths": {
                    "critical": int(self.critical_queue_depth),
                    "normal": int(self.normal_queue_depth),
                    "bulk": int(self.bulk_queue_depth),
                    "catalog": int(self.catalog_queue_depth),
                },
                "last_ingested_event_time": self.last_ingested_event_time,
                "last_committed_at": self.last_committed_at,
                "offset_commits_total": self.offset_commits_total,
                "offset_commit_failures_total": self.offset_commit_failures_total,
                "rebalance_count": self.rebalance_count,
                "restart_count": self.restart_count,
                "parse_error_count": self.parse_error_count,
                "persistence_write_failures": self.persistence_write_failures,
                "persistence_write_success_total": self.persistence_write_success_total,
                "api_auth_failures_total": self.api_auth_failures_total,
                "export_requests_total": self.export_requests_total,
                "export_denied_total": self.export_denied_total,
                "replay_runs_total": self.replay_runs_total,
                "replay_failures_total": self.replay_failures_total,
                "replay_in_progress": self.replay_in_progress,
                "replay_last_started_at": self.replay_last_started_at,
                "replay_last_completed_at": self.replay_last_completed_at,
                "replay_last_success_at": self.replay_last_success_at,
                "replay_last_error": self.replay_last_error,
                "replay_records_processed_total": self.replay_records_processed_total,
                "replay_source_mode": self.replay_source_mode,
                "replay_window": self.replay_window,
                "poll_count": self.poll_count,
                "empty_poll_count": self.empty_poll_count,
                "records_consumed_total": self.records_consumed_total,
                "retry_count": self.retry_count,
                "consecutive_error_count": self.consecutive_error_count,
                "last_error": self.last_error,
                "last_error_at": self.last_error_at,
                "last_successful_poll": self.last_successful_poll,
                "backoff_seconds": self.backoff_seconds,
                "consumer_state": self.consumer_state,
                "db_write_success_total": self.db_write_success_total,
                "db_write_error_total": self.db_write_error_total,
                "db_write_batch_size": self.db_write_batch_size,
                "db_last_successful_write": self.db_last_successful_write,
                "db_writer_state": self.db_writer_state,
                "db_last_error": self.db_last_error,
                "db_last_cleanup_at": self.db_last_cleanup_at,
                "db_last_cleanup_deleted_count": self.db_last_cleanup_deleted_count,
                "produce_retry_exhausted_total": self.produce_retry_exhausted_total,
                "delivery_attempts_by_topic": dict(self.delivery_attempts_by_topic),
                "delivery_success_by_topic": dict(self.delivery_success_by_topic),
                "delivery_failures_by_topic": dict(self.delivery_failures_by_topic),
                "signal_counts": dict(self.signal_counts),
                "data_quality": dict(self.data_quality),
                "persistence_status": dict(self.persistence_status),
            }

# Create global metrics instance
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


def _request_filters(params: dict) -> dict:
    return {
        "q": (params.get("q", [""])[0] or "").strip(),
        "criticality": (params.get("criticality", [""])[0] or "").strip(),
        "principal": (params.get("principal", [""])[0] or "").strip(),
        "method": (params.get("method", [""])[0] or "").strip(),
        "resource": (params.get("resource", [""])[0] or "").strip(),
        "time_from": (params.get("time_from", [""])[0] or "").strip(),
        "time_to": (params.get("time_to", [""])[0] or "").strip(),
    }


def _request_actor(headers):
    return authenticator.authenticate(headers)


def _normalize_json_keys(obj):
    if isinstance(obj, dict):
        return {str(key): _normalize_json_keys(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_normalize_json_keys(item) for item in obj]
    return obj


# ──────────── metrics server ────────────
class MetricsHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict, headers: dict | None = None):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        try:
            safe_payload = _normalize_json_keys(payload)
            self.wfile.write(orjson.dumps(safe_payload, option=orjson.OPT_INDENT_2))
        except Exception:
            logger.error("JSON serialization error in health endpoint")
            fallback = {"status": "error", "message": "serialization failure"}
            self.wfile.write(orjson.dumps(fallback, option=orjson.OPT_INDENT_2))

    def _send_bytes(self, status_code: int, content_type: str, payload: bytes, headers: dict | None = None):
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(payload)

    def _json_error(self, status_code: int, message: str):
        self._send_json(status_code, {
            "error": message,
            "timestamp": utc_now_iso(),
        })

    def _record_api_audit(self, actor, action: str, endpoint: str, status_code: int, filters: dict, denied_reason: str | None = None):
        if product_store and PERSISTENCE_CONFIG.enabled:
            try:
                product_store.record_api_audit(
                    actor_id=actor.actor_id if actor else None,
                    role=actor.role.value if actor else None,
                    action=action,
                    endpoint=endpoint,
                    status_code=status_code,
                    remote_addr=self.client_address[0] if self.client_address else None,
                    user_agent=self.headers.get("User-Agent"),
                    filters=filters,
                    denied_reason=denied_reason,
                )
            except Exception as exc:
                logger.warning("Failed to record API audit log: %s", exc)

    def _authorize_request(self, endpoint: str, params: dict, export: bool = False):
        auth_result = _request_actor(self.headers)
        filters = _request_filters(params)
        if not auth_result.ok:
            metrics.record_api_auth_failure()
            self._record_api_audit(None, "authenticate", endpoint, auth_result.status_code, filters, auth_result.error)
            self._json_error(auth_result.status_code, auth_result.error or "unauthorized")
            return None

        actor = auth_result.actor
        assert actor is not None
        permission = authenticator.require_export(actor) if export else authenticator.require_view(actor)
        if not permission.ok:
            if export:
                metrics.record_export_denied()
            self._record_api_audit(actor, "authorize", endpoint, permission.status_code, filters, permission.error)
            self._json_error(permission.status_code, permission.error or "forbidden")
            return None

        return actor

    def _search_records(self, filters: dict, actor, limit: int):
        if product_store and PERSISTENCE_CONFIG.enabled and product_store.health().get("healthy"):
            return product_store.query_enriched(filters, actor, limit), "persistence"
        snapshot = api_state.snapshot()
        params = {k: [v] for k, v in filters.items() if v}
        return [
            event for event in snapshot["enriched_events"]
            if actor.scope_allows(event.get("organization_id"), event.get("environment_id"), event.get("cluster_id"))
            and self._match_event(event, params)
        ][:limit], "memory"

    def _high_risk_records(self, filters: dict, actor, limit: int):
        if product_store and PERSISTENCE_CONFIG.enabled and product_store.health().get("healthy"):
            return product_store.query_high_risk(filters, actor, limit), "persistence"
        snapshot = api_state.snapshot()
        params = {k: [v] for k, v in filters.items() if v}
        return [
            event for event in snapshot["high_risk_events"]
            if actor.scope_allows(event.get("organization_id"), event.get("environment_id"), event.get("cluster_id"))
            and self._match_event(event, params)
        ][:limit], "memory"

    def _denial_records(self, actor, limit: int):
        if product_store and PERSISTENCE_CONFIG.enabled and product_store.health().get("healthy"):
            return product_store.query_denials(actor, limit), "persistence"
        snapshot = api_state.snapshot()
        return [
            item for item in snapshot["denial_summaries"]
            if actor.scope_allows(
                (item.get("organization_ids") or [None])[0],
                (item.get("environment_ids") or [None])[0],
                (item.get("cluster_ids") or [None])[0],
            )
        ][:limit], "memory"

    def _validate_export_window(self, filters: dict) -> tuple[bool, str | None]:
        if not filters.get("time_from") or not filters.get("time_to"):
            return True, None
        try:
            start = datetime.fromisoformat(filters["time_from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(filters["time_to"].replace("Z", "+00:00"))
        except ValueError:
            return False, "invalid export time window"
        hours = (end - start).total_seconds() / 3600
        if hours > API_EXPORT_MAX_HOURS:
            return False, f"export window exceeds {API_EXPORT_MAX_HOURS} hours"
        return True, None

    def _health_payload(self):
        metrics_data = metrics.get_metrics()
        snapshot = api_state.snapshot()
        replay_snapshot = replay_state.snapshot()
        startup_config = validate_startup_config()

        idle_seconds = metrics_data['idle_seconds']
        error_count = metrics_data['error_count']
        processed = metrics_data['processed_messages_total']
        consumer_state = metrics_data.get("consumer_state", "unknown")
        consecutive_errors = metrics_data.get("consecutive_error_count", 0)
        is_idle = (
            consumer_state == "connected"
            and consecutive_errors == 0
            and metrics_data['uptime_seconds'] > 60
            and idle_seconds > 60
        )
        runtime_consumer_state = "idle" if is_idle else consumer_state
        is_healthy = True
        reasons = []

        if not startup_config["valid"]:
            is_healthy = False
            reasons.append("Startup configuration is invalid")
        if idle_seconds > 300 and not is_idle:
            is_healthy = False
            reasons.append(f"Idle for {idle_seconds:.0f}s (> 300s)")
        if processed > 0 and error_count / processed > 0.1:
            is_healthy = False
            reasons.append(f"High error rate: {error_count}/{processed} ({error_count/processed*100:.1f}%)")

        payload = {
            "status": "healthy" if is_healthy else "unhealthy",
            "state": runtime_consumer_state,
            "timestamp": utc_now_iso(),
            "version": VERSION,
            "uptime_seconds": metrics_data['uptime_seconds'],
            "processed_total": processed,
            "error_count": error_count,
            "idle_seconds": idle_seconds,
            "consumer_lag": metrics_data['consumer_lag_total'],
            "consumer_lag_by_partition": metrics_data['consumer_lag_by_partition'],
            "processing_rate": metrics_data['processing_rate_per_second'],
            "record_queue_depth": metrics_data.get('record_queue_depth', 0),
            "record_queue_capacity": metrics_data.get('record_queue_capacity', 0),
            "queues": metrics_data.get("priority_queue_depths", {
                "critical": 0, "normal": 0, "bulk": 0, "catalog": 0,
            }),
            "freshness": {
                "last_enriched_event_time": snapshot["last_enriched_event_time"],
                "last_enriched_ingest_at": snapshot["last_enriched_ingest_at"],
                "last_denial_flush_at": snapshot["last_denial_flush_at"],
                "last_committed_at": metrics_data.get("last_committed_at"),
            },
            "coverage": {
                "mode": "persistence_plus_recent_cache" if product_store and PERSISTENCE_CONFIG.enabled else "recent_in_memory_plus_kafka",
                "note": (
                    "Recent search/export uses persistence when healthy. "
                    "If persistence is unavailable, API falls back to recent in-memory cache with reduced durability."
                    if product_store and PERSISTENCE_CONFIG.enabled else snapshot["coverage_note"]
                ),
                "api_window_counts": {
                    "enriched_events": len(snapshot["enriched_events"]),
                    "high_risk_events": len(snapshot["high_risk_events"]),
                    "denial_summaries": len(snapshot["denial_summaries"]),
                    "alerts": len(snapshot["alerts"]),
                },
            },
            "offset_recovery": {
                "model": "consumer_group_only",
                "commit_behavior": "commit only after persistence success and Kafka producer flush without delivery errors",
                "delivery_semantics": "at_least_once",
                "duplicate_risk": "replay can occur after crash or rebalance between downstream success and offset commit",
            },
            "recovery": {
                "replay_available": REPLAY_ENABLED,
                "replay_in_progress": replay_snapshot["in_progress"],
                "last_replay_started_at": replay_snapshot["started_at"],
                "last_replay_completed_at": replay_snapshot["completed_at"],
                "last_replay_success_at": replay_snapshot["last_success_at"],
                "last_replay_error": replay_snapshot["last_error"],
                "replay_source_mode": replay_snapshot["source_mode"],
                "replay_window_mode": replay_snapshot["window_mode"],
            },
            "observability": {
                "offset_commits_total": metrics_data.get("offset_commits_total", 0),
                "offset_commit_failures_total": metrics_data.get("offset_commit_failures_total", 0),
                "rebalance_count": metrics_data.get("rebalance_count", 0),
                "restart_count": metrics_data.get("restart_count", 0),
                "parse_error_count": metrics_data.get("parse_error_count", 0),
                "dlq_sent_total": dlq_stats["sent"],
                "dlq_failed_total": dlq_stats["failed"],
                "api_auth_failures_total": metrics_data.get("api_auth_failures_total", 0),
                "export_requests_total": metrics_data.get("export_requests_total", 0),
                "export_denied_total": metrics_data.get("export_denied_total", 0),
                "replay_runs_total": metrics_data.get("replay_runs_total", 0),
                "replay_failures_total": metrics_data.get("replay_failures_total", 0),
                "replay_records_processed_total": metrics_data.get("replay_records_processed_total", 0),
                "consumer_runtime": {
                    "poll_count": metrics_data.get("poll_count", 0),
                    "empty_poll_count": metrics_data.get("empty_poll_count", 0),
                    "records_consumed_total": metrics_data.get("records_consumed_total", 0),
                    "retry_count": metrics_data.get("retry_count", 0),
                    "consecutive_error_count": metrics_data.get("consecutive_error_count", 0),
                    "last_error": metrics_data.get("last_error"),
                    "last_error_at": metrics_data.get("last_error_at"),
                    "last_successful_poll": metrics_data.get("last_successful_poll"),
                    "backoff_seconds": metrics_data.get("backoff_seconds", 0),
                    "consumer_state": runtime_consumer_state,
                },
                "db_writer": {
                    "enabled": ENABLE_DB_WRITER,
                    "db_write_success_total": metrics_data.get("db_write_success_total", 0),
                    "db_write_error_total": metrics_data.get("db_write_error_total", 0),
                    "db_write_batch_size": metrics_data.get("db_write_batch_size", 0),
                    "db_last_successful_write": metrics_data.get("db_last_successful_write"),
                    "db_writer_state": metrics_data.get("db_writer_state", "disabled"),
                    "db_last_error": metrics_data.get("db_last_error"),
                    "db_last_cleanup_at": metrics_data.get("db_last_cleanup_at"),
                    "db_last_cleanup_deleted_count": metrics_data.get("db_last_cleanup_deleted_count", 0),
                    "retention_days": EVENT_RETENTION_DAYS,
                    "flush_interval_seconds": DB_WRITE_FLUSH_INTERVAL_SECONDS,
                },
                "signal_counts": metrics_data.get("signal_counts", {}),
                "data_quality": metrics_data.get("data_quality", {}),
                "persistence_storage": metrics_data.get("persistence_status", {}),
            },
            "components": [
                {
                    "name": "config",
                    "status": "healthy" if startup_config["valid"] else "unhealthy",
                    "last_check": utc_now_iso(),
                    "details": {
                        "missing_required": startup_config["missing_required"],
                        "duplicate_topics": startup_config["duplicate_topics"],
                        "invalid_values": startup_config["invalid_values"],
                    },
                },
                {
                    "name": "consumer",
                    "status": "idle" if is_idle else ("healthy" if idle_seconds <= 300 else "degraded"),
                    "last_check": utc_now_iso(),
                    "details": {
                        "group_id": GROUP_ID,
                        "source_topic": AUDIT_TOPIC,
                        "consumer_lag": metrics_data['consumer_lag_total'],
                        "state": runtime_consumer_state,
                        "poll_count": metrics_data.get("poll_count", 0),
                        "empty_poll_count": metrics_data.get("empty_poll_count", 0),
                        "records_consumed_total": metrics_data.get("records_consumed_total", 0),
                        "retry_count": metrics_data.get("retry_count", 0),
                        "consecutive_error_count": metrics_data.get("consecutive_error_count", 0),
                        "last_error": metrics_data.get("last_error"),
                        "last_successful_poll": metrics_data.get("last_successful_poll"),
                        "backoff_seconds": metrics_data.get("backoff_seconds", 0),
                    },
                },
                {
                    "name": "producer",
                    "status": "healthy" if delivery_errors["count"] == 0 else "degraded",
                    "last_check": utc_now_iso(),
                    "details": {
                        "delivery_errors": delivery_errors["count"],
                        "last_delivery_error": delivery_errors["last_error"],
                        "delivery_attempts_by_topic": metrics_data.get("delivery_attempts_by_topic", {}),
                        "delivery_failures_by_topic": metrics_data.get("delivery_failures_by_topic", {}),
                    },
                },
                {
                    "name": "persistence",
                    "status": "healthy" if metrics_data.get("persistence_status", {}).get("healthy") else "degraded",
                    "last_check": utc_now_iso(),
                    "details": metrics_data.get("persistence_status", {}),
                },
                {
                    "name": "api_auth",
                    "status": "healthy" if not AUTH_CONFIG.enabled or AUTH_CONFIG.tokens else "unhealthy",
                    "last_check": utc_now_iso(),
                    "details": {
                        "enabled": AUTH_CONFIG.enabled,
                        "token_count": len(AUTH_CONFIG.tokens),
                    },
                },
                {
                    "name": "replay",
                    "status": "degraded" if replay_snapshot["in_progress"] else "healthy",
                    "last_check": utc_now_iso(),
                    "details": replay_snapshot,
                },
            ],
        }
        if reasons:
            payload["reasons"] = reasons
        return (200 if is_healthy else 503), payload

    def _match_event(self, event: dict, params: dict) -> bool:
        q = (params.get("q", [""])[0] or "").strip().lower()
        if q:
            haystack = " ".join(str(event.get(field, "") or "") for field in (
                "id", "principal", "principal_normalized", "principal_type",
                "methodName", "resourceName", "authzResourceName",
                "resultStatus", "result_message", "cluster_id", "environment_id",
            )).lower()
            if q not in haystack:
                return False

        for field, param in (
            ("criticality", "criticality"),
            ("principal_normalized", "principal"),
            ("methodName", "method"),
            ("resourceName", "resource"),
        ):
            value = (params.get(param, [""])[0] or "").strip().lower()
            if value and value not in str(event.get(field, "") or "").lower():
                if field == "resourceName" and value not in str(event.get("authzResourceName", "") or "").lower():
                    return False
                if field != "resourceName":
                    return False
        return True

    def _limit_from_params(self, params: dict, default: int = 100) -> int:
        try:
            return max(1, min(int(params.get("limit", [str(default)])[0]), API_MAX_SEARCH_RESULTS))
        except ValueError:
            return default

    def _serialize_export_csv(self, rows: list[dict]) -> bytes:
        if not rows:
            return b""
        fieldnames = sorted({key for row in rows for key in row.keys()})
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode("utf-8")

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/metrics':
            # Get current metrics
            metrics_data = metrics.get_metrics()
            
            # Format metrics in Prometheus format
            prometheus_metrics = []
            prometheus_metrics.append(f"# HELP audit_forwarder_uptime_seconds Uptime of the forwarder in seconds")
            prometheus_metrics.append(f"# TYPE audit_forwarder_uptime_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_uptime_seconds {metrics_data['uptime_seconds']}")
            
            prometheus_metrics.append(f"# HELP audit_forwarder_processed_messages_total Total number of messages processed")
            prometheus_metrics.append(f"# TYPE audit_forwarder_processed_messages_total counter")
            prometheus_metrics.append(f"audit_forwarder_processed_messages_total {metrics_data['processed_messages_total']}")
            
            prometheus_metrics.append(f"# HELP audit_forwarder_processing_rate_per_second Rate of messages processed per second")
            prometheus_metrics.append(f"# TYPE audit_forwarder_processing_rate_per_second gauge")
            prometheus_metrics.append(f"audit_forwarder_processing_rate_per_second {metrics_data['processing_rate_per_second']}")
            
            prometheus_metrics.append(f"# HELP audit_forwarder_error_count_total Total number of processing errors")
            prometheus_metrics.append(f"# TYPE audit_forwarder_error_count_total counter")
            prometheus_metrics.append(f"audit_forwarder_error_count_total {metrics_data['error_count']}")
            
            prometheus_metrics.append(f"# HELP audit_forwarder_idle_seconds Seconds since last message was processed")
            prometheus_metrics.append(f"# TYPE audit_forwarder_idle_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_idle_seconds {metrics_data['idle_seconds']}")
            
            prometheus_metrics.append(f"# HELP audit_forwarder_consumer_lag_total Total consumer lag across all partitions")
            prometheus_metrics.append(f"# TYPE audit_forwarder_consumer_lag_total gauge")
            prometheus_metrics.append(f"audit_forwarder_consumer_lag_total {metrics_data['consumer_lag_total']}")
            
            # Add partition-specific lag metrics
            prometheus_metrics.append(f"# HELP audit_forwarder_consumer_lag Consumer lag by partition")
            prometheus_metrics.append(f"# TYPE audit_forwarder_consumer_lag gauge")
            for partition, lag in metrics_data['consumer_lag_by_partition'].items():
                prometheus_metrics.append(f"audit_forwarder_consumer_lag{{partition=\"{partition}\"}} {lag}")

            prometheus_metrics.append("# HELP audit_forwarder_offset_commits_total Successful offset commits")
            prometheus_metrics.append("# TYPE audit_forwarder_offset_commits_total counter")
            prometheus_metrics.append(f"audit_forwarder_offset_commits_total {metrics_data['offset_commits_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_offset_commit_failures_total Failed offset commits")
            prometheus_metrics.append("# TYPE audit_forwarder_offset_commit_failures_total counter")
            prometheus_metrics.append(f"audit_forwarder_offset_commit_failures_total {metrics_data['offset_commit_failures_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_rebalance_total Consumer rebalance callbacks")
            prometheus_metrics.append("# TYPE audit_forwarder_rebalance_total counter")
            prometheus_metrics.append(f"audit_forwarder_rebalance_total {metrics_data['rebalance_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_restart_total Forwarder startups recorded in persistence")
            prometheus_metrics.append("# TYPE audit_forwarder_restart_total counter")
            prometheus_metrics.append(f"audit_forwarder_restart_total {metrics_data['restart_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_parse_errors_total Parse errors")
            prometheus_metrics.append("# TYPE audit_forwarder_parse_errors_total counter")
            prometheus_metrics.append(f"audit_forwarder_parse_errors_total {metrics_data['parse_error_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_writes_total Successful persistence writes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_writes_total counter")
            prometheus_metrics.append(f"audit_forwarder_persistence_writes_total {metrics_data['persistence_write_success_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_failures_total Persistence write failures")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_failures_total counter")
            prometheus_metrics.append(f"audit_forwarder_persistence_failures_total {metrics_data['persistence_write_failures']}")

            prometheus_metrics.append("# HELP audit_forwarder_api_auth_failures_total API auth failures")
            prometheus_metrics.append("# TYPE audit_forwarder_api_auth_failures_total counter")
            prometheus_metrics.append(f"audit_forwarder_api_auth_failures_total {metrics_data['api_auth_failures_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_export_requests_total API export requests")
            prometheus_metrics.append("# TYPE audit_forwarder_export_requests_total counter")
            prometheus_metrics.append(f"audit_forwarder_export_requests_total {metrics_data['export_requests_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_export_denied_total Denied export requests")
            prometheus_metrics.append("# TYPE audit_forwarder_export_denied_total counter")
            prometheus_metrics.append(f"audit_forwarder_export_denied_total {metrics_data['export_denied_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_replay_runs_total Replay runs started")
            prometheus_metrics.append("# TYPE audit_forwarder_replay_runs_total counter")
            prometheus_metrics.append(f"audit_forwarder_replay_runs_total {metrics_data['replay_runs_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_replay_failures_total Replay failures")
            prometheus_metrics.append("# TYPE audit_forwarder_replay_failures_total counter")
            prometheus_metrics.append(f"audit_forwarder_replay_failures_total {metrics_data['replay_failures_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_replay_records_processed_total Replay records processed")
            prometheus_metrics.append("# TYPE audit_forwarder_replay_records_processed_total counter")
            prometheus_metrics.append(f"audit_forwarder_replay_records_processed_total {metrics_data['replay_records_processed_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_replay_in_progress Replay in-progress indicator")
            prometheus_metrics.append("# TYPE audit_forwarder_replay_in_progress gauge")
            prometheus_metrics.append(f"audit_forwarder_replay_in_progress {1 if metrics_data['replay_in_progress'] else 0}")

            prometheus_metrics.append("# HELP audit_forwarder_poll_count_total Kafka consume poll attempts")
            prometheus_metrics.append("# TYPE audit_forwarder_poll_count_total counter")
            prometheus_metrics.append(f"audit_forwarder_poll_count_total {metrics_data['poll_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_empty_poll_count_total Kafka consume polls that returned no records")
            prometheus_metrics.append("# TYPE audit_forwarder_empty_poll_count_total counter")
            prometheus_metrics.append(f"audit_forwarder_empty_poll_count_total {metrics_data['empty_poll_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_records_consumed_total Kafka records consumed before downstream processing")
            prometheus_metrics.append("# TYPE audit_forwarder_records_consumed_total counter")
            prometheus_metrics.append(f"audit_forwarder_records_consumed_total {metrics_data['records_consumed_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_retry_count_total Kafka retry/backoff attempts")
            prometheus_metrics.append("# TYPE audit_forwarder_retry_count_total counter")
            prometheus_metrics.append(f"audit_forwarder_retry_count_total {metrics_data['retry_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_consecutive_error_count Consecutive Kafka/runtime errors")
            prometheus_metrics.append("# TYPE audit_forwarder_consecutive_error_count gauge")
            prometheus_metrics.append(f"audit_forwarder_consecutive_error_count {metrics_data['consecutive_error_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_backoff_seconds Current Kafka/runtime backoff sleep")
            prometheus_metrics.append("# TYPE audit_forwarder_backoff_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_backoff_seconds {metrics_data['backoff_seconds']}")

            consumer_state_value = {"connected": 0, "idle": 0, "retrying": 1, "backoff": 2, "degraded": 3, "starting": 4}.get(metrics_data.get("consumer_state"), 4)
            prometheus_metrics.append("# HELP audit_forwarder_consumer_state Consumer state (0=connected_or_idle,1=retrying,2=backoff,3=degraded,4=starting)")
            prometheus_metrics.append("# TYPE audit_forwarder_consumer_state gauge")
            prometheus_metrics.append(f"audit_forwarder_consumer_state {consumer_state_value}")

            last_poll = metrics_data.get("last_successful_poll")
            last_poll_ts = int(datetime.fromisoformat(last_poll.replace('Z', '+00:00')).timestamp()) if last_poll else 0
            prometheus_metrics.append("# HELP audit_forwarder_last_successful_poll_timestamp_seconds Unix timestamp of last successful Kafka poll")
            prometheus_metrics.append("# TYPE audit_forwarder_last_successful_poll_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_last_successful_poll_timestamp_seconds {last_poll_ts}")

            prometheus_metrics.append("# HELP audit_forwarder_db_write_success_total Successful DB write batches")
            prometheus_metrics.append("# TYPE audit_forwarder_db_write_success_total counter")
            prometheus_metrics.append(f"audit_forwarder_db_write_success_total {metrics_data.get('db_write_success_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_db_write_error_total Failed DB write batches")
            prometheus_metrics.append("# TYPE audit_forwarder_db_write_error_total counter")
            prometheus_metrics.append(f"audit_forwarder_db_write_error_total {metrics_data.get('db_write_error_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_db_write_batch_size Last DB write batch size")
            prometheus_metrics.append("# TYPE audit_forwarder_db_write_batch_size gauge")
            prometheus_metrics.append(f"audit_forwarder_db_write_batch_size {metrics_data.get('db_write_batch_size', 0)}")

            db_state_value = {"disabled": 0, "connected": 1, "retrying": 2, "backoff": 3, "degraded": 3}.get(metrics_data.get("db_writer_state"), 0)
            prometheus_metrics.append("# HELP audit_forwarder_db_writer_state DB writer state (0=disabled,1=connected,2=retrying,3=backoff)")
            prometheus_metrics.append("# TYPE audit_forwarder_db_writer_state gauge")
            prometheus_metrics.append(f"audit_forwarder_db_writer_state {db_state_value}")

            last_db_write = metrics_data.get("db_last_successful_write")
            last_db_write_ts = int(datetime.fromisoformat(last_db_write.replace('Z', '+00:00')).timestamp()) if last_db_write else 0
            prometheus_metrics.append("# HELP audit_forwarder_db_last_successful_write_timestamp_seconds Unix timestamp of last successful DB write")
            prometheus_metrics.append("# TYPE audit_forwarder_db_last_successful_write_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_db_last_successful_write_timestamp_seconds {last_db_write_ts}")

            last_db_cleanup = metrics_data.get("db_last_cleanup_at")
            last_db_cleanup_ts = int(datetime.fromisoformat(last_db_cleanup.replace('Z', '+00:00')).timestamp()) if last_db_cleanup else 0
            prometheus_metrics.append("# HELP audit_forwarder_db_last_cleanup_timestamp_seconds Last successful DB retention cleanup timestamp")
            prometheus_metrics.append("# TYPE audit_forwarder_db_last_cleanup_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_db_last_cleanup_timestamp_seconds {last_db_cleanup_ts}")
            prometheus_metrics.append("# HELP audit_forwarder_db_last_cleanup_deleted_count Rows deleted by the last DB retention cleanup")
            prometheus_metrics.append("# TYPE audit_forwarder_db_last_cleanup_deleted_count gauge")
            prometheus_metrics.append(f"audit_forwarder_db_last_cleanup_deleted_count {metrics_data.get('db_last_cleanup_deleted_count', 0)}")
            prometheus_metrics.append("# HELP audit_forwarder_produce_retry_exhausted_total Produce retries exhausted before success")
            prometheus_metrics.append("# TYPE audit_forwarder_produce_retry_exhausted_total counter")
            prometheus_metrics.append(f"audit_forwarder_produce_retry_exhausted_total {metrics_data.get('produce_retry_exhausted_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_delivery_attempts_total Delivery attempts by topic")
            prometheus_metrics.append("# TYPE audit_forwarder_delivery_attempts_total counter")
            for topic, count in metrics_data['delivery_attempts_by_topic'].items():
                prometheus_metrics.append(f'audit_forwarder_delivery_attempts_total{{topic="{topic}"}} {count}')

            prometheus_metrics.append("# HELP audit_forwarder_delivery_failures_total Delivery failures by topic")
            prometheus_metrics.append("# TYPE audit_forwarder_delivery_failures_total counter")
            for topic, count in metrics_data['delivery_failures_by_topic'].items():
                prometheus_metrics.append(f'audit_forwarder_delivery_failures_total{{topic="{topic}"}} {count}')

            prometheus_metrics.append("# HELP audit_forwarder_delivery_success_total Successful deliveries by topic")
            prometheus_metrics.append("# TYPE audit_forwarder_delivery_success_total counter")
            for topic, count in metrics_data['delivery_success_by_topic'].items():
                prometheus_metrics.append(f'audit_forwarder_delivery_success_total{{topic="{topic}"}} {count}')

            prometheus_metrics.append("# HELP audit_forwarder_signal_total Signals emitted by type")
            prometheus_metrics.append("# TYPE audit_forwarder_signal_total counter")
            for signal_type, count in metrics_data['signal_counts'].items():
                prometheus_metrics.append(f'audit_forwarder_signal_total{{type="{signal_type}"}} {count}')

            prometheus_metrics.append("# HELP audit_forwarder_data_quality_total Data quality counters")
            prometheus_metrics.append("# TYPE audit_forwarder_data_quality_total counter")
            for metric_name, count in metrics_data['data_quality'].items():
                prometheus_metrics.append(f'audit_forwarder_data_quality_total{{metric="{metric_name}"}} {count}')

            persistence_status = metrics_data.get("persistence_status", {})
            prometheus_metrics.append("# HELP audit_forwarder_persistence_db_file_bytes SQLite DB file size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_db_file_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_db_file_bytes {persistence_status.get('db_file_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_storage_db_size_bytes SQLite hot-cache DB plus WAL size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_storage_db_size_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_storage_db_size_bytes {persistence_status.get('current_db_size', persistence_status.get('db_file_bytes', 0))}")

            storage_mode_value = {"normal": 0, "warning": 1, "critical": 2, "emergency": 3}.get(persistence_status.get('storage_mode', 'normal'), 0)
            prometheus_metrics.append("# HELP audit_forwarder_storage_mode SQLite storage mode (0=normal,1=warning,2=critical,3=emergency)")
            prometheus_metrics.append("# TYPE audit_forwarder_storage_mode gauge")
            prometheus_metrics.append(f"audit_forwarder_storage_mode {storage_mode_value}")

            prometheus_metrics.append("# HELP audit_forwarder_rotation_total SQLite hot-cache rotations completed")
            prometheus_metrics.append("# TYPE audit_forwarder_rotation_total counter")
            prometheus_metrics.append(f"audit_forwarder_rotation_total {persistence_status.get('rotation_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_rotation_duration_ms Last SQLite hot-cache rotation duration in milliseconds")
            prometheus_metrics.append("# TYPE audit_forwarder_rotation_duration_ms gauge")
            prometheus_metrics.append(f"audit_forwarder_rotation_duration_ms {persistence_status.get('rotation_duration_ms', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_storage_write_dropped_total Low-priority persistence writes dropped by storage guard")
            prometheus_metrics.append("# TYPE audit_forwarder_storage_write_dropped_total counter")
            prometheus_metrics.append(f"audit_forwarder_storage_write_dropped_total {persistence_status.get('storage_write_dropped_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_wal_file_bytes SQLite WAL file size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_wal_file_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_wal_file_bytes {persistence_status.get('wal_file_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_free_disk_bytes Free disk bytes for the persistence path")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_free_disk_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_free_disk_bytes {persistence_status.get('free_disk_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_db_max_bytes Configured maximum SQLite DB size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_db_max_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_db_max_bytes {persistence_status.get('db_max_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_wal_max_bytes Configured maximum SQLite WAL size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_wal_max_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_wal_max_bytes {persistence_status.get('wal_max_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_free_disk_warning_bytes Warning threshold for free disk bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_free_disk_warning_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_free_disk_warning_bytes {persistence_status.get('free_disk_warning_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_free_disk_critical_bytes Critical threshold for free disk bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_free_disk_critical_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_free_disk_critical_bytes {persistence_status.get('free_disk_critical_bytes', 0)}")

            storage_status_value = {"ok": 0, "warning": 1, "critical": 2}.get(persistence_status.get('storage_status', 'ok'), 0)
            prometheus_metrics.append("# HELP audit_forwarder_persistence_storage_status SQLite storage status (0=ok,1=warning,2=critical)")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_storage_status gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_storage_status {storage_status_value}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_last_cleanup_deleted_rows Rows deleted by the last persistence cleanup")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_last_cleanup_deleted_rows gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_last_cleanup_deleted_rows {persistence_status.get('last_cleanup_deleted_rows', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_size_cleanup_deleted_rows_total Rows deleted by the last size-pressure cleanup")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_size_cleanup_deleted_rows_total gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_size_cleanup_deleted_rows_total {persistence_status.get('last_cleanup_size_deleted_rows', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_sqlite_reclaimable_bytes SQLite bytes that can be reclaimed by successful VACUUM")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_sqlite_reclaimable_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_sqlite_reclaimable_bytes {persistence_status.get('sqlite_reclaimable_bytes', 0)}")

            cleanup_strategy = str(persistence_status.get('last_cleanup_strategy') or 'none').replace('\\', '\\\\').replace('"', '\\"')
            prometheus_metrics.append("# HELP audit_forwarder_persistence_cleanup_strategy Last persistence cleanup strategy as an info-style metric")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_cleanup_strategy gauge")
            prometheus_metrics.append(f'audit_forwarder_persistence_cleanup_strategy{{strategy="{cleanup_strategy}"}} 1')

            configured_retention_hours = {
                "enriched_events": PERSISTENCE_CONFIG.enriched_retention_days * 24,
                "high_risk_events": PERSISTENCE_CONFIG.signals_retention_days * 24,
                "denial_summaries": PERSISTENCE_CONFIG.signals_retention_days * 24,
                "alerts": PERSISTENCE_CONFIG.alerts_retention_days * 24,
                "api_audit_log": PERSISTENCE_CONFIG.audit_retention_days * 24,
            }
            effective_retention_hours = persistence_status.get('effective_retention_hours') or {}
            adaptive_limited = 0
            prometheus_metrics.append("# HELP audit_forwarder_persistence_effective_retention_hours Effective SQLite retention window after adaptive size pressure")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_effective_retention_hours gauge")
            for table, configured_hours in configured_retention_hours.items():
                effective_hours = int(effective_retention_hours.get(table, configured_hours))
                if effective_hours < configured_hours:
                    adaptive_limited = 1
                prometheus_metrics.append(
                    f'audit_forwarder_persistence_effective_retention_hours{{table="{table}"}} {effective_hours}'
                )

            prometheus_metrics.append("# HELP audit_forwarder_persistence_adaptive_retention_limited Whether adaptive retention shortened any table below configured retention")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_adaptive_retention_limited gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_adaptive_retention_limited {adaptive_limited}")

            cleanup_at = persistence_status.get('last_cleanup_at')
            cleanup_ts = int(datetime.fromisoformat(cleanup_at.replace('Z', '+00:00')).timestamp()) if cleanup_at else 0
            prometheus_metrics.append("# HELP audit_forwarder_persistence_last_cleanup_timestamp_seconds Unix timestamp of the last persistence cleanup")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_last_cleanup_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_last_cleanup_timestamp_seconds {cleanup_ts}")

            cleanup_status_value = persistence_status.get('cleanup_status')
            cleanup_status = 0 if cleanup_status_value == 'failure' else 1
            prometheus_metrics.append("# HELP audit_forwarder_persistence_cleanup_status Persistence cleanup health status (1=healthy or not yet failed)")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_cleanup_status gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_cleanup_status {cleanup_status}")

            checkpoint_at = persistence_status.get('last_checkpoint_at')
            checkpoint_ts = int(datetime.fromisoformat(checkpoint_at.replace('Z', '+00:00')).timestamp()) if checkpoint_at else 0
            prometheus_metrics.append("# HELP audit_forwarder_persistence_last_checkpoint_timestamp_seconds Unix timestamp of the last WAL checkpoint")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_last_checkpoint_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_last_checkpoint_timestamp_seconds {checkpoint_ts}")

            checkpoint_status = 1 if persistence_status.get('last_checkpoint_status') == 'success' else 0
            prometheus_metrics.append("# HELP audit_forwarder_persistence_checkpoint_status WAL checkpoint success status (1=success)")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_checkpoint_status gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_checkpoint_status {checkpoint_status}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_checkpoint_busy SQLite WAL checkpoint busy flag")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_checkpoint_busy gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_checkpoint_busy {persistence_status.get('last_checkpoint_busy', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_checkpoint_log_frames SQLite WAL frames seen at last checkpoint")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_checkpoint_log_frames gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_checkpoint_log_frames {persistence_status.get('last_checkpoint_log_frames', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_checkpointed_frames SQLite WAL frames checkpointed at last checkpoint")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_checkpointed_frames gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_checkpointed_frames {persistence_status.get('last_checkpoint_checkpointed_frames', 0)}")

            # Add audit event metrics
            prometheus_metrics.append("")
            prometheus_metrics.append(audit_event_metrics.format_prometheus())

            response = "\n".join(prometheus_metrics)
            
            self._send_bytes(200, 'text/plain', response.encode())
        elif parsed.path in {'/health', '/api/v1/health'}:
            if parsed.path == '/api/v1/health':
                actor = self._authorize_request(parsed.path, params, export=False)
                if actor is None:
                    return
                status_code, payload = self._health_payload()
                self._record_api_audit(actor, "health", parsed.path, status_code, {})
                self._send_json(status_code, payload)
            else:
                status_code, payload = self._health_payload()
                self._send_json(status_code, payload)
        elif parsed.path == '/api/v1/events/search':
            actor = self._authorize_request(parsed.path, params, export=False)
            if actor is None:
                return
            filters = _request_filters(params)
            matches, source = self._search_records(filters, actor, self._limit_from_params(params))
            payload = {
                "items": matches,
                "count": len(matches),
                "coverage_note": "search served from durable persistence" if source == "persistence" else api_state.snapshot()["coverage_note"],
                "source": source,
            }
            self._record_api_audit(actor, "search", parsed.path, 200, filters)
            self._send_json(200, payload)
        elif parsed.path == '/api/v1/events/high-risk':
            actor = self._authorize_request(parsed.path, params, export=False)
            if actor is None:
                return
            filters = _request_filters(params)
            matches, source = self._high_risk_records(filters, actor, self._limit_from_params(params, default=50))
            self._send_json(200, {
                "items": matches,
                "count": len(matches),
                "coverage_note": "high-risk search served from durable persistence" if source == "persistence" else api_state.snapshot()["coverage_note"],
                "source": source,
            })
            self._record_api_audit(actor, "list_high_risk", parsed.path, 200, filters)
        elif parsed.path == '/api/v1/signals/denials':
            actor = self._authorize_request(parsed.path, params, export=False)
            if actor is None:
                return
            limit = self._limit_from_params(params, default=50)
            items, source = self._denial_records(actor, limit)
            self._send_json(200, {
                "items": items,
                "count": len(items),
                "coverage_note": "denial summaries served from durable persistence" if source == "persistence" else api_state.snapshot()["coverage_note"],
                "source": source,
            })
            self._record_api_audit(actor, "list_denials", parsed.path, 200, {})
        elif parsed.path == '/api/v1/export':
            actor = self._authorize_request(parsed.path, params, export=True)
            if actor is None:
                return
            filters = _request_filters(params)
            valid_export_window, export_error = self._validate_export_window(filters)
            if not valid_export_window:
                metrics.record_export_denied()
                self._record_api_audit(actor, "export", parsed.path, 403, filters, export_error)
                self._json_error(403, export_error or "invalid export window")
                return
            rows, source = self._search_records(filters, actor, min(self._limit_from_params(params, default=1000), API_EXPORT_MAX_ROWS))
            metrics.record_export_request()
            export_format = (params.get("format", ["json"])[0] or "json").lower()
            export_headers = {
                "X-AuditLens-Source": source,
                "X-AuditLens-Last-Enriched-At": api_state.snapshot().get("last_enriched_ingest_at") or "",
                "X-AuditLens-Partial-Data": "false" if source == "persistence" else "true",
            }
            if export_format == "csv":
                self._record_api_audit(actor, "export", parsed.path, 200, filters)
                self._send_bytes(200, "text/csv", self._serialize_export_csv(rows), headers=export_headers)
            elif export_format == "jsonl":
                self._record_api_audit(actor, "export", parsed.path, 200, filters)
                payload = "\n".join(orjson.dumps(row).decode("utf-8") for row in rows).encode("utf-8")
                self._send_bytes(200, "application/x-ndjson", payload, headers=export_headers)
            else:
                self._record_api_audit(actor, "export", parsed.path, 200, filters)
                self._send_json(200, {
                    "metadata": {
                        "partial_data": source != "persistence",
                        "freshness_timestamp": api_state.snapshot().get("last_enriched_ingest_at"),
                        "source": source,
                    },
                    "items": rows,
                    "count": len(rows),
                    "exported_at": utc_now_iso(),
                    "coverage_note": "export served from durable persistence" if source == "persistence" else api_state.snapshot()["coverage_note"],
                    "source": source,
                }, headers=export_headers)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = orjson.loads(raw_body) if raw_body else {}
        except orjson.JSONDecodeError:
            self._json_error(400, "invalid json body")
            return

        if parsed.path == "/api/v1/replay":
            actor = self._authorize_request(parsed.path, {}, export=False)
            if actor is None:
                return
            if actor.role != Role.ADMIN:
                self._record_api_audit(actor, "replay", parsed.path, 403, body, "admin access required")
                self._json_error(403, "admin access required")
                return
            if replay_state.snapshot()["in_progress"]:
                self._record_api_audit(actor, "replay", parsed.path, 409, body, "replay already in progress")
                self._json_error(409, "replay already in progress")
                return

            source_mode = body.get("source_mode", "raw")
            from_earliest = bool(body.get("from_earliest", False))
            hours = body.get("hours")
            if hours is not None:
                hours = int(hours)
            publish_topics = bool(body.get("publish_topics", REPLAY_PUBLISH_DERIVED_TOPICS))

            def _runner():
                try:
                    replay_events(
                        source_mode=source_mode,
                        hours=hours,
                        from_earliest=from_earliest,
                        publish_topics=publish_topics,
                    )
                except Exception:
                    logger.exception("Replay background operation failed")

            thread = threading.Thread(target=_runner, daemon=True, name="auditlens-replay")
            thread.start()
            self._record_api_audit(actor, "replay", parsed.path, 202, body)
            self._send_json(202, {
                "status": "accepted",
                "source_mode": source_mode,
                "from_earliest": from_earliest,
                "hours": hours,
                "publish_topics": publish_topics,
                "replay_state": replay_state.snapshot(),
            })
            return

        if parsed.path == "/admin/vacuum":
            actor = self._authorize_request(parsed.path, {}, export=False)
            if actor is None:
                return
            if actor.role != Role.ADMIN:
                self._record_api_audit(actor, "vacuum", parsed.path, 403, body, "admin access required")
                self._json_error(403, "admin access required")
                return
            if not (product_store and PERSISTENCE_CONFIG.enabled):
                self._record_api_audit(actor, "vacuum", parsed.path, 503, body, "persistence disabled")
                self._json_error(503, "persistence disabled")
                return
            try:
                result = product_store.vacuum()
            except Exception as exc:
                logger.exception("VACUUM via /admin/vacuum failed")
                self._record_api_audit(actor, "vacuum", parsed.path, 500, body, str(exc))
                self._json_error(500, f"vacuum failed: {exc}")
                return
            status_code = 200 if result.get("status") == "success" else 500
            self._record_api_audit(actor, "vacuum", parsed.path, status_code, body)
            self._send_json(status_code, result)
            return

        self.send_response(404)
        self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress HTTP server logs to avoid cluttering the output
        pass

def start_metrics_server(port=METRICS_PORT):
    """Start metrics server in a separate thread"""
    server = HTTPServer(('0.0.0.0', port), MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Metrics server started on port {port}")
    return server


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

# ──────────── flatten helpers ────────────
def _to_scalar(value):
    """Convert principal object to scalar resourceId."""
    if isinstance(value, dict):
        for k in ("confluentServiceAccount", "confluentUser", "identityPool", "group"):
            if k in value and isinstance(value[k], dict):
                rid = value[k].get("resourceId")
                if rid:
                    return rid
        return orjson.dumps(value).decode('utf-8')
    if isinstance(value, list):
        return orjson.dumps(value).decode('utf-8')
    return value

def _extract_email(principal_obj):
    """Extract email from principal object if present."""
    if not principal_obj or not isinstance(principal_obj, dict):
        return None
    # Direct email field
    if 'email' in principal_obj:
        return principal_obj['email']
    # Check nested structures
    for k in ("confluentServiceAccount", "confluentUser"):
        if k in principal_obj and isinstance(principal_obj[k], dict):
            if 'email' in principal_obj[k]:
                return principal_obj[k]['email']
    return None

def _extract_client_ip(data):
    """Extract client IP from various possible locations in the audit event."""
    # Primary: clientAddress array
    addr = data.get("clientAddress", [])
    if addr and isinstance(addr, list) and len(addr) > 0:
        ip = addr[0].get("ip")
        if ip:
            return ip

    # Fallback: requestMetadata.clientAddress
    meta = data.get("requestMetadata", {})
    if isinstance(meta, dict):
        meta_addr = meta.get("clientAddress", [])
        if meta_addr and isinstance(meta_addr, list) and len(meta_addr) > 0:
            ip = meta_addr[0].get("ip")
            if ip:
                return ip

    # Fallback: authorizationInfo.requestMetadata.clientAddress
    authz = data.get("authorizationInfo", {})
    if isinstance(authz, dict):
        authz_meta = authz.get("requestMetadata", {})
        if isinstance(authz_meta, dict):
            authz_addr = authz_meta.get("clientAddress", [])
            if authz_addr and isinstance(authz_addr, list) and len(authz_addr) > 0:
                ip = authz_addr[0].get("ip")
                if ip:
                    return ip

    return None

def flatten_audit(event):
    out = {
        "id":             event.get("id"),
        "specversion":    event.get("specversion"),
        "source":         event.get("source"),
        "subject":        event.get("subject"),
        "type":           event.get("type"),
        "time":           event.get("time"),
        "datacontenttype":event.get("datacontenttype")
    }
    data = event.get("data", {})
    out["serviceName"]         = data.get("serviceName")
    out["methodName"]          = data.get("methodName")
    out["resourceName"]        = data.get("resourceName")

    authn = data.get("authenticationInfo", {})
    principal_obj = authn.get("principal")
    principal_raw = _to_scalar(principal_obj)
    principal_normalized, principal_type = normalize_with_type(principal_raw)
    out["principal"]           = principal_raw
    out["principal_raw"]       = principal_raw
    out["principal_normalized"] = principal_normalized
    out["principal_type"]      = principal_type
    out["principalResourceId"] = authn.get("principalResourceId")
    out["identity"]            = authn.get("identity")
    out["email"]               = _extract_email(principal_obj)
    authn_meta = authn.get("metadata", {})
    out["auth_mechanism"]      = authn_meta.get("mechanism")
    out["auth_identifier"]     = authn_meta.get("identifier")

    authz = data.get("authorizationInfo", {})
    out["granted"]             = authz.get("granted")
    out["operation"]           = authz.get("operation")
    out["resourceType"]        = authz.get("resourceType")
    out["authzResourceName"]   = authz.get("resourceName")
    out["patternType"]         = authz.get("patternType")

    rbac = authz.get("rbacAuthorization", {})
    out["rbacRole"]            = rbac.get("role")
    scope = rbac.get("scope", {}).get("outerScope", [])
    out["rbacScope"]           = scope[0] if scope else None

    acl = authz.get("aclAuthorization", {})
    out["aclPermissionType"]   = acl.get("permissionType")
    out["aclHost"]             = acl.get("host")

    req = data.get("request", {})
    out["correlationId"]       = req.get("correlationId")
    out["correlation_id"]      = req.get("correlation_id")

    meta = data.get("requestMetadata", {})
    out["requestId"]           = meta.get("request_id") or meta.get("requestId")
    out["connectionId"]        = meta.get("connection_id") or meta.get("connectionId")
    out["network_id"]          = meta.get("network_id") or meta.get("networkId")

    # clientId can be in request.clientId OR requestMetadata.clientId (kafka.Fetch/Produce events)
    out["clientId"] = req.get("clientId") or req.get("client_id") or meta.get("clientId") or meta.get("client_id")

    # Extract client IP from multiple possible locations
    out["clientIp"] = _extract_client_ip(data)

    out["data_json"] = orjson.dumps(data).decode('utf-8')

    # ──────────── Computed fields for criticality and classification ────────────
    # Get result status from result.status
    result = data.get("result", {})
    result_status = result.get("status") if isinstance(result, dict) else None
    out["result_message"] = result.get("message") if isinstance(result, dict) else None

    # Use the modular classification system
    classification_result = calculate_criticality(out)
    out["criticality"] = classification_result.criticality.value
    out["classification_reason"] = classification_result.reason
    out["criticality_elevated"] = classification_result.elevated
    out["method_category"] = classification_result.method_category
    out["is_security_event"] = classification_result.is_security_event

    # Boolean classification flags
    method_name = out.get("methodName", "") or ""
    out["is_deletion"] = "Delete" in method_name
    out["is_creation"] = "Create" in method_name
    out["is_modification"] = any(op in method_name for op in ("Update", "Alter"))

    # Extract IDs from CRN fields (source, resourceName, subject)
    # mds.Authorize events have minimal source but full resourceName/subject
    source = out.get("source", "")
    resource_name = out.get("resourceName", "")
    subject = out.get("subject", "")

    # Try source first, then resourceName, then subject
    out["organization_id"] = (
        extract_from_crn(source, "organization") or
        extract_from_crn(resource_name, "organization") or
        extract_from_crn(subject, "organization")
    )
    out["environment_id"] = (
        extract_from_crn(source, "environment") or
        extract_from_crn(resource_name, "environment") or
        extract_from_crn(subject, "environment")
    )
    out["cluster_id"] = (
        extract_from_crn(source, "kafka") or
        extract_from_crn(source, "schema-registry") or
        extract_from_crn(source, "ksqldb") or
        extract_from_crn(source, "flink") or
        extract_from_crn(resource_name, "kafka") or
        extract_from_crn(resource_name, "schema-registry") or
        extract_from_crn(resource_name, "ksqldb") or
        extract_from_crn(resource_name, "flink") or
        extract_from_crn(subject, "kafka") or
        extract_from_crn(subject, "schema-registry") or
        extract_from_crn(subject, "ksqldb") or
        extract_from_crn(subject, "flink")
    )

    # Store result status for reference
    out["resultStatus"] = result_status
    metrics.record_data_quality(out, classification_result)

    return out

# ──────────── delivery callback ────────────
delivery_errors = {"count": 0, "last_error": None}
dlq_stats = {"sent": 0, "failed": 0}

def delivery_callback(err, msg):
    """Track delivery errors."""
    if err:
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
            "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "forwarder_version": VERSION,
        }
        producer.produce(
            DLQ_TOPIC,
            key=f"{source_topic}-{partition}-{offset}".encode('utf-8'),
            value=orjson.dumps(dlq_event),
            callback=lambda err, msg: dlq_stats.update({"sent": dlq_stats["sent"] + 1}) if not err else dlq_stats.update({"failed": dlq_stats["failed"] + 1})
        )
        dlq_stats["sent"] += 1
    except Exception as e:
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
    global db_writer
    if not ENABLE_DB_WRITER:
        metrics.set_db_writer_state("disabled")
        return None
    if db_writer is not None:
        return db_writer
    metrics.set_db_writer_state("retrying")
    db_writer = AuditEventDbWriter(
        DATABASE_URL,
        retention_days=EVENT_RETENTION_DAYS,
        retention_cleanup_interval_seconds=DB_RETENTION_CLEANUP_INTERVAL_SECONDS,
    )
    metrics.set_db_writer_state("connected")
    logger.info("DB writer enabled: mode=%s", db_writer.mode)
    return db_writer


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
        # Pass defer_catalog only when set so older test doubles whose
        # write_batch signature predates the kwarg keep working.
        if defer_catalog:
            result = writer.write_batch(payloads, defer_catalog=True)
        else:
            result = writer.write_batch(payloads)
        metrics.record_db_write_success(result.attempted)
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
            futures = [executor.submit(flush_db_writer_batch, list(chunk), backoff, log_state) for chunk in chunks]
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
    try:
        product_store = SQLiteProductStore(PERSISTENCE_CONFIG)
        product_store.initialize()
        product_store.enforce_storage_bounds(trigger="startup")
        metrics.record_persistence_success(product_store.health())
        metrics.set_restart_count(product_store.health().get("startup_count", 0))
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
    updated["is_deletion"] = "Delete" in method_name
    updated["is_creation"] = "Create" in method_name
    updated["is_modification"] = any(op in method_name for op in ("Update", "Alter"))
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
def main():
    global db_writer
    logger.info("=" * 70)
    logger.info("AuditLens Foundation Forwarder")
    logger.info(f"Version: {VERSION}")
    logger.info("Mode: Kafka-native foundation pipeline")
    logger.info("=" * 70)

    startup_config = validate_startup_config()
    if not startup_config["valid"]:
        logger.error("Startup validation failed: %s", mask_config_for_logging(startup_config))
        sys.exit(1)
    logger.info("Startup configuration validated successfully")

    initialize_product_store_or_exit()
    start_storage_monitor()
    if ENABLE_DB_WRITER:
        try:
            initialize_db_writer_if_enabled()
        except Exception as exc:
            db_writer = None
            masked_exc = mask_sensitive_text(str(exc))
            metrics.record_db_write_error(masked_exc, 0)
            logger.warning("DB writer enabled but initial connection failed; will retry in processing loop: %s", masked_exc)
    else:
        metrics.set_db_writer_state("disabled")

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

    # Create clients. Hook the librdkafka stats callback so per-partition
    # consumer_lag flows in via stats.json, not synchronous watermark polls.
    consumer_conf_with_stats = dict(consumer_conf)
    consumer_conf_with_stats["stats_cb"] = make_rdkafka_stats_callback(metrics)
    consumer = Consumer(consumer_conf_with_stats)
    producer = Producer(producer_conf)

    # Start metrics server
    metrics_server = start_metrics_server(METRICS_PORT)

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

    # Load schema (optional - only if Schema Registry is configured)
    json_serializer = None
    if SCHEMA_REGISTRY_URL:
        try:
            sr = SchemaRegistryClient({
                "url": SCHEMA_REGISTRY_URL,
                "basic.auth.user.info": f"{SCHEMA_REGISTRY_KEY}:{SCHEMA_REGISTRY_SECRET}"
            })
            subject = f"{AUDIT_ENRICHED_TOPIC}-value"
            meta = sr.get_latest_version(subject)
            json_serializer = JSONSerializer(
                meta.schema.schema_str, sr,
                to_dict=None,
                conf={"auto.register.schemas": False}
            )
            logger.info("Loaded schema v%d for %s", meta.version, subject)
        except Exception as e:
            logger.error("Schema Registry load failed (continuing without Schema Registry): %s", e)
            record_schema_registry_failure()
            json_serializer = None
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
    RECORD_QUEUE_SIZE = max(1, int(os.getenv("RECORD_QUEUE_SIZE", "20")))
    record_queue: queue.Queue = queue.Queue(maxsize=RECORD_QUEUE_SIZE)
    metrics.record_queue_capacity = RECORD_QUEUE_SIZE
    consumer_log_state: dict = {}
    consumer_backoff = RuntimeBackoff()

    # Priority routing — only used when DB writer is enabled. Sized so the
    # critical lane stays small (drains fast), normal lane is moderate, and
    # bulk lane absorbs noise without blocking the producer.
    PRIORITY_QUEUES_ENABLED = ENABLE_DB_WRITER
    if PRIORITY_QUEUES_ENABLED:
        critical_queue: queue.Queue = queue.Queue(
            maxsize=max(100, int(os.getenv("PRIORITY_QUEUE_CRITICAL_MAX", "1000")))
        )
        normal_queue: queue.Queue = queue.Queue(
            maxsize=max(500, int(os.getenv("PRIORITY_QUEUE_NORMAL_MAX", "5000")))
        )
        bulk_queue: queue.Queue = queue.Queue(
            maxsize=max(5000, int(os.getenv("PRIORITY_QUEUE_BULK_MAX", "50000")))
        )
        catalog_queue: queue.Queue = queue.Queue(
            maxsize=max(1000, int(os.getenv("PRIORITY_QUEUE_CATALOG_MAX", "10000")))
        )
    else:
        critical_queue = normal_queue = bulk_queue = catalog_queue = None

    def _route_to_queue(enriched_event: dict) -> None:
        """Fast routing — pick the priority lane based on methodName.

        Critical+High methods → critical_queue (small batches, < 0.1s wait).
        Read-only / authentication / authz checks → bulk_queue (huge batches).
        Everything else → normal_queue (medium batches).
        """
        if not PRIORITY_QUEUES_ENABLED:
            return
        method = enriched_event.get("methodName") or enriched_event.get("method") or ""
        if method in CRITICAL_METHODS or method in HIGH_METHODS:
            target, target_name = critical_queue, "critical"
        elif (
            method in READ_ONLY_METHODS
            or method in AUTHENTICATION_METHODS
            or method in AUTHORIZATION_CHECK_METHODS
        ):
            target, target_name = bulk_queue, "bulk"
        else:
            target, target_name = normal_queue, "normal"
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

    def _consume_thread() -> None:
        """Thread A: poll Kafka and queue batches. Never processes events."""
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
            try:
                record_queue.put(batch_local, timeout=5.0)
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
                    record_queue.put(batch_local, timeout=30.0)
                    metrics.record_queue_depth = record_queue.qsize()
                except queue.Full:
                    logger.error(
                        "record_queue still full after backpressure — dropping batch of %d",
                        len(batch_local),
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
                batch = record_queue.get(timeout=1.0)
            except queue.Empty:
                if _shutdown_requested and record_queue.empty():
                    break
                # Still run the maintenance ticks even when idle.
                now = time.time()
                _run_periodic_maintenance(now)
                continue
            metrics.record_queue_depth = record_queue.qsize()
            if batch is None:
                # Shutdown sentinel from consumer thread.
                break
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
                    normalized_event = build_normalized_event(flat)
                    enriched_event = build_enriched_event(flat)
                    event_key = enriched_event.get('id', '').encode('utf-8') if enriched_event.get('id') else None

                    if product_store:
                        persist_safely(
                            "enriched_event",
                            product_store.persist_enriched_event,
                            enriched_event, msg.topic(), msg.partition(), msg.offset(),
                        )
                        metrics.record_persistence_success(product_store.health())
                    if ENABLE_DB_WRITER:
                        # Route into the priority lane based on methodName
                        # (critical / normal / bulk). Writer threads drain
                        # each queue into Postgres asynchronously; we no
                        # longer block this batch on the DB write. Events
                        # remain durable in the audit Kafka topics, so a
                        # crash between offset-commit and async-write is
                        # recoverable via replay.
                        _route_to_queue(enriched_event)

                    safe_produce(producer, AUDIT_NORMALIZED_TOPIC, event_key, orjson.dumps(normalized_event))
                    safe_produce(producer, AUDIT_ENRICHED_TOPIC, event_key, orjson.dumps(enriched_event))
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
                                metrics.record_persistence_success(product_store.health())

                    # Send alert for built-in alert rules or CRITICAL events
                    if webhook_sender.enabled and ENABLE_BUILTIN_ALERTS:
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
                            metrics.record_persistence_success(product_store.health())
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
                            metrics.record_persistence_success(product_store.health())

                    if ENABLE_MULTI_TOPIC_ROUTING and topic_router:
                        topic_router.route_event(enriched_event)

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

            if not should_commit:
                # Some messages failed to deliver - do NOT commit offsets
                # These events will be reprocessed on restart
                logger.error("Batch not committed: %s", commit_details)
                metrics.record_commit_failure()
            elif not batch_max_offsets:
                # No successfully-processed messages in this batch (everything
                # was a parse error / consume error). Nothing to commit.
                metrics.record_commit_success()
            else:
                # All messages delivered - safe to commit offsets.
                # Build explicit TopicPartitions: librdkafka's auto-offset-store
                # is unreliable when consume() and commit() run in different
                # threads. Commit offset = max processed + 1 per partition.
                offsets_to_commit = [
                    TopicPartition(t, p, offset + 1)
                    for (t, p), offset in batch_max_offsets.items()
                ]
                try:
                    consumer.commit(offsets=offsets_to_commit, asynchronous=False)
                    metrics.record_commit_success()
                    logger.debug("Batch committed: %d events across %d partitions",
                                 batch_size, len(offsets_to_commit))
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
        nonlocal last_heartbeat, last_lag_ts
        if now - last_heartbeat >= 30:
            _refresh_queue_depths()
            logger.info(
                "Forwarder is alive at %s. Processed: %d, Errors: %d, Delivery failures: %d, "
                "DLQ: %d sent/%d failed, queue=%d/%d, lanes critical=%d normal=%d bulk=%d catalog=%d",
                time.ctime(), metrics.processed_total, metrics.error_count, delivery_errors["count"],
                dlq_stats["sent"], dlq_stats["failed"],
                record_queue.qsize(), RECORD_QUEUE_SIZE,
                metrics.critical_queue_depth, metrics.normal_queue_depth,
                metrics.bulk_queue_depth, metrics.catalog_queue_depth,
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
        if processor_thread.is_alive():
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
    parser = argparse.ArgumentParser(description="AuditLens foundation runtime")
    subparsers = parser.add_subparsers(dest="command")

    replay_parser = subparsers.add_parser("replay", help="Rebuild durable state from Kafka")
    replay_parser.add_argument("--source-mode", choices=["raw", "enriched"], default="raw")
    replay_parser.add_argument("--hours", type=int, default=None, help="Replay last N hours")
    replay_parser.add_argument("--from-earliest", action="store_true", help="Replay from earliest offset")
    replay_parser.add_argument("--publish-topics", action="store_true", help="Republish rebuilt signals/alerts to Kafka topics")

    args = parser.parse_args(argv)
    if args.command != "replay":
        main()
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
