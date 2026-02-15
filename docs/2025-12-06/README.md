# Confluent Audit Log Intelligence System - Complete Documentation

**Document Version:** 1.0
**Last Updated:** December 6, 2025
**System Version:** v1.0.0

---

## Overview

This documentation suite provides comprehensive technical guides for the Confluent Audit Log Intelligence System, covering architecture, deployment, operations, security, monitoring, cost optimization, and troubleshooting.

**What is the Audit Log Intelligence System?**

An enterprise-grade real-time security monitoring and compliance solution that:
- **Consumes** audit events from Confluent Cloud (`confluent-audit-log-events`)
- **Enriches** events with AI-powered criticality classification (CRITICAL/HIGH/MEDIUM/LOW)
- **Detects** anomalies using rate-based spike detection
- **Routes** events to multiple destinations (Kafka, S3, GCS)
- **Stores** events in Apache Iceberg for time-series analysis
- **Visualizes** insights through an interactive Streamlit dashboard

---

## Documentation Structure

```
docs/2025-12-06/
├── README.md (This file)
├── architecture/
│   └── 01-SYSTEM_OVERVIEW.md
├── operations/
│   └── 02-DEPLOYMENT_GUIDE.md
├── security/
│   └── 01-SECURITY_HARDENING.md
├── cost/
│   └── 01-COST_ANALYSIS.md
├── monitoring/
│   └── 01-OBSERVABILITY_SETUP.md
└── troubleshooting/
    └── 01-ERROR_HANDLING.md
```

---

## Quick Start

### **1. For First-Time Users:**

