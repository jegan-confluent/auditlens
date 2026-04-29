# AuditLens Monitoring Capabilities

**Complete Reference: Metrics, Alerts, Retention, Export**

---

## Table of Contents

1. [Overview](#overview)
2. [Prometheus Metrics](#prometheus-metrics)
3. [Alert Configuration](#alert-configuration)
4. [Retention Policies](#retention-policies)
5. [Export Capabilities](#export-capabilities)
6. [Grafana Dashboards](#grafana-dashboards)
7. [Health Checks](#health-checks)

---

## Overview

AuditLens provides comprehensive monitoring across three layers:

```
┌─────────────────────────────────────────────────────────────────────┐
│                       MONITORING STACK                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────────┐   ┌────────────────┐   ┌────────────────┐     │
│  │  Prometheus    │   │    Grafana     │   │  Alertmanager  │     │
│  │  :9090         │──▶│    :3000       │──▶│  (optional)    │     │
│  │                │   │                │   │                │     │
│  │  • Metrics     │   │  • Dashboards  │   │  • PagerDuty   │     │
│  │  • Time series │   │  • Alerts      │   │  • Slack       │     │
│  │  • Queries     │   │  • Analytics   │   │  • Email       │     │
│  └────────────────┘   └────────────────┘   └────────────────┘     │
│         ▲                                                          │
│         │                                                          │
│  ┌──────┴──────────────────────────────────────────────────┐      │
│  │            AuditLens Forwarder :8003/metrics            │      │
│  │  • Processing rate      • Consumer lag                  │      │
│  │  • Event counts         • Error rates                   │      │
│  │  • Criticality breakdown • Uptime                       │      │
│  └─────────────────────────────────────────────────────────┘      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Prometheus Metrics

### Forwarder Metrics (`http://localhost:8003/metrics`)

AuditLens exposes metrics in Prometheus format for scraping.

#### Core Processing Metrics

| Metric | Type | Description | Example Value |
|--------|------|-------------|---------------|
| `audit_forwarder_uptime_seconds` | Gauge | Forwarder uptime in seconds | `86400` (1 day) |
| `audit_forwarder_processed_messages_total` | Counter | Total messages processed | `1247893` |
| `audit_forwarder_processing_rate_per_second` | Gauge | Current processing rate | `147.3` |
| `audit_forwarder_error_count_total` | Counter | Total processing errors | `23` |
| `audit_forwarder_idle_seconds` | Gauge | Seconds since last message | `2.5` |

**Example Query:**
```promql
# Processing rate over last 5 minutes
rate(audit_forwarder_processed_messages_total[5m])
```

---

#### Consumer Lag Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `audit_forwarder_consumer_lag` | Gauge | `partition` | Lag per partition |
| `audit_forwarder_consumer_lag_total` | Gauge | - | Total lag across all partitions |

**Example Query:**
```promql
# Alert if lag > 10000
audit_forwarder_consumer_lag_total > 10000
```

**What is consumer lag?**
- Difference between latest offset and consumer position
- High lag = forwarder is behind real-time
- Causes: Network issues, slow processing, high event volume

---

#### Event Classification Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `audit_events_by_criticality` | Counter | `criticality` | Events by CRITICAL/HIGH/MEDIUM/LOW |
| `audit_events_by_service` | Counter | `service` | Events by Kafka/SR/ksqlDB/Flink |
| `audit_events_by_method` | Counter | `method` | Events by method name |
| `audit_events_dropped` | Counter | `reason` | Dropped events (LOW, invalid, DLQ) |

**Example Queries:**
```promql
# CRITICAL events per minute
rate(audit_events_by_criticality{criticality="CRITICAL"}[1m])

# Dropped LOW events (storage savings)
audit_events_dropped{reason="low_criticality"}
```

---

#### Security Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `audit_security_failures_total` | Counter | `type` | Auth/authz failures |
| `audit_denials_aggregated` | Counter | `principal` | Aggregated denials sent as alerts |
| `audit_webhook_alerts_sent` | Counter | `destination` | Alerts sent to webhooks |
| `audit_webhook_alerts_failed` | Counter | `destination` | Failed webhook deliveries |

**Example Queries:**
```promql
# Authorization failures per hour
rate(audit_security_failures_total{type="authorization"}[1h]) * 3600

# Webhook success rate
rate(audit_webhook_alerts_sent[5m]) /
(rate(audit_webhook_alerts_sent[5m]) + rate(audit_webhook_alerts_failed[5m]))
```

---

#### Sink Metrics (S3/GCS Export)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `audit_sink_writes_total` | Counter | `sink` | Successful writes to S3/GCS |
| `audit_sink_write_errors` | Counter | `sink`, `error_type` | Failed writes |
| `audit_sink_write_duration_seconds` | Histogram | `sink` | Write latency distribution |
| `audit_sink_bytes_written` | Counter | `sink` | Bytes written to storage |

**Example Queries:**
```promql
# S3 write error rate
rate(audit_sink_write_errors{sink="s3"}[5m])

# Average S3 write latency (p95)
histogram_quantile(0.95, audit_sink_write_duration_seconds{sink="s3"})
```

---

#### Dead Letter Queue (DLQ) Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `audit_dlq_events_total` | Counter | `reason` | Events sent to DLQ |
| `audit_dlq_retries_total` | Counter | - | Retry attempts from DLQ |

**What triggers DLQ?**
- Kafka write failures (network, quota, topic missing)
- Sink write failures (S3/GCS permission denied)
- Invalid event format (malformed JSON)

**Example Query:**
```promql
# DLQ events per minute (should be 0)
rate(audit_dlq_events_total[1m])
```

---

### Dashboard Metrics (Not exposed via Prometheus)

The Streamlit dashboard tracks these internally:

| Metric | Description | Location |
|--------|-------------|----------|
| Dashboard load time | Kafka consumer → DataFrame load time | Performance tab |
| Active filters | Number of user-applied filters | Session state |
| Export count | CSV/PDF exports generated | Export tab |
| Email cache hit rate | % of email lookups from cache | Identity enrichment |

---

## Alert Configuration

### Built-In Alert Rules

AuditLens includes pre-configured alert rules for common scenarios.

#### Alert 1: High Consumer Lag

**Trigger:** Consumer lag > 10,000 messages

**Prometheus Rule:**
```yaml
groups:
  - name: auditlens_alerts
    interval: 30s
    rules:
      - alert: AuditForwarderLagHigh
        expr: audit_forwarder_consumer_lag_total > 10000
        for: 5m
        labels:
          severity: warning
          component: forwarder
        annotations:
          summary: "AuditLens consumer lag is high"
          description: "Consumer lag is {{ $value }} messages (threshold: 10000)"
          runbook_url: "https://docs.auditlens/runbooks/consumer-lag"
```

**What to do:**
1. Check forwarder logs: `docker logs audit-forwarder --tail 100`
2. Verify network connectivity to Kafka cluster
3. Check for processing errors (error_count_total metric)
4. Consider scaling forwarder (increase partition parallelism)

---

#### Alert 2: Forwarder Stopped Processing

**Trigger:** No messages processed in 5 minutes

**Prometheus Rule:**
```yaml
- alert: AuditForwarderIdle
  expr: audit_forwarder_idle_seconds > 300
  for: 2m
  labels:
    severity: critical
    component: forwarder
  annotations:
    summary: "AuditLens forwarder is idle"
    description: "No messages processed for {{ $value }} seconds"
```

**What to do:**
1. Check if source cluster is producing audit logs
2. Verify API keys are valid (check for auth failures)
3. Check network connectivity
4. Restart forwarder: `docker compose restart audit-forwarder`

---

#### Alert 3: High Error Rate

**Trigger:** Error rate > 1% of processed messages

**Prometheus Rule:**
```yaml
- alert: AuditForwarderErrorRateHigh
  expr: |
    rate(audit_forwarder_error_count_total[5m]) /
    rate(audit_forwarder_processed_messages_total[5m]) > 0.01
  for: 5m
  labels:
    severity: warning
    component: forwarder
  annotations:
    summary: "AuditLens error rate is high"
    description: "Error rate is {{ $value | humanizePercentage }}"
```

**What to do:**
1. Check error logs for specific error types
2. Common causes:
   - Invalid JSON in source topic
   - Destination topic missing/quota exceeded
   - S3/GCS permission denied
3. Review DLQ metrics to see failed events

---

#### Alert 4: Mass Deletion Event

**Trigger:** >5 topic deletions in 5 minutes

**Prometheus Rule:**
```yaml
- alert: MassTopicDeletion
  expr: |
    sum(rate(audit_events_by_method{method="kafka.DeleteTopics"}[5m])) * 300 > 5
  for: 0m  # Immediate
  labels:
    severity: critical
    component: security
  annotations:
    summary: "Mass topic deletion detected"
    description: "{{ $value }} topics deleted in 5 minutes"
```

**What to do:**
1. Check **Deletions** tab in dashboard
2. Identify principal responsible
3. Verify if planned (Terraform run, cleanup job) or accidental
4. Contact responsible team immediately

---

#### Alert 5: Aggregated Authorization Denials

**Trigger:** ≥20 denials in 60 seconds (built into forwarder)

**Configuration:**
```bash
# .env
DENIAL_AGGREGATION_ENABLED=true
DENIAL_THRESHOLD_HIGH=20      # HIGH alert
DENIAL_THRESHOLD_MEDIUM=5     # MEDIUM alert
DENIAL_WINDOW_SECONDS=60
```

**Example Alert Payload (Slack):**
```json
{
  "attachments": [{
    "color": "#fd7e14",
    "title": "🔒 HIGH - Aggregated Authorization Denials",
    "text": "47 authorization denials detected for sa-prod-analytics",
    "fields": [
      {"title": "Principal", "value": "sa-prod-analytics", "short": true},
      {"title": "Denial Count", "value": "47", "short": true},
      {"title": "Operations", "value": "Read on orders, payments, users", "short": false},
      {"title": "Source IPs", "value": "10.0.1.45", "short": true}
    ],
    "footer": "AuditLens",
    "ts": 1708359823
  }]
}
```

**What to do:**
1. Navigate to **Security Alerts** tab
2. Review alert details (principal, operations, IPs)
3. Determine if attack or misconfiguration:
   - Single IP + short time window = likely misconfiguration
   - Multiple IPs + long time window = possible attack
4. Check service account ACLs if misconfiguration
5. Revoke credentials if compromised

---

#### Alert 6: Webhook Delivery Failure

**Trigger:** Webhook alerts failing for 10 minutes

**Prometheus Rule:**
```yaml
- alert: WebhookDeliveryFailing
  expr: |
    rate(audit_webhook_alerts_failed[5m]) > 0 and
    rate(audit_webhook_alerts_sent[5m]) == 0
  for: 10m
  labels:
    severity: warning
    component: alerting
  annotations:
    summary: "Webhook alerts not being delivered"
    description: "Check Slack/Teams webhook configuration"
```

**What to do:**
1. Verify webhook URL is correct
2. Check webhook endpoint is reachable
3. Review webhook logs: `docker logs audit-forwarder | grep webhook`
4. Test webhook manually:
   ```bash
   curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
        -H 'Content-Type: application/json' \
        -d '{"text": "Test from AuditLens"}'
   ```

---

### Alertmanager Configuration (Optional)

For production, route alerts to PagerDuty, Slack, or email via Alertmanager.

**Configuration:**
```yaml
# alertmanager.yml
route:
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty'
    - match:
        severity: warning
      receiver: 'slack'

receivers:
  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_SERVICE_KEY'

  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
        channel: '#alerts-auditlens'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ .Annotations.description }}'

  - name: 'default'
    webhook_configs:
      - url: 'http://localhost:9093/webhook'
```

---

## Retention Policies

### Topic Retention by Criticality

AuditLens routes events to different topics with tiered retention policies.

| Topic | Criticality | Retention | Rationale | Storage Cost |
|-------|-------------|-----------|-----------|--------------|
| `audit_events_critical` | CRITICAL | 90 days | Compliance, security incidents | High |
| `audit_events_high` | HIGH | 30 days | Security reviews, investigations | Medium |
| `audit_events_medium` | MEDIUM | 14 days | Operational audits | Low |
| `audit_events_low` | LOW | 7 days (or dropped) | Recent troubleshooting only | Minimal |
| `security_alerts` | N/A | 365 days | Compliance, trend analysis | Low volume |

**Configuration:**
```bash
# Kafka topic retention configuration
kafka-configs --alter --entity-type topics \
  --entity-name audit_events_critical \
  --add-config retention.ms=7776000000  # 90 days

kafka-configs --alter --entity-type topics \
  --entity-name audit_events_high \
  --add-config retention.ms=2592000000  # 30 days
```

---

### Storage Cost Optimization

#### DROP_LOW_EVENTS Feature

**Configuration:**
```bash
# .env
DROP_LOW_EVENTS=true  # Recommended for production
```

**Impact:**
- **Before:** 10,000 events/min → 14.4M events/day → ~$450/month storage
- **After:** 1,100 events/min → 1.58M events/day → ~$50/month storage
- **Savings:** 89% cost reduction

**What gets dropped:**
- `kafka.Fetch` (read operations)
- `kafka.Produce` (write operations)
- `mds.Authorize` with `granted=true` (successful RBAC checks)
- `kafka.Heartbeat`, `kafka.JoinGroup` (client housekeeping)

**What is kept:**
- All CRITICAL, HIGH, MEDIUM events
- All failures (`granted=false`, `resultStatus=FAILURE`)
- All destructive operations (DeleteTopics, DeleteApiKey, etc.)
- All permission changes (CreateAcl, CreateRoleBinding, etc.)

---

### Retention by Use Case

| Use Case | Recommended Retention | Justification |
|----------|----------------------|---------------|
| **SOC2 Audit** | 365 days | Auditors may request 1-year history |
| **HIPAA** | 2,555 days (7 years) | Legal requirement for PHI access logs |
| **ISO27001** | 90 days | Minimum for access reviews |
| **PCI-DSS** | 365 days | Cardholder data access logs |
| **GDPR** | 30-90 days | Minimize retention (data minimization principle) |
| **Incident Response** | 90 days | Most investigations within 3 months |
| **Operational Debugging** | 7-14 days | Recent troubleshooting only |

---

### Long-Term Archival

For compliance requiring >90 day retention, export to S3/GCS.

**Lifecycle Policy Example (S3):**
```json
{
  "Rules": [{
    "Id": "archive-audit-logs",
    "Status": "Enabled",
    "Transitions": [{
      "Days": 90,
      "StorageClass": "GLACIER"
    }],
    "Expiration": {
      "Days": 2555
    }
  }]
}
```

**Cost Comparison:**
| Storage | Cost per GB/month | 1 TB/year |
|---------|-------------------|-----------|
| Kafka (Confluent Cloud) | $0.10 | $1,200 |
| S3 Standard | $0.023 | $276 |
| S3 Glacier | $0.004 | $48 |

**Recommendation:** Keep 90 days in Kafka for fast access, archive rest to Glacier.

---

## Export Capabilities

### Real-Time Export to S3/GCS

AuditLens can export events in real-time to cloud storage.

#### S3 Export Configuration

```bash
# .env
ENABLE_S3_SINK=true
S3_BUCKET_NAME=company-audit-logs
S3_PREFIX=confluent-audit/
S3_REGION=us-west-2
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional: Partitioning
S3_PARTITION_BY=date  # or hour, criticality, service
S3_FILE_FORMAT=parquet  # or json, csv
S3_COMPRESSION=snappy  # or gzip, none
```

**Output Structure:**
```
s3://company-audit-logs/confluent-audit/
├── date=2025-02-19/
│   ├── hour=00/
│   │   ├── events-00001.parquet (10 MB, compressed)
│   │   └── events-00002.parquet
│   ├── hour=01/
│   │   └── events-00001.parquet
│   ...
└── date=2025-02-20/
    └── hour=00/
        └── events-00001.parquet
```

---

#### GCS Export Configuration

```bash
# .env
ENABLE_GCS_SINK=true
GCS_BUCKET_NAME=company-audit-logs
GCS_PREFIX=confluent-audit/
GCS_PROJECT_ID=my-gcp-project
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

---

### Dashboard Export Features

#### CSV Export

**Available in all tabs:**
- Audit Trail
- Failures
- Deletions
- API Keys
- Security Alerts

**Example CSV:**
```csv
time,principal,methodName,resourceName,resultStatus,criticality
2025-02-19T15:23:45Z,sa-prod-analytics,kafka.Fetch,orders,SUCCESS,LOW
2025-02-19T15:22:11Z,user:jane@company.com,kafka.CreateTopics,dev-test,SUCCESS,MEDIUM
2025-02-19T15:20:33Z,sa-terraform-ci,kafka.DeleteTopics,old-data,SUCCESS,HIGH
```

**Use cases:**
- Import to Excel for pivot tables
- Load into data warehouse (Snowflake, BigQuery)
- Compliance reports for auditors

---

#### PDF Compliance Report

**Location:** Export tab

**Configuration:**
```python
# Report parameters
{
  "time_range": "last_30_days",
  "criticality": ["CRITICAL", "HIGH"],
  "include_sections": [
    "executive_summary",
    "access_by_principal",
    "failed_access_attempts",
    "temporal_analysis",
    "attestation"
  ]
}
```

**Output:** 10-15 page PDF with charts, tables, and executive summary

**Use cases:**
- SOC2 Type II audits
- ISO27001 evidence collection
- Management reporting

---

#### JSON Export (Machine-Readable)

**Format:**
```json
{
  "export_metadata": {
    "generated_at": "2025-02-19T15:30:00Z",
    "time_range": {"start": "2025-02-01", "end": "2025-02-28"},
    "total_events": 125478,
    "filters_applied": {"criticality": ["CRITICAL", "HIGH"]}
  },
  "events": [
    {
      "id": "uuid-1234",
      "time": "2025-02-19T15:23:45Z",
      "type": "io.confluent.kafka.server/authorization",
      "principal": "sa-prod-analytics",
      "methodName": "kafka.Fetch",
      "resourceName": "orders",
      "granted": true,
      "criticality": "LOW"
    },
    ...
  ]
}
```

**Use cases:**
- API integration with SIEM (Splunk, Datadog)
- Custom analytics pipelines
- Automated compliance checks

---

### MCP Export Tools

Via Claude Code (see [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md)):

```
You: "Export all CRITICAL events from last quarter to S3"

Claude Code:
  ✅ Calls export_to_s3 tool
  ✅ Parameters: {
      "bucket": "company-audit-logs",
      "prefix": "q1-2025/",
      "start_time": "2025-01-01",
      "end_time": "2025-03-31",
      "format": "parquet",
      "partition_by": "day"
  }
  ✅ Returns job ID for status tracking
```

---

## Grafana Dashboards

### Pre-Built Dashboards

AuditLens includes 3 Grafana dashboards:

#### Dashboard 1: Forwarder Health

**URL:** http://localhost:3000/d/auditlens-forwarder

**Panels:**
1. **Processing Rate** (time series)
   - Messages/second over time
   - Alert: drops below 10/s for 5 minutes

2. **Consumer Lag** (gauge)
   - Current lag per partition
   - Alert: >10,000 messages

3. **Uptime** (stat)
   - Current uptime in days

4. **Error Rate** (time series)
   - Errors/minute over time
   - Alert: >10 errors/min

5. **Memory Usage** (gauge)
   - Python process memory
   - Alert: >80% of allocated

---

#### Dashboard 2: Security Overview

**URL:** http://localhost:3000/d/auditlens-security

**Panels:**
1. **CRITICAL Events** (stat + time series)
   - Count of CRITICAL events today
   - Trend over last 7 days

2. **Authorization Failures** (table)
   - Top 10 principals by denial count

3. **Aggregated Alerts** (time series)
   - HIGH and MEDIUM alerts sent

4. **Webhook Success Rate** (gauge)
   - % of successful webhook deliveries

5. **Access Transparency Events** (table)
   - Confluent personnel access to your resources

---

#### Dashboard 3: Capacity Planning

**URL:** http://localhost:3000/d/auditlens-capacity

**Panels:**
1. **Event Volume by Criticality** (stacked area chart)
   - CRITICAL, HIGH, MEDIUM, LOW over time

2. **Storage Usage** (projection)
   - Current storage + 30-day projection

3. **Processing Efficiency** (%)
   - (Processed / Received) * 100

4. **Peak Hours Heatmap**
   - Hour-of-day vs day-of-week

---

### Custom Dashboards

**Create your own:**

1. Open Grafana: http://localhost:3000 (admin/admin)
2. Create → Dashboard
3. Add Panel → Prometheus data source
4. Example query:
   ```promql
   # Top 5 methods by volume
   topk(5, sum by (method) (rate(audit_events_by_method[1h])))
   ```

---

## Health Checks

### Endpoint: `/health`

**URL:** http://localhost:8003/health

**Response:**
```json
{
  "status": "healthy",
  "version": "3.0.0",
  "uptime_seconds": 86400,
  "checks": {
    "kafka_consumer": {
      "status": "healthy",
      "lag": 125,
      "last_message_age_seconds": 2.3
    },
    "kafka_producer": {
      "status": "healthy",
      "last_write_success": "2025-02-19T15:30:12Z"
    },
    "s3_sink": {
      "status": "healthy",
      "last_write_success": "2025-02-19T15:29:45Z",
      "last_write_bytes": 1048576
    },
    "webhook": {
      "status": "degraded",
      "last_success": "2025-02-19T14:30:00Z",
      "consecutive_failures": 3
    }
  }
}
```

**Status Codes:**
- `200` - All systems healthy
- `503` - One or more components degraded

---

### Health Check Automation

**Kubernetes Liveness Probe:**
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8003
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

**Docker Healthcheck:**
```yaml
services:
  audit-forwarder:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8003/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 40s
```

---

## Monitoring Checklist

### Daily (Automated Alerts)

- [ ] Consumer lag <10,000
- [ ] No processing errors in last hour
- [ ] Webhook alerts delivering successfully
- [ ] No CRITICAL events requiring investigation

---

### Weekly (Manual Review)

- [ ] Review **Security Alerts** tab
- [ ] Check for stale ACLs (Topic × Identity tab)
- [ ] Review top principals by activity
- [ ] Verify storage usage trends

---

### Monthly (Compliance)

- [ ] Generate compliance report (Export tab)
- [ ] Review access certifications (Topic × Identity)
- [ ] Audit permission changes (filter by CreateRoleBinding, DeleteAcl)
- [ ] Archive old events to S3 Glacier

---

### Quarterly (Capacity Planning)

- [ ] Review event volume trends (Grafana)
- [ ] Adjust retention policies if needed
- [ ] Evaluate DROP_LOW_EVENTS impact
- [ ] Plan for peak usage (Black Friday, tax season, etc.)

---

## Troubleshooting Monitoring Issues

### Issue: Prometheus not scraping metrics

**Symptoms:** Grafana shows "No data"

**Solutions:**
1. Verify metrics endpoint:
   ```bash
   curl http://localhost:8003/metrics
   # Should return Prometheus-format metrics
   ```

2. Check Prometheus targets:
   ```
   http://localhost:9090/targets
   # Should show audit-forwarder as UP
   ```

3. Check Prometheus config:
   ```yaml
   # prometheus.yml
   scrape_configs:
     - job_name: 'audit-forwarder'
       static_configs:
         - targets: ['audit-forwarder:8003']
   ```

---

### Issue: High consumer lag

**Symptoms:** `audit_forwarder_consumer_lag_total > 50000`

**Solutions:**
1. Check processing rate:
   ```bash
   curl http://localhost:8003/metrics | grep processing_rate
   # Should be >10/s
   ```

2. Check for errors:
   ```bash
   docker logs audit-forwarder --tail 100 | grep ERROR
   ```

3. Increase parallelism:
   ```bash
   # Increase Kafka consumer fetch size
   KAFKA_CONSUMER_FETCH_MIN_BYTES=10485760  # 10 MB
   ```

4. Scale horizontally (run multiple forwarders in different consumer groups)

---

### Issue: Missing events in dashboard

**Symptoms:** Dashboard shows fewer events than expected

**Solutions:**
1. Check if DROP_LOW_EVENTS is enabled:
   ```bash
   echo $DROP_LOW_EVENTS
   # If true, LOW events are intentionally dropped
   ```

2. Verify time range filter:
   - Dashboard default: Last 24 hours
   - Older events may be outside range

3. Check topic retention:
   ```bash
   kafka-topics --describe --topic audit_events_high
   # Verify retention.ms setting
   ```

---

## Next Steps

- **Setup:** [Quick Start Guide](./QUICK_START.md)
- **Use Cases:** [Customer Use Cases](./CUSTOMER_USE_CASES.md)
- **AI Integration:** [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md)
- **Compliance:** [Compliance Templates](./COMPLIANCE_TEMPLATES.md)

---

**Version:** 1.0
**Last Updated:** 2025-02-19
**Compatible with:** AuditLens v11.0+, Prometheus 2.x, Grafana 9.x+
