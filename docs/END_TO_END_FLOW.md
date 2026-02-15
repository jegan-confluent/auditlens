# Confluent AuditLens: End-to-End Flow Documentation

**Version 2.1.0** | Complete Technical Flow Analysis

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Data Flow Pipeline](#data-flow-pipeline)
3. [Component Deep Dive](#component-deep-dive)
4. [Classification Logic](#classification-logic)
5. [Routing Strategy](#routing-strategy)
6. [Alerting & Anomaly Detection](#alerting--anomaly-detection)
7. [Dashboard Visualization](#dashboard-visualization)
8. [Design Decisions & Rationale](#design-decisions--rationale)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CONFLUENT CLOUD                                     │
│  ┌───────────────────┐                         ┌────────────────────────────┐   │
│  │   Audit Log       │                         │   Your Kafka Cluster       │   │
│  │   Cluster         │                         │                            │   │
│  │   ┌─────────────┐ │                         │  ┌──────────────────────┐  │   │
│  │   │ confluent-  │ │                         │  │ audit_events_critical│  │   │
│  │   │ audit-log-  │ │   ┌─────────────────┐   │  ├──────────────────────┤  │   │
│  │   │ events      │─┼──►│  FORWARDER      │──►│  │ audit_events_high    │  │   │
│  │   └─────────────┘ │   │  (Python)       │   │  ├──────────────────────┤  │   │
│  └───────────────────┘   │                 │   │  │ audit_events_medium  │  │   │
│                          │  • Consume      │   │  ├──────────────────────┤  │   │
│                          │  • Flatten      │   │  │ security_alerts      │  │   │
│                          │  • Classify     │   │  └──────────────────────┘  │   │
│                          │  • Route        │   └────────────────────────────┘   │
│                          │  • Alert        │                                    │
│                          └─────────────────┘                                    │
└─────────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              LOCAL DOCKER                                        │
│                                                                                  │
│  ┌─────────────────┐    ┌────────────────┐    ┌──────────────────────────────┐  │
│  │  Forwarder      │    │  Dashboard     │    │      Observability Stack     │  │
│  │  :8003          │    │  :8503         │    │  ┌──────────┐  ┌───────────┐ │  │
│  │                 │◄───│                │    │  │Prometheus│  │  Grafana  │ │  │
│  │  /metrics       │    │  10 Tabs       │    │  │  :9090   │  │   :3000   │ │  │
│  │  /health        │    │  Real-time     │    │  └──────────┘  └───────────┘ │  │
│  └─────────────────┘    │  Filtering     │    │       │             │        │  │
│                         └────────────────┘    │       └──────┬──────┘        │  │
│                                               │              │               │  │
│                                               │  ┌───────────▼───────────┐   │  │
│                                               │  │   Loki + Promtail     │   │  │
│                                               │  │   (Log Aggregation)   │   │  │
│                                               │  └───────────────────────┘   │  │
│                                               └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Pipeline

### Phase 1: Consumption (audit_forwarder.py:720-800)

```
                     ┌─────────────────────────────────────┐
                     │       Confluent Audit Log Cluster   │
                     │     confluent-audit-log-events      │
                     └────────────────┬────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           KAFKA CONSUMER                                         │
│                                                                                  │
│  Configuration (audit_forwarder.py:301-316):                                     │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  • auto.offset.reset: "latest"          # Start from real-time             │ │
│  │  • fetch.min.bytes: 1MB                 # Batch fetching for throughput    │ │
│  │  • fetch.max.bytes: 100MB               # Large batch support              │ │
│  │  • max.partition.fetch.bytes: 10MB      # Per-partition limit              │ │
│  │  • queued.min.messages: 10000           # Pre-fetch buffer                 │ │
│  │  • enable.auto.commit: true             # Automatic offset management      │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
│  Batch Processing: consume(5000 messages, timeout=1.0s)                          │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Why this approach:**
- `auto.offset.reset=latest`: Skip historical backlog, focus on real-time
- Large batches (5000): Maximize throughput, reduce overhead
- Pre-fetching: Keep consumer busy while processing

---

### Phase 2: Parsing & Flattening (audit_forwarder.py:423-528)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    RAW CLOUDEVENTS AUDIT EVENT                                   │
│                                                                                  │
│  {                                                                               │
│    "id": "uuid",                                                                 │
│    "type": "io.confluent.kafka.server/authorization",                            │
│    "source": "crn://confluent.cloud/organization=o-xxx/environment=env-xxx/...", │
│    "time": "2024-12-12T10:00:00Z",                                               │
│    "data": {                                                                     │
│      "serviceName": "crn://confluent.cloud/...",                                 │
│      "methodName": "kafka.CreateTopics",                                         │
│      "authenticationInfo": { "principal": {...} },                               │
│      "authorizationInfo": { "granted": true, "operation": "CREATE" },            │
│      "request": { "clientId": "producer-1" },                                    │
│      "requestMetadata": { "clientAddress": [{"ip": "1.2.3.4"}] }                 │
│    }                                                                             │
│  }                                                                               │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼ flatten_audit()
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         FLATTENED EVENT                                          │
│                                                                                  │
│  {                                                                               │
│    // CloudEvents envelope                                                       │
│    "id": "uuid",                                                                 │
│    "type": "io.confluent.kafka.server/authorization",                            │
│    "time": "2024-12-12T10:00:00Z",                                               │
│                                                                                  │
│    // Extracted fields                                                           │
│    "serviceName": "...",                                                         │
│    "methodName": "kafka.CreateTopics",                                           │
│    "principal": "sa-xxx",                  # Scalar from nested object           │
│    "email": "user@example.com",            # Extracted from principal            │
│    "clientId": "producer-1",               # From request OR requestMetadata     │
│    "clientIp": "1.2.3.4",                  # From multiple possible locations    │
│    "granted": true,                                                              │
│                                                                                  │
│    // COMPUTED FIELDS (enrichment)                                               │
│    "criticality": "MEDIUM",                # Classification result               │
│    "is_security_event": false,                                                   │
│    "is_deletion": false,                                                         │
│    "is_creation": true,                                                          │
│    "organization_id": "o-xxx",             # Extracted from CRN                  │
│    "environment_id": "env-xxx",            # Extracted from CRN                  │
│    "cluster_id": "lkc-xxx",                # Extracted from CRN                  │
│                                                                                  │
│    "data_json": "{...}"                    # Original data preserved             │
│  }                                                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Key Extraction Logic:**

| Field | Extraction Path | Fallback Paths |
|-------|-----------------|----------------|
| `principal` | `data.authenticationInfo.principal.confluentServiceAccount.resourceId` | `confluentUser.resourceId`, raw dict |
| `email` | `data.authenticationInfo.principal.email` | Nested in `confluentUser` |
| `clientId` | `data.request.clientId` | `data.requestMetadata.clientId` |
| `clientIp` | `data.clientAddress[0].ip` | `data.requestMetadata.clientAddress[0].ip`, `data.authorizationInfo.requestMetadata.clientAddress[0].ip` |
| `cluster_id` | CRN parsing from `source` | CRN parsing from `resourceName`, `subject` |

**Why multiple fallback paths:**
- Confluent audit events have inconsistent field locations depending on event type
- `kafka.Fetch`/`kafka.Produce` events have `clientId` in `requestMetadata`
- `mds.Authorize` events have IDs in `subject` instead of `source`

---

### Phase 3: Classification (src/classification/criticality.py)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     CLASSIFICATION DECISION TREE                                 │
│                                                                                  │
│                              ┌─────────────────┐                                 │
│                              │  Flattened Event│                                 │
│                              └────────┬────────┘                                 │
│                                       │                                          │
│                                       ▼                                          │
│                     ┌─────────────────────────────────┐                          │
│                     │ result_status in                │                          │
│                     │ SECURITY_FAILURE_STATUSES?      │                          │
│                     │ (UNAUTHENTICATED, PERMISSION_   │                          │
│                     │  DENIED, UNAUTHORIZED...)       │                          │
│                     └─────────────┬───────────────────┘                          │
│                            YES    │    NO                                        │
│                    ┌──────────────┴──────────────┐                               │
│                    ▼                              ▼                               │
│            ┌───────────────┐        ┌─────────────────────────┐                  │
│            │   CRITICAL    │        │     granted == false?   │                  │
│            │ Security fail │        └───────────┬─────────────┘                  │
│            └───────────────┘               YES  │  NO                            │
│                                    ┌────────────┴──────────────┐                 │
│                                    ▼                            ▼                │
│                     ┌──────────────────────────┐    ┌────────────────────────┐   │
│                     │ method in AUTHORIZATION_ │    │ method in              │   │
│                     │ CHECK_METHODS?           │    │ CRITICAL_METHODS?      │   │
│                     │ (mds.Authorize,          │    │ (DeleteKafkaCluster,   │   │
│                     │  flink.Authorize...)     │    │  kafka.DeleteTopics...)│   │
│                     └────────────┬─────────────┘    └───────────┬────────────┘   │
│                           YES    │   NO                   YES   │   NO           │
│                    ┌─────────────┴─────┐                 ┌──────┴──────┐         │
│                    ▼                   ▼                 ▼              ▼        │
│            ┌───────────────┐   ┌───────────────┐  ┌───────────┐  ┌──────────┐   │
│            │    MEDIUM     │   │   CRITICAL    │  │ CRITICAL  │  │ Continue │   │
│            │ Routine check │   │ Denied on     │  │ Dangerous │  │ checking │   │
│            └───────────────┘   │ sensitive op  │  │ operation │  └──────────┘   │
│                                └───────────────┘  └───────────┘                  │
│                                                                                  │
│  ... continues checking HIGH_METHODS, MEDIUM_METHODS, patterns ...               │
│                                                                                  │
│                              DEFAULT: LOW                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Classification Categories:**

| Level | Trigger | Example Methods | Response Time |
|-------|---------|-----------------|---------------|
| **CRITICAL** | Destructive ops, security failures | `DeleteKafkaCluster`, `kafka.DeleteTopics`, `PERMISSION_DENIED` | Immediate |
| **HIGH** | Credential ops, permission changes | `CreateApiKey`, `DeleteServiceAccount`, `CreateRoleBinding` | Hours |
| **MEDIUM** | Config changes, resource creation | `kafka.CreateTopics`, `UpdateKafkaCluster`, `CreateConnector` | Daily |
| **LOW** | Read ops, routine activity | `kafka.Fetch`, `kafka.Produce`, `mds.Authorize` (granted) | Archive |

**Why this classification approach:**
1. **Security-first**: Security failures always CRITICAL regardless of method
2. **Intent-based**: `granted=false` on sensitive ops indicates attack attempt
3. **Routine filtering**: `mds.Authorize` denials are routine RBAC checks, not security events (prevents alert fatigue)
4. **Pattern fallback**: Unknown methods classified by naming patterns (Delete→HIGH, Create→MEDIUM)

---

### Phase 4: Routing (src/routing/topic_router.py)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           ROUTING DECISION                                       │
│                                                                                  │
│                        ┌────────────────────┐                                    │
│                        │ Classified Event   │                                    │
│                        │ criticality=MEDIUM │                                    │
│                        └─────────┬──────────┘                                    │
│                                  │                                               │
│                                  ▼                                               │
│                    ┌─────────────────────────────┐                               │
│                    │ DROP_LOW_EVENTS enabled?    │                               │
│                    └──────────────┬──────────────┘                               │
│                            YES    │    NO                                        │
│                    ┌──────────────┴──────────────┐                               │
│                    ▼                              ▼                               │
│         ┌──────────────────────┐    ┌──────────────────────┐                     │
│         │ criticality == LOW?  │    │   Route to topic     │                     │
│         └──────────┬───────────┘    └──────────────────────┘                     │
│              YES   │    NO                                                       │
│         ┌──────────┴──────────┐                                                  │
│         ▼                      ▼                                                  │
│  ┌─────────────┐    ┌──────────────────────────────────────────────────────────┐ │
│  │   DROP      │    │                 TOPIC MAPPING                            │ │
│  │   Event     │    │                                                          │ │
│  │   (89%      │    │   CRITICAL  →  audit_events_critical                     │ │
│  │   savings)  │    │   HIGH      →  audit_events_high                         │ │
│  └─────────────┘    │   MEDIUM    →  audit_events_medium                       │ │
│                     │   LOW       →  audit_events_low                          │ │
│                     │                                                          │ │
│                     │   + Optional: audit_events_all (unified topic)           │ │
│                     └──────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Why multi-topic routing:**

| Benefit | Explanation |
|---------|-------------|
| **Tiered Retention** | CRITICAL: 90 days, HIGH: 30 days, MEDIUM: 14 days, LOW: 7 days |
| **Targeted Alerting** | Only subscribe to CRITICAL topic for PagerDuty |
| **Cost Optimization** | DROP_LOW_EVENTS reduces 89% of storage/throughput |
| **Separate Processing** | Different consumer groups for different purposes |

**Cost Impact:**
- Without DROP_LOW_EVENTS: ~10K events/min → $XXX/month storage
- With DROP_LOW_EVENTS: ~1.1K events/min → 89% cost reduction

---

### Phase 5: Denial Aggregation (src/aggregation/denial_aggregator.py)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    DENIAL AGGREGATION FLOW                                       │
│                                                                                  │
│  Problem: mds.Authorize with granted=false generates 1000s of events/minute     │
│  Solution: Aggregate into summary alerts                                         │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  Incoming Events (granted=false on mds.Authorize, flink.Authorize, etc.)   │ │
│  └────────────────────────────────────┬───────────────────────────────────────┘ │
│                                       │                                          │
│                                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                        AGGREGATION BUCKETS                                 │ │
│  │                                                                            │ │
│  │  Key: (principal, resource_type, operation)                                │ │
│  │                                                                            │ │
│  │  Bucket Example:                                                           │ │
│  │  ┌──────────────────────────────────────────────────────────────────────┐ │ │
│  │  │  principal: "sa-abc123"                                              │ │ │
│  │  │  resource_type: "Topic"                                              │ │ │
│  │  │  operation: "Read"                                                   │ │ │
│  │  │  denial_count: 47                                                    │ │ │
│  │  │  window_start: "2024-12-12T10:00:00Z"                                │ │ │
│  │  │  unique_resources: ["orders", "payments", "users"]                   │ │ │
│  │  │  unique_ips: ["1.2.3.4", "5.6.7.8"]                                  │ │ │
│  │  └──────────────────────────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────┬───────────────────────────────────────┘ │
│                                       │                                          │
│                        Window expires (60s default)                              │
│                                       │                                          │
│                                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                    THRESHOLD EVALUATION                                    │ │
│  │                                                                            │ │
│  │  denial_count >= 20  →  HIGH alert (possible attack)                       │ │
│  │  denial_count >= 5   →  MEDIUM alert (misconfiguration)                    │ │
│  │  denial_count < 5    →  No alert (normal behavior)                         │ │
│  └────────────────────────────────────┬───────────────────────────────────────┘ │
│                                       │                                          │
│                                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                    OUTPUT: AGGREGATED ALERT                                │ │
│  │                                                                            │ │
│  │  → Produce to: security_alerts topic                                       │ │
│  │  → Send to: Slack webhook (if HIGH)                                        │ │
│  │                                                                            │ │
│  │  {                                                                         │ │
│  │    "alert_type": "aggregated_authorization_denials",                       │ │
│  │    "severity": "HIGH",                                                     │ │
│  │    "principal": "sa-abc123",                                               │ │
│  │    "denial_count": 47,                                                     │ │
│  │    "window_seconds": 60,                                                   │ │
│  │    "resources": ["orders", "payments", "users"],                           │ │
│  │    "source_ips": ["1.2.3.4", "5.6.7.8"],                                   │ │
│  │    "recommendation": "Check service account permissions for Topic/Read"    │ │
│  │  }                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Why aggregation instead of direct alerting:**
1. **Volume**: 1000s of denial events/minute → 1 summary alert
2. **Context**: Single event says nothing; 47 denials from same principal = pattern
3. **Actionability**: "sa-abc123 denied 47 times on Topic/Read" is actionable

---

### Phase 6: Real-time Alerting (src/alerting/webhook_sender.py)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         ALERTING PIPELINE                                        │
│                                                                                  │
│  Trigger Points:                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  1. CRITICAL event detected (DeleteKafkaCluster, etc.)                     │ │
│  │  2. Built-in alert rule matched (kafka.DeleteTopics, CreateApiKey, etc.)   │ │
│  │  3. Aggregated denial threshold exceeded (HIGH: 20+, MEDIUM: 5+)           │ │
│  │  4. Anomaly detected (rate spike, auth failure burst)                      │ │
│  └────────────────────────────────────┬───────────────────────────────────────┘ │
│                                       │                                          │
│                                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                    WEBHOOK SENDER                                          │ │
│  │                                                                            │ │
│  │  Supported Platforms:                                                      │ │
│  │  • Slack (SLACK_WEBHOOK_URL)                                               │ │
│  │  • Microsoft Teams (MS_TEAMS_WEBHOOK_URL)                                  │ │
│  │  • PagerDuty (PAGERDUTY_ROUTING_KEY)                                       │ │
│  │  • Generic webhook (GENERIC_WEBHOOK_URL)                                   │ │
│  │                                                                            │ │
│  │  Features:                                                                 │ │
│  │  • Retry with exponential backoff (tenacity: 3 retries, 1-10s delays)      │ │
│  │  • Platform-specific formatting (Slack blocks, Teams cards)                │ │
│  │  • Rate limiting to prevent alert storms                                   │ │
│  └────────────────────────────────────┬───────────────────────────────────────┘ │
│                                       │                                          │
│                                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                    SLACK MESSAGE EXAMPLE                                   │ │
│  │                                                                            │ │
│  │  ┌────────────────────────────────────────────────────────────────────┐   │ │
│  │  │  🚨 CRITICAL: Kafka cluster deleted                                │   │ │
│  │  │                                                                    │   │ │
│  │  │  Method: DeleteKafkaCluster                                        │   │ │
│  │  │  Principal: sa-admin-xyz                                           │   │ │
│  │  │  Resource: lkc-production-001                                      │   │ │
│  │  │  Time: 2024-12-12T10:15:23Z                                        │   │ │
│  │  │  Source IP: 203.0.113.42                                           │   │ │
│  │  │                                                                    │   │ │
│  │  │  [View in Dashboard] [View Raw Event]                              │   │ │
│  │  └────────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Dashboard Visualization

### Data Loading Flow (dashboard/data/kafka_consumer.py)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    DASHBOARD DATA LOADING                                        │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  User selects: Criticality=HIGH, Time=1 hour                               │ │
│  └────────────────────────────────────┬───────────────────────────────────────┘ │
│                                       │                                          │
│                                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  TOPIC SELECTION                                                           │ │
│  │                                                                            │ │
│  │  Criticality=All      → [audit_events_critical, high, medium]              │ │
│  │  Criticality=CRITICAL → [audit_events_critical]                            │ │
│  │  Criticality=HIGH     → [audit_events_high]                                │ │
│  │  Criticality=MEDIUM   → [audit_events_medium]                              │ │
│  └────────────────────────────────────┬───────────────────────────────────────┘ │
│                                       │                                          │
│                                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  PARALLEL PARTITION READING (Optimized)                                    │ │
│  │                                                                            │ │
│  │  For each topic:                                                           │ │
│  │    For each partition:                                                     │ │
│  │      1. Get watermark offsets (low, high)                                  │ │
│  │      2. Calculate start_offset = high - (max_events / partitions)          │ │
│  │      3. Seek to start_offset                                               │ │
│  │      4. Consume forward to high                                            │ │
│  │                                                                            │ │
│  │  Strategy: Read LATEST N events, not oldest                                │ │
│  └────────────────────────────────────┬───────────────────────────────────────┘ │
│                                       │                                          │
│                                       ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │  POST-PROCESSING                                                           │ │
│  │                                                                            │ │
│  │  1. Deduplicate: (time, principal, methodName, resourceName)               │ │
│  │  2. Time filter: events within selected time window                        │ │
│  │  3. Enhance: add computed columns (is_failure, is_deletion, user_display)  │ │
│  │  4. Email enrichment: resolve sa-xxx → email via Confluent Cloud IAM API   │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Dashboard Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         DASHBOARD STRUCTURE                                      │
│                                                                                  │
│  dashboard/                                                                      │
│  ├── app.py                    # Main entry (229 lines, down from 2667)          │
│  ├── config.py                 # All configuration, themes, CSS                  │
│  │                                                                               │
│  ├── data/                     # Data layer                                      │
│  │   ├── kafka_consumer.py     # Kafka loading with parallel partition read      │
│  │   ├── transformations.py    # DataFrame processing, anomaly detection         │
│  │   ├── email_cache.py        # LRU cache for email resolution                  │
│  │   └── export.py             # CSV/JSON export functions                       │
│  │                                                                               │
│  ├── components/               # Reusable UI components                          │
│  │   ├── metrics.py            # Metric cards                                    │
│  │   ├── filters.py            # Quick filters, alert banners                    │
│  │   └── charts.py             # Chart components                                │
│  │                                                                               │
│  └── tabs/                     # Tab modules (one file per tab)                  │
│      ├── audit_trail.py        # Main event table                                │
│      ├── failures.py           # Authorization failures                          │
│      ├── deletions.py          # Deletion events                                 │
│      ├── api_keys.py           # API key operations                              │
│      ├── security.py           # Security events                                 │
│      ├── details.py            # Event detail view with JSON                     │
│      ├── analytics.py          # Charts and statistics                           │
│      ├── time_insights.py      # Temporal analysis                               │
│      ├── export.py             # Export functionality                            │
│      └── security_alerts.py    # Aggregated denial alerts                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Design Decisions & Rationale

### 1. Why Python + Kafka Direct (No Flink)?

| Factor | Flink Approach | Kafka Direct (This Solution) |
|--------|---------------|------------------------------|
| **Cost** | ~$1,171/month (Flink pool) | ~$770/month |
| **Complexity** | SQL + Java/Scala runtime | Python (simple, debuggable) |
| **Latency** | Sub-second | 1-5 seconds |
| **Maintenance** | Flink versions, SQL syntax | pip install, Docker |
| **Flexibility** | Limited by Flink SQL | Full Python ecosystem |

**Decision:** For audit log processing, sub-second latency isn't required. The $401/month savings and reduced complexity justified the Kafka Direct approach.

### 2. Why orjson Instead of json?

```python
# Before (json module)
import json
data = json.loads(msg.value())  # ~500μs per event

# After (orjson)
import orjson
data = orjson.loads(msg.value())  # ~150μs per event (3x faster)
```

**Impact:** At 10K events/min, saves ~35 seconds/minute of CPU time.

### 3. Why DROP_LOW_EVENTS?

Analysis of real audit log traffic:

| Criticality | % of Events | Example Events |
|-------------|-------------|----------------|
| LOW | 89% | kafka.Fetch, kafka.Produce, mds.Authorize (granted) |
| MEDIUM | 8% | kafka.CreateTopics, UpdateConnector |
| HIGH | 2.5% | CreateApiKey, CreateRoleBinding |
| CRITICAL | 0.5% | DeleteKafkaCluster, PERMISSION_DENIED |

**Decision:** LOW events are routine operations that rarely need investigation. Dropping them reduces storage by 89% with minimal information loss.

### 4. Why Aggregate Authorization Denials?

```
Without aggregation:
  10:00:00 - mds.Authorize denied for sa-xxx on Topic/orders
  10:00:00 - mds.Authorize denied for sa-xxx on Topic/orders
  10:00:01 - mds.Authorize denied for sa-xxx on Topic/orders
  ... (47 more identical events) ...

With aggregation:
  10:01:00 - ALERT: sa-xxx denied 47 times on Topic/Read in 60s
             Resources: orders, payments, users
             Recommendation: Check service account permissions
```

**Decision:** Individual denial events are noise. Aggregated alerts are actionable.

### 5. Why Multi-Topic Routing?

**Operational Benefits:**

1. **Separate Retention Policies:**
   ```
   audit_events_critical: retention.ms=7776000000 (90 days)
   audit_events_high:     retention.ms=2592000000 (30 days)
   audit_events_medium:   retention.ms=1209600000 (14 days)
   ```

2. **Targeted Subscriptions:**
   - PagerDuty: Subscribe only to `audit_events_critical`
   - Security team: Subscribe to `critical` + `high`
   - Compliance: Subscribe to all topics

3. **Different Processing:**
   - CRITICAL: Real-time alerting, immediate investigation
   - HIGH: Daily security review
   - MEDIUM: Weekly configuration audit

### 6. Why LRU Cache for Email Resolution?

```python
# Problem: Confluent IAM API rate limits
# 1000+ events with same principal = 1000+ API calls = rate limited

# Solution: LRU cache
from cachetools import LRUCache
GLOBAL_EMAIL_CACHE = LRUCache(maxsize=10000)

# First event: API call, cache result
# Next 999 events: Cache hit, no API call
```

**Impact:** Reduces IAM API calls by 99%+ for typical workloads.

### 7. Why Modular Dashboard Architecture?

**Before (v10.14):**
- Single `app.py`: 2,667 lines
- Hard to maintain, test, or extend
- Merge conflicts on every change

**After (v10.15):**
- Main `app.py`: 229 lines
- 10 separate tab modules
- Clear separation of concerns
- Easy to add new tabs

---

## Summary: Complete Event Lifecycle

```
1. CONSUME     → Kafka consumer polls 5000 events from audit-log-events

2. PARSE       → orjson.loads() deserializes CloudEvents JSON (3x faster)

3. FLATTEN     → Extract nested fields to top-level (principal, clientId, clientIp)
                 Extract IDs from CRN strings (organization_id, cluster_id)

4. CLASSIFY    → Apply criticality rules:
                 - Security failures → CRITICAL
                 - Denied sensitive ops → CRITICAL
                 - Method-based lookup → CRITICAL/HIGH/MEDIUM/LOW
                 - Pattern matching for unknown methods

5. AGGREGATE   → Group authorization denials by (principal, resource_type, operation)
                 Flush as summary alerts when window expires

6. ROUTE       → Send to criticality-specific topic:
                 - CRITICAL → audit_events_critical
                 - HIGH → audit_events_high
                 - MEDIUM → audit_events_medium
                 - LOW → DROP (if DROP_LOW_EVENTS) or audit_events_low

7. ALERT       → For CRITICAL events or HIGH aggregated alerts:
                 - Send Slack/Teams/PagerDuty webhook
                 - Retry with exponential backoff

8. VISUALIZE   → Dashboard reads from destination topics:
                 - Parallel partition reading for performance
                 - Time-based filtering
                 - Email enrichment via IAM API (cached)
                 - 10 specialized tabs for different views
```

---

**Document Version:** 2.1.0
**Last Updated:** December 12, 2025
