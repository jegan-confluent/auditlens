#!/usr/bin/env python3
"""
Confluent Audit Log Intelligence System - Main Forwarder v8.0

This forwarder:
1. Consumes events from Confluent Cloud audit log topic
2. Flattens and enriches events with criticality classification
3. Tracks events for anomaly detection
4. Records metrics for Prometheus exposition
5. Produces flattened events to destination topic
6. Routes to multi-topic architecture based on criticality
7. Sends real-time alerts for CRITICAL events
"""

# Version - read from VERSION file for consistency across all modules
from pathlib import Path as _VersionPath
_version_file = _VersionPath(__file__).parent / "VERSION"
VERSION = _version_file.read_text().strip() if _version_file.exists() else "2.1.0"

import os
import sys
import signal
import orjson
import logging
import time
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from dotenv import load_dotenv
from confluent_kafka import Consumer, Producer, TopicPartition, KafkaError
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.json_schema import JSONSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

# Import our intelligence modules
from src.metrics.audit_events import (
    audit_event_metrics,
    record_event_metrics,
    record_anomaly_metrics,
    record_routing_metrics,
    record_schema_registry_failure,
)
from src.classification import calculate_criticality, CriticalityLevel
from src.anomaly import RateTracker, RateTrackerConfig
from src.routing import TopicRouter, RouterConfig
from src.alerting import get_webhook_sender
from src.aggregation import DenialAggregator, AggregatorConfig

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
DEST_TOPIC             = os.getenv("DEST_TOPIC", "jegan_auditlog")
AUDIT_TOPIC            = os.getenv("AUDIT_TOPIC", "confluent-audit-log-events")
# Consumer group - offsets are managed by Kafka consumer groups (not files)
GROUP_ID               = os.getenv("GROUP_ID", "audit-fwd-v3-feb")
METRICS_PORT           = int(os.getenv("METRICS_PORT", "8000"))

# Anomaly detection configuration
ANOMALY_WINDOW_SECONDS = int(os.getenv("ANOMALY_WINDOW_SECONDS", "60"))
ANOMALY_AUTH_FAILURE_THRESHOLD = int(os.getenv("ANOMALY_AUTH_FAILURE_THRESHOLD", "10"))
ANOMALY_ACTIVITY_SPIKE_THRESHOLD = int(os.getenv("ANOMALY_ACTIVITY_SPIKE_THRESHOLD", "100"))
ANOMALY_DELETION_THRESHOLD = int(os.getenv("ANOMALY_DELETION_THRESHOLD", "5"))
ANOMALY_API_KEY_THRESHOLD = int(os.getenv("ANOMALY_API_KEY_THRESHOLD", "10"))

# Routing configuration - whether to use multi-topic routing
ENABLE_MULTI_TOPIC_ROUTING = os.getenv("ENABLE_MULTI_TOPIC_ROUTING", "false").lower() == "true"
ROUTER_DRY_RUN = os.getenv("AUDIT_ROUTER_DRY_RUN", "false").lower() == "true"

# Dead Letter Queue - for events that fail processing
DLQ_TOPIC = os.getenv("DLQ_TOPIC", "audit_events_dlq")
ENABLE_DLQ = os.getenv("ENABLE_DLQ", "true").lower() == "true"

# Denial aggregation - aggregate auth denials into summary alerts
ENABLE_DENIAL_AGGREGATION = os.getenv("ENABLE_DENIAL_AGGREGATION", "true").lower() == "true"

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

# ──────────── metrics tracking ────────────
class Metrics:
    def __init__(self):
        self.start_time = time.time()
        self.processed_total = 0
        self.error_count = 0
        self.last_process_time = time.time()
        self.partition_lag = {}
        self.lock = threading.Lock()
    
    def record_processed(self, count):
        with self.lock:
            self.processed_total += count
            self.last_process_time = time.time()
    
    def record_error(self):
        with self.lock:
            self.error_count += 1
    
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
                "consumer_lag_by_partition": self.partition_lag
            }

# Create global metrics instance
metrics = Metrics()

