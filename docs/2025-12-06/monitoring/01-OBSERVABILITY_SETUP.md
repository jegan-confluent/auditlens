# Observability & Monitoring Setup Guide

**Document Version:** 1.0
**Last Updated:** December 6, 2025
**Audience:** SRE, DevOps, Platform Engineering

---

## Overview

The Confluent Audit Log Intelligence System exposes comprehensive metrics, logs, and traces for complete observability. This guide covers Prometheus metrics, Grafana dashboards, log aggregation, alerting, and troubleshooting workflows.

---

## Observability Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         AUDIT FORWARDER                                  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Application Metrics (Prometheus Client)                          │  │
│  │  • audit_events_processed_total                                  │  │
│  │  • audit_events_by_criticality                                   │  │
│  │  • processing_duration_seconds                                   │  │
│  │  • anomaly_detected_total                                        │  │
│  │  • producer_send_error_total                                     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                │                                         │
│                                │ HTTP :8000/metrics                      │
│                                ▼                                         │
└────────────────────────────────┼─────────────────────────────────────────┘
                                 │
┌────────────────────────────────┼─────────────────────────────────────────┐
│                         STREAMLIT DASHBOARD                              │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Application Logs (stdout)                                        │  │
│  │  • Query execution logs                                          │  │
│  │  • Identity resolution logs                                      │  │
│  │  • User access logs                                              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                │                                         │
│                                │ stdout/stderr                           │
│                                ▼                                         │
└────────────────────────────────┼─────────────────────────────────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │                             │
                  ▼                             ▼
┌─────────────────────────────┐  ┌──────────────────────────────────────┐
│   PROMETHEUS SERVER         │  │   LOG AGGREGATION                    │
│   (Port 9090)               │  │   (ELK/Splunk/CloudWatch)            │
│                             │  │                                      │
│  • Scrapes /metrics every   │  │  • Collects stdout/stderr            │
│    30 seconds               │  │  • Indexes and searches              │
│  • Stores time-series data  │  │  • Long-term retention               │
│  • 7-day retention          │  │                                      │
│  • PromQL queries           │  └──────────┬───────────────────────────┘
└──────────────┬──────────────┘             │
               │                             │
               │ PromQL API                  │ Search API
               ▼                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        GRAFANA DASHBOARD                                 │
│  • Real-time metrics visualization                                      │
│  • Custom dashboards (forwarder health, event rates, anomalies)         │
│  • Alerts (PagerDuty, Slack, email)                                     │
│  • Log correlation                                                      │
└─────────────────────────────────────────────────────────────────────────┘
               │
               │ Webhooks
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     ALERTING CHANNELS                                    │
│  • Slack: #audit-alerts                                                 │
│  • PagerDuty: On-call rotation                                          │
│  • Email: security-team@company.com                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Prometheus Metrics

### **Exported Metrics**

The forwarder exposes metrics on `http://localhost:8000/metrics` (configurable via `METRICS_PORT`).

#### **Event Processing Metrics**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `audit_events_processed_total` | Counter | `criticality` | Total events processed by criticality level |
| `audit_events_by_criticality` | Gauge | `criticality` | Current count of events by criticality |
| `processing_duration_seconds` | Histogram | - | Time to process a single event (p50, p95, p99) |
| `audit_events_total` | Counter | - | Total events consumed from audit log topic |

**Example PromQL Queries:**
```promql
# Events per second by criticality
rate(audit_events_processed_total[5m])

# P99 processing latency
histogram_quantile(0.99, rate(processing_duration_seconds_bucket[5m]))

# Total CRITICAL events in last hour
increase(audit_events_processed_total{criticality="CRITICAL"}[1h])
```

---

#### **Anomaly Detection Metrics**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `anomaly_detected_total` | Counter | `anomaly_type` | Total anomalies detected (auth_failure_spike, deletion_burst, etc.) |
| `anomaly_rate` | Gauge | `anomaly_type` | Current anomaly rate per minute |

**Anomaly Types:**
- `auth_failure_spike`: Authentication failures >10/min
- `activity_spike`: General activity >100/min
- `deletion_burst`: Deletions >5/min
- `api_key_creation_spike`: API key creations >10/min

