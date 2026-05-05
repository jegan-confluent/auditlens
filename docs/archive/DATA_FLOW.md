# Audit Log Intelligence System - Complete Data Flow

**Last Updated:** December 5, 2024
**System Version:** v2.0 with Multi-Topic Routing

---

## Executive Summary

This document traces the complete data flow from Confluent Cloud audit logs through classification, routing, and visualization. The system processes audit events in real-time, classifies them by criticality, detects anomalies, and makes data available through both Kafka topics and Iceberg tables.

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUDIT LOG INTELLIGENCE SYSTEM - DATA FLOW                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ SOURCE: Confluent Cloud Audit Log Cluster (READ-ONLY)          │         │
│  │                                                                 │         │
│  │ Cluster:  lkc-qzk87 (pkc-4ywp7.us-west-2.aws)                 │         │
│  │ Env:      env-oxo9j                                            │         │
│  │ Topic:    confluent-audit-log-events                           │         │
│  │ Format:   CloudEvents v1.0 (JSON)                              │         │
│  │                                                                 │         │
│  │ Event Types:                                                   │         │
│  │   • io.confluent.kafka.server/authentication                   │         │
│  │   • io.confluent.kafka.server/authorization                    │         │
│  │   • io.confluent.cloud/request                                 │         │
│  └──────────────────────────────┬─────────────────────────────────┘         │
│                                 │                                            │
│                                 │ Kafka Consumer API                         │
│                                 │ (confluent_kafka.Consumer)                 │
│                                 ▼                                            │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ FORWARDER: audit_forwarder.py                                  │         │
│  │                                                                 │         │
│  │ Location: /Users/jegan/playground/audit-forwarder/             │         │
│  │ Process:  Python 3 daemon                                      │         │
│  │ Port:     8000 (or 8003 via METRICS_PORT env var)              │         │
│  │                                                                 │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ STEP 1: CONSUME                                          │   │         │
│  │ │ • Reads from confluent-audit-log-events                  │   │         │
│  │ │ • Batch size: 500 messages                               │   │         │
│  │ │ • Group ID: audit-forwarder-group                        │   │         │
│  │ │ • Offset tracking: offsets.json (local file)             │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ STEP 2: FLATTEN & EXTRACT                                │   │         │
│  │ │ • Flatten nested CloudEvents structure                   │   │         │
│  │ │ • Extract CRN fields (org, env, cluster IDs)             │   │         │
│  │ │ • Parse authentication/authorization info                │   │         │
│  │ │ • Extract ~40 flat fields                                │   │         │
│  │ │                                                           │   │         │
│  │ │ Function: flatten_audit(event)                           │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ STEP 3: CLASSIFY CRITICALITY                             │   │         │
│  │ │ • Loads method sets from src/classification/methods.py   │   │         │
│  │ │ • Applies priority logic from criticality.py             │   │         │
│  │ │ • Assigns: CRITICAL / HIGH / MEDIUM / LOW                │   │         │
│  │ │                                                           │   │         │
│  │ │ Key Logic:                                               │   │         │
│  │ │   1. Security failures → CRITICAL                        │   │         │
│  │ │   2. mds.Authorize granted=False → MEDIUM                │   │         │
│  │ │   3. DeleteKafkaCluster → CRITICAL                       │   │         │
│  │ │   4. CreateApiKey → HIGH                                 │   │         │
│  │ │   5. mds.Authorize granted=True → LOW                    │   │         │
│  │ │                                                           │   │         │
│  │ │ Function: calculate_criticality(event)                   │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ STEP 4: ANOMALY DETECTION                                │   │         │
│  │ │ • Track events in 60-second sliding window               │   │         │
│  │ │ • Detect:                                                │   │         │
│  │ │   - Auth failures (>10 in 60s)                           │   │         │
│  │ │   - Activity spikes (>100 events per principal)          │   │         │
│  │ │   - New source IPs                                       │   │         │
│  │ │   - API key abuse (>10 operations in 60s)                │   │         │
│  │ │                                                           │   │         │
│  │ │ Module: src/anomaly/rate_tracker.py                      │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ STEP 5: ROUTE TO DESTINATION(S)                          │   │         │
│  │ │                                                           │   │         │
│  │ │ TWO MODES:                                               │   │         │
│  │ │                                                           │   │         │
│  │ │ MODE A: Single Topic (default)                           │   │         │
│  │ │   • All events → audit_events_flattened                  │   │         │
│  │ │   • ENABLE_MULTI_TOPIC_ROUTING=false                     │   │         │
│  │ │                                                           │   │         │
│  │ │ MODE B: Multi-Topic Routing                              │   │         │
│  │ │   • CRITICAL → audit_events_critical                     │   │         │
│  │ │   • HIGH     → audit_events_high                         │   │         │
│  │ │   • MEDIUM   → audit_events_medium                       │   │         │
│  │ │   • LOW      → audit_events_low                          │   │         │
│  │ │   • ENABLE_MULTI_TOPIC_ROUTING=true                      │   │         │
│  │ │   • Optional: DROP_LOW_EVENTS=true (saves 89% volume)    │   │         │
│  │ │                                                           │   │         │
│  │ │ Module: src/routing/topic_router.py                      │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         │                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ METRICS EXPOSURE                                         │   │         │
│  │ │ • HTTP Server: http://localhost:8003/metrics             │   │         │
│  │ │ • Format: Prometheus                                     │   │         │
│  │ │ • Metrics:                                               │   │         │
│  │ │   - audit_events_processed_total                         │   │         │
│  │ │   - audit_errors_total                                   │   │         │
│  │ │   - audit_events_by_criticality{criticality="..."}       │   │         │
│  │ │   - audit_anomalies_detected_total                       │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  └────────────────────────────────────────────────────────────────┘         │
│                                 │                                            │
│                                 │ Kafka Producer API                         │
│                                 │ (confluent_kafka.Producer)                 │
│                                 ▼                                            │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ DESTINATION: Customer Cluster (WRITE)                          │         │
│  │                                                                 │         │
│  │ Cluster:  lkc-3q9omo (pkc-l7pr2.ap-south-1.aws)               │         │
│  │ Env:      env-p9r0mo                                           │         │
│  │                                                                 │         │
│  │ TOPICS (depends on routing mode):                              │         │
│  │                                                                 │         │
│  │ Single Topic Mode:                                             │         │
│  │   ✓ audit_events_flattened (currently active)                  │         │
│  │                                                                 │         │
│  │ Multi-Topic Mode:                                              │         │
│  │   • audit_events_critical  (~0% of events)                     │         │
│  │   • audit_events_high      (~1% of events)                     │         │
│  │   • audit_events_medium    (~10% of events)                    │         │
│  │   • audit_events_low       (~89% of events, or dropped)        │         │
│  └──────────────────────────────┬─────────────────────────────────┘         │
│                                 │                                            │
│                                 │ Flink SQL / TableFlow                      │
│                                 ▼                                            │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ TABLEFLOW / ICEBERG LAYER                                       │         │
│  │                                                                 │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ Flink SQL Processing                                     │   │         │
│  │ │                                                          │   │         │
│  │ │ File: flink-sql/01_audit_events_source.sql               │   │         │
│  │ │ CREATE TABLE audit_events_raw                            │   │         │
│  │ │   • Reads: confluent-audit-log-events (audit cluster)    │   │         │
│  │ │   • OR: audit_events_flattened (dest cluster)            │   │         │
│  │ │                                                          │   │         │
│  │ │ File: flink-sql/02_audit_events_flattened.sql            │   │         │
│  │ │ CREATE TABLE audit_events_flattened                      │   │         │
│  │ │   • Flattens nested JSON                                 │   │         │
│  │ │   • Extracts CRN fields                                  │   │         │
│  │ │   • Classifies criticality (Flink SQL version)           │   │         │
│  │ │   • INSERT INTO from audit_events_raw                    │   │         │
│  │ │                                                          │   │         │
│  │ │ ⚠️  Note: Flink SQL classification is OUTDATED          │   │         │
│  │ │     Use forwarder classification instead                │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ TableFlow Automatic Materialization                      │   │         │
│  │ │ • Converts Kafka topics to Iceberg tables                │   │         │
│  │ │ • Schema evolution                                       │   │         │
│  │ │ • Partition management (time-based)                      │   │         │
│  │ │ • Compaction & maintenance                               │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ ICEBERG TABLE                                            │   │         │
│  │ │                                                          │   │         │
│  │ │ Table Name: lkc-3q9omo.audit_events_flattened            │   │         │
│  │ │ Catalog URI: https://tableflow.ap-south-1.aws...         │   │         │
│  │ │ Format: Apache Iceberg                                   │   │         │
│  │ │ Storage: S3 (Parquet files)                              │   │         │
│  │ │                                                          │   │         │
│  │ │ Schema: 40+ flattened columns                            │   │         │
│  │ │   • event_id, event_time, event_type                     │   │         │
│  │ │   • principal, principal_type, principal_id              │   │         │
│  │ │   • method_name, service_name                            │   │         │
│  │ │   • organization_id, environment_id, cluster_id          │   │         │
│  │ │   • criticality (CRITICAL/HIGH/MEDIUM/LOW)               │   │         │
│  │ │   • is_security_event, is_deletion, is_creation          │   │         │
│  │ │   • client_ip, result_status, authz_granted              │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  └────────────────────────────────────────────────────────────────┘         │
│                                 │                                            │
│                                 │ PyIceberg REST Catalog API                 │
│                                 ▼                                            │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ DASHBOARD: dashboard_V6.py (Streamlit)                         │         │
│  │                                                                 │         │
│  │ Port: 8501 (Streamlit default)                                 │         │
│  │                                                                 │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ DATA SOURCE: PyIceberg                                   │   │         │
│  │ │ • Connects to TableFlow REST Catalog                     │   │         │
│  │ │ • Queries: lkc-3q9omo.audit_events_flattened             │   │         │
│  │ │ • Time filter: Last 1 hour (default), up to 7 days       │   │         │
│  │ │ • Row limit: 10,000 rows (configurable)                  │   │         │
│  │ │                                                           │   │         │
│  │ │ Function: fetch_events_iceberg_fast()                    │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ CLASSIFICATION RE-SYNC                                   │   │         │
│  │ │ • Uses SAME logic as forwarder                           │   │         │
│  │ │ • Copied from src/classification/                        │   │         │
│  │ │ • Recalculates criticality on query results              │   │         │
│  │ │ • Ensures dashboard matches forwarder classification     │   │         │
│  │ │                                                           │   │         │
│  │ │ Function: compute_criticality(row)                       │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ FORWARDER STATUS INTEGRATION                             │   │         │
│  │ │ • Fetches: http://localhost:8003/metrics                 │   │         │
│  │ │ • Parses Prometheus metrics                              │   │         │
│  │ │ • Shows: events processed, errors, anomalies             │   │         │
│  │ │ • Status: 🟢 Running / 🔴 Offline                        │   │         │
│  │ │                                                           │   │         │
│  │ │ Function: get_forwarder_status()                         │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  │                         │                                       │         │
│  │                         ▼                                       │         │
│  │ ┌─────────────────────────────────────────────────────────┐   │         │
│  │ │ VISUALIZATION                                            │   │         │
│  │ │                                                           │   │         │
│  │ │ Tabs:                                                    │   │         │
│  │ │   1. All Events (filterable by principal, method)        │   │         │
│  │ │   2. Critical & High (priority events)                   │   │         │
│  │ │   3. Deletions (all Delete operations)                   │   │         │
│  │ │   4. Anomalies & Security (auth failures, spikes)        │   │         │
│  │ │                                                           │   │         │
│  │ │ Charts:                                                  │   │         │
│  │ │   • Criticality distribution (validates classification)  │   │         │
│  │ │   • Metrics cards (total, critical, high, security)      │   │         │
│  │ └─────────────────────────────────────────────────────────┘   │         │
│  └────────────────────────────────────────────────────────────────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Component Analysis