# ──────────── metrics server ────────────
class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/metrics':
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

            # Add audit event metrics
            prometheus_metrics.append("")
            prometheus_metrics.append(audit_event_metrics.format_prometheus())

            response = "\n".join(prometheus_metrics)
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(response.encode())
        elif self.path == '/health':
            # Enhanced health check endpoint
            # Returns 200 if healthy, 503 if unhealthy
            metrics_data = metrics.get_metrics()

            # Determine health status
            idle_seconds = metrics_data['idle_seconds']
            error_count = metrics_data['error_count']
            processed = metrics_data['processed_messages_total']

            # Health checks:
            # 1. Not idle for more than 5 minutes (300s)
            # 2. Error rate is not too high (< 10% of processed messages)
            # 3. Has processed at least 1 message (after first minute of uptime)
            is_healthy = True
            reasons = []

            if idle_seconds > 300:
                is_healthy = False
                reasons.append(f"Idle for {idle_seconds:.0f}s (> 300s)")

            if processed > 0 and error_count / processed > 0.1:
                is_healthy = False
                reasons.append(f"High error rate: {error_count}/{processed} ({error_count/processed*100:.1f}%)")

            if metrics_data['uptime_seconds'] > 60 and processed == 0:
                is_healthy = False
                reasons.append("No messages processed after 60s uptime")

            status_code = 200 if is_healthy else 503
            status_text = "healthy" if is_healthy else "unhealthy"

            health_data = {
                "status": status_text,
                "timestamp": time.time(),
                "uptime_seconds": metrics_data['uptime_seconds'],
                "processed_total": processed,
                "error_count": error_count,
                "idle_seconds": idle_seconds,
                "consumer_lag": metrics_data['consumer_lag_total'],
                "processing_rate": metrics_data['processing_rate_per_second']
            }

            if not is_healthy:
                health_data["reasons"] = reasons

            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(orjson.dumps(health_data, option=orjson.OPT_INDENT_2))
        else:
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

# ──────────── kafka configs ────────────
consumer_conf = {
    "bootstrap.servers":         AUDIT_BOOTSTRAP,
    "security.protocol":         "SASL_SSL",
    "sasl.mechanism":            "PLAIN",
    "sasl.username":             AUDIT_API_KEY,
    "sasl.password":             AUDIT_API_SECRET,
    "group.id":                  GROUP_ID,
    # Explicit offset commits after batch processing (at-least-once delivery)
    "enable.auto.commit":        False,
    "auto.offset.reset":         "latest",  # Start from latest on new consumer group
    "fetch.min.bytes":           1024 * 1024,      # Wait for 1MB before fetching
    "fetch.max.bytes":           200 * 1024 * 1024,  # 200MB max fetch
    "fetch.wait.max.ms":         50,                 # Wait up to 50ms
    "max.partition.fetch.bytes": 20 * 1024 * 1024,   # 20MB per partition
    "queued.min.messages":       50000,              # Pre-fetch 50K messages
    "queued.max.messages.kbytes": 500 * 1024,        # 500MB prefetch buffer
    # Cross-region latency settings
    "socket.timeout.ms":         30000,              # 30s socket timeout
    "session.timeout.ms":        45000,              # 45s session timeout
}

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
    "batch.size":                   2 * 1024 * 1024,    # 2MB batches (was 1MB)
    "batch.num.messages":           20000,              # Up to 20K msgs per batch
    "queue.buffering.max.messages": 5000000,            # 5M buffer (was 2M)
    "queue.buffering.max.kbytes":   3 * 1024 * 1024,    # 3GB buffer (was 2GB)
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
    out["principal"]           = _to_scalar(principal_obj)
    out["principalResourceId"] = authn.get("principalResourceId")
    out["identity"]            = authn.get("identity")
    out["email"]               = _extract_email(principal_obj)

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

    # clientId can be in request.clientId OR requestMetadata.clientId (kafka.Fetch/Produce events)
    out["clientId"] = req.get("clientId") or req.get("client_id") or meta.get("clientId") or meta.get("client_id")

    # Extract client IP from multiple possible locations
    out["clientIp"] = _extract_client_ip(data)

    out["data_json"] = orjson.dumps(data).decode('utf-8')

    # ──────────── Computed fields for criticality and classification ────────────
    # Get result status from result.status
    result = data.get("result", {})
    result_status = result.get("status") if isinstance(result, dict) else None

    # Use the modular classification system
    classification_result = calculate_criticality(out)
    out["criticality"] = classification_result.criticality.value
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

    return out

# ──────────── delivery callback ────────────
delivery_errors = {"count": 0, "last_error": None}
dlq_stats = {"sent": 0, "failed": 0}

