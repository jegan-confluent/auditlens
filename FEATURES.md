# AuditLens Feature List

Complete feature catalog for Confluent Audit Log Intelligence System.

**Current Version:** Forwarder v2.2.0 | Dashboard v10.19

---

## Forwarder Features

### Core Processing

| Feature | Description | Config |
|---------|-------------|--------|
| **Audit Log Consumption** | Consumes from Confluent Cloud audit log topic | `AUDIT_TOPIC` |
| **Event Flattening** | Extracts nested fields into flat structure | Built-in |
| **Criticality Classification** | Classifies events as CRITICAL/HIGH/MEDIUM/LOW | `src/classification/` |
| **Multi-topic Routing** | Routes events to criticality-specific topics | `ENABLE_MULTI_TOPIC_ROUTING` |
| **LOW Event Dropping** | Drops LOW events to save ~89% storage | `DROP_LOW_EVENTS` |

### Reliability & Data Safety

| Feature | Description | Config | Version |
|---------|-------------|--------|---------|
| **acks=all** | All replicas must acknowledge writes | Built-in | v2.2.0 |
| **Idempotent Producer** | Exactly-once semantics | Built-in | v2.2.0 |
| **Dead Letter Queue** | Failed events sent to DLQ for reprocessing | `ENABLE_DLQ`, `DLQ_TOPIC` | v2.2.0 |
| **Offset Persistence** | Saves consumer offsets to file | `OFFSET_FILE` | v2.0.0 |
| **Graceful Shutdown** | Proper cleanup on SIGTERM/SIGINT | Built-in | v2.0.0 |

### Security & Anomaly Detection

| Feature | Description | Config |
|---------|-------------|--------|
| **Auth Failure Detection** | Alerts on auth failure spikes | `ANOMALY_AUTH_FAILURE_THRESHOLD` |
| **Activity Spike Detection** | Alerts on unusual activity volume | `ANOMALY_ACTIVITY_SPIKE_THRESHOLD` |
| **Deletion Monitoring** | Tracks resource deletions | `ANOMALY_DELETION_THRESHOLD` |
| **API Key Monitoring** | Alerts on excessive API key operations | `ANOMALY_API_KEY_THRESHOLD` |
| **Denial Aggregation** | Aggregates RBAC denials into alerts | `ENABLE_DENIAL_AGGREGATION` |

### Alerting & Webhooks

| Feature | Description | Config |
|---------|-------------|--------|
| **Webhook Alerts** | Sends alerts to external webhooks | `WEBHOOK_URL` |
| **Retry with Backoff** | Uses tenacity for reliable delivery | Built-in |
| **Alert Topic** | Publishes alerts to Kafka topic | `ALERTS_TOPIC` |

### Observability

| Feature | Description | Config |
|---------|-------------|--------|
| **Prometheus Metrics** | Exposes metrics on HTTP endpoint | `METRICS_PORT` |
| **Health Endpoint** | `/health` returns JSON health status | Built-in |
| **Heartbeat Logging** | Logs stats every 30 seconds | Built-in |
| **DLQ Statistics** | Tracks sent/failed DLQ events | v2.2.0 |

### Performance

| Feature | Description | Impact |
|---------|-------------|--------|
| **orjson Parsing** | Fast JSON serialization | 2-3x faster |
| **Batch Processing** | 5000 messages per batch | High throughput |
| **LZ4 Compression** | Compressed producer output | Lower network I/O |
| **LRU Offset Cache** | Bounded memory for offsets | Memory safe |

---

## Dashboard Features

### Data Visualization

| Feature | Description | Tab |
|---------|-------------|-----|
| **Audit Trail** | Complete event log with filtering | Audit Trail |
| **Failure Analysis** | All failed operations | All Failures |
| **Deletion Tracking** | Resource deletion events | Deletions |
| **API Key Audit** | API key create/delete/rotate | API Keys |
| **Security Events** | Auth failures, permission denials | Security |
| **Event Details** | JSON viewer for raw events | Details |
| **Analytics** | Charts and aggregations | Analytics |
| **Time Insights** | Activity heatmap (day × hour) | Time Insights |
| **Export** | PDF compliance report | Export |
| **Security Alerts** | Aggregated denial alerts | Security Alerts |

### Filtering & Search

| Feature | Description |
|---------|-------------|
| **Criticality Filter** | Filter by CRITICAL/HIGH/MEDIUM |
| **Time Window** | 15min to 24 hours |
| **Cluster Filter** | Filter by Kafka cluster ID |
| **Environment Filter** | Filter by environment ID |
| **Principal Filter** | Search by user/service account |
| **Method Filter** | Filter by operation type |
| **Resource Filter** | Search by resource name |
| **Hide Internal** | Hide system/internal operations |
| **Quick Filters** | One-click common filters |
| **Filter Presets** | Save/load filter combinations |

### User Experience