**Example Queries:**
```promql
# Anomaly detection rate
rate(anomaly_detected_total[5m])

# Top anomaly types
topk(5, sum by (anomaly_type) (anomaly_detected_total))
```

---

#### **Producer/Consumer Metrics**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `producer_send_success_total` | Counter | `topic` | Successful message deliveries |
| `producer_send_error_total` | Counter | `topic`, `error_type` | Failed message deliveries |
| `consumer_lag` | Gauge | `partition` | Current consumer lag (messages behind) |
| `offset_commit_total` | Counter | - | Total offset commits |

**Example Queries:**
```promql
# Producer error rate
rate(producer_send_error_total[5m])

# Consumer lag per partition
sum by (partition) (consumer_lag)

# Producer success rate
rate(producer_send_success_total[5m]) / rate(audit_events_total[5m])
```

---

#### **Routing Metrics (Multi-Topic)**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `events_routed_total` | Counter | `destination_topic` | Events routed to each destination topic |
| `routing_decision_duration` | Histogram | - | Time to make routing decision |

**Example Queries:**
```promql
# Events per destination topic
rate(events_routed_total[5m])
```

---

#### **Dead Letter Queue Metrics**

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `dlq_events_total` | Counter | `error_reason` | Events sent to DLQ |
| `dlq_size` | Gauge | - | Current DLQ size (number of events) |

**Example Queries:**
```promql
# DLQ event rate
rate(dlq_events_total[5m])

# Most common DLQ errors
topk(5, sum by (error_reason) (dlq_events_total))
```

---

### **Prometheus Server Setup**

#### **Option A: Self-Hosted Prometheus (Kubernetes)**

**1. Create Prometheus ConfigMap:**
```yaml
# deploy/kubernetes/prometheus-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: audit-system
data:
  prometheus.yml: |
    global:
      scrape_interval: 30s
      evaluation_interval: 30s

    scrape_configs:
      - job_name: 'audit-forwarder'
        kubernetes_sd_configs:
          - role: pod
            namespaces:
              names:
                - audit-system
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_label_app]
            action: keep
            regex: audit-forwarder
          - source_labels: [__meta_kubernetes_pod_ip]
            target_label: __address__
            replacement: $1:8000

      - job_name: 'kubernetes-pods'
        kubernetes_sd_configs:
          - role: pod
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: true
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
            action: replace
            target_label: __address__
            regex: ([^:]+)(?::\d+)?;(\d+)
            replacement: $1:$2
```

**2. Deploy Prometheus:**
```bash
kubectl apply -f deploy/kubernetes/prometheus-config.yaml

kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus
  namespace: audit-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prometheus
  template:
    metadata:
      labels:
        app: prometheus
    spec:
      containers:
      - name: prometheus
        image: prom/prometheus:v2.48.0
        args:
          - '--config.file=/etc/prometheus/prometheus.yml'
          - '--storage.tsdb.path=/prometheus'
          - '--storage.tsdb.retention.time=7d'
        ports:
        - containerPort: 9090
        volumeMounts:
        - name: config
          mountPath: /etc/prometheus
        - name: storage
          mountPath: /prometheus
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 1000m
            memory: 2Gi
      volumes:
      - name: config
        configMap:
          name: prometheus-config
      - name: storage
        persistentVolumeClaim:
          claimName: prometheus-storage
---
apiVersion: v1
kind: Service
metadata:
  name: prometheus
  namespace: audit-system
spec:
  selector:
    app: prometheus
  ports:
  - port: 9090
    targetPort: 9090
  type: ClusterIP
EOF
```

**3. Verify Prometheus:**
```bash
# Port-forward to access UI
kubectl port-forward -n audit-system svc/prometheus 9090:9090

# Open browser: http://localhost:9090
# Check targets: http://localhost:9090/targets
```

---

#### **Option B: Grafana Cloud (Managed)**

**1. Sign Up:**
- Visit https://grafana.com/auth/sign-up
- Free tier: 10K metrics series, 14-day retention

**2. Get Remote Write Credentials:**
```bash
# From Grafana Cloud UI, get:
GRAFANA_CLOUD_PROMETHEUS_URL=https://prometheus-blocks-prod-us-central1.grafana.net/api/prom/push
GRAFANA_CLOUD_USERNAME=123456
GRAFANA_CLOUD_API_KEY=glc_xxx
```