### 1. DATA SOURCES & ORIGINS

#### **Source: Confluent Cloud Audit Log Cluster**

```yaml
Cluster ID:    lkc-qzk87
Environment:   env-oxo9j
Bootstrap:     pkc-4ywp7.us-west-2.aws.confluent.cloud:9092
Topic:         confluent-audit-log-events
Access:        READ-ONLY (managed by Confluent)
Auth:          SASL_SSL/PLAIN with API key

Event Format:  CloudEvents v1.0 (JSON)
Event Types:
  - io.confluent.kafka.server/authentication    # Kafka auth events
  - io.confluent.kafka.server/authorization     # Kafka ACL checks
  - io.confluent.cloud/request                  # Cloud API requests

Typical Volume:
  - ~100-1000 events/second (varies by cluster activity)
  - ~89% authorization checks (mds.Authorize)
  - ~10% cloud API operations
  - ~1% security events
```

**Event Structure (CloudEvents):**
```json
{
  "id": "uuid",
  "specversion": "1.0",
  "source": "crn://confluent.cloud/organization=xxx/environment=yyy/kafka=zzz",
  "subject": "crn://confluent.cloud/.../topic=my-topic",
  "type": "io.confluent.kafka.server/authorization",
  "time": "2024-12-05T10:30:00.123Z",
  "datacontenttype": "application/json",
  "data": {
    "serviceName": "crn://...",
    "methodName": "kafka.Produce",
    "authorizationInfo": {
      "granted": true,
      "operation": "Write",
      "resourceType": "Topic",
      "resourceName": "my-topic"
    }
  }
}
```

