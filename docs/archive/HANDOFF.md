# AuditLens Project Handoff Document

**Date:** December 11, 2025
**Version:** v10.4
**Author:** Claude (AI Assistant)

---

## Previous Context

### Earlier Handoffs Summary

1. **Initial Build (v10.0):** Created AuditLens package with Kafka audit log forwarder, Streamlit dashboard, Grafana/Prometheus monitoring stack
2. **Deduplication (v10.1):** Implemented `drop_duplicates()` in `enhance_events_dataframe()` using composite key `['time', 'principal', 'methodName', 'resourceName']`
3. **Column Enhancement (v10.2):** Added 15+ new columns across 5 tabs (service, cluster_id, email, topic_name, request_id, operation, acl_host)
4. **Bug Fixes (v10.3):** Fixed `Topic: nan` display bug, fixed raw JSON in user_display column
5. **User ID Enrichment (v10.4):** Added user ID → email mapping for data plane events

### Key Decisions Made

| Decision | Rationale |
|----------|-----------|
| Route by criticality (CRITICAL/HIGH/MEDIUM/LOW) | Enables tiered alerting and storage optimization |
| Drop LOW events by default | 96%+ of events are LOW; reduces noise and cost |
| Build user mapping from audit logs | No need for Cloud API credentials; self-learning |
| Use Streamlit for dashboard | Rapid development, Python-native, good for data apps |
| Deduplicate in dashboard, not forwarder | Preserves raw data; allows re-processing |

---

## Project Overview

### Value Proposition

**AuditLens** transforms Confluent Cloud's raw audit logs into actionable security intelligence by:
- Routing events by criticality for tiered alerting
- Providing real-time visibility into who did what, when, and where
- Detecting anomalies (auth failures, activity spikes)
- Enabling compliance reporting with full audit trail

### Target Users

- **Security Teams:** Monitor access patterns, detect threats
- **Platform Teams:** Track resource changes, debug issues
- **Compliance Officers:** Generate audit reports, prove access controls
- **DevOps Engineers:** Monitor connector/cluster health

### Core Functionality

1. **Audit Forwarder:** Consumes from Confluent Cloud audit log cluster, routes to customer cluster by criticality
2. **Real-time Dashboard:** 9-tab Streamlit UI with filters, charts, export
3. **Anomaly Detection:** Identifies auth failure spikes, unusual activity patterns
4. **User Attribution:** Maps data plane operations to actual users via ID lookup

---

## Technical Architecture

### Infrastructure

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Confluent Cloud                                  │
│  ┌──────────────────┐     ┌──────────────────────────────────────┐ │
│  │ Audit Log Cluster│     │ Customer Destination Cluster          │ │
│  │ (12 partitions)  │────▶│ ├─ audit_events_critical (6 parts)   │ │
│  │                  │     │ ├─ audit_events_high (6 parts)        │ │
│  │                  │     │ ├─ audit_events_medium (6 parts)      │ │
│  └──────────────────┘     │ └─ audit_events_low (optional)        │ │
│                           └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Local Docker Environment                         │
│  ┌────────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ audit-forwarder│  │  dashboard  │  │   grafana   │              │
│  │   (v9.4)       │  │  (v10.4)    │  │  (11.3.1)   │              │
│  │   :8003        │  │   :8503     │  │   :3000     │              │
│  └────────────────┘  └─────────────┘  └─────────────┘              │
│  ┌────────────────┐  ┌─────────────┐                               │
│  │  prometheus    │  │    loki     │                               │
│  │   :9090        │  │   :3100     │                               │
│  └────────────────┘  └─────────────┘                               │
│                                                                     │
│  Network: audit-network                                             │
└─────────────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Forwarder | Python + confluent-kafka | 3.11 |
| Dashboard | Streamlit + Pandas + Plotly | 1.31.0 |
| Monitoring | Grafana + Prometheus | 11.3.1 / 2.54.1 |
| Logging | Loki + Promtail | 3.2.1 |
| Container | Docker + Docker Compose | Latest |

### Database Schema (Kafka Topics)

**Source Topic:** `confluent-audit-log-events` (12 partitions)

**Destination Topics:**

| Topic | Partitions | Retention | Purpose |
|-------|------------|-----------|---------|
| `audit_events_critical` | 6 | 30 days | Security events, deletions |
| `audit_events_high` | 6 | 14 days | Create operations, config changes |
| `audit_events_medium` | 6 | 7 days | Read operations, auth checks |
| `audit_events_low` | 6 | 3 days | Routine operations (optional) |

