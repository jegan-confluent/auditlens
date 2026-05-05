# Confluent Cloud Audit Log Analyzer - Comprehensive Handoff Document

**Session Date:** December 3, 2025
**Status:** Working System - Ready for Production Planning
**Next Session Priority:** Test Streamlit Dashboard, Configure Alerting

---

## Table of Contents

1. [Previous Context](#1-previous-context)
2. [Project Overview](#2-project-overview)
3. [Technical Architecture](#3-technical-architecture)
4. [Application Flow](#4-application-flow)
5. [Current Session Achievements](#5-current-session-achievements)
6. [Implementation Status](#6-implementation-status)
7. [Technical Context](#7-technical-context)
8. [Decision Log](#8-decision-log)
9. [Issues Faced & Resolutions](#9-issues-faced--resolutions)
10. [Next Steps](#10-next-steps)
11. [Blockers/Dependencies](#11-blockersdependencies)
12. [References](#12-references)

---

## 1. Previous Context

### Original Vision (from ARCHITECTURE.md, DESIGN_REVIEW.md)
The project was originally designed with three architecture options:

1. **Option 1: Tableflow + Flink (AWS only)** - Serverless, Iceberg tables, Athena integration
2. **Option 2: Python Forwarder (Multi-Cloud)** - Custom processing, S3/GCS sinks, MCP integration
3. **Option 3: Hybrid** - Both paths for multi-cloud organizations

### What Was Planned vs What We Built

| Planned Feature | Status | Notes |
|-----------------|--------|-------|
| Flink SQL for flattening | Abandoned | Moved to Python forwarder for simplicity |
| Python forwarder with transforms | **BUILT** | Working, producing to destination |
| S3/GCS Parquet sinks | Not built | Future enhancement |
| MCP Server integration | Not built | Future enhancement |
| Streamlit Dashboard | **BUILT** | New addition this session |
| CLI Query Tool | **BUILT** | Working with Schema Registry handling |
| Docker Compose stack | **BUILT** | Forwarder + Prometheus + Grafana + Loki |

### Key Pivots Made

1. **Flink SQL → Python**: Originally planned pure Flink SQL approach, but pivoted to Python forwarder for:
   - Better control over transformation logic
   - Simpler debugging
   - No CFU costs during development

2. **Flink for querying only**: Now using Flink SQL as a query layer, not for ETL

3. **Added Streamlit**: User wanted a visual UI instead of CLI-only queries

---

## 2. Project Overview

### Value Proposition
**"Answer 'who did what, when?' in Confluent Cloud in seconds, not hours."**

Confluent Cloud audit logs are:
- Stored in a **read-only** cluster managed by Confluent
- Complex nested CloudEvents JSON format
- 7-day default retention (need longer retention)
- Not directly queryable with simple SQL

This tool:
- Forwards audit events to your own cluster
- Flattens nested JSON to queryable columns
- Provides multiple query interfaces (CLI, Web UI, Flink SQL)
- Enables long-term retention and compliance

### Target Users

| Role | Use Case |
|------|----------|
| **Security Teams** | Investigate auth failures, track suspicious IPs, monitor access |
| **Platform Engineers** | Track resource changes, debug issues, audit deletions |
| **Compliance Officers** | Generate audit trails, deletion reports, access logs |
| **DevOps/SRE** | Operational visibility, troubleshooting, change tracking |

### Core Functionality

```
┌─────────────────────────────┐     ┌─────────────────────────────┐
│  AUDIT LOG CLUSTER          │     │  YOUR CLUSTER               │
│  (Managed by Confluent)     │     │  (You control)              │
│                             │     │                             │
│  confluent-audit-log-events │────▶│  audit_events_flattened     │
│  (nested CloudEvents JSON)  │     │  (flat, queryable JSON)     │
│                             │     │                             │
│  ~764M messages             │     │  Schema Registry validated  │
│  12 partitions              │     │  cleanup.policy=compact     │
└─────────────────────────────┘     └─────────────────────────────┘
              │                                    │
              │         PYTHON FORWARDER           │
              │    ┌─────────────────────────┐     │
              └───▶│ • Consume from audit    │─────┘
                   │ • Flatten nested JSON   │
                   │ • Generate message keys │
                   │ • Produce with Schema   │
                   │ • Persist offsets       │
                   │ • Expose metrics        │
                   └─────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ CLI Tool │   │ Streamlit│   │ Flink    │
        │ query.py │   │ Dashboard│   │ SQL      │
        └──────────┘   └──────────┘   └──────────┘
```

---

## 3. Technical Architecture

### Infrastructure Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CONFLUENT CLOUD                                 │
├─────────────────────────────────┬───────────────────────────────────────────┤
│   AUDIT LOG CLUSTER (Source)    │    CUSTOMER CLUSTER (Destination)         │
│   Region: us-east-2 (AWS)       │    Region: ap-south-1 (AWS)               │
│   Cluster: pkc-921jm            │    Cluster: pkc-v3rm2j (lkc-3q9omo)       │
│                                 │                                           │
│   ┌─────────────────────────┐   │    ┌─────────────────────────┐            │
│   │ confluent-audit-log-    │   │    │ audit_events_flattened  │            │
│   │ events                  │   │    │ (6 partitions)          │            │
│   │ • 12 partitions         │───┼───▶│ • cleanup.policy=compact│            │
│   │ • ~764M total messages  │   │    │ • JSON Schema validated │            │
│   │ • CloudEvents format    │   │    │                         │            │
│   └─────────────────────────┘   │    └─────────────────────────┘            │
│                                 │                                           │
│   API Key: (audit cluster)      │    API Key: RBG2XYYEFWIF2YJB              │
│   Read-only access              │    Write access                           │
│                                 │                                           │
│                                 │    ┌─────────────────────────┐            │
│                                 │    │ Schema Registry         │            │
│                                 │    │ psrc-kk5gg.ap-south-1   │            │
│                                 │    │ JSON Schema for events  │            │
│                                 │    └─────────────────────────┘            │
│                                 │                                           │
│                                 │    ┌─────────────────────────┐            │
│                                 │    │ Flink Compute Pool      │            │
│                                 │    │ lfcp-zx1j13             │            │
│                                 │    │ (for SQL queries)       │            │
│                                 │    └─────────────────────────┘            │
└─────────────────────────────────┴───────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │     LOCAL DOCKER STACK        │
                    │                               │
                    │  ┌─────────────────────────┐  │
                    │  │   audit-forwarder       │  │
                    │  │   Container             │  │
                    │  │   • Python 3            │  │
                    │  │   • confluent-kafka     │  │
                    │  │   • Metrics: :8000      │  │
                    │  └─────────────────────────┘  │
                    │                               │
                    │  ┌─────────────────────────┐  │
                    │  │   Monitoring Stack      │  │
                    │  │   • Prometheus :9090    │  │
                    │  │   • Grafana :3000       │  │
                    │  │   • Loki + Promtail     │  │
                    │  └─────────────────────────┘  │
                    │                               │
                    │  ┌─────────────────────────┐  │
                    │  │   Streamlit Dashboard   │  │
                    │  │   :8501                 │  │
                    │  │   (just created)        │  │
                    │  └─────────────────────────┘  │
                    └───────────────────────────────┘
```

### Tech Stack

| Component | Technology | Version/Details |
|-----------|------------|-----------------|
| **Forwarder** | Python 3 | confluent-kafka, prometheus_client |
| **Schema Registry** | Confluent Cloud | JSON Schema |
| **Monitoring** | Prometheus | v2.47.2 |
| **Dashboards** | Grafana | v10.2.0 |
| **Logging** | Loki + Promtail | v2.9.2 |
| **Web UI** | Streamlit | Latest |
| **SQL Queries** | Confluent Flink | Compute pool lfcp-zx1j13 |
| **Container** | Docker Compose | Multi-service stack |

### Flattened Event Schema

The forwarder transforms nested CloudEvents JSON into flat structure:

```json
{
  "id": "unique-event-uuid",
  "time": "2025-12-03T12:00:00.000Z",
  "type": "io.confluent.kafka.server/authorization",
  "source": "crn://confluent.cloud/organization=.../kafka=lkc-xxx",
  "subject": "crn://confluent.cloud/.../topic=my-topic",
  "specversion": "1.0",

  "principal": "User:sa-abc123",
  "methodName": "kafka.CreateTopics",
  "resourceName": "kafka-cluster/lkc-xxx/topic/my-topic",
  "resourceType": "Topic",
  "serviceName": "crn://.../kafka=lkc-xxx",

  "granted": true,
  "authOperation": "Create",
  "authResourceType": "Topic",
  "authResourceName": "my-topic",

  "clientIp": "10.0.1.100",
  "resultStatus": "SUCCESS",
  "resultMessage": "",

  "originalSize": 2048
}
```

### Key Files

```
/Users/jegan/playground/audit-forwarder/
├── audit_forwarder.py      # Main forwarder (850+ lines)
├── query.py                # CLI query tool (243 lines)
├── dashboard.py            # Streamlit web UI (278 lines) - NEW
├── docker-compose.yml      # Full stack deployment
├── Dockerfile              # Forwarder container image
├── .env                    # Non-sensitive configuration
├── .secrets                # API keys (gitignored)
├── data/
│   └── offsets.json        # Persisted consumer offsets
├── prometheus/
│   └── prometheus.yml      # Prometheus scrape config
├── grafana/
│   ├── provisioning/       # Auto-provisioning config
│   └── dashboards/         # Dashboard JSON files
├── promtail-config.yml     # Log shipping config
├── status.sh               # Quick status check script
├── ARCHITECTURE.md         # Architecture options doc
├── DESIGN_REVIEW.md        # Detailed design document
├── HANDOFF.md              # Previous handoff doc
└── README.md               # User-facing documentation
```

---

## 4. Application Flow

### Data Pipeline Flow

```
1. STARTUP
   ├── Load environment variables (.env, .secrets)
   ├── Load persisted offsets from data/offsets.json
   ├── Initialize Schema Registry client
   ├── Create Kafka consumer (source cluster)
   └── Create Kafka producer (destination cluster)

2. PROCESSING LOOP (continuous)
   ├── Poll messages from confluent-audit-log-events
   ├── For each message:
   │   ├── Deserialize CloudEvents JSON
   │   ├── Extract nested fields:
   │   │   ├── data.authenticationInfo.principal
   │   │   ├── data.authorizationInfo.granted
   │   │   ├── data.methodName
   │   │   ├── data.resourceName
   │   │   ├── data.result.status
   │   │   └── data.requestMetadata.client_address
   │   ├── Flatten to single-level JSON
   │   ├── Generate message key from event ID  ← CRITICAL FIX
   │   ├── Serialize with Schema Registry
   │   └── Produce to audit_events_flattened
   └── Track metrics (processed, errors, lag)

3. OFFSET PERSISTENCE (every 10 seconds)
   └── Save current offsets to data/offsets.json

4. METRICS EXPOSURE (continuous)
   └── Prometheus endpoint on :8000/metrics
```

### Query Flow (CLI - query.py)

```
1. User runs: ./query.py
2. Interactive menu displayed
3. User selects query type (e.g., "Recent events")
4. Consumer created for audit_events_flattened
5. Messages fetched (handling Schema Registry 5-byte header)
6. Events filtered based on selection
7. Results formatted and displayed
```

### Query Flow (Web - dashboard.py)

```
1. User opens: http://localhost:8501
2. Streamlit fetches up to 5000 events from Kafka
3. Events loaded into Pandas DataFrame
4. User applies filters via sidebar:
   ├── Time range (Last 1h, 6h, 24h, 7d)
   ├── Method name
   ├── Principal
   └── Free-text search
5. Metrics cards displayed (totals, unique counts)
6. Events table with color-coded granted column
7. Analytics charts (bar charts, timeline)
8. Raw JSON viewer for individual events
```

### Query Flow (Flink SQL)

```
1. User runs: confluent flink shell --compute-pool lfcp-zx1j13 --environment env-p9r0mo
2. Flink connects to destination cluster
3. User runs SQL:
   SELECT * FROM audit_events_flattened
   WHERE resourceName LIKE '%my-topic%'
   LIMIT 10;
4. Results returned from Kafka topic
```

---

## 5. Current Session Achievements

### Major Bug Fixed: INVALID_RECORD Error

**The Problem:**
- Forwarder showed 3.38M+ messages "processed"
- Destination topic had **0 messages**
- No obvious errors in logs
- Silent failures - produces looked successful

**Discovery Process:**
1. Added delivery callback to producer
2. Found all messages failing with: `Broker: Broker failed to validate record (INVALID_RECORD)`
3. Investigated broker rejection reasons

**Root Cause:**
- Source audit log messages have `key=None` (null keys)
- Destination topic configured with `cleanup.policy=compact`
- **Compacted topics require non-null keys!**

**Fix Applied** (`audit_forwarder.py:413-415`):
```python
# Use event ID as key for compacted topic (source messages have no key)
event_key = flat.get('id', '').encode('utf-8') if flat.get('id') else None
safe_produce(producer, DEST_TOPIC, event_key, value)
```

**Delivery Callback Added** (`audit_forwarder.py:278-288`):
```python
delivery_errors = {"count": 0, "last_error": None}

def delivery_callback(err, msg):
    """Track delivery errors."""
    if err:
        delivery_errors["count"] += 1
        delivery_errors["last_error"] = str(err)
        if delivery_errors["count"] <= 10 or delivery_errors["count"] % 1000 == 0:
            logger.error("Delivery failed (%d total): %s", delivery_errors["count"], err)
        metrics.record_error()
```

### Validation Completed

1. **Created test topic:** `jegan-audit-test-1764757218`
2. **Deleted test topic**
3. **Queried via Python CLI:** Found events
4. **Queried via Flink SQL:**
   ```sql
   SELECT time, methodName, resourceName
   FROM audit_events_flattened
   WHERE resourceName LIKE '%jegan-audit-test%';
   ```
   **Result:** Found 2 CreateTopics events + 1 DeleteTopics event

### Query Tools Built

#### 1. CLI Tool (query.py)
- Interactive menu with 12 query options
- Fixed Schema Registry magic bytes handling (skip 5-byte header)
- Supports: recent events, by user, by method, deletions, creations, auth failures, etc.

#### 2. Streamlit Dashboard (dashboard.py) - NEW
Created a full web UI with:
- **Sidebar Filters:**
  - Time range selector (All, Last 1h, 6h, 24h, 7d)
  - Method name dropdown
  - Principal dropdown
  - Free-text search
- **Metrics Cards:**
  - Total events count
  - Unique methods count
  - Unique principals count
  - Access denied count
- **Quick Filter Buttons:**
  - Deletions
  - Creations
  - Auth Events
  - Topic Ops
  - API Keys
- **Three Tabs:**
  - Events Table (with color-coded granted column - green/red)
  - Analytics (bar charts for methods, principals; timeline chart)
  - Raw Data (JSON viewer for individual events)

### Status After Fixes

```
./status.sh output:
─────────────────────────────────────────
AUDIT FORWARDER STATUS
─────────────────────────────────────────
Container: Running
Processed: 18,XXX+ messages
Errors: 0
Rate: ~50 msg/sec
Consumer Lag: Catching up
─────────────────────────────────────────
```

---

## 6. Implementation Status

### Completed ✅

| Item | Priority | Notes |
|------|----------|-------|
| Two-cluster architecture setup | High | Source audit → Destination customer |
| Python forwarder with transforms | High | Flattens nested JSON to flat structure |
| Schema Registry integration | High | JSON schema validation on produce |
| **CRITICAL FIX: Message key generation** | High | Uses event ID as key for compacted topic |
| Delivery callback for error tracking | High | Now surfaces produce failures |
| Offset persistence (JSON file) | High | Survives restarts |
| Prometheus metrics endpoint | Medium | :8000/metrics |
| Docker Compose stack | Medium | forwarder + prometheus + grafana + loki |
| CLI query tool (query.py) | Medium | 12 query types, interactive menu |
| **NEW: Streamlit dashboard** | Medium | Full web UI at :8501 |
| Flink SQL queries | Medium | Validated working |
| Status script | Low | Quick health check |

### In Progress 🔄

| Item | Priority | Notes |
|------|----------|-------|
| Dashboard testing | Medium | Created, running at :8501, needs user testing |

### Pending ⏳

| Item | Priority | Notes |
|------|----------|-------|
| Production deployment | High | Currently local Docker only |
| Grafana dashboard configuration | Medium | Pre-built dashboards for audit metrics |
| Alerting rules | Medium | Alert on deletions, API keys, auth failures |
| Historical backfill | Low | 764M messages in source, only processing new |
| S3/GCS Parquet export | Low | Original design had this, not implemented |
| MCP Server integration | Low | Original design had this, not implemented |
| Multi-environment support | Low | dev/staging/prod configs |

---

## 7. Technical Context

### Environment Variables

#### .env (non-sensitive)
```bash
# Source (Audit Log Cluster - READ ONLY)
AUDIT_BOOTSTRAP=pkc-921jm.us-east-2.aws.confluent.cloud:9092
AUDIT_TOPIC=confluent-audit-log-events

# Destination (Customer Cluster)
DEST_BOOTSTRAP=pkc-v3rm2j.ap-south-1.aws.confluent.cloud:9092
DEST_TOPIC=audit_events_flattened
SCHEMA_REGISTRY_URL=https://psrc-kk5gg.ap-south-1.aws.confluent.cloud

# Processing
GROUP_ID=audit-forwarder-group
OFFSET_FILE=/app/data/offsets.json
METRICS_PORT=8000
```

#### .secrets (sensitive - gitignored)
```bash
AUDIT_API_KEY=<audit-cluster-api-key>
AUDIT_API_SECRET=<audit-cluster-api-secret>
DEST_API_KEY=RBG2XYYEFWIF2YJB
DEST_API_SECRET=<dest-cluster-api-secret>
SR_API_KEY=<schema-registry-api-key>
SR_API_SECRET=<schema-registry-api-secret>
```

### Important Endpoints

| Service | URL | Credentials |
|---------|-----|-------------|
| Forwarder Metrics | http://localhost:8000/metrics | None |
| Prometheus | http://localhost:9090 | None |
| Grafana | http://localhost:3000 | admin / password |
| **Streamlit Dashboard** | http://localhost:8501 | None |
| Loki | http://localhost:3100 | None |

### Flink Configuration

```bash
# Flink Shell Command
confluent flink shell \
  --compute-pool lfcp-zx1j13 \
  --environment env-p9r0mo

# Useful Flink SQL Queries
SELECT * FROM audit_events_flattened LIMIT 10;

SELECT time, methodName, resourceName, principal
FROM audit_events_flattened
WHERE methodName LIKE '%Delete%'
ORDER BY time DESC;

SELECT methodName, COUNT(*) as cnt
FROM audit_events_flattened
GROUP BY methodName
ORDER BY cnt DESC;
```

### Current Consumer Offsets

From `data/offsets.json`:
```json
{
  "confluent-audit-log-events_0": 63784937,
  "confluent-audit-log-events_1": 63542461,
  "confluent-audit-log-events_2": 63701714,
  "confluent-audit-log-events_3": 63741212,
  "confluent-audit-log-events_4": 63580766,
  "confluent-audit-log-events_5": 64112654,
  "confluent-audit-log-events_6": 63709936,
  "confluent-audit-log-events_7": 63518040,
  "confluent-audit-log-events_8": 63643008,
  "confluent-audit-log-events_9": 63646459,
  "confluent-audit-log-events_10": 63431310,
  "confluent-audit-log-events_11": 64147483
}
```
**Total: ~764M messages in source topic**

---

## 8. Decision Log

### Architecture Decisions

| Decision | Choice | Rationale | Date |
|----------|--------|-----------|------|
| ETL Approach | Python Forwarder | More control than Flink SQL, easier debugging, no CFU costs during dev | Earlier |
| Query Layer | Flink SQL + Streamlit | Flink for SQL queries, Streamlit for visual UI | Dec 3 |
| Offset Storage | Local JSON file | Simple, survives restarts, no external dependency | Earlier |
| Message Keys | Event ID | **CRITICAL** - Required for compacted destination topic | Dec 3 |
| Schema Format | JSON Schema | Matches source format, easier debugging than Avro | Earlier |
| Web UI | Streamlit | Quick to build, interactive, no frontend expertise needed | Dec 3 |
| Monitoring | Prometheus + Grafana | Industry standard, comprehensive | Earlier |

### Debates & Alternatives Considered

| Topic | Options Considered | Final Choice | Why |
|-------|-------------------|--------------|-----|
| UI for queries | Flink Console, Trino+Superset, Streamlit | Streamlit | Easiest, fastest to build, runs locally |
| Flink endpoint | Generic endpoint vs CLI fetch | Use CLI command | CLI provides correct endpoint automatically |
| Message format | Avro vs JSON Schema | JSON Schema | Simpler debugging, source is JSON |

---

## 9. Issues Faced & Resolutions

### Issue 1: INVALID_RECORD - All Messages Rejected (CRITICAL)

**Symptoms:**
- Forwarder processing millions of messages
- Destination topic empty
- No obvious errors

**Investigation:**
1. Added delivery callback
2. Found: `Broker: Broker failed to validate record`

**Root Cause:**
- Source messages have null keys
- Destination topic has `cleanup.policy=compact` requiring keys

**Resolution:**
```python
event_key = flat.get('id', '').encode('utf-8') if flat.get('id') else None
safe_produce(producer, DEST_TOPIC, event_key, value)
```

**Lesson:** Always check topic configuration (compaction, key requirements) when produces fail.

---

### Issue 2: Schema Registry Magic Bytes in Query Tool

**Symptoms:**
- JSON parsing failures in query.py
- `json.JSONDecodeError: Expecting value`

**Root Cause:**
- Schema Registry adds 5-byte header to messages
- Byte 0: Magic byte (0x00)
- Bytes 1-4: Schema ID (4 bytes)

**Resolution** (`query.py:120-126`):
```python
if len(value) > 5 and value[0] == 0:
    json_data = value[5:]  # Skip 5-byte header
else:
    json_data = value
event = json.loads(json_data.decode('utf-8'))
```

---

### Issue 3: API Key Quota Exceeded

**Symptoms:**
- Couldn't create test API key
- Error: quota limit (10 keys max)

**Resolution:**
- Worked around by testing with topic create/delete only
- For production: request quota increase or clean up unused keys

---

### Issue 4: Flink Shell Endpoint Warning

**Symptoms:**
- Warning: "No Flink endpoint is specified"
- User confused about "generic" endpoint

**Explanation:**
- This is informational, not an error
- CLI automatically uses correct public endpoint
- `confluent flink shell` handles endpoint resolution

---

### Issue 5: Streamlit Deprecation Warnings

**Symptoms:**
- `FutureWarning: Styler.applymap has been deprecated`
- `FutureWarning: 'H' is deprecated`

**Resolution:**
```python
# Changed:
display_df.style.applymap(...)  # Old
display_df.style.map(...)       # New

df_time.resample('1H')          # Old
df_time.resample('1h')          # New
```

---

## 10. Next Steps

### Immediate Priorities (Next Session)

1. **Test Streamlit Dashboard**
   - Open http://localhost:8501
   - Search for `jegan-audit-test` to find validation events
   - Test all filters and tabs

2. **Verify Forwarder Stability**
   - Check `docker logs audit-forwarder`
   - Confirm steady message rate
   - Monitor for any errors

3. **Configure Grafana Dashboards**
   - Import/create dashboard for:
     - Events per minute
     - Events by method type
     - Authorization denials
     - Error rate
     - Consumer lag

### Short-Term (This Week)

4. **Set Up Alerting**
   - Prometheus alerting rules for:
     - Any DeleteTopic event
     - API key creation/deletion
     - Auth failure spike
     - Forwarder lag > threshold
     - Error rate > 0

5. **Document Production Deployment**
   - Kubernetes manifests or
   - Cloud Run deployment or
   - ECS Fargate setup

### Medium-Term

6. **Historical Backfill** (Optional)
   - Reset offsets to beginning
   - Process 764M historical messages
   - Estimate: Several hours to days

7. **Add More Aggregations**
   - Pre-computed tables for common queries
   - Hourly/daily summaries

---

## 11. Blockers/Dependencies

### Resolved Blockers ✅

| Blocker | Resolution |
|---------|------------|
| INVALID_RECORD errors | Fixed by adding message keys |
| Schema Registry magic bytes | Fixed by skipping 5-byte header |
| API key quota | Worked around, not blocking |

### Current Blockers

**None** - System is functional

### Potential Future Blockers

| Potential Issue | Mitigation |
|-----------------|------------|
| API key quota (10 max) | Request increase for production |
| Historical backfill time | Run during off-peak, or accept partial history |
| Flink CFU costs | Monitor usage, scale as needed |

### Dependencies for Production

1. **Cloud infrastructure** - K8s cluster, Cloud Run, or ECS
2. **Secret management** - Vault, AWS Secrets Manager, or GCP Secret Manager
3. **CI/CD pipeline** - For automated deployments
4. **Monitoring integration** - PagerDuty/Slack for alerts

---

## 12. References

### Documentation Links

- [Confluent Audit Logs Overview](https://docs.confluent.io/cloud/current/security/audit-logging.html)
- [Audit Log Schema Reference](https://docs.confluent.io/cloud/current/monitoring/audit-logging/audit-log-schema.html)
- [CloudEvents Specification](https://cloudevents.io/)
- [Confluent Flink Documentation](https://docs.confluent.io/cloud/current/flink/)
- [Streamlit Documentation](https://docs.streamlit.io/)

### Project Files

| File | Purpose |
|------|---------|
| `/Users/jegan/playground/audit-forwarder/audit_forwarder.py` | Main forwarder code |
| `/Users/jegan/playground/audit-forwarder/query.py` | CLI query tool |
| `/Users/jegan/playground/audit-forwarder/dashboard.py` | Streamlit web dashboard |
| `/Users/jegan/playground/audit-forwarder/docker-compose.yml` | Full stack deployment |
| `/Users/jegan/playground/audit-forwarder/ARCHITECTURE.md` | Architecture options |
| `/Users/jegan/playground/audit-forwarder/DESIGN_REVIEW.md` | Detailed design |
| `/Users/jegan/playground/audit-forwarder/HANDOFF.md` | Previous handoff |

### Commands Reference

```bash
# Start forwarder stack
cd /Users/jegan/playground/audit-forwarder
docker compose up -d

# Check status
./status.sh

# View forwarder logs
docker logs -f audit-forwarder

# Run CLI queries
./query.py

# Start web dashboard
streamlit run dashboard.py

# Flink SQL shell
confluent flink shell --compute-pool lfcp-zx1j13 --environment env-p9r0mo

# Stop everything
docker compose down
```

---

## Summary for Next Session

### What Works
- Forwarder consuming, transforming, producing ✅
- 18K+ messages successfully processed ✅
- CLI query tool working ✅
- Flink SQL queries working ✅
- Streamlit dashboard created and running ✅

### What to Do Next
1. **Test dashboard** at http://localhost:8501
2. Search for test events (`jegan-audit-test`)
3. Configure Grafana dashboards
4. Set up alerting rules
5. Plan production deployment

### Key Insight from This Session
**Message keys are required for compacted topics.** The source audit log has null keys, so we must generate keys from event IDs when producing to a compacted destination topic.

---

*Document generated: December 3, 2025*
*Session duration: ~2 hours*
*Key fix: Message key generation for compacted topic*
