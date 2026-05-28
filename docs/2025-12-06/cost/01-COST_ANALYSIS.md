# Cost Analysis & Optimization Guide

**Document Version:** 1.0
**Last Updated:** December 6, 2025
**Audience:** Engineering Leadership, FinOps, Architecture

---

## Executive Summary

The Confluent Audit Log Intelligence System operates on a **pay-as-you-go** model with predictable costs based on event volume, storage retention, and compute resources. This document provides detailed cost breakdowns, optimization strategies, and budget recommendations for different deployment scales.

**Estimated Monthly Costs:**
- **Development:** $200-400/month
- **Staging:** $800-1,500/month
- **Production (50K events/hour):** $2,500-4,000/month
- **Production (500K events/hour):** $8,000-12,000/month

---

## Cost Components

### 1. Confluent Cloud Costs

#### **Audit Log Cluster (Source)**

**Type:** Standard Kafka cluster (multi-zone)

| Component | Unit | Rate | Monthly Cost (50K events/hour) |
|-----------|------|------|-------------------------------|
| **Cluster Hours** | 720 hours | $1.50/hour | $1,080 |
| **Storage** | ~500 GB (7 days retention) | $0.10/GB | $50 |
| **Network Egress** | ~2 TB/month | $0.05/GB | $100 |
| **Partitions** | 3 partitions | Included | $0 |
| **Total** | | | **$1,230/month** |

**Notes:**
- Audit log cluster is **managed by Confluent** (included with Confluent Cloud)
- No separate cluster cost for audit logs
- Only pay for egress when consuming events
- Retention fixed at 7 days (Confluent default)

---

#### **Destination Kafka Cluster**

**Type:** Basic or Standard cluster

| Component | Unit | Rate | Monthly Cost (50K events/hour) |
|-----------|------|------|-------------------------------|
| **Cluster Hours** | 720 hours | $1.00/hour (Basic) | $720 |
| **Storage** | ~200 GB (7 days) | $0.10/GB | $20 |
| **Network Ingress** | ~2 TB/month | Free | $0 |
| **Partitions** | 3 partitions | Included | $0 |
| **Total** | | | **$740/month** |

**Optimization Options:**

**Option A: Basic Cluster (Single-Zone)**
- Cost: $1.00/hour ($720/month)
- Use case: Dev/staging, non-critical workloads
- SLA: 99.5%
- Trade-off: No multi-zone redundancy

**Option B: Standard Cluster (Multi-Zone)**
- Cost: $1.50/hour ($1,080/month)
- Use case: Production, high availability required
- SLA: 99.95%
- Benefit: Automatic failover, zero downtime

**Option C: Dedicated Cluster**
- Cost: $2,000-5,000/month (fixed)
- Use case: High throughput (>500K events/hour), compliance
- Benefit: Isolated resources, guaranteed performance

---

#### **Schema Registry**

| Component | Unit | Rate | Monthly Cost |
|-----------|------|------|--------------|
| **Essentials Tier** | 1 environment | $150/month | $150 |
| **Schema Count** | ~5 schemas | Included | $0 |
| **API Calls** | ~50M/month | Included | $0 |
| **Total** | | | **$150/month** |

**Notes:**
- Schema Registry required for JSON Schema validation
- Essentials tier sufficient for most workloads (up to 100 schemas)
- Advanced tier ($500/month) needed for schema migration features

---

#### **TableFlow (Iceberg Connector)**

**Type:** Managed Kafka Connect with Iceberg sink

| Component | Unit | Rate | Monthly Cost (50K events/hour) |
|-----------|------|------|-------------------------------|
| **Connector Tasks** | 1 task | $0.11/hour | $79 |
| **Throughput** | ~40K events/hour | Included | $0 |
| **Iceberg Table** | 1 table | Included | $0 |
| **Total** | | | **$79/month** |

**Scaling Costs:**
- 1 task handles up to 100K events/hour
- 2 tasks ($158/month) for 100K-500K events/hour
- 4 tasks ($316/month) for 500K-1M events/hour

---

#### **Iceberg Storage (S3/GCS)**

**Type:** Object storage for Iceberg table data