### Key Integrations

1. **Confluent Cloud IAM API:** (Commented out) For user lookup
2. **Kafka Consumer/Producer:** confluent-kafka Python library
3. **Prometheus Metrics:** Exposed on :8003/metrics

---

## Application Flow

### User Journey: Security Analyst

```
1. Open Dashboard (localhost:8503)
         │
         ▼
2. Select Time Range (Last 24h default)
         │
         ▼
3. Apply Quick Filters:
   ├── By Email (dropdown)
   ├── By Service (kafka/connect/flink)
   ├── By Action (Create/Delete/Read)
   └── By Status (Success/Denied)
         │
         ▼
4. Review Tabs:
   ├── Audit Trail (all events)
   ├── All Failures (denied access)
   ├── Deletions (resource removal)
   ├── API Keys (key operations)
   ├── Security (RBAC/ACL)
   ├── Details (single event deep-dive)
   ├── Analytics (charts)
   ├── Time Insights (patterns)
   └── Export (CSV/JSON)
         │
         ▼
5. Export Report for Compliance
```

### System Workflow: Audit Event Processing

```
Confluent Cloud Action (e.g., CreateTopic)
         │
         ▼
Audit Log Generated (~2-5 min delay)
         │
         ▼
audit_forwarder.py consumes from source
         │
         ▼
Classify by criticality:
├── CRITICAL: Deletions, security failures
├── HIGH: Creates, config changes
├── MEDIUM: Reads, auth checks
└── LOW: Routine (dropped by default)
         │
         ▼
Route to destination topic
         │
         ▼
Dashboard polls destination topics
         │
         ▼
enhance_events_dataframe():
├── Extract fields (user, action, resource)
├── Enrich email from cache/mapping
├── Compute display fields
└── Deduplicate
         │
         ▼
Display in Streamlit UI
```

---

## Current Session Achievements

### Completed Today

1. **User ID → Email Enrichment (v10.4)**
   - Built `user_mapping.json` with 33 user ID → email mappings from audit logs
   - Added `extract_user_id()` function to parse various principal formats
   - Enhanced `enrich_email_from_cache()` to look up by user ID
   - Updated `build_cache_from_dataframe()` to cache user IDs separately

2. **Bug Fixes**
   - Fixed `Topic: nan` appearing in Deletions tab (pandas NaN truthiness issue)
   - Fixed raw JSON `{"externalAccount":...}` showing in Who column
   - Enhanced `extract_user_display()` to parse JSON principal strings

3. **Investigation: Live Audit Trail Monitoring**
   - Attempted real-time capture of user actions
   - Identified ~2-5 minute delay in Confluent Cloud audit log propagation
   - Verified forwarder is working (lag=0, data fresh in HIGH/MEDIUM topics)

### Decisions Made Today

| Decision | Rationale |
|----------|-----------|
| Build user mapping from audit logs, not API | Avoids need for Cloud API credentials |
| Triple-check for NaN: `if x and pd.notna(x) and str(x) != 'nan'` | Pandas NaN passes Python truthiness |
| Use 'user' field instead of 'principal' in user_display | 'user' is pre-cleaned by extract_user_display() |

### Unresolved Issue

**Real-time event capture failed** - User performed actions (topics, connectors, schemas, deletions) but events were not captured in polling. Possible causes:
- Different principal format than expected
- Filtering logic issue
- Audit log propagation delay > 5 min

---

## Implementation Status

### Completed ✅

| Item | Priority | Notes |
|------|----------|-------|
| ✅ Audit forwarder with criticality routing | High | v9.4 deployed |
| ✅ Streamlit dashboard with 9 tabs | High | v10.4 deployed |
| ✅ Email cache for user lookup | High | Works for Cloud API events |
| ✅ User ID → email mapping | High | 33 users mapped |
| ✅ Deduplication in dashboard | Medium | Composite key dedup |
| ✅ Column enhancements (15+ columns) | Medium | All 5 table tabs updated |
| ✅ Bug fix: nan in resource display | Medium | pd.notna() check added |
| ✅ Bug fix: JSON in user_display | Medium | JSON parsing added |
| ✅ Grafana dashboards | Low | 4 pre-configured dashboards |
| ✅ Prometheus alerting rules | Low | In prometheus/audit-forwarder.yml |
| ✅ Clean AuditLens package | Low | Ready for distribution |

### In Progress 🔄

| Item | Priority | Blocker |
|------|----------|---------|
| 🔄 Real-time user action tracking | High | Events not captured; needs debugging |
| 🔄 Data plane event attribution | High | Depends on user mapping completeness |

