"""Forwarder runtime configuration — all module-level constants derived from env."""

import os
from pathlib import Path
from dotenv import load_dotenv

from src.product import AuthConfig, PersistenceConfig


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

# Short-circuit bulk-noise events (mds.Authorize, kafka.Fetch, kafka.Produce, …)
# at the consume point — they go straight to the bulk writer, bypassing
# flatten_audit, the seven canonical Kafka produces, anomaly tracking, and
# the SQLite hot cache. Saves the processor thread from doing ~83% of its
# work. Disable for debugging if the full pipeline is needed for every event.
ENABLE_NOISE_SHORT_CIRCUIT = os.getenv("ENABLE_NOISE_SHORT_CIRCUIT", "true").lower() == "true"
# How long the processor will wait for the bulk writer to persist
# short-circuited noise events before declining to commit. Bulk writes
# normally complete in tens of milliseconds — this is a defensive ceiling.
NOISE_PERSIST_WAIT_TIMEOUT_SECONDS = float(os.getenv("NOISE_PERSIST_WAIT_TIMEOUT_SECONDS", "60.0"))

AUTH_CONFIG = AuthConfig.from_env()
PERSISTENCE_CONFIG = PersistenceConfig.from_env()

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

# Gate the legacy SLACK_WEBHOOK firing path now that the configurable
# notifications layer (notifications.yml) is the supported way forward.
#   auto   → disabled when notifications.yml provides destinations
#   true   → always enable (backward compatibility)
#   false  → always disable (notifier-only)
LEGACY_WEBHOOK_ENABLED = os.getenv("ENABLE_LEGACY_SLACK_WEBHOOK", "auto").lower()

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