---

### 2. FORWARDER FLOW (audit_forwarder.py)

#### **Configuration**

```bash
# Source: Audit Log Cluster (READ)
AUDIT_BOOTSTRAP=pkc-4ywp7.us-west-2.aws.confluent.cloud:9092
AUDIT_API_KEY=GCBUNLE56LVNO3DX
AUDIT_API_SECRET=***
AUDIT_TOPIC=confluent-audit-log-events

# Destination: Customer Cluster (WRITE)
DEST_BOOTSTRAP=pkc-l7pr2.ap-south-1.aws.confluent.cloud:9092
DEST_API_KEY=RBG2XYYEFWIF2YJB
DEST_API_SECRET=***
DEST_TOPIC=audit_events_flattened

# Routing Mode
ENABLE_MULTI_TOPIC_ROUTING=false  # Default: single topic
AUDIT_ROUTER_DRY_RUN=false        # Set true to test routing logic
DROP_LOW_EVENTS=false             # Set true to drop LOW criticality events

# Metrics
METRICS_PORT=8000  # Change to 8003 to avoid port conflicts
```

#### **Processing Pipeline**

**Step 1: Consume**
```python
# Location: audit_forwarder.py:430-439
consumer = Consumer(consumer_conf)
consumer.subscribe([AUDIT_TOPIC], on_assign=on_assign)

# Batch processing
BATCH_SIZE = 500
batch = consumer.consume(num_messages=BATCH_SIZE, timeout=1.0)
```