### Pending ⏳

| Item | Priority | Effort |
|------|----------|--------|
| ⏳ Cloud API integration for user lookup | Medium | Requires API credentials |
| ⏳ Service account → owner mapping | Medium | Need SA ownership data |
| ⏳ Numeric User:NNNNN format mapping | Medium | Format unclear |
| ⏳ Real-time WebSocket updates | Low | Current polling is sufficient |
| ⏳ Multi-tenancy support | Low | Single org currently |
| ⏳ Custom alerting rules UI | Low | Use Grafana for now |

---

## Technical Context

### Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Non-sensitive config (bootstrap servers, topic names) |
| `.secrets` | Sensitive credentials (API keys) |
| `docker-compose.yml` | Service orchestration |
| `prometheus/prometheus.yml` | Scrape config |
| `grafana/provisioning/` | Dashboard/datasource auto-provisioning |

### Environment Variables

```bash
# .env
AUDIT_BOOTSTRAP=pkc-xxxxx.region.cloud:9092
DEST_BOOTSTRAP=pkc-yyyyy.region.cloud:9092
AUDIT_TOPIC=confluent-audit-log-events
DEST_TOPIC_CRITICAL=audit_events_critical
DEST_TOPIC_HIGH=audit_events_high
DEST_TOPIC_MEDIUM=audit_events_medium
DROP_LOW_EVENTS=true
ENABLE_MULTI_TOPIC_ROUTING=true

# .secrets
AUDIT_API_KEY=xxxxxxxxxx
AUDIT_API_SECRET=xxxxxxxxxx
DEST_API_KEY=xxxxxxxxxx
DEST_API_SECRET=xxxxxxxxxx
# CONFLUENT_CLOUD_API_KEY=  (commented out)
# CONFLUENT_CLOUD_API_SECRET=  (commented out)
```

### API Endpoints

| Endpoint | Port | Purpose |
|----------|------|---------|
| Dashboard | 8503 | Streamlit UI |
| Forwarder Metrics | 8003 | Prometheus metrics |
| Grafana | 3000 | Monitoring dashboards |
| Prometheus | 9090 | Metrics storage |
| Loki | 3100 | Log aggregation |

### Key Files and Line Numbers

| File | Lines | Function |
|------|-------|----------|
| `dashboard/app.py:147-175` | `extract_user_id()` | Parse user ID from principal |
| `dashboard/app.py:177-202` | `enrich_email_from_cache()` | Email lookup by user ID |
| `dashboard/app.py:204-230` | `build_cache_from_dataframe()` | Build cache from events |
| `dashboard/app.py:232-242` | `load_user_mapping()` | Load pre-built mapping |
| `dashboard/app.py:763-795` | `extract_user_display()` | Parse principal to display name |
| `dashboard/app.py:793-801` | `format_resource_for_display()` | NaN-safe resource formatting |
| `dashboard/app.py:1255-1266` | Cache merge + rebuild | Email enrichment pipeline |
| `audit_forwarder.py:200-300` | Criticality classification | Event routing logic |

---

## Decision Log

| # | Decision | Options Considered | Chosen | Rationale |
|---|----------|-------------------|--------|-----------|
| 1 | Deduplication location | Forwarder vs Dashboard | Dashboard | Preserves raw data; allows schema evolution |
| 2 | User mapping source | Cloud API vs Audit logs | Audit logs | No extra credentials; self-learning |
| 3 | NaN handling | Single check vs Triple check | Triple | `pd.notna()` alone doesn't catch string 'nan' |
| 4 | Principal field for display | 'principal' vs 'user' | 'user' | 'user' is pre-cleaned |
| 5 | LOW event handling | Route vs Drop | Drop (96.5%) | Reduces noise and storage |
| 6 | Dashboard framework | Streamlit vs Dash vs React | Streamlit | Fastest development; Python-native |

---

## Next Steps

### Immediate Priorities (Today/Tomorrow)

1. **Debug Real-time Event Capture** (HIGH)
   - Review `dashboard/app.py` lines 147-202 for filtering logic
   - Check if principal format differs from expected `u-xxxxx`
   - Test with known event and verify it appears
   - Add logging to trace why events are filtered out

2. **Verify User Mapping Completeness** (HIGH)
   - Check if your user ID is in `user_mapping.json`
   - Run: `grep "jnagarajan" dashboard/user_mapping.json`
   - Add missing mappings manually if needed

3. **Test Data Plane Attribution** (HIGH)
   - Create a topic via CLI with known API key
   - Verify event shows correct email in dashboard