**3. Configure Prometheus Remote Write:**
```yaml
# prometheus.yml
remote_write:
  - url: ${GRAFANA_CLOUD_PROMETHEUS_URL}
    basic_auth:
      username: ${GRAFANA_CLOUD_USERNAME}
      password: ${GRAFANA_CLOUD_API_KEY}
```

---

## Grafana Dashboards

### **Dashboard Setup**

#### **Option A: Import Pre-Built Dashboard**

**1. Create Dashboard JSON:**

Save this as `deploy/grafana/audit-forwarder-dashboard.json`:

```json
{
  "dashboard": {
    "title": "Audit Forwarder - System Health",
    "tags": ["audit", "security", "kafka"],
    "timezone": "browser",
    "panels": [
      {
        "id": 1,
        "title": "Events Processed per Second",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(audit_events_processed_total[5m])",
            "legendFormat": "{{criticality}}"
          }
        ]
      },
      {
        "id": 2,
        "title": "Processing Latency (P99)",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.99, rate(processing_duration_seconds_bucket[5m]))"
          }
        ]
      },
      {
        "id": 3,
        "title": "Anomaly Detection Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(anomaly_detected_total[5m])",
            "legendFormat": "{{anomaly_type}}"
          }
        ]
      },
      {
        "id": 4,
        "title": "Producer Errors",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(producer_send_error_total[5m])"
          }
        ]
      },
      {
        "id": 5,
        "title": "Consumer Lag",
        "type": "graph",
        "targets": [
          {
            "expr": "sum by (partition) (consumer_lag)"
          }
        ]
      },
      {
        "id": 6,
        "title": "DLQ Events",
        "type": "stat",
        "targets": [
          {
            "expr": "sum(dlq_events_total)"
          }
        ]
      }
    ]
  }
}
```

**2. Import to Grafana:**
```bash
# Via Grafana UI: Dashboards → Import → Upload JSON file

# Or via API:
curl -X POST \
  -H "Authorization: Bearer ${GRAFANA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @deploy/grafana/audit-forwarder-dashboard.json \
  http://localhost:3000/api/dashboards/db
```

---

#### **Option B: Create Dashboard from Scratch**

**1. Deploy Grafana:**
```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: audit-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
      - name: grafana
        image: grafana/grafana:10.2.0
        ports:
        - containerPort: 3000
        env:
        - name: GF_SECURITY_ADMIN_PASSWORD
          value: "changeme"
        - name: GF_USERS_ALLOW_SIGN_UP
          value: "false"
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: audit-system
spec:
  selector:
    app: grafana
  ports:
  - port: 3000
    targetPort: 3000
  type: LoadBalancer
EOF
```

**2. Add Prometheus Data Source:**
```bash
# Access Grafana: kubectl port-forward svc/grafana 3000:3000
# Login: admin / changeme

# Configuration → Data Sources → Add data source → Prometheus
# URL: http://prometheus:9090 (if in same namespace)
# Save & Test
```

**3. Create Panels:**
- Dashboard → Add Panel → Add Query
- Use PromQL queries from metrics section
- Configure visualization (Graph, Stat, Table, etc.)

---

### **Key Dashboards to Create**

#### **1. System Health Dashboard**
**Panels:**
- Event processing rate (overall + by criticality)
- Processing latency (p50, p95, p99)
- Consumer lag per partition
- Producer success rate
- Forwarder uptime

**Purpose:** At-a-glance system health check

---

#### **2. Security Events Dashboard**
**Panels:**
- Anomaly detection rate (by type)
- CRITICAL events per hour
- Authentication failure spike alerts
- Deletion burst alerts
- High-risk IP activity

**Purpose:** Security team monitoring

---

#### **3. Performance Dashboard**
**Panels:**
- Throughput (events/sec)
- End-to-end latency (consume → process → produce)
- Kafka producer queue depth
- Memory/CPU utilization
- Network I/O

**Purpose:** Performance tuning and capacity planning

---

#### **4. Troubleshooting Dashboard**
**Panels:**
- Producer errors (by error type)
- DLQ events (by error reason)
- Schema Registry errors
- Offset commit failures
- Kubernetes pod restarts

**Purpose:** Operational troubleshooting

---

## Alerting