**Step 2: Flatten**
```python
# Location: audit_forwarder.py:281-362
def flatten_audit(event):
    """
    Converts nested CloudEvents structure to flat dictionary.

    Input: CloudEvents JSON (nested 3-4 levels)
    Output: ~40 flat fields

    Examples:
      data.authenticationInfo.principal → principal
      data.methodName → methodName
      source (CRN) → organization_id, environment_id, cluster_id
    """
```

**Step 3: Classify**
```python
# Location: src/classification/criticality.py:47-215
def calculate_criticality(event):
    """
    Priority-based classification:

    1. Security failures → CRITICAL
       - UNAUTHENTICATED, PERMISSION_DENIED, UNAUTHORIZED

    2. Denied access handling:
       - mds.Authorize granted=False → MEDIUM (routine RBAC)
       - Other methods granted=False → HIGH or CRITICAL

    3. Explicit method sets:
       - DeleteKafkaCluster, kafka.DeleteTopics → CRITICAL
       - CreateApiKey, DeleteApiKey → HIGH
       - kafka.CreateTopics, UpdateKafkaCluster → MEDIUM

    4. Pattern matching:
       - Any Delete* not in lists → HIGH
       - Any Create*/Update* not in lists → MEDIUM
       - Read operations → LOW

    5. Default: LOW
    """
```

**Step 4: Detect Anomalies**
```python
# Location: src/anomaly/rate_tracker.py
class RateTracker:
    """
    Sliding window tracking (60 seconds default).

    Detects:
      • auth_failure_spike: >10 auth failures per principal in 60s
      • activity_spike: >100 events per principal in 60s
      • new_source_ip: New IP for known principal
      • api_key_abuse: >10 API key operations in 60s
    """
```

**Step 5: Route**
```python
# Location: audit_forwarder.py:547-559
if ENABLE_MULTI_TOPIC_ROUTING and topic_router:
    # Multi-topic mode
    routing_result = topic_router.route_event(flat)
    # Produces to:
    #   audit_events_critical  (CRITICAL)
    #   audit_events_high      (HIGH)
    #   audit_events_medium    (MEDIUM)
    #   audit_events_low       (LOW, unless DROP_LOW_EVENTS=true)
else:
    # Single topic mode (current default)
    safe_produce(producer, DEST_TOPIC, event_key, value)
    # Produces to:
    #   audit_events_flattened (ALL events)
```

#### **Metrics Exposure**

```bash
# Endpoint
http://localhost:8003/metrics

# Format: Prometheus
audit_events_processed_total 15234
audit_errors_total 2
audit_events_by_criticality{criticality="CRITICAL"} 12
audit_events_by_criticality{criticality="HIGH"} 156
audit_events_by_criticality{criticality="MEDIUM"} 1523
audit_events_by_criticality{criticality="LOW"} 13543
audit_anomalies_detected_total 3
```

---

### 3. TABLEFLOW / ICEBERG FLOW

#### **Flink SQL Processing**