Read in this order:
1. [System Architecture Overview](#architecture) - Understand the system design
2. [Deployment Guide](#operations) - Set up your environment (local/Docker/Kubernetes)
3. [Security Hardening](#security) - Configure credentials and access control
4. [Observability Setup](#monitoring) - Set up Prometheus and Grafana

### **2. For Operators:**

Essential guides:
- [Deployment Guide](#operations) - Deploy and manage the system
- [Error Handling & Recovery](#troubleshooting) - Handle forwarder failures
- [Observability Setup](#monitoring) - Monitor system health

### **3. For Security Teams:**

Focus areas:
- [Security Hardening](#security) - Defense-in-depth architecture
- [System Overview](#architecture) - Data flow and compliance
- [Cost Analysis](#cost) - Budget planning

### **4. For Decision Makers:**

Key documents:
- [System Overview](#architecture) - Architecture and design rationale
- [Cost Analysis](#cost) - ROI and budget recommendations
- [Security Hardening](#security) - Compliance mapping

---

## Documentation Guides

### Architecture

**File:** [`architecture/01-SYSTEM_OVERVIEW.md`](architecture/01-SYSTEM_OVERVIEW.md)

**What's Covered:**
- Complete system architecture diagram
- Data flow from audit log cluster → forwarder → Iceberg → dashboard
- Technology stack with version details
- Design rationale for each component
  - Why Confluent Cloud Audit Logs?
  - Why Apache Iceberg?
  - Why Streamlit?
  - Why AI criticality classification?
  - Why manual offset management?
  - Why multi-sink architecture?
- Scalability considerations (50K → 500K events/hour)
- High availability architecture
- Compliance & governance (SOC 2, GDPR, HIPAA, PCI-DSS)

**Key Concepts:**
- CloudEvents v1.0 format
- 44-field event flattening
- AI criticality levels: CRITICAL, HIGH, MEDIUM, LOW
- Anomaly detection types: auth_failure_spike, deletion_burst, activity_spike
- Consumer group: `audit-forwarder-group`
- Manual offset management via `offsets.json`
- Exactly-once semantics (idempotent producer + manual commits)
- PyIceberg REST catalog for queries
- MAX_ROWS: 500,000 (covers ~12 hours at 40K events/hour)

**Who Should Read:**
- Architects designing the deployment
- Engineers understanding system internals
- Security teams evaluating the solution

---

### Operations

**File:** [`operations/02-DEPLOYMENT_GUIDE.md`](operations/02-DEPLOYMENT_GUIDE.md)

**What's Covered:**
- Prerequisites (Confluent Cloud account, API keys, Kubernetes cluster)
- Local development setup
  - Python environment configuration
  - `.env` and `.secrets` file creation
  - Running forwarder and dashboard locally
- Docker Compose deployment
  - Complete docker-compose.yml
  - Dockerfiles for forwarder and dashboard
  - Service orchestration (forwarder, dashboard, Prometheus, Grafana)
- Kubernetes deployment
  - Namespace creation
  - Secrets and ConfigMap management
  - Persistent Volume Claims for offsets
  - Deployment manifests with high availability (3 replicas)
  - Service and Ingress configuration
  - Pod security context and resource limits
- Configuration management
  - Environment-specific configs (dev, staging, production)
  - Kustomize for multi-environment deployment
- Upgrade procedures
  - Rolling updates (zero downtime)
  - Blue-green deployments
  - Rollback procedures
- Backup & restore
  - Offset file backup (manual and automated CronJob)
  - Prometheus data backup using VolumeSnapshots
  - Restore procedures
- Operational runbooks
  - Scaling for high load
  - Emergency stop
  - Disaster recovery

**Key Procedures:**
- Generate Confluent Cloud API keys
- Create `.secrets` file (NEVER commit to Git)
- Deploy to Kubernetes with 3 replicas for HA
- Rolling update with `kubectl set image`
- Backup offsets every 6 hours with CronJob
- Scale horizontally: `kubectl scale deployment audit-forwarder --replicas=5`

**Who Should Read:**
- DevOps engineers deploying the system
- SREs managing production deployments
- Platform engineers setting up infrastructure

---

### Security

**File:** [`security/01-SECURITY_HARDENING.md`](security/01-SECURITY_HARDENING.md)

**What's Covered:**
- 5-layer defense-in-depth architecture
  1. Network security (TLS 1.2+, Private Link)
  2. Authentication & authorization (API keys, RBAC)
  3. Secrets management (Kubernetes Secrets, Vault)
  4. Application security (input validation, schema validation)
  5. Audit & compliance (immutable logs, access tracking)
- Credentials management
  - Separate API keys for each purpose (audit consumer, dest producer, Schema Registry)
  - Quarterly rotation schedule
  - 3 secret storage options: Kubernetes Secrets (production), Vault (enterprise), .secrets (dev)
- Access control
  - Confluent Cloud RBAC minimum permissions
  - Forwarder service account: DeveloperRead, DeveloperManage, DeveloperWrite
  - Dashboard service account: Read-only Iceberg, OrganizationAdmin for IAM
- Network security
  - Private Link setup for AWS
  - Kubernetes network policies (egress only to Kafka 9092/9093, SR 443)
- Dashboard authentication
  - Option A: OAuth2 Proxy (SSO)
  - Option B: Streamlit Basic Auth
  - Option C: VPN-only access
- Data security
  - Encryption table (in-transit TLS, at-rest AES-256)
  - Data retention policies (7 days Kafka, 90 days Iceberg)
  - Data anonymization option (hash email, anonymize IP)
- Incident response
  - Compromised API key: 6-step procedure within 15 minutes
  - Unauthorized dashboard access: IP blocking, session termination
- Compliance mapping
  - SOC 2: Immutable logs, access controls, encryption
  - GDPR: Data anonymization, right to erasure
  - HIPAA: Encryption, access logs, Private Link
  - PCI-DSS: Network segmentation, key rotation, audit logs
- Pre-production security checklist (15 items)

**Key Security Measures:**
- Separate API keys per purpose (never reuse)
- Rotate API keys every 90 days
- Store secrets in Kubernetes Secrets (encrypted at rest)
- Use Private Link for production (traffic never leaves cloud network)
- Pod security: runAsNonRoot, read-only filesystem, drop ALL capabilities
- Network policies: egress-only to Kafka and Schema Registry
- TLS 1.2+ enforced for all connections

**Who Should Read:**
- Security engineers designing secure deployments
- Compliance officers evaluating the solution
- Operations teams implementing security controls

---

### Cost

**File:** [`cost/01-COST_ANALYSIS.md`](cost/01-COST_ANALYSIS.md)

**What's Covered:**
- Cost components breakdown
  - Confluent Cloud (audit cluster, destination cluster, Schema Registry, TableFlow, Iceberg storage)
  - Compute (Kubernetes pods for forwarder and dashboard)
  - Monitoring (Prometheus, Grafana, log aggregation)
- Total cost estimates
  - Development: $400-600/month (optimized)
  - Staging: $800-1,500/month
  - Production (50K events/hour): $1,837-3,337/month
  - Production (500K events/hour): $5,256/month
- Cost optimization strategies
  - Reduce Kafka costs: Use Basic cluster, optimize retention, enable compression
  - Optimize Iceberg storage: S3 lifecycle policies, Glacier archival, compaction
  - Right-size compute: VPA, HPA, spot instances
  - Reduce monitoring costs: Recording rules, Grafana Cloud free tier
  - Optimize TableFlow: Batch events, single table with partitioning
- Cost monitoring & alerts
  - Confluent Cloud billing alerts
  - AWS Cost Explorer with tags
  - Kubecost for per-pod cost tracking
- Budget recommendations
  - Small team (<5 users): $600-1,000/month
  - Medium team (10-50 users): $2,000-3,000/month
  - Enterprise (100+ users): $5,000-10,000/month
- ROI analysis
  - Labor savings: $4,000/month (40 hours @ $100/hour)
  - Infrastructure cost: $2,500/month
  - Net savings: $1,500/month ($18,000/year)
  - Additional value: Reduced MTTR, prevented incidents, compliance readiness

**Key Costs:**
- Confluent Cloud Standard cluster: $1,080/month (destination)
- Confluent Cloud Dedicated cluster: $3,000/month (high-scale production)
- Schema Registry Essentials: $150/month
- TableFlow: $79/month (1 task, up to 100K events/hour)
- Iceberg storage (90 days): $45/month with S3-IA
- Kubernetes compute (3 forwarder + 3 dashboard replicas): $273/month

**Optimization Tips:**
- Use S3 Intelligent-Tiering (55% savings on storage >30 days)
- Enable zstd compression (40% reduction in storage + network)
- Use VPA to right-size pods (20-30% savings)
- Run dashboard on spot instances (70% discount)

**Who Should Read:**
- Finance teams budgeting for the system
- Engineering leaders evaluating cost-effectiveness
- FinOps teams optimizing cloud spend

---

### Monitoring

**File:** [`monitoring/01-OBSERVABILITY_SETUP.md`](monitoring/01-OBSERVABILITY_SETUP.md)

**What's Covered:**
- Observability architecture diagram
  - Forwarder → Prometheus metrics (port 8000)
  - Dashboard → Logs (stdout/stderr)
  - Prometheus → Grafana → Alerting channels (Slack, PagerDuty)
- Prometheus metrics
  - Event processing: `audit_events_processed_total`, `processing_duration_seconds`
  - Anomaly detection: `anomaly_detected_total`, `anomaly_rate`
  - Producer/Consumer: `producer_send_error_total`, `consumer_lag`
  - Routing: `events_routed_total` (multi-topic)
  - DLQ: `dlq_events_total`, `dlq_size`
- Prometheus server setup
  - Option A: Self-hosted (Kubernetes with ConfigMap)
  - Option B: Grafana Cloud (managed, free tier: 10K series, 14-day retention)
- Grafana dashboards
  - System Health: Event rates, latency, lag, uptime
  - Security Events: Anomalies, CRITICAL events, auth failures
  - Performance: Throughput, latency, CPU/memory
  - Troubleshooting: Errors, DLQ, offsets, pod restarts
- Alerting
  - AlertManager setup with Slack and PagerDuty
  - Alert rules:
    - ForwarderDown: up == 0 for 2 min (CRITICAL)
    - HighProducerErrors: >0.1/sec for 2 min (CRITICAL)
    - HighConsumerLag: >100K messages for 5 min (WARNING)
    - AnomalyDetected: >10/sec for 1 min (WARNING)
    - AuthFailureSpike: >0/sec for 1 min (CRITICAL)
- Log aggregation
  - Option A: AWS CloudWatch Logs (Fluent Bit DaemonSet)
  - Option B: ELK Stack (Elasticsearch, Logstash, Kibana)
- Distributed tracing (optional)
  - Jaeger setup for end-to-end request tracing
- Health checks
  - Forwarder `/health` endpoint
  - Kubernetes liveness and readiness probes
- Troubleshooting workflows
  - Forwarder not processing events
  - High processing latency
  - Dashboard not loading data

**Key Metrics to Monitor:**
- `audit_events_processed_total`: Alert if no increase for 5 min
- `producer_send_error_total`: Alert if >10 in 1 min
- `consumer_lag`: Alert if >100K messages
- `processing_duration_seconds` (p99): Alert if >10s
- `anomaly_detected_total`: Alert if >50 in 5 min

**Who Should Read:**
- SREs setting up monitoring
- Operations teams maintaining the system
- Platform engineers integrating with observability stack

---

### Troubleshooting

**File:** [`troubleshooting/01-ERROR_HANDLING.md`](troubleshooting/01-ERROR_HANDLING.md)

**What's Covered:**
- Layered error handling strategy
  1. Consumer resilience (auto-reconnection, retry)
  2. Processing pipeline (try-catch, graceful degradation)
  3. Producer resilience (idempotent, 5 retries, 300s timeout)
  4. Dead Letter Queue (failed event capture and replay)
- Offset management deep dive
  - Offset file format: `offsets.json` with `{topic}_{partition}: offset`
  - Offset commit flow: consume → process → produce → callback → save
  - 4 starting position options:
    1. **Resume from Last Saved (DEFAULT):** No data loss, no duplicates
    2. **Start from Earliest:** Reprocess all available events (7 days)
    3. **Start from Latest:** Ignore historical, start from "now"
    4. **Start from Specific Timestamp:** Replay from incident time
- Failure scenarios with solutions
  1. Forwarder crashes → Kubernetes restart, resume from offset
  2. Destination unavailable → Producer retry, DLQ, no offset commit
  3. Slow destination (backpressure) → Queue buffers, tune batch size
  4. Corrupted offset file → Backup and recreate
  5. Schema Registry unavailable → Retry, DLQ, continue processing
- Complete recovery checklist (9 steps)
  - Verify clusters accessible
  - Check offset file validity
  - Check consumer lag before/after restart
  - Monitor startup logs
  - Validate events in destination
- DLQ management
  - Event format with error reason, timestamp, retry count
  - Review and replay procedures
- Critical metrics and alerts
  - `audit_events_processed_total`: No increase → Restart forwarder
  - `producer_send_error_total`: >10 in 1 min → Check destination
  - Consumer lag: >100K → Scale or investigate
  - Processing duration p99: >10s → Optimize pipeline
- Prometheus alert examples
  - ForwarderDown, HighProducerErrors, HighConsumerLag

**Key Recovery Procedures:**
- **Start from earliest:** `rm offsets.json && python audit_forwarder.py`
- **Start from latest:** Use Python script to get high watermark offsets
- **Start from timestamp:** Use `offsets_for_times()` API for incident investigation
- **Restore from backup:** `kubectl cp offsets-backup.json audit-forwarder:/data/offsets.json`

**Common Errors:**
- "Broker: Offset out of range" → Delete offsets.json, restart
- "Schema registry timeout" → Check SR_KEY/SECRET, verify SR URL
- "Producer queue full" → Increase partitions or scale forwarder
- "JSON decode error" → Log event, skip, continue (automatic)
- "Authentication failure" → Verify AUDIT_API_KEY/SECRET

**Who Should Read:**
- Operations teams handling incidents
- SREs troubleshooting system issues
- Developers debugging processing pipeline

---

## System Quick Reference

### **Key Metrics**

| Metric | Normal Value | Alert Threshold | Action |
|--------|--------------|-----------------|--------|
| Event processing rate | 40K-50K/hour | <1K/hour for >5 min | Check forwarder logs |
| Processing latency (p99) | <1s | >10s | Optimize pipeline or scale |
| Consumer lag | <1,000 messages | >100K messages | Scale forwarder |
| Producer errors | 0/sec | >0.1/sec | Check destination cluster |
| Anomaly rate | 0-5/min | >10/min | Security investigation |
| DLQ events | 0 | >1/sec for 5 min | Review DLQ, fix root cause |

### **Key Commands**

**Check System Health:**
```bash
# Forwarder metrics
curl http://localhost:8000/metrics

# Consumer lag
confluent kafka consumer group describe audit-forwarder-group --cluster lkc-xxxxx

# Pod status (Kubernetes)
kubectl get pods -n audit-system

# View logs
kubectl logs -f deployment/audit-forwarder -n audit-system
```

**Operational Commands:**
```bash
# Scale forwarder
kubectl scale deployment audit-forwarder --replicas=5 -n audit-system

# Restart forwarder
kubectl rollout restart deployment/audit-forwarder -n audit-system

# Backup offsets
kubectl cp audit-system/audit-forwarder:/data/offsets.json offsets-backup.json

# Restore offsets
kubectl cp offsets-backup.json audit-system/audit-forwarder:/data/offsets.json
```

**Troubleshooting:**
```bash
# Start from earliest (reprocess all)
rm offsets.json && python audit_forwarder.py

# Check DLQ events
confluent kafka topic consume jegan_auditlog_dlq --cluster lkc-yyyyy --from-beginning

# Monitor real-time processing
watch -n 5 'curl -s localhost:8000/metrics | grep audit_events_total'
```

### **Configuration Files**

| File | Purpose | Location |
|------|---------|----------|
| `.env` | Environment variables (non-sensitive) | Project root |
| `.secrets` | API keys and passwords | Project root (NEVER commit) |
| `offsets.json` | Consumer offset tracking | Project root or `/data` in container |
| `docker-compose.yml` | Docker Compose orchestration | Project root |
| `deploy/kubernetes/*.yaml` | Kubernetes manifests | `deploy/kubernetes/` |
| `requirements.txt` | Python dependencies | Project root |

### **Important URLs**

| Service | URL | Purpose |
|---------|-----|---------|
| **Confluent Cloud** | https://confluent.cloud | Manage Kafka clusters |
| **Forwarder Metrics** | http://localhost:8000/metrics | Prometheus metrics |
| **Dashboard** | http://localhost:8504 | Streamlit UI |
| **Prometheus** | http://localhost:9090 | Metrics queries |
| **Grafana** | http://localhost:3000 | Dashboards |
| **Confluent Docs** | https://docs.confluent.io | Official documentation |
| **TableFlow Docs** | https://docs.confluent.io/cloud/current/connectors/cc-iceberg-sink.html | Iceberg connector |

---

## Common Use Cases

### **Use Case 1: Investigate Security Incident**

**Scenario:** Alert triggered for authentication failure spike

**Steps:**
1. Open dashboard: http://localhost:8504
2. Navigate to "Security Events" tab
3. Filter by `criticality = CRITICAL` and `method_name = CONTAINS "Authenticate"`
4. Review failed attempts by principal and IP address
5. Identify suspicious IPs or service accounts
6. Check anomaly detection for spike patterns
7. Export findings for security team

**Alternative:** Query Iceberg directly
```python
from pyiceberg.catalog import load_catalog
catalog = load_catalog("default")
table = catalog.load_table("audit_events")

df = table.scan(
    row_filter="criticality = 'CRITICAL' AND method_name LIKE '%Authenticate%'",
    selected_fields=["timestamp", "principal", "client_ip", "result_code"]
).to_pandas()
```

---

### **Use Case 2: Compliance Audit**

**Scenario:** Auditor requests all deletion events from last 30 days

**Steps:**
1. Open dashboard
2. Navigate to "Deletions" tab
3. Set date range: Last 30 days
4. Filter by `method_name CONTAINS "Delete"`
5. Review deleted resources by type (cluster, topic, API key, service account)
6. Identify who deleted what and when
7. Export to CSV for auditor

**Data Retention:** Ensure Iceberg retention ≥30 days (default: 90 days)

---

### **Use Case 3: Performance Optimization**

**Scenario:** Forwarder processing is slow, consumer lag increasing

**Steps:**
1. Check metrics:
   ```bash
   curl localhost:8000/metrics | grep processing_duration_seconds
   ```
2. Identify bottleneck:
   - High p99 latency → Optimize AI classification
   - High producer errors → Check destination cluster
   - High consumer lag → Scale horizontally
3. Scale forwarder:
   ```bash
   kubectl scale deployment audit-forwarder --replicas=5 -n audit-system
   ```
4. Monitor lag reduction:
   ```bash
   watch -n 10 'confluent kafka consumer group describe audit-forwarder-group --cluster lkc-xxxxx'
   ```

---

### **Use Case 4: Cost Reduction**

**Scenario:** Monthly cost exceeds budget, need to optimize

**Steps:**
1. Review [Cost Analysis Guide](cost/01-COST_ANALYSIS.md)
2. Identify highest cost component (usually Kafka cluster)
3. Apply optimizations:
   - Reduce Kafka retention: 7d → 3d (30% storage savings)
   - Enable compression: `compression.type=zstd` (40% savings)
   - Use S3-IA for Iceberg >30 days (50% savings)
   - Right-size pods with VPA (20-30% compute savings)
4. Monitor cost reduction:
   - Confluent Cloud billing dashboard
   - AWS Cost Explorer
   - Kubecost

**Expected Savings:** 20-40% total cost reduction

---

## Support & Resources

### **Internal Support**

| Team | Contact | Responsibility |
|------|---------|----------------|
| **DevOps** | devops@company.com | Deployment, infrastructure |
| **Security** | security@company.com | Security incidents, compliance |
| **FinOps** | finops@company.com | Cost optimization, budgeting |
| **Monitoring** | monitoring@company.com | Prometheus, Grafana, alerts |
| **On-Call** | PagerDuty rotation | Emergency incidents (24/7) |

### **External Support**

| Provider | Contact | Purpose |
|----------|---------|---------|
| **Confluent Cloud Support** | https://support.confluent.io | Kafka cluster issues, TableFlow |
| **Confluent Community** | https://forum.confluent.io | Community discussions |
| **Streamlit Support** | https://discuss.streamlit.io | Dashboard issues |

### **Additional Resources**

- **Confluent Cloud Docs:** https://docs.confluent.io/cloud/current/
- **PyIceberg Docs:** https://py.iceberg.apache.org/
- **Prometheus Docs:** https://prometheus.io/docs/
- **Grafana Docs:** https://grafana.com/docs/
- **Kubernetes Docs:** https://kubernetes.io/docs/

---

## Changelog

### **Version 1.0.0 (December 6, 2025)**

**Initial Documentation Release:**
- Architecture overview with design rationale
- Deployment guide (local, Docker, Kubernetes)
- Security hardening guide with 5-layer defense
- Cost analysis with ROI calculation
- Monitoring & observability setup
- Error handling & recovery procedures

**Included Guides:**
- 6 comprehensive documentation files
- 4 operational runbooks
- 3 dashboard setup options
- 15-item security checklist
- 9-step recovery procedure

---

## Next Steps

1. **New Users:** Start with [System Overview](architecture/01-SYSTEM_OVERVIEW.md) to understand the architecture
2. **Deploying:** Follow [Deployment Guide](operations/02-DEPLOYMENT_GUIDE.md) for your environment
3. **Securing:** Review [Security Hardening](security/01-SECURITY_HARDENING.md) before production
4. **Monitoring:** Set up [Observability](monitoring/01-OBSERVABILITY_SETUP.md) for production readiness
5. **Optimizing:** Apply [Cost Optimization](cost/01-COST_ANALYSIS.md) strategies
6. **Operating:** Bookmark [Error Handling](troubleshooting/01-ERROR_HANDLING.md) for incidents

---

## Contributing

To improve this documentation:

1. Identify gaps or unclear sections
2. Create issue describing the problem
3. Submit pull request with updates
4. Include examples and diagrams where helpful
5. Follow existing formatting and structure

**Documentation Standards:**
- Use markdown for all files
- Include code examples with language tags
- Add diagrams for complex concepts
- Link between related documents
- Update changelog with changes

---

## License

Internal Use Only - Company Confidential

---

**Document Maintained By:** Platform Engineering Team
**Last Review:** December 6, 2025
**Next Review:** March 6, 2026 (Quarterly)