| Component | Unit | Rate | Monthly Cost (50K events/hour) |
|-----------|------|------|-------------------------------|
| **Storage (7 days)** | ~100 GB | $0.023/GB (S3 Standard) | $2.30 |
| **Storage (90 days)** | ~1.3 TB | $0.023/GB | $30 |
| **PUT Requests** | ~3M/month | $0.005/1K requests | $15 |
| **GET Requests** | ~500K/month (dashboard) | $0.0004/1K requests | $0.20 |
| **Total (7 days)** | | | **$17.50/month** |
| **Total (90 days)** | | | **$45.20/month** |

**Optimization:**
- Use S3 Standard-IA for data >30 days old (50% cheaper: $0.0125/GB)
- Enable S3 Intelligent-Tiering for automatic cost optimization
- Archive to Glacier after 90 days ($0.004/GB) for compliance retention

**Example with Intelligent-Tiering (90 days):**
```
First 30 days (frequent access): 400 GB × $0.023 = $9.20
Next 60 days (infrequent): 900 GB × $0.0125 = $11.25
Total: $20.45/month (55% savings vs. Standard)
```

---

### 2. Compute Costs (Kubernetes/Cloud)

#### **Audit Forwarder (Kubernetes Pod)**

**Type:** Stateful application with persistent volume

| Component | Unit | Rate | Monthly Cost |
|-----------|------|------|--------------|
| **CPU** | 1 vCPU | $30/month | $30 |
| **Memory** | 2 GB RAM | $15/GB/month | $30 |
| **Persistent Volume** | 10 GB (offsets, cache) | $0.10/GB/month | $1 |
| **Total (1 replica)** | | | **$61/month** |
| **Total (3 replicas)** | High availability | | **$183/month** |

**Scaling Considerations:**
- 1 replica sufficient for up to 100K events/hour
- 3 replicas recommended for production (HA + zero downtime upgrades)
- Vertical scaling: 2 vCPU + 4 GB RAM for 500K events/hour ($120/replica)

---

#### **Dashboard (Streamlit on Kubernetes)**

**Type:** Stateless web application

| Component | Unit | Rate | Monthly Cost |
|-----------|------|------|--------------|
| **CPU** | 0.5 vCPU | $30/month | $15 |
| **Memory** | 1 GB RAM | $15/GB/month | $15 |
| **Total (1 replica)** | | | **$30/month** |
| **Total (3 replicas)** | Load balancing | | **$90/month** |

**Usage-Based Scaling:**
- 1 replica: Up to 10 concurrent users
- 3 replicas: Up to 50 concurrent users
- 5 replicas: Up to 100 concurrent users ($150/month)

---

#### **Load Balancer**

| Component | Type | Rate | Monthly Cost |
|-----------|------|------|--------------|
| **AWS ALB** | Application Load Balancer | $16.20/month + $0.008/LCU-hour | $25-40 |
| **GCP Load Balancer** | HTTP(S) Load Balancer | $18/month + $0.008/hour | $23-35 |

**Note:** Only required if exposing dashboard externally. Use Kubernetes ClusterIP + kubectl port-forward for internal-only access (cost: $0).

---

### 3. Monitoring & Observability Costs

#### **Prometheus (Self-Hosted)**

| Component | Unit | Rate | Monthly Cost |
|-----------|------|------|--------------|
| **CPU** | 1 vCPU | $30/month | $30 |
| **Memory** | 2 GB RAM | $15/GB/month | $30 |
| **Storage** | 50 GB (7 days metrics) | $0.10/GB/month | $5 |
| **Total** | | | **$65/month** |

**Alternative: Grafana Cloud (Managed)**
- Free tier: Up to 10K series, 14-day retention
- Pro tier: $49/month (50K series, 30-day retention)
- Advanced: $299/month (unlimited series, 13-month retention)

---

#### **Log Aggregation (Optional)**

| Service | Tier | Cost |
|---------|------|------|
| **AWS CloudWatch Logs** | 10 GB ingestion/month | $5 + $0.50/GB storage |
| **Datadog** | 5 hosts, 150 GB logs/month | $90/month |
| **Elasticsearch (self-hosted)** | 3-node cluster | $180/month |

**Recommendation:** Start with CloudWatch Logs ($10-20/month), upgrade to Datadog only if advanced analytics needed.

---

## Total Cost Breakdown

### **Development Environment**

| Component | Monthly Cost |
|-----------|--------------|
| Audit Log Cluster (egress only) | $50 |
| Destination Cluster (Basic) | $720 |
| Schema Registry (Essentials) | $150 |
| TableFlow (1 task) | $79 |
| Iceberg Storage (7 days) | $17 |
| Forwarder (1 replica, 0.5 vCPU) | $30 |
| Dashboard (1 replica, 0.5 vCPU) | $15 |
| Prometheus (self-hosted) | $65 |
| **TOTAL** | **~$1,126/month** |

**Cost Optimization for Dev:**
- Use Confluent Cloud free tier credits ($400/month)
- Run forwarder locally instead of Kubernetes (save $30)
- Skip Prometheus, use Confluent Cloud metrics (save $65)
- **Optimized Dev Cost:** ~$400-600/month

---

### **Production Environment (50K events/hour)**

| Component | Monthly Cost |
|-----------|--------------|
| Audit Log Cluster (egress) | $100 |
| Destination Cluster (Standard) | $1,080 |
| Schema Registry (Essentials) | $150 |
| TableFlow (1 task) | $79 |
| Iceberg Storage (90 days, S3-IA) | $45 |
| Forwarder (3 replicas, 1 vCPU) | $183 |
| Dashboard (3 replicas) | $90 |
| Load Balancer | $30 |
| Prometheus (self-hosted) | $65 |
| CloudWatch Logs | $15 |
| **TOTAL** | **~$1,837/month** |

**With Confluent Dedicated Cluster:**
- Replace Standard cluster with Dedicated: +$1,500
- **Total with Dedicated:** ~$3,337/month

---

### **Production Environment (500K events/hour)**

| Component | Monthly Cost |
|-----------|--------------|
| Audit Log Cluster (egress) | $500 |
| Destination Cluster (Dedicated) | $3,000 |
| Schema Registry (Essentials) | $150 |
| TableFlow (4 tasks) | $316 |
| Iceberg Storage (90 days, S3-IA) | $300 |
| Forwarder (5 replicas, 2 vCPU) | $600 |
| Dashboard (5 replicas) | $150 |
| Load Balancer | $50 |
| Prometheus (or Grafana Cloud Pro) | $100 |
| Datadog Logs | $90 |
| **TOTAL** | **~$5,256/month** |

---

## Cost Optimization Strategies

### 1. **Reduce Kafka Cluster Costs**

#### **Strategy A: Use Basic Cluster for Non-Critical Workloads**
```
Savings: $360/month (Standard → Basic)
Trade-off: Single-zone, 99.5% SLA
Use case: Dev, staging, non-critical analytics
```

#### **Strategy B: Optimize Topic Retention**
```bash
# Reduce retention from 7 days to 3 days
confluent kafka topic update jegan_auditlog \
  --config retention.ms=259200000  # 3 days

Savings: ~30% storage costs ($15/month)
Trade-off: Shorter backfill window
```

#### **Strategy C: Enable Compression**
```bash
# Use zstd compression (60-70% compression ratio)
confluent kafka topic update jegan_auditlog \
  --config compression.type=zstd

Savings: 40% storage + 40% network egress (~$80/month)
```

---

### 2. **Optimize Iceberg Storage Costs**

#### **Strategy A: Use S3 Lifecycle Policies**
```bash
# Automatically transition to S3-IA after 30 days
aws s3api put-bucket-lifecycle-configuration \
  --bucket audit-iceberg-data \
  --lifecycle-configuration '{
    "Rules": [{
      "Id": "MoveToIA",
      "Status": "Enabled",
      "Transitions": [{
        "Days": 30,
        "StorageClass": "STANDARD_IA"
      }]
    }]
  }'

Savings: 50% on storage >30 days old (~$15-20/month)
```

#### **Strategy B: Archive Old Partitions to Glacier**
```bash
# Move data >90 days to Glacier Deep Archive
aws s3api put-bucket-lifecycle-configuration \
  --lifecycle-configuration '{
    "Rules": [{
      "Id": "ArchiveToGlacier",
      "Transitions": [{
        "Days": 90,
        "StorageClass": "DEEP_ARCHIVE"
      }]
    }]
  }'

Savings: 95% on archived data ($0.00099/GB vs $0.023/GB)
```

#### **Strategy C: Enable Iceberg Compaction**
```python
# Reduce small file overhead with compaction
from pyiceberg.catalog import load_catalog

catalog = load_catalog("default")
table = catalog.load_table("audit_events")

# Compact files daily (reduces storage by 10-15%)
table.compact()

Savings: $5-10/month on storage + faster queries
```

---

### 3. **Right-Size Compute Resources**

#### **Strategy A: Vertical Pod Autoscaling**
```yaml
# Kubernetes VPA automatically adjusts CPU/memory
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: audit-forwarder-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: audit-forwarder
  updatePolicy:
    updateMode: "Auto"

Savings: 20-30% on overprovisioned resources ($40-60/month)
```

#### **Strategy B: Horizontal Pod Autoscaling**
```yaml
# Scale dashboard replicas based on CPU usage
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: dashboard-hpa
spec:
  minReplicas: 1
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70

Savings: Run 1 replica during off-hours, scale to 5 during peak
Average cost: $50/month (vs. fixed 3 replicas at $90/month)
```

#### **Strategy C: Use Spot Instances (Non-Critical Workloads)**
```bash
# Run dashboard on spot instances (70% discount)
# Forwarder should always run on on-demand (stateful)

Savings: $60/month (dashboard only)
Trade-off: Occasional pod evictions (acceptable for stateless app)
```

---

### 4. **Reduce Monitoring Costs**

#### **Strategy A: Use Prometheus Recording Rules**
```yaml
# Pre-compute expensive queries, reduce storage
groups:
  - name: audit_metrics
    interval: 60s
    rules:
      - record: audit:events_per_hour
        expr: rate(audit_events_total[1h]) * 3600

Savings: 50% reduction in time-series cardinality
```

#### **Strategy B: Use Grafana Cloud Free Tier**
```
Free tier includes:
- 10K metrics series
- 50 GB logs
- 14-day retention

Savings: $65/month (vs. self-hosted Prometheus)
```

#### **Strategy C: Reduce Log Verbosity**
```bash
# Only log WARN and ERROR in production
export LOG_LEVEL=WARNING

Savings: 70% reduction in log volume (~$10/month)
```

---

### 5. **Optimize TableFlow Usage**

#### **Strategy A: Batch Events Before Writing**
```python
# TableFlow connector config: increase flush interval
{
  "flush.size": "10000",          # Batch 10K events
  "rotate.interval.ms": "300000"  # Flush every 5 minutes
}

Savings: 50% reduction in S3 PUT requests (~$7/month)
```

#### **Strategy B: Use Single Iceberg Table with Partitioning**
```python
# Instead of multiple tables, use one table with partitions
partition_spec = PartitionSpec(
    PartitionField(source_id=1, field_id=1000, transform=DayTransform(), name="event_date"),
    PartitionField(source_id=2, field_id=1001, transform=IdentityTransform(), name="criticality")
)

Savings: 1 TableFlow task instead of 4 ($237/month savings)
```

---

## Cost Monitoring & Alerts

### **Confluent Cloud Cost Tracking**

```bash
# Enable billing alerts in Confluent Cloud UI
# Set alert thresholds:
- Warning: $1,500/month (50% of budget)
- Critical: $2,000/month (80% of budget)

# Use Confluent CLI to check current spend
confluent billing cost list --start-date 2025-12-01
```

### **AWS Cost Explorer Tags**

```bash
# Tag all resources for cost allocation
aws resourcegroupstaggingapi tag-resources \
  --resource-arn-list <resource-arn> \
  --tags project=audit-intelligence,environment=production,cost-center=security

# Create cost anomaly detection
aws ce put-anomaly-monitor \
  --anomaly-monitor "Name=AuditSystemMonitor,MonitorType=DIMENSIONAL"
```

### **Kubernetes Cost Monitoring (Kubecost)**