**Source Table (reads from audit cluster):**
```sql
-- File: flink-sql/01_audit_events_source.sql
CREATE TABLE IF NOT EXISTS `audit_events_raw` (
    `id` STRING NOT NULL,
    `source` STRING,
    `type` STRING,
    `time` TIMESTAMP(3),
    `data` ROW<...>  -- Nested CloudEvents structure
) WITH (
    'connector' = 'confluent',
    'kafka.topic' = 'confluent-audit-log-events',
    'scan.startup.mode' = 'earliest-offset'
);
```

**Flattened Table (writes to destination cluster):**
```sql
-- File: flink-sql/02_audit_events_flattened.sql
CREATE TABLE `audit_events_flattened` (
    `event_id` STRING NOT NULL,
    `event_time` TIMESTAMP(3),
    `principal` STRING,
    `method_name` STRING,
    `organization_id` STRING,
    `environment_id` STRING,
    `cluster_id` STRING,
    `criticality` STRING,  -- Computed in SQL
    `is_security_event` BOOLEAN,
    `is_deletion` BOOLEAN,
    ... -- 40+ columns total
    PRIMARY KEY (`event_id`) NOT ENFORCED,
    WATERMARK FOR `event_time` AS `event_time` - INTERVAL '5' SECOND
) WITH (
    'changelog.mode' = 'upsert',
    'kafka.cleanup-policy' = 'compact'
);

-- Transformation
INSERT INTO `audit_events_flattened`
SELECT
    `id` AS `event_id`,
    `time` AS `event_time`,
    COALESCE(`data`.`authenticationInfo`.`principal`, ...) AS `principal`,
    REGEXP_EXTRACT(`source`, 'organization=([^/]+)', 1) AS `organization_id`,
    CASE
        WHEN `data`.`methodName` LIKE '%DeleteKafkaCluster%' THEN 'CRITICAL'
        WHEN `data`.`result`.`status` = 'PERMISSION_DENIED' THEN 'HIGH'
        WHEN `data`.`methodName` LIKE '%Delete%' THEN 'HIGH'
        WHEN `data`.`methodName` LIKE '%Create%' THEN 'MEDIUM'
        ELSE 'LOW'
    END AS `criticality`,
    ...
FROM `audit_events_raw`;
```

⚠️ **CRITICAL NOTE:** The Flink SQL classification logic (shown above) is **OUTDATED** and does NOT match the forwarder's sophisticated classification. The forwarder's Python-based classification is the source of truth.

#### **TableFlow Integration**

**What is TableFlow?**
- Confluent's managed service for Kafka → Iceberg transformation
- Automatically materializes Kafka topics as Iceberg tables
- Provides REST Catalog API for querying

**How Data Flows:**
```
Kafka Topic: audit_events_flattened (lkc-3q9omo)
         │
         │ TableFlow monitors topic
         │ Converts to Iceberg format
         ▼
Iceberg Table: lkc-3q9omo.audit_events_flattened
         │
         │ Storage: S3 (Parquet files)
         │ Catalog: TableFlow REST Catalog
         ▼
Query via PyIceberg REST Catalog API
```

**Iceberg Table Details:**
```yaml
Table Name:    lkc-3q9omo.audit_events_flattened
Catalog URI:   https://tableflow.ap-south-1.aws.confluent.cloud/iceberg/catalog/
               organizations/f5f511c7-d821-48cc-8388-c96a6f11f12a/environments/env-p9r0mo
Format:        Apache Iceberg
Storage:       S3 (AWS ap-south-1)
Partitioning:  Time-based (automatic by TableFlow)
Compression:   Snappy
File Format:   Parquet

Access Method: PyIceberg REST Catalog
Authentication: Confluent Cloud API Key

Columns: 40+ fields (same as Kafka topic schema)
  • event_id (primary key)
  • event_time (watermark)
  • principal, method_name, service_name
  • organization_id, environment_id, cluster_id
  • criticality, result_status, authz_granted
  • is_security_event, is_deletion, is_creation
  • client_ip, principal_type, resource_type
  • ... and more
```

---

### 4. DASHBOARD DATA SOURCES

#### **Current Configuration (dashboard_V6.py)**

**Data Source: PyIceberg (TableFlow REST Catalog)**