### **Prometheus AlertManager Setup**

**1. Create AlertManager ConfigMap:**
```yaml
# deploy/kubernetes/alertmanager-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-config
  namespace: audit-system
data:
  alertmanager.yml: |
    global:
      slack_api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'

    route:
      receiver: 'slack-audit-alerts'
      group_by: ['alertname', 'severity']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      routes:
        - match:
            severity: critical
          receiver: 'pagerduty'
        - match:
            severity: warning
          receiver: 'slack-audit-alerts'

    receivers:
      - name: 'slack-audit-alerts'
        slack_configs:
          - channel: '#audit-alerts'
            title: '{{ .GroupLabels.alertname }}'
            text: '{{ range .Alerts }}{{ .Annotations.summary }}\n{{ end }}'

      - name: 'pagerduty'
        pagerduty_configs:
          - service_key: 'YOUR_PAGERDUTY_SERVICE_KEY'
```

**2. Deploy AlertManager:**
```bash
kubectl apply -f deploy/kubernetes/alertmanager-config.yaml

kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alertmanager
  namespace: audit-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: alertmanager
  template:
    metadata:
      labels:
        app: alertmanager
    spec:
      containers:
      - name: alertmanager
        image: prom/alertmanager:v0.26.0
        args:
          - '--config.file=/etc/alertmanager/alertmanager.yml'
          - '--storage.path=/alertmanager'
        ports:
        - containerPort: 9093
        volumeMounts:
        - name: config
          mountPath: /etc/alertmanager
      volumes:
      - name: config
        configMap:
          name: alertmanager-config
---
apiVersion: v1
kind: Service
metadata:
  name: alertmanager
  namespace: audit-system
spec:
  selector:
    app: alertmanager
  ports:
  - port: 9093
    targetPort: 9093
EOF
```

---

### **Alert Rules**

**Create Alert Rules ConfigMap:**
```yaml
# deploy/kubernetes/prometheus-alert-rules.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-alert-rules
  namespace: audit-system
data:
  alert-rules.yml: |
    groups:
      - name: audit_forwarder_alerts
        interval: 30s
        rules:
          # Forwarder down
          - alert: ForwarderDown
            expr: up{job="audit-forwarder"} == 0
            for: 2m
            labels:
              severity: critical
            annotations:
              summary: "Audit forwarder is down"
              description: "Forwarder has been down for more than 2 minutes"

          # High producer error rate
          - alert: HighProducerErrors
            expr: rate(producer_send_error_total[5m]) > 0.1
            for: 2m
            labels:
              severity: critical
            annotations:
              summary: "High producer error rate"
              description: "Producer errors at {{ $value }} per second"

          # High consumer lag
          - alert: HighConsumerLag
            expr: sum(consumer_lag) > 100000
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "High consumer lag"
              description: "Consumer lag is {{ $value }} messages"

          # Anomaly detection spike
          - alert: AnomalyDetected
            expr: rate(anomaly_detected_total[5m]) > 10
            for: 1m
            labels:
              severity: warning
            annotations:
              summary: "Anomaly detection spike"
              description: "Anomaly rate: {{ $value }} per second"

          # DLQ events increasing
          - alert: DLQEventsIncreasing
            expr: rate(dlq_events_total[5m]) > 1
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "Events being sent to DLQ"
              description: "DLQ rate: {{ $value }} per second"

          # Slow processing
          - alert: SlowProcessing
            expr: histogram_quantile(0.99, rate(processing_duration_seconds_bucket[5m])) > 10
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "Slow event processing"
              description: "P99 latency is {{ $value }} seconds"

          # Critical events spike
          - alert: CriticalEventsSpike
            expr: rate(audit_events_processed_total{criticality="CRITICAL"}[5m]) > 50
            for: 2m
            labels:
              severity: warning
            annotations:
              summary: "Spike in CRITICAL events"
              description: "Critical events at {{ $value }} per second"

          # Authentication failure spike
          - alert: AuthFailureSpike
            expr: rate(anomaly_detected_total{anomaly_type="auth_failure_spike"}[5m]) > 0
            for: 1m
            labels:
              severity: critical
            annotations:
              summary: "Authentication failure spike detected"
              description: "Possible brute-force attack or credential stuffing"

          # Dashboard down
          - alert: DashboardDown
            expr: up{job="audit-dashboard"} == 0
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "Audit dashboard is down"
              description: "Dashboard has been unavailable for 5 minutes"
```

**Apply Alert Rules:**
```bash
kubectl apply -f deploy/kubernetes/prometheus-alert-rules.yaml

# Update Prometheus ConfigMap to include rules
kubectl edit configmap prometheus-config -n audit-system
# Add:
# rule_files:
#   - '/etc/prometheus/alert-rules.yml'
```

---

## Log Aggregation

### **Option A: AWS CloudWatch Logs**

**1. Install Fluent Bit DaemonSet:**
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: audit-system
data:
  fluent-bit.conf: |
    [INPUT]
        Name              tail
        Path              /var/log/containers/audit-*.log
        Parser            docker
        Tag               kube.*
        Refresh_Interval  5

    [OUTPUT]
        Name                cloudwatch
        Match               *
        region              us-west-2
        log_group_name      /aws/kubernetes/audit-forwarder
        log_stream_prefix   from-fluent-bit-
        auto_create_group   true
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: audit-system
spec:
  selector:
    matchLabels:
      app: fluent-bit
  template:
    metadata:
      labels:
        app: fluent-bit
    spec:
      serviceAccountName: fluent-bit
      containers:
      - name: fluent-bit
        image: amazon/aws-for-fluent-bit:latest
        volumeMounts:
        - name: varlog
          mountPath: /var/log
        - name: config
          mountPath: /fluent-bit/etc/
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: config
        configMap:
          name: fluent-bit-config
EOF
```

**2. Query Logs:**
```bash
# Via AWS Console: CloudWatch → Log Groups → /aws/kubernetes/audit-forwarder

# Via AWS CLI:
aws logs tail /aws/kubernetes/audit-forwarder --follow
aws logs filter-log-events --log-group-name /aws/kubernetes/audit-forwarder \
  --filter-pattern "ERROR"
```

---

### **Option B: ELK Stack (Elasticsearch, Logstash, Kibana)**

**1. Deploy Elasticsearch:**
```bash
helm repo add elastic https://helm.elastic.co
helm install elasticsearch elastic/elasticsearch \
  --namespace audit-system \
  --set replicas=3 \
  --set minimumMasterNodes=2
```

**2. Deploy Filebeat (log shipper):**
```bash
helm install filebeat elastic/filebeat \
  --namespace audit-system \
  --set daemonset.filebeatConfig.'filebeat.yml'.output.elasticsearch.hosts[0]=elasticsearch:9200
```

**3. Deploy Kibana:**
```bash
helm install kibana elastic/kibana \
  --namespace audit-system \
  --set elasticsearchHosts=http://elasticsearch:9200
```

---

## Distributed Tracing (Optional)

For end-to-end request tracing from audit log → forwarder → destination:

### **Jaeger Setup**

**1. Deploy Jaeger:**
```bash
kubectl apply -f https://raw.githubusercontent.com/jaegertracing/jaeger-operator/main/deploy/crds/jaegertracing.io_jaegers_crd.yaml
kubectl apply -f - <<EOF
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: jaeger
  namespace: audit-system
spec:
  strategy: allInOne
  allInOne:
    image: jaegertracing/all-in-one:latest
    options:
      memory:
        max-traces: 100000
EOF
```

**2. Instrument Code (Python):**
```python
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

trace.set_tracer_provider(TracerProvider())
jaeger_exporter = JaegerExporter(
    agent_host_name="jaeger-agent",
    agent_port=6831,
)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(jaeger_exporter)
)

tracer = trace.get_tracer(__name__)

# In processing pipeline:
with tracer.start_as_current_span("process_event"):
    # Event processing logic
    pass
```

---

## Health Checks

### **Forwarder Health Endpoint**

The forwarder exposes a health check endpoint on `/health`:

```bash
# Check forwarder health
curl http://localhost:8000/health

# Response:
{
  "status": "healthy",
  "consumer": "connected",
  "producer": "connected",
  "offset_file": "valid",
  "last_processed": "2025-12-06T12:00:00Z"
}
```

### **Kubernetes Liveness & Readiness Probes**

```yaml
# deploy/kubernetes/deployment.yaml
spec:
  containers:
  - name: forwarder
    livenessProbe:
      httpGet:
        path: /health
        port: 8000
      initialDelaySeconds: 30
      periodSeconds: 10
      failureThreshold: 3

    readinessProbe:
      httpGet:
        path: /metrics
        port: 8000
      initialDelaySeconds: 10
      periodSeconds: 5
```

---

## Troubleshooting Workflows

### **1. Forwarder Not Processing Events**

**Check:**
```bash
# 1. Verify forwarder is running
kubectl get pods -n audit-system | grep forwarder

# 2. Check logs for errors
kubectl logs -n audit-system deployment/audit-forwarder --tail=100

# 3. Check consumer lag
curl localhost:8000/metrics | grep consumer_lag

# 4. Verify Kafka connectivity
kubectl exec -it deployment/audit-forwarder -- \
  curl -v telnet://pkc-xxxxx.confluent.cloud:9092
```

**Resolution:**
- High lag → Scale forwarder replicas
- Connection errors → Check API keys, network policies
- Offset errors → Review offset file, consider reset

---

### **2. High Processing Latency**

**Check:**
```bash
# Check P99 latency
curl localhost:8000/metrics | grep processing_duration_seconds

# Check Prometheus alert
kubectl port-forward svc/prometheus 9090:9090
# Query: histogram_quantile(0.99, rate(processing_duration_seconds_bucket[5m]))
```

**Resolution:**
- Optimize AI classification logic
- Increase forwarder CPU/memory
- Enable batch processing

---

### **3. Dashboard Not Loading Data**

**Check:**
```bash
# 1. Verify dashboard pod running
kubectl get pods -n audit-system | grep dashboard

# 2. Check dashboard logs
kubectl logs -n audit-system deployment/audit-dashboard --tail=100

# 3. Verify PyIceberg connectivity
kubectl exec -it deployment/audit-dashboard -- python3 -c "
from pyiceberg.catalog import load_catalog
catalog = load_catalog('default')
print(catalog.list_tables())
"
```

**Resolution:**
- Connection errors → Check TableFlow connector status
- Slow queries → Optimize partition pruning, reduce MAX_ROWS
- Confluent CLI errors → Verify CONFLUENT_CLOUD_EMAIL/PASSWORD

---

## Observability Best Practices

### **1. Metric Naming Conventions**
- Use `_total` suffix for counters
- Use `_seconds` suffix for durations
- Use lowercase with underscores
- Namespace with `audit_` prefix

### **2. Log Levels**
- **ERROR:** Unrecoverable errors (DLQ events, offset failures)
- **WARNING:** Recoverable errors (producer retries, schema errors)
- **INFO:** Normal operations (startup, offset commits, partition assignments)
- **DEBUG:** Detailed diagnostics (event contents, API calls)

### **3. Alert Fatigue Prevention**
- Group related alerts (e.g., all anomaly types → single alert)
- Use `for` clause to avoid flapping (2-5 min thresholds)
- Set up alert routing (CRITICAL → PagerDuty, WARNING → Slack)
- Regularly review and tune thresholds

### **4. Dashboard Organization**
- **Executive:** High-level KPIs (event rate, uptime, critical alerts)
- **Operations:** System health (lag, latency, errors)
- **Security:** Threat intelligence (anomalies, critical events)
- **Troubleshooting:** Debug-level metrics (DLQ, retries, offsets)

---

## Monitoring Checklist

**Daily:**
- [ ] Check forwarder uptime (should be 100%)
- [ ] Review CRITICAL event count
- [ ] Verify consumer lag <1000 messages
- [ ] Check DLQ for new events

**Weekly:**
- [ ] Review anomaly detection alerts
- [ ] Analyze processing latency trends
- [ ] Check Kafka cluster health (Confluent Cloud UI)
- [ ] Verify Iceberg table size growth

**Monthly:**
- [ ] Review alert thresholds (tune if needed)
- [ ] Update Grafana dashboards with new metrics
- [ ] Analyze cost vs. retention trade-offs
- [ ] Test disaster recovery procedures

---

## Contact Information

**Monitoring Team:** monitoring@company.com
**On-Call Rotation:** PagerDuty schedule
**Prometheus Support:** [Internal Wiki]
**Grafana Cloud Support:** support@grafana.com