```yaml
# Install Kubecost for per-pod cost tracking
helm install kubecost kubecost/cost-analyzer \
  --namespace kubecost \
  --set prometheus.enabled=true

# View dashboard at http://localhost:9090
kubectl port-forward -n kubecost svc/kubecost-cost-analyzer 9090:9090
```

---

## Budget Recommendations

### **Small Team (< 5 users, dev/staging only)**

**Monthly Budget:** $600-1,000

**Recommended Configuration:**
- Confluent Cloud Basic cluster
- 7-day Kafka retention
- 7-day Iceberg retention
- 1 forwarder replica
- 1 dashboard replica
- Free tier Grafana Cloud
- No load balancer (kubectl port-forward)

---

### **Medium Team (10-50 users, production)**

**Monthly Budget:** $2,000-3,000

**Recommended Configuration:**
- Confluent Cloud Standard cluster
- 7-day Kafka retention
- 30-day Iceberg retention (S3-IA)
- 3 forwarder replicas
- 3 dashboard replicas
- Prometheus + CloudWatch Logs
- ALB for dashboard

---

### **Enterprise (100+ users, high-scale production)**

**Monthly Budget:** $5,000-10,000

**Recommended Configuration:**
- Confluent Cloud Dedicated cluster
- 7-day Kafka retention
- 90-day Iceberg retention (S3 Intelligent-Tiering)
- 5 forwarder replicas (HPA enabled)
- 5 dashboard replicas (HPA enabled)
- Grafana Cloud Pro or Datadog
- Multi-region deployment (add 80% for DR)

---

## Cost vs. Value Analysis

| Scenario | Monthly Cost | Value Delivered |
|----------|--------------|----------------|
| **No Audit System** | $0 | Security blind spots, compliance risk, manual incident investigation (100+ hours/month @ $100/hour = $10,000 opportunity cost) |
| **Manual Audit Log Analysis** | $0 infrastructure + 40 hours/month @ $100/hour | $4,000/month labor cost, delayed detection, no automation |
| **Audit Intelligence System** | $2,000-3,000/month | Real-time threat detection, automated anomaly alerts, 95% reduction in investigation time, compliance automation |

**ROI Calculation:**
```
Labor savings: 40 hours/month × $100/hour = $4,000/month
Infrastructure cost: $2,500/month
Net savings: $1,500/month
Annual ROI: $18,000

Additional value:
- Reduced MTTR (Mean Time To Response): 4 hours → 15 minutes
- Prevented security incidents: $50,000+ per incident
- Compliance audit readiness: $20,000+ savings per audit
```

---

## Cost Review Checklist

**Monthly Cost Review:**
- [ ] Review Confluent Cloud bill for unexpected spikes
- [ ] Check Iceberg storage growth rate
- [ ] Verify TableFlow task count matches traffic
- [ ] Review Kubernetes resource utilization (VPA recommendations)
- [ ] Check for unused resources (idle clusters, stale data)

**Quarterly Optimization Review:**
- [ ] Evaluate retention policies (Kafka, Iceberg)
- [ ] Review compression effectiveness
- [ ] Analyze dashboard usage patterns (scale down if low usage)
- [ ] Consider reserved capacity for Kubernetes (up to 60% savings)
- [ ] Review S3 storage class distribution

**Annual Budget Planning:**
- [ ] Forecast event volume growth (20-50% YoY typical)
- [ ] Plan for Confluent Cloud tier upgrades
- [ ] Evaluate dedicated vs. standard cluster economics
- [ ] Budget for disaster recovery / multi-region
- [ ] Reserve budget for security incidents / scaling emergencies

---

## Appendix: Cost Calculators

### **Confluent Cloud Pricing Calculator**
https://www.confluent.io/pricing-calculator/

### **AWS Pricing Calculator**
https://calculator.aws/

### **Google Cloud Pricing Calculator**
https://cloud.google.com/products/calculator

### **Kubecost (Kubernetes Cost Monitoring)**
https://www.kubecost.com/

---

## Contact Information

**FinOps Team:** finops@company.com
**Confluent Account Manager:** [Your Account Manager]
**Cloud Cost Optimization:** cloud-ops@company.com