```python
# Configuration
TABLEFLOW_CATALOG_URI = "https://tableflow.ap-south-1.aws.confluent.cloud/iceberg/catalog/..."
CONFLUENT_CLOUD_API_KEY = "3ASTEJPTNPR3M3IL"
CONFLUENT_CLOUD_API_SECRET = "cflt..."
ICEBERG_TABLE_NAME = "lkc-3q9omo.audit_events_flattened"

# Connection
@st.cache_resource(ttl=300)
def get_iceberg_catalog():
    from pyiceberg.catalog import load_catalog
    catalog = load_catalog(
        "confluent_tableflow",
        type="rest",
        uri=TABLEFLOW_CATALOG_URI,
        credential=f"{API_KEY}:{API_SECRET}",
    )
    return catalog

# Query
@st.cache_data(ttl=30)
def fetch_events_iceberg_fast(hours=1, limit=10000):
    table = catalog.load_table(ICEBERG_TABLE_NAME)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    scan = table.scan(
        row_filter=f"time >= '{cutoff_str}'",
        selected_fields=tuple(ACTUAL_COLUMNS),
        limit=limit
    )

    df = scan.to_pandas()
    df = enrich_dataframe(df)  # Re-classify with forwarder logic
    return df
```

**Why PyIceberg vs Direct Kafka?**

| Aspect | PyIceberg (Current) | Direct Kafka |
|--------|---------------------|--------------|
| **Latency** | ~5-10 seconds behind real-time | Real-time |
| **Query Flexibility** | SQL-like filters, time travel | Sequential scan only |
| **State** | Stateless (no offset management) | Stateful (offset tracking) |
| **Historical Data** | Easy access to past events | Must replay from beginning |
| **Performance** | Optimized for analytics queries | Optimized for streaming |
| **Use Case** | Dashboard, BI, investigations | Real-time alerting, monitoring |

**Current Choice: PyIceberg** ✓
- Dashboard queries historical data (last 1-24 hours)
- No need for real-time streaming
- Simpler deployment (no consumer offset management)
- Better for ad-hoc filtering and analysis

**Future Option: Direct Kafka**
- Could read from `audit_events_critical`, `audit_events_high` topics
- Useful for real-time alerting dashboard
- Would require consumer group management

#### **Forwarder Status Integration**

```python
def get_forwarder_status():
    """
    Fetches forwarder metrics from http://localhost:8003/metrics.
    Parses Prometheus format.
    """
    try:
        response = requests.get('http://localhost:8003/metrics', timeout=2)
        # Parse metrics...
        return {
            'status': 'running',
            'processed': 15234,
            'errors': 2,
            'anomalies': 3
        }
    except:
        return {'status': 'offline'}

# Displayed in sidebar:
#   🟢 Status: Running
#   Events Processed: 15,234
#   Errors: 2
#   Anomalies Detected: 3
```

---

## 5. CURRENT STATE

### **Running Components**

```bash
# Check forwarder status
ps aux | grep audit_forwarder.py
# If running:
#   jegan  12345  audit_forwarder.py

# Check metrics endpoint
curl http://localhost:8003/metrics
# Expected:
#   audit_events_processed_total 15234
#   audit_errors_total 2

# Check dashboard
ps aux | grep streamlit
# If running:
#   streamlit run dashboard_V6.py (port 8501)
```

### **Active Configuration**

```yaml
Forwarder:
  Mode: Single Topic (ENABLE_MULTI_TOPIC_ROUTING=false)
  Input:
    Cluster: lkc-qzk87 (us-west-2)
    Topic: confluent-audit-log-events
  Output:
    Cluster: lkc-3q9omo (ap-south-1)
    Topic: audit_events_flattened
  Metrics: http://localhost:8003/metrics (or 8000 if METRICS_PORT not set)

TableFlow:
  Table: lkc-3q9omo.audit_events_flattened
  Source: audit_events_flattened topic (via Flink SQL)
  Classification: OUTDATED (Flink SQL-based, not forwarder logic)

Dashboard:
  Data Source: PyIceberg → lkc-3q9omo.audit_events_flattened
  Classification: SYNCED (re-applies forwarder logic on query results)
  Forwarder Status: Polling http://localhost:8003/metrics
  Refresh: Manual + optional 30s auto-refresh
```

### **Verification Checklist**

#### **✓ Working**
- [x] Forwarder consuming from audit log cluster
- [x] Forwarder producing to `audit_events_flattened` topic
- [x] Forwarder metrics endpoint responding
- [x] TableFlow materializing Iceberg table
- [x] Dashboard querying Iceberg table via PyIceberg
- [x] Dashboard classification logic synced with forwarder

#### **⚠️ Gaps / Misconfigurations**

1. **Flink SQL Classification is Outdated**
   - **Issue:** `flink-sql/02_audit_events_flattened.sql` uses simple string matching
   - **Impact:** `criticality` column in Iceberg table is incorrect
   - **Fix:** Dashboard re-classifies on query (workaround implemented)
   - **Proper Fix:** Update Flink SQL to use exact method sets and priority logic