| Feature | Description | Version |
|---------|-------------|---------|
| **Theme Toggle** | Pastel/Clean/Professional themes | v10.18 |
| **Auto-refresh** | Non-blocking 60s refresh | v10.19 |
| **Clickable Metrics** | Click metric cards to filter | v10.18 |
| **Keyboard Shortcuts** | R to refresh, H for help | v10.18 |
| **Timezone Selection** | Display in preferred timezone | v10.15 |
| **User Enrichment** | Shows email for known users | v10.10 |

### Export & Compliance

| Feature | Description |
|---------|-------------|
| **PDF Report** | Compliance report with fpdf2 |
| **CSV Export** | Export filtered data |
| **Time-based Filtering** | For audit periods |

### Performance (v10.19)

| Feature | Description | Impact |
|---------|-------------|--------|
| **Static Consumer Groups** | No group explosion | Cleaner monitoring |
| **orjson Parsing** | Fast JSON in consumer | 2x faster |
| **Non-blocking Refresh** | st_autorefresh | No UI freeze |
| **60s Data Cache** | Prevents Kafka hammering | Reduced load |

---

## Infrastructure Features

### Docker Deployment

| Feature | Description |
|---------|-------------|
| **Docker Compose** | Single-command deployment |
| **Non-root Containers** | Security hardened |
| **Health Checks** | Container health monitoring |
| **Resource Limits** | CPU/memory constraints |
| **Network Segmentation** | Separate networks per function |
| **Log Rotation** | JSON file driver with limits |

### AWS Fargate (Terraform)

| Feature | Description |
|---------|-------------|
| **VPC** | Isolated network with public/private subnets |
| **ECR** | Container registry with lifecycle policies |
| **Secrets Manager** | Secure credential storage |
| **ECS Cluster** | Fargate + Fargate Spot support |
| **ALB** | Application Load Balancer for dashboard |
| **CloudWatch** | Logs, alarms, dashboard |
| **IAM** | Least-privilege roles |

### Monitoring Stack

| Feature | Description |
|---------|-------------|
| **Prometheus** | Metrics collection |
| **Grafana** | Visualization dashboards |
| **Loki** | Log aggregation |
| **Promtail** | Log shipping |

---

## Configuration Reference

### Required Environment Variables

```bash
# Source Kafka (Audit Log Cluster)
AUDIT_BOOTSTRAP=pkc-xxx.confluent.cloud:9092
AUDIT_API_KEY=your-key
AUDIT_API_SECRET=your-secret
AUDIT_TOPIC=confluent-audit-log-events

# Destination Kafka
DEST_BOOTSTRAP=pkc-yyy.confluent.cloud:9092
DEST_API_KEY=your-key
DEST_API_SECRET=your-secret
```

### Optional Configuration

```bash
# Forwarder
GROUP_ID=audit-forwarder-group          # Consumer group
ENABLE_MULTI_TOPIC_ROUTING=true         # Route to criticality topics
DROP_LOW_EVENTS=true                    # Drop LOW events (saves ~89%)
ENABLE_DLQ=true                         # Enable Dead Letter Queue
DLQ_TOPIC=audit_events_dlq              # DLQ topic name
METRICS_PORT=8003                       # Prometheus metrics port
ENABLE_DENIAL_AGGREGATION=true          # Aggregate denials

# Anomaly Thresholds
ANOMALY_AUTH_FAILURE_THRESHOLD=10
ANOMALY_ACTIVITY_SPIKE_THRESHOLD=100
ANOMALY_DELETION_THRESHOLD=5
ANOMALY_API_KEY_THRESHOLD=10

# Webhooks
WEBHOOK_URL=https://hooks.slack.com/... # Alert webhook
```

### Output Topics

| Topic | Content | Retention |
|-------|---------|-----------|
| `audit_events_critical` | CRITICAL events | 7 days |
| `audit_events_high` | HIGH events | 7 days |
| `audit_events_medium` | MEDIUM events | 3 days |
| `audit_events_low` | LOW events (if not dropped) | 1 day |
| `audit_events_alerts` | Aggregated security alerts | 7 days |
| `audit_events_dlq` | Failed events | 30 days |

---

## API Reference

### Health Endpoint

```
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": 1702567890.123,
  "uptime_seconds": 3600,
  "processed_total": 150000,
  "error_count": 0,
  "idle_seconds": 2.5,
  "consumer_lag": 0,
  "processing_rate": 1500.5
}
```

### Metrics Endpoint

```
GET /metrics
```

Returns Prometheus-compatible metrics.

### DLQ Event Schema

```json
{
  "original_value": "<raw event JSON>",
  "error": "Processing error message",
  "source_topic": "confluent-audit-log-events",
  "source_partition": 5,
  "source_offset": 1234567,
  "failed_at": "2025-12-14T10:30:00Z",
  "forwarder_version": "2.2.0"
}
```

---

## Roadmap

### Planned Features

| Feature | Priority | Status |
|---------|----------|--------|
| Async processing (aiokafka) | High | Planned |
| Dashboard pagination | High | Planned |
| AgGrid tables | Medium | Planned |
| WebSocket real-time | Medium | Planned |
| GCP Cloud Run Terraform | Medium | Planned |
| Multi-process consumer | Medium | Planned |
| Polars DataFrame | Low | Backlog |

---

*Last Updated: 2025-12-14*