### Recommended Approach for Continuation

```bash
# 1. Check current state
cd /Users/jegan/playground/audit-forwarder
docker ps  # Verify all services running
curl -s http://localhost:8503 | grep v10  # Check dashboard version

# 2. Verify user mapping
cat dashboard/user_mapping.json | grep -i jnagarajan

# 3. Check forwarder logs for recent events
docker logs audit-forwarder --tail 50 | grep -i jnagarajan

# 4. Check destination topics for your events
source .secrets
timeout 30 confluent kafka topic consume audit_events_high \
  --from-beginning \
  --bootstrap $DEST_BOOTSTRAP \
  --api-key $DEST_API_KEY \
  --api-secret $DEST_API_SECRET | grep -i jnagarajan

# 5. If events missing, check source audit log
timeout 30 confluent kafka topic consume confluent-audit-log-events \
  --bootstrap $AUDIT_BOOTSTRAP \
  --api-key $AUDIT_API_KEY \
  --api-secret $AUDIT_API_SECRET | grep -i jnagarajan
```

---

## Blockers/Dependencies

### Active Blockers

| Blocker | Impact | Owner | Resolution |
|---------|--------|-------|------------|
| Real-time event capture not working | Cannot demo live audit trail | Developer | Debug filtering logic |
| Audit log propagation delay (2-5 min) | Events appear delayed | Confluent Cloud | Expected behavior; document it |

### Dependencies

| Dependency | Status | Required For |
|------------|--------|--------------|
| Confluent Cloud audit log access | ✅ Working | Event ingestion |
| Destination cluster access | ✅ Working | Event storage |
| Docker environment | ✅ Running | All services |
| Cloud API credentials | ⏳ Not configured | Direct user lookup (optional) |

---

## References

### Project Repositories

- **Working Directory:** `/Users/jegan/playground/audit-forwarder`
- **Clean Package:** `/Users/jegan/playground/AuditLens`

### Documentation

- [Confluent Cloud Audit Logs](https://docs.confluent.io/cloud/current/monitoring/audit-logging.html)
- [Streamlit Documentation](https://docs.streamlit.io/)
- [confluent-kafka Python](https://docs.confluent.io/platform/current/clients/confluent-kafka-python/html/index.html)

### File Structure

```
/Users/jegan/playground/audit-forwarder/
├── audit_forwarder.py          # Main forwarder (36KB)
├── Dockerfile                  # Forwarder container
├── docker-compose.yml          # Service orchestration
├── .env                        # Configuration
├── .secrets                    # Credentials (gitignored)
├── requirements.txt            # Python dependencies
├── HANDOFF.md                  # This document
├── dashboard/
│   ├── app.py                  # Streamlit dashboard (v10.4)
│   ├── Dockerfile              # Dashboard container
│   ├── requirements.txt        # Dashboard dependencies
│   ├── user_mapping.json       # User ID → email mapping
│   └── static/logo.png         # Confluent logo
├── grafana/
│   ├── dashboards/             # 4 JSON dashboard files
│   └── provisioning/           # Datasource configs
├── prometheus/
│   ├── prometheus.yml          # Scrape config
│   └── audit-forwarder.yml     # Alert rules
└── scripts/
    ├── setup.sh                # One-click deploy
    ├── verify.sh               # Health check
    ├── stop.sh                 # Stop services
    └── logs.sh                 # View logs
```

### Running Services

```
CONTAINER       IMAGE                    PORT      STATUS
dashboard       audit-dashboard:v10.4    8503      Up
audit-forwarder audit-forwarder:v9.4     8003      Up (healthy)
audit-grafana   grafana/grafana:11.3.1   3000      Up
audit-prometheus prom/prometheus:v2.54.1  9090      Up
loki            grafana/loki:3.2.1       3100      Up
promtail        grafana/promtail:3.2.1   -         Up
```

---

## Quick Commands

```bash
# Rebuild dashboard after code changes
cd /Users/jegan/playground/AuditLens
docker build -t audit-dashboard:v10.5 dashboard/
docker stop dashboard && docker rm dashboard
docker run -d --name dashboard \
  --env-file /Users/jegan/playground/audit-forwarder/.env \
  --env-file /Users/jegan/playground/audit-forwarder/.secrets \
  -p 8503:8501 audit-dashboard:v10.5
docker network connect audit-network dashboard

# View dashboard logs
docker logs dashboard -f

# Restart forwarder
docker restart audit-forwarder

# Check all service status
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

---

**End of Handoff Document**