def delivery_callback(err, msg):
    """Track delivery errors."""
    if err:
        delivery_errors["count"] += 1
        delivery_errors["last_error"] = str(err)
        if delivery_errors["count"] <= 10 or delivery_errors["count"] % 1000 == 0:
            logger.error("Delivery failed (%d total): %s", delivery_errors["count"], err)
        metrics.record_error()

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
def safe_produce(p: Producer, topic: str, key: bytes, value: bytes):
    while True:
        try:
            # drive I/O to free up buffer slots
            p.poll(0)
            p.produce(topic, key=key, value=value, callback=delivery_callback)
            return
        except BufferError:
            # buffer is full—wait briefly for background I/O
            p.poll(0.1)

# ──────────── partition assign callback ────────────
def on_assign(consumer, partitions):
    """Handle partition assignment - offsets managed by Kafka consumer groups."""
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

# ──────────── main ────────────
def main():
    logger.info("=" * 70)
    logger.info("Confluent Audit Log Intelligence System")
    logger.info(f"Version: {VERSION}")
    logger.info("Mode: Kafka Direct (No Flink required - Saves $401/month)")
    logger.info("=" * 70)

    # Validate environment (Schema Registry is optional)
    required_vars = [
        "AUDIT_BOOTSTRAP","AUDIT_API_KEY","AUDIT_API_SECRET",
        "DEST_BOOTSTRAP","DEST_API_KEY","DEST_API_SECRET"
    ]
    missing = [k for k in required_vars if not os.getenv(k)]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    # Optional Schema Registry check
    if SCHEMA_REGISTRY_URL:
        logger.info("Schema Registry configured: %s", SCHEMA_REGISTRY_URL)
    else:
        logger.info("Schema Registry not configured (optional)")

    # Initialize anomaly detection
    anomaly_config = RateTrackerConfig(
        window_seconds=ANOMALY_WINDOW_SECONDS,
        auth_failure_threshold=ANOMALY_AUTH_FAILURE_THRESHOLD,
        activity_spike_threshold=ANOMALY_ACTIVITY_SPIKE_THRESHOLD,
        deletion_threshold=ANOMALY_DELETION_THRESHOLD,
        api_key_threshold=ANOMALY_API_KEY_THRESHOLD,
    )
    anomaly_tracker = RateTracker(anomaly_config)
    logger.info("Anomaly detection initialized: window=%ds, auth_failure_threshold=%d",
                ANOMALY_WINDOW_SECONDS, ANOMALY_AUTH_FAILURE_THRESHOLD)

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

    # Create clients
    consumer = Consumer(consumer_conf)
    producer = Producer(producer_conf)

    # Start metrics server
    metrics_server = start_metrics_server(METRICS_PORT)

    # Connectivity checks
    try:
        md = consumer.list_topics(timeout=10.0)
        assert AUDIT_TOPIC in md.topics
        logger.info("Connected to source; topic %s exists", AUDIT_TOPIC)
    except Exception as e:
        logger.error("Source connectivity failed: %s", e)
        sys.exit(1)

    # Initialize router if multi-topic routing is enabled
    topic_router = None
    if ENABLE_MULTI_TOPIC_ROUTING:
        router_config = RouterConfig.from_env()
        topic_router = TopicRouter(producer, router_config)
        logger.info("Multi-topic routing enabled: %s", topic_router.get_enabled_topic_names())

    # Initialize denial aggregator (aggregates auth denials into summary alerts)
    denial_aggregator = None
    if ENABLE_DENIAL_AGGREGATION and ENABLE_MULTI_TOPIC_ROUTING:
        aggregator_config = AggregatorConfig.from_env()
        # Pass webhook_sender to send Slack alerts for HIGH aggregated alerts
        denial_aggregator = DenialAggregator(
            producer,
            aggregator_config,
            webhook_sender=webhook_sender if webhook_sender.enabled else None
        )
        logger.info("Denial aggregation enabled: window=%ds, threshold=%d, topic=%s, webhook=%s",
                    aggregator_config.window_seconds, aggregator_config.high_threshold,
                    aggregator_config.alerts_topic, "enabled" if webhook_sender.enabled else "disabled")

    # Destination connectivity check
    try:
        md2 = producer.list_topics(timeout=10.0)

        if ENABLE_MULTI_TOPIC_ROUTING and topic_router:
            # Verify all destination topics exist
            if ROUTER_DRY_RUN:
                logger.warning("Router in dry-run mode - skipping destination topic verification")
            else:
                for dest_topic in topic_router.get_enabled_topic_names():
                    if dest_topic not in md2.topics:
                        logger.error("Destination topic %s not found! Create it before starting.", dest_topic)
                        sys.exit(1)
                    logger.info("Verified destination topic: %s", dest_topic)
        else:
            # Single topic mode - verify the single destination topic
            assert DEST_TOPIC in md2.topics
            logger.info("Connected to dest; topic %s exists", DEST_TOPIC)
    except Exception as e:
        logger.error("Dest connectivity failed: %s", e)
        sys.exit(1)

    # Load schema (optional - only if Schema Registry is configured)
    json_serializer = None
    if SCHEMA_REGISTRY_URL:
        try:
            sr = SchemaRegistryClient({
                "url": SCHEMA_REGISTRY_URL,
                "basic.auth.user.info": f"{SCHEMA_REGISTRY_KEY}:{SCHEMA_REGISTRY_SECRET}"
            })
            subject = f"{DEST_TOPIC}-value"
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
    consumer.subscribe([AUDIT_TOPIC], on_assign=on_assign)
    logger.info("Subscribed to %s with consumer group %s", AUDIT_TOPIC, GROUP_ID)

    # Main processing loop
    BATCH_SIZE     = 5000  # Increased from 500 for 10x throughput
    processed      = 0
    start_ts       = time.time()
    last_heartbeat = start_ts
    last_lag_ts    = start_ts

    logger.info("Entering processing loop")
    try:
        while not _shutdown_requested:
            batch = consumer.consume(num_messages=BATCH_SIZE, timeout=1.0)
            if not batch:
                producer.poll(0)
            else:
                # Record in metrics
                batch_size = len([m for m in batch if m and not m.error()])
                if batch_size > 0:
                    metrics.record_processed(batch_size)
                
                for msg in batch:
                    if msg is None or msg.error():
                        if msg and msg.error().code() != KafkaError._PARTITION_EOF:
                            logger.error("Consume error: %s", msg.error())
                        continue
                    try:
                        evt  = orjson.loads(msg.value())
                        flat = flatten_audit(evt)
                        record_event_metrics(flat)

                        # Track event for anomaly detection
                        anomalies = anomaly_tracker.track_event(flat)
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

                        # Send alert for built-in alert rules or CRITICAL events
                        if webhook_sender.enabled and ENABLE_BUILTIN_ALERTS:
                            method_name = flat.get('methodName', '')

                            # Check if this method triggers a built-in alert
                            if method_name in BUILTIN_ALERT_METHODS:
                                alert_config = BUILTIN_ALERT_METHODS[method_name]
                                logger.info("Built-in alert triggered: %s - %s",
                                           method_name, alert_config['message'])
                                webhook_sender.send_critical_event_alert(flat)
                            # Also send alert for any CRITICAL event not in built-in rules
                            elif flat.get('criticality') == 'CRITICAL':
                                webhook_sender.send_critical_event_alert(flat)

                        # Route event to appropriate topic(s)
                        if ENABLE_MULTI_TOPIC_ROUTING and topic_router:
                            # Check if event should be aggregated (auth denials)
                            if denial_aggregator and denial_aggregator.should_aggregate(flat):
                                # Aggregate auth denials - will be flushed as summary alert
                                denial_aggregator.add_event(flat)
                            else:
                                # Use TopicRouter for multi-topic routing
                                routing_result = topic_router.route_event(flat)
                                # Track routing metrics
                                criticality = flat.get('criticality', 'LOW')
                                record_routing_metrics(f"audit_events_{criticality.lower()}", ROUTER_DRY_RUN)
                        else:
                            # Single topic mode - produce to DEST_TOPIC
                            ctx  = SerializationContext(DEST_TOPIC, MessageField.VALUE)
                            value = json_serializer(flat, ctx)
                            # Use event ID as key for compacted topic (source messages have no key)
                            event_key = flat.get('id', '').encode('utf-8') if flat.get('id') else None
                            safe_produce(producer, DEST_TOPIC, event_key, value)
                    except Exception as ex:
                        metrics.record_error()
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

                # Flush producer to ensure ALL messages are delivered before committing offsets
                # This is critical for at-least-once delivery guarantee
                remaining = producer.flush(timeout=30)

                if remaining > 0:
                    # Some messages failed to deliver - do NOT commit offsets
                    # These events will be reprocessed on restart
                    logger.error("Producer flush timed out: %d messages still in queue. NOT committing offsets.", remaining)
                    metrics.record_error()
                else:
                    # All messages delivered - safe to commit offsets
                    try:
                        consumer.commit(asynchronous=False)  # Synchronous commit for durability
                        logger.debug("Batch committed: %d events", batch_size)
                    except Exception as e:
                        logger.error("Failed to commit offsets: %s", e)
                        metrics.record_error()

                processed += batch_size
                if processed >= 1000 and processed % 1000 < batch_size:
                    elapsed = time.time() - start_ts
                    logger.info("Processed %d msgs in %.1f s (%.1f msg/s)",
                                processed, elapsed, processed / elapsed)

            now = time.time()
            # heartbeat
            if now - last_heartbeat >= 30:
                logger.info("Forwarder is alive at %s. Processed: %d, Errors: %d, Delivery failures: %d, DLQ: %d sent/%d failed",
                           time.ctime(), metrics.processed_total, metrics.error_count, delivery_errors["count"],
                           dlq_stats["sent"], dlq_stats["failed"])
                if delivery_errors["last_error"]:
                    logger.info("Last delivery error: %s", delivery_errors["last_error"])
                # Log routing stats if multi-topic routing is enabled
                if ENABLE_MULTI_TOPIC_ROUTING and topic_router:
                    stats = topic_router.get_stats()
                    if stats.get('low_dropped', 0) > 0:
                        logger.info("Routing stats - LOW dropped: %d (%.1f%% of total), CRITICAL: %d, HIGH: %d, MEDIUM: %d, LOW routed: %d",
                                   stats['low_dropped'],
                                   stats['low_dropped'] / max(stats['total_events'], 1) * 100,
                                   stats['critical_routed'], stats['high_routed'],
                                   stats['medium_routed'], stats['low_routed'])
                # Log aggregator stats if denial aggregation is enabled
                if denial_aggregator:
                    agg_stats = denial_aggregator.get_stats()
                    if agg_stats.get('events_aggregated', 0) > 0:
                        logger.info("Aggregator stats - aggregated: %d, alerts: %d (HIGH: %d, MEDIUM: %d), pending: %d",
                                   agg_stats['events_aggregated'], agg_stats['alerts_produced'],
                                   agg_stats['high_alerts'], agg_stats['medium_alerts'],
                                   agg_stats['pending_denials'])
                last_heartbeat = now

            # lag report
            if now - last_lag_ts >= 60:
                for tp in consumer.assignment():
                    try:
                        low, high = consumer.get_watermark_offsets(tp, timeout=5.0)
                        positions = consumer.position([tp])
                        if positions and len(positions) > 0:
                            pos = positions[0].offset
                            if pos >= 0:
                                lag = high - pos
                                metrics.update_lag(tp.partition, pos, high)
                                logger.info("Lag p%d: pos=%d, high=%d, lag=%d",
                                            tp.partition, pos, high, lag)
                    except Exception as e:
                        logger.warning("Error getting lag for partition %d: %s", tp.partition, e)

                # Periodic cleanup of rate tracker to prevent memory leak
                anomaly_tracker.cleanup()
                tracker_stats = anomaly_tracker.get_stats()
                logger.debug("Rate tracker cleanup: %d principals, %d IPs tracked",
                            tracker_stats.get('tracked_principals', 0),
                            tracker_stats.get('tracked_ips', 0))

                last_lag_ts = now

    except KeyboardInterrupt:
        logger.info("Interrupted by user (KeyboardInterrupt)")
    finally:
        logger.info("Shutting down gracefully...")

        # Shutdown denial aggregator FIRST (flushes pending alerts before producer)
        if denial_aggregator:
            denial_aggregator.shutdown()

        # Stop metrics server
        if metrics_server:
            metrics_server.shutdown()

        # Flush producer and commit final offsets
        remaining = producer.flush(timeout=30)
        if remaining > 0:
            logger.warning("Could not flush %d messages during shutdown", remaining)
        else:
            # Only commit if all messages were delivered
            try:
                consumer.commit(asynchronous=False)
                logger.info("Final offset commit successful")
            except Exception as e:
                logger.error("Failed to commit offsets during shutdown: %s", e)

        consumer.close()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    main()