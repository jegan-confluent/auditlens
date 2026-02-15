# Confluent Audit Log Intelligence System - Architecture Overview

**Document Version:** 1.0
**Last Updated:** December 6, 2025
**Author:** System Architecture Team

---

## Executive Summary

The Confluent Audit Log Intelligence System is an enterprise-grade real-time security monitoring and compliance solution that processes, enriches, and analyzes Confluent Cloud audit events. The system provides actionable intelligence through AI-powered criticality classification, anomaly detection, and interactive visualization.

---

## System Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    CONFLUENT CLOUD AUDIT LOG CLUSTER                     │
│                     (confluent-audit-log-events topic)                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                │ CloudEvents Format
                                │ (50K+ events/hour)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         AUDIT FORWARDER                                  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Consumer Layer (confluent-kafka-python)                          │  │
│  │ • Auto-commit: disabled  • Offset management: manual             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                │                                         │
│                                ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Processing Pipeline                                              │  │
│  │  1. CloudEvents Parsing                                          │  │
│  │  2. Event Flattening (44 fields)                                 │  │
│  │  3. CRN Extraction                                               │  │
│  │  4. AI Criticality Classification (CRITICAL/HIGH/MEDIUM/LOW)     │  │
│  │  5. Anomaly Detection (Rate tracking, spike detection)           │  │
│  │  6. Metrics Recording (Prometheus)                               │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                │                                         │
│                                ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Multi-Sink Output Layer                                          │  │
│  │  • Kafka Sink (primary)                                          │  │
│  │  • S3 Sink (long-term storage)                                   │  │
│  │  • GCS Sink (Google Cloud)                                       │  │
│  │  • DLQ Sink (failed events)                                      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└───────────────┬──────────────────────────┬──────────────────────────────┘
                │                          │
                │ Enriched Events          │ Prometheus Metrics
                ▼                          ▼
┌───────────────────────────┐  ┌──────────────────────────┐
│  DESTINATION KAFKA TOPIC  │  │   PROMETHEUS SERVER      │
│  (jegan_auditlog)         │  │   (Port 8000)            │
│  • Enriched events        │  │   • Event counters       │
│  • JSON Schema validated  │  │   • Criticality metrics  │
└───────────────┬───────────┘  │   • Anomaly counters     │
                │              │   • Processing latency   │
                │              └───────────┬──────────────┘
                │                          │
                │                          │ Scrape
                ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      APACHE ICEBERG TABLE                                │
│                      (Confluent TableFlow)                               │
│  • Partition: daily                                                      │
│  • Retention: 7 days                                                     │
│  • Queryable via PyIceberg                                               │
│  • ~40K events/hour stored                                               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                │ PyIceberg REST API
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    STREAMLIT DASHBOARD (Port 8504)                       │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Real-time Intelligence UI                                        │  │
│  │  • Overview (Criticality breakdown)                              │  │
│  │  • Critical & High Events (Resolved principals, full context)    │  │
│  │  • Failure Analysis (By principal, method, IP)                   │  │
│  │  • Security Events (Auth failures, Access denied, High-risk IPs) │  │
│  │  • Deletions (Comprehensive tracking)                            │  │
│  │  • Analytics (Trends and patterns)                               │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Identity Resolution (Confluent CLI)                              │  │
│  │  • Service account mapping                                       │  │
│  │  • User email resolution                                         │  │
│  │  • Cached for 1 hour                                             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### 1. **Event Ingestion**
- **Source:** Confluent Cloud audit log cluster
- **Topic:** `confluent-audit-log-events`
- **Format:** CloudEvents v1.0
- **Volume:** 50,000+ events/hour (production)
- **Retention:** 7 days (Confluent Cloud default)

### 2. **Event Processing**
1. **Consumption:**
   - Consumer group: `audit-forwarder-group`
   - Auto-commit: **DISABLED** (manual offset management)
   - Offset storage: `offsets.json` (persistent file)
   - Resume behavior: From last committed offset

2. **Transformation:**
   - CloudEvents envelope extraction
   - 44-field flattening (from nested JSON)
   - CRN parsing for service/resource identification
   - Timestamp normalization

3. **Enrichment:**
   - **AI Criticality Classification:**
     - CRITICAL: Security failures, critical deletions
     - HIGH: API key ops, service account changes, reconnaissance
     - MEDIUM: Configuration changes, topic operations
     - LOW: Read operations, routine checks
   - **Anomaly Detection:**
     - Auth failure rate spikes (>10/min threshold)
     - Activity spikes (>100/min threshold)
     - Deletion bursts (>5/min threshold)
     - API key creation spikes (>10/min threshold)

4. **Metrics Recording:**
   - Event counts by criticality
   - Processing duration
   - Anomaly detection counters
   - Routing metrics (if multi-topic enabled)

### 3. **Event Output**
- **Primary Sink:** Kafka topic (`jegan_auditlog`)
- **Schema:** JSON Schema validated via Schema Registry
- **Delivery:** At-least-once with idempotent producer
- **Backup Sinks:** S3, GCS (optional)
- **DLQ:** Failed events captured separately

### 4. **Storage & Querying**
- **Storage:** Apache Iceberg table via TableFlow
- **Connector:** Kafka → Iceberg automatic sync
- **Query Engine:** PyIceberg (Python client)
- **Partitioning:** Daily partitions
- **Retention:** 7 days

### 5. **Visualization**
- **Dashboard:** Streamlit web UI
- **Data Source:** Direct PyIceberg queries
- **Caching:** 30-second TTL for event data
- **Identity Resolution:** Confluent CLI (1-hour cache)
- **Max Rows:** 500,000 (configurable)

---

## Technology Stack

### **Core Technologies**

| Component | Technology | Version/Details | Purpose |
|-----------|------------|-----------------|---------|
| **Event Streaming** | Confluent Kafka | Cloud SaaS | Audit log source & destination |
| **Consumer** | confluent-kafka-python | Latest | Event consumption |
| **Producer** | confluent-kafka-python | Idempotent | Event publishing |
| **Schema** | JSON Schema | Via Schema Registry | Event validation |
| **Storage** | Apache Iceberg | TableFlow managed | Time-series storage |
| **Query Engine** | PyIceberg | REST catalog | Data access |
| **Dashboard** | Streamlit | 1.28+ | Interactive UI |
| **Metrics** | Prometheus | Client library | Observability |
| **Monitoring** | Grafana | (optional) | Visualization |
| **Alerting** | Webhooks | Slack/Teams | Notifications |

### **Python Libraries**

```
confluent-kafka==2.3.0          # Kafka client
pyiceberg==0.5.1                # Iceberg queries
streamlit==1.28.0               # Dashboard UI
prometheus-client==0.19.0       # Metrics exposition
pandas==2.1.3                   # Data manipulation
plotly==5.18.0                  # Interactive charts
python-dotenv==1.0.0            # Configuration
```

### **Infrastructure**

- **Deployment:** Docker Compose (local), Kubernetes (production)
- **Configuration:** Environment variables + `.env` + `.secrets`
- **Secrets Management:** Confluent Cloud API keys, Schema Registry credentials
- **Networking:** SASL_SSL for Kafka, HTTPS for Schema Registry

---

## Design Decisions & Rationale

### **Why Confluent Cloud Audit Logs?**
- ✅ **Native:** Built-in to Confluent Cloud (no additional infrastructure)
- ✅ **Comprehensive:** All control plane & data plane events
- ✅ **CloudEvents:** Industry-standard format
- ✅ **Real-time:** Events available within seconds
- ✅ **Tamper-proof:** Managed by Confluent, immutable

### **Why Apache Iceberg via TableFlow?**
- ✅ **Time-travel:** Query historical data at any point
- ✅ **Schema evolution:** Add fields without breaking queries
- ✅ **Partitioning:** Efficient daily partition pruning
- ✅ **Compatibility:** Works with Spark, Presto, Trino
- ✅ **Cost-effective:** Separate compute & storage
- ✅ **Managed:** TableFlow handles Kafka → Iceberg sync automatically

### **Why Streamlit for Dashboard?**
- ✅ **Rapid development:** Python-first, no HTML/CSS/JS
- ✅ **Interactive:** Built-in filtering, search, export
- ✅ **Direct queries:** PyIceberg integration
- ✅ **Real-time:** Auto-refresh capability
- ✅ **Deployment:** Simple Python app, no complex stack

### **Why AI Criticality Classification?**
- ✅ **Noise reduction:** Focus on CRITICAL/HIGH events first
- ✅ **Contextual:** Same method can be different criticality (e.g., deletion failures are CRITICAL)
- ✅ **Actionable:** Clear priority for security teams
- ✅ **Automated:** No manual tagging required

### **Why Manual Offset Management?**
- ✅ **Reliability:** Commit only after successful processing
- ✅ **Exactly-once semantics:** Combined with idempotent producer
- ✅ **Resume capability:** Restart from last known good position
- ✅ **Auditability:** Offset file provides clear state

### **Why Multi-Sink Architecture?**
- ✅ **Flexibility:** Route different events to different destinations
- ✅ **Compliance:** Long-term S3/GCS archival
- ✅ **Resilience:** DLQ for failed events
- ✅ **Performance:** Parallel writes

---

## Scalability Considerations

| Aspect | Current | Maximum | Scaling Strategy |
|--------|---------|---------|------------------|
| **Event Rate** | 50K/hour | 500K/hour | Horizontal pod scaling (Kubernetes) |
| **Dashboard Users** | 10 concurrent | 100 concurrent | Load balancer + multiple instances |
| **Data Retention** | 7 days | 90 days | Increase Iceberg retention policy |
| **Query Performance** | <5s (500K rows) | <10s (5M rows) | Partition pruning + caching |
| **Forwarder Lag** | <30s | <60s | Increase consumer threads |

---

## High Availability

### **Forwarder**
- Deployment: Kubernetes StatefulSet (1 replica for offset safety)
- Restart Policy: Always restart on failure
- Health Checks: Prometheus `/metrics` endpoint
- Data Loss Prevention: Manual offset commits

### **Dashboard**
- Deployment: Kubernetes Deployment (3+ replicas)
- Load Balancer: HTTP load balancing
- Session State: Stateless (Streamlit caching)
- Failover: Automatic pod replacement

### **Data Storage**
- Kafka: Multi-AZ replication (Confluent Cloud SLA: 99.95%)
- Iceberg: Object storage redundancy (S3/GCS: 99.999999999%)
- Offsets: Persistent volume + backup

---

## Compliance & Governance

- **Audit Trail:** All events captured and immutable
- **Data Residency:** Confluent Cloud region selection
- **Access Control:** Confluent RBAC + Kubernetes RBAC
- **Encryption:** TLS in transit, AES-256 at rest
- **Retention:** Configurable per compliance requirements
- **GDPR/CCPA:** Right to be forgotten via Iceberg schema evolution

---

## Next Steps

1. Review [Operations Guide](../operations/02-DEPLOYMENT_GUIDE.md)
2. Configure [Error Handling](../troubleshooting/01-ERROR_HANDLING.md)
3. Set up [Monitoring](../monitoring/01-PROMETHEUS_SETUP.md)
4. Review [Security Best Practices](../security/01-SECURITY_HARDENING.md)
5. Understand [Cost Optimization](../cost/01-COST_ANALYSIS.md)