2. **Multi-Topic Routing Not Active**
   - **Issue:** `ENABLE_MULTI_TOPIC_ROUTING=false` (default)
   - **Impact:** All events go to single topic `audit_events_flattened`
   - **Use Case:** Multi-topic routing enables tiered alerting/retention
   - **To Enable:** Set `ENABLE_MULTI_TOPIC_ROUTING=true`, create 4 destination topics

3. **Dashboard Cannot Read Multi-Topic Setup**
   - **Issue:** Dashboard only reads from Iceberg table (single source)
   - **Impact:** If multi-topic routing is enabled, dashboard won't see separated streams
   - **Fix Options:**
     - Keep reading from Iceberg (aggregates all topics via Flink)
     - Add Kafka consumer to read from `audit_events_critical`, `audit_events_high` directly

4. **Metrics Port Conflict Risk**
   - **Issue:** Default `METRICS_PORT=8000` may conflict with other services
   - **Current:** Changed to 8003 in some runs, but not in `.env`
   - **Fix:** Update `.env` with `METRICS_PORT=8003`

---

## Configuration File Summary

### **.env**
```bash
# Audit Log Cluster (Source - READ ONLY)
AUDIT_CLUSTER_ID=lkc-qzk87
AUDIT_ENV_ID=env-oxo9j
AUDIT_BOOTSTRAP=pkc-4ywp7.us-west-2.aws.confluent.cloud:9092
AUDIT_TOPIC=confluent-audit-log-events
AUDIT_API_KEY=GCBUNLE56LVNO3DX

# Destination Cluster (Your cluster - WRITE)
DEST_ENV_ID=env-p9r0mo
DEST_CLUSTER_ID=lkc-3q9omo
DEST_BOOTSTRAP=pkc-l7pr2.ap-south-1.aws.confluent.cloud:9092
DEST_API_KEY=RBG2XYYEFWIF2YJB
DEST_TOPIC=audit_events_flattened

# Schema Registry
SCHEMA_REGISTRY_URL=https://psrc-epkz2.ap-southeast-2.aws.confluent.cloud
SCHEMA_REGISTRY_KEY=X7BAO7CW5MMHULFH

# Forwarder Settings
GROUP_ID=audit-forwarder-group
OFFSET_FILE=offsets.json
METRICS_PORT=8000  # ⚠️ Change to 8003 to avoid conflicts

# TableFlow (for dashboard)
CONFLUENT_CLOUD_API_KEY=3ASTEJPTNPR3M3IL
TABLEFLOW_CATALOG_URI=https://tableflow.ap-south-1.aws.confluent.cloud/iceberg/catalog/organizations/f5f511c7-d821-48cc-8388-c96a6f11f12a/environments/env-p9r0mo
ICEBERG_TABLE_NAME=lkc-3q9omo.audit_events_flattened
```

### **.secrets**
```bash
AUDIT_API_SECRET=***
DEST_API_SECRET=***
SCHEMA_REGISTRY_SECRET=***
CONFLUENT_CLOUD_API_SECRET=***
```

---

## Quick Start Commands

### **Start Forwarder**
```bash
cd /Users/jegan/playground/audit-forwarder

# Single topic mode (default)
python3 audit_forwarder.py

# Multi-topic mode
ENABLE_MULTI_TOPIC_ROUTING=true python3 audit_forwarder.py

# Multi-topic with LOW dropping (reduces volume by 89%)
ENABLE_MULTI_TOPIC_ROUTING=true DROP_LOW_EVENTS=true python3 audit_forwarder.py

# Dry-run mode (test routing logic without producing)
ENABLE_MULTI_TOPIC_ROUTING=true AUDIT_ROUTER_DRY_RUN=true python3 audit_forwarder.py
```

### **Check Forwarder Status**
```bash
# Metrics endpoint
curl http://localhost:8003/metrics

# Or via browser
open http://localhost:8003/metrics
```

### **Start Dashboard**
```bash
cd /Users/jegan/playground/audit-forwarder

# Start Streamlit dashboard
streamlit run dashboard_V6.py

# Opens in browser at http://localhost:8501
```

### **Query Iceberg Table Directly**
```python
from pyiceberg.catalog import load_catalog
import os

catalog = load_catalog(
    "tableflow",
    type="rest",
    uri=os.getenv('TABLEFLOW_CATALOG_URI'),
    credential=f"{os.getenv('CONFLUENT_CLOUD_API_KEY')}:{os.getenv('CONFLUENT_CLOUD_API_SECRET')}"
)

table = catalog.load_table('lkc-3q9omo.audit_events_flattened')
df = table.scan(limit=100).to_pandas()
print(df)
```

---

## Recommendations

### **1. Update Flink SQL Classification**

**Problem:** Flink SQL classification is outdated and doesn't match forwarder logic.

**Solution:**
```sql
-- In flink-sql/02_audit_events_flattened.sql
-- Replace simple CASE statement with explicit method checks

CASE
    -- CRITICAL: Security failures
    WHEN `data`.`result`.`status` IN ('UNAUTHENTICATED', 'PERMISSION_DENIED', 'UNAUTHORIZED') THEN 'CRITICAL'

    -- CRITICAL: Infrastructure deletions
    WHEN `data`.`methodName` IN ('DeleteKafkaCluster', 'DeleteEnvironment', 'kafka.DeleteTopics', 'kafka.DeleteAcls') THEN 'CRITICAL'

    -- MEDIUM: mds.Authorize denied (not CRITICAL)
    WHEN `data`.`methodName` IN ('mds.Authorize', 'flink.Authorize', 'ksql.Authorize')
         AND `data`.`authorizationInfo`.`granted` = FALSE THEN 'MEDIUM'

    -- HIGH: Denied on sensitive methods
    WHEN `data`.`authorizationInfo`.`granted` = FALSE THEN 'HIGH'

    -- HIGH: API keys, service accounts
    WHEN `data`.`methodName` IN ('CreateApiKey', 'DeleteApiKey', 'CreateServiceAccount', 'DeleteServiceAccount') THEN 'HIGH'

    -- ... (full method sets from forwarder)

    ELSE 'LOW'
END AS `criticality`
```

### **2. Enable Multi-Topic Routing (Optional)**

**When to use:**
- Tiered retention policies (keep CRITICAL for 1 year, LOW for 7 days)
- Separate alerting streams (alert on CRITICAL topic only)
- Volume management (drop LOW events to save 89% of throughput)

**How to enable:**
```bash
# 1. Create destination topics
confluent kafka topic create audit_events_critical --cluster lkc-3q9omo
confluent kafka topic create audit_events_high --cluster lkc-3q9omo
confluent kafka topic create audit_events_medium --cluster lkc-3q9omo
confluent kafka topic create audit_events_low --cluster lkc-3q9omo

# 2. Update .env
echo "ENABLE_MULTI_TOPIC_ROUTING=true" >> .env

# 3. Restart forwarder
python3 audit_forwarder.py
```

### **3. Fix Metrics Port**

```bash
# Update .env
sed -i '' 's/METRICS_PORT=8000/METRICS_PORT=8003/' .env

# Restart forwarder
pkill -f audit_forwarder.py
python3 audit_forwarder.py
```

---

## Appendix: Classification Examples

### **Example 1: mds.Authorize (Most Common)**

**Event:**
```json
{
  "methodName": "mds.Authorize",
  "authorizationInfo": {
    "granted": true,
    "operation": "Write",
    "resourceType": "Topic"
  }
}
```

**Classification:**
- Forwarder: **LOW** (routine RBAC check, granted=True)
- Old Flink SQL: **HIGH** (incorrect - treats all denials as HIGH)
- Dashboard: **LOW** (re-classifies using forwarder logic)

### **Example 2: DeleteKafkaCluster**

**Event:**
```json
{
  "methodName": "DeleteKafkaCluster",
  "result": {"status": "SUCCESS"}
}
```

**Classification:**
- Forwarder: **CRITICAL** (in CRITICAL_METHODS set)
- Old Flink SQL: **CRITICAL** (correct by coincidence)
- Dashboard: **CRITICAL** (synced)

### **Example 3: CreateApiKey**

**Event:**
```json
{
  "methodName": "CreateApiKey",
  "result": {"status": "SUCCESS"}
}
```

**Classification:**
- Forwarder: **HIGH** (in HIGH_METHODS set)
- Old Flink SQL: **MEDIUM** (incorrect - treats all Create as MEDIUM)
- Dashboard: **HIGH** (synced)

### **Example 4: Auth Failure**

**Event:**
```json
{
  "methodName": "kafka.Authentication",
  "result": {"status": "UNAUTHENTICATED"}
}
```

**Classification:**
- Forwarder: **CRITICAL** (security failure)
- Old Flink SQL: **CRITICAL** (correct)
- Dashboard: **CRITICAL** (synced)

---

**END OF DOCUMENT**
