# Architecture Guide - Audit Forwarder v2

This document covers the architecture options for processing Confluent Cloud audit logs.

## Architecture Options

### Option 1: Tableflow + Flink (Recommended for AWS)

**Best for:** AWS deployments, Athena/Redshift analytics, minimal infrastructure management

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    TABLEFLOW + FLINK ARCHITECTURE (AWS)                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────────┐                                                           │
│  │ Confluent Cloud  │                                                           │
│  │ Audit Log Topic  │                                                           │
│  │ (Source)         │                                                           │
│  └────────┬─────────┘                                                           │
│           │                                                                      │
│           ▼                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                         FLINK SQL PROCESSING                              │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐   │   │
│  │  │ CRN Extraction  │  │ Event           │  │ Windowed Aggregations   │   │   │
│  │  │ & Parsing       │─▶│ Classification  │─▶│ (5min, 1hr)             │   │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│           │                         │                        │                   │
│           ▼                         ▼                        ▼                   │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────────┐      │
│  │ Processed       │    │ Alert Topics    │    │ Stats Topics            │      │
│  │ Events Topic    │    │ (Auth Failures, │    │ (Hourly Aggregates)     │      │
│  │                 │    │  Transparency)  │    │                         │      │
│  └────────┬────────┘    └────────┬────────┘    └───────────┬─────────────┘      │
│           │                      │                         │                     │
│           └──────────────────────┼─────────────────────────┘                     │
│                                  │                                               │
│                                  ▼                                               │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                           TABLEFLOW                                       │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │   │
│  │  │ Automatic Iceberg Table Materialization                             │ │   │
│  │  │ • Schema Evolution                                                  │ │   │
│  │  │ • Partition Management                                              │ │   │
│  │  │ • Compaction & Maintenance                                          │ │   │
│  │  │ • Exactly-once Semantics                                            │ │   │
│  │  └─────────────────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                  │                                               │
│                    ┌─────────────┴─────────────┐                                │
│                    ▼                           ▼                                │
│  ┌──────────────────────────┐    ┌──────────────────────────┐                  │
│  │ AWS Glue Data Catalog    │    │ S3 (Iceberg Tables)      │                  │
│  │ • Database per cluster   │    │ • Parquet files          │                  │
│  │ • Auto-sync metadata     │    │ • Time-partitioned       │                  │
│  └────────────┬─────────────┘    │ • Snappy compressed      │                  │
│               │                  └──────────────────────────┘                  │
│               │                                                                 │
│    ┌──────────┴─────────────────────────────────────┐                          │
│    │                                                │                          │
│    ▼                                                ▼                          │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐         │
│  │ Amazon Athena    │    │ Redshift         │    │ QuickSight       │         │
│  │ (SQL Queries)    │    │ Spectrum         │    │ (Dashboards)     │         │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘         │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Key Benefits:**
- Zero infrastructure to manage (fully serverless)
- Automatic schema evolution
- Time travel queries (Iceberg feature)
- Native Athena/Redshift integration
- Exactly-once processing guarantees

**Requirements:**
- Confluent Cloud Dedicated cluster (AWS)
- Topics must have schemas (Avro/Protobuf/JSON Schema)

### Option 2: Python Forwarder (Multi-Cloud)

**Best for:** GCP deployments, custom processing logic, multi-cloud environments

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    PYTHON FORWARDER ARCHITECTURE (Multi-Cloud)                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────────┐                                                           │
│  │ Confluent Cloud  │                                                           │
│  │ Audit Log Topic  │                                                           │
│  └────────┬─────────┘                                                           │
│           │                                                                      │
│           ▼                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                      PYTHON AUDIT FORWARDER                               │   │
│  │                                                                           │   │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │   │
│  │  │   Kafka     │──▶│ CloudEvents │──▶│    CRN      │──▶│   Event     │   │   │
│  │  │  Consumer   │   │   Parser    │   │   Parser    │   │   Router    │   │   │
│  │  └─────────────┘   └─────────────┘   └─────────────┘   └──────┬──────┘   │   │
│  │                                                                │          │   │
│  │  ┌────────────────────────────────────────────────────────────┘          │   │
│  │  │                                                                        │   │
│  │  ▼                         ▼                         ▼                    │   │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │   │
│  │  │ Kafka Sink  │   │  S3 Sink    │   │  GCS Sink   │   │  DLQ Sink   │   │   │
│  │  │ (Processed) │   │ (Parquet)   │   │ (Parquet)   │   │ (Failures)  │   │   │
│  │  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   │   │
│  │                                                                           │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │   │
│  │  │ Resilience: Circuit Breaker, Retry with Backoff, Buffering          │ │   │
│  │  └─────────────────────────────────────────────────────────────────────┘ │   │
│  │                                                                           │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │   │
│  │  │ MCP Server: list_events, search, export, analyze, get_status        │ │   │
│  │  └─────────────────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│           │                         │                         │                  │
│           ▼                         ▼                         ▼                  │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐             │
│  │ Destination     │    │ S3 / GCS        │    │ BigQuery /      │             │
│  │ Kafka Topic     │    │ (Parquet)       │    │ Athena          │             │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘             │
│                                                                                  │
│  Deployment Options:                                                             │
│  ├── AWS: ECS Fargate + S3                                                      │
│  ├── GCP: Cloud Run + GCS                                                       │
│  └── K8s: Any Kubernetes cluster                                                │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Key Benefits:**
- Works on any cloud (AWS, GCP, Azure)
- Custom processing logic possible
- MCP server for AI agent integration
- More control over batching and partitioning

**Requirements:**
- Container runtime (ECS, Cloud Run, Kubernetes)
- Cloud storage bucket (S3 or GCS)

### Option 3: Hybrid (Recommended for Multi-Cloud)

**Best for:** Organizations using both AWS and GCP

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         HYBRID ARCHITECTURE                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────────┐                                                           │
│  │ Confluent Cloud  │                                                           │
│  │ Audit Log Topic  │                                                           │
│  └────────┬─────────┘                                                           │
│           │                                                                      │
│           ├───────────────────────────────────┐                                 │
│           │                                   │                                 │
│           ▼                                   ▼                                 │
│  ┌─────────────────────────┐    ┌─────────────────────────┐                    │
│  │ AWS PATH                │    │ GCP PATH                │                    │
│  │                         │    │                         │                    │
│  │ Flink SQL Processing    │    │ Python Forwarder        │                    │
│  │         │               │    │ (Cloud Run)             │                    │
│  │         ▼               │    │         │               │                    │
│  │ Tableflow → Iceberg     │    │         ▼               │                    │
│  │         │               │    │ GCS (Parquet)           │                    │
│  │         ▼               │    │         │               │                    │
│  │ AWS Glue Catalog        │    │         ▼               │                    │
│  │         │               │    │ BigQuery External       │                    │
│  │         ▼               │    │ Tables                  │                    │
│  │ Athena / Redshift       │    │                         │                    │
│  │                         │    │                         │                    │
│  └─────────────────────────┘    └─────────────────────────┘                    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Feature Comparison

| Feature | Tableflow + Flink | Python Forwarder |
|---------|-------------------|------------------|
| **Cloud Support** | AWS only | AWS, GCP, Azure |
| **Schema Evolution** | Automatic | Manual |
| **Exactly-once** | Built-in | Manual (with effort) |
| **Time Travel** | Yes (Iceberg) | No |
| **Athena Support** | Native | Via Glue Crawler |
| **BigQuery Support** | No | Yes |
| **Custom Logic** | Limited (SQL) | Full flexibility |
| **MCP Integration** | No | Yes |
| **Infrastructure** | None (serverless) | Container runtime |
| **Cost Model** | CFU + Storage | Compute + Storage |

## Recommended Architecture by Use Case

### 1. AWS-only, Analytics-focused
**Use:** Tableflow + Flink
- Direct Athena integration
- Minimal operational overhead
- Best query performance

### 2. GCP-only
**Use:** Python Forwarder
- Cloud Run deployment
- GCS + BigQuery
- MCP for AI agents

### 3. Multi-cloud
**Use:** Hybrid
- Tableflow for AWS analytics
- Python forwarder for GCP
- Consistent data in both clouds

### 4. Custom Processing Requirements
**Use:** Python Forwarder
- Full control over transformations
- Custom enrichment logic
- Integration with other systems

## Deployment Quick Reference

### Tableflow + Flink (AWS)

```bash
cd deploy/terraform/confluent-cloud

# Enable Tableflow and Flink
cat >> terraform.tfvars <<EOF
tableflow_enabled    = true
tableflow_s3_bucket  = "my-audit-logs-bucket"
tableflow_s3_region  = "us-west-2"
glue_enabled         = true
glue_catalog_id      = "123456789012"
flink_enabled        = true
flink_region         = "us-west-2"
flink_max_cfu        = 10
EOF

terraform apply

# Deploy Flink SQL statements
confluent flink statement create --sql "$(cat flink-sql/03_process_audit_events.sql)"
```

### Python Forwarder (GCP)

```bash
cd deploy/terraform/gcp
terraform apply

# Build and push image
gcloud builds submit --tag gcr.io/$PROJECT_ID/audit-forwarder

# Deploy to Cloud Run
gcloud run deploy audit-forwarder \
  --image gcr.io/$PROJECT_ID/audit-forwarder \
  --region us-central1
```

## Querying Audit Logs

### With Athena (Tableflow)

```sql
-- All authentication failures in last 24 hours
SELECT
    event_time,
    principal,
    cluster_id,
    result_status,
    client_address
FROM "lkc-xxxxx"."audit_events_processed"
WHERE is_authentication_failure = true
  AND event_time > current_timestamp - interval '24' hour
ORDER BY event_time DESC;

-- Hourly failure rate by cluster
SELECT
    date_trunc('hour', event_time) as hour,
    cluster_id,
    COUNT(*) as total_events,
    SUM(CASE WHEN result_status != 'SUCCESS' THEN 1 ELSE 0 END) as failures
FROM "lkc-xxxxx"."audit_events_processed"
WHERE event_time > current_timestamp - interval '7' day
GROUP BY 1, 2
ORDER BY 1 DESC;
```

### With BigQuery (Python Forwarder)

```sql
-- Create external table
CREATE EXTERNAL TABLE `project.dataset.audit_events`
WITH PARTITION COLUMNS
OPTIONS (
  format = 'PARQUET',
  uris = ['gs://my-bucket/confluent-audit-logs/*']
);

-- Query authentication failures
SELECT *
FROM `project.dataset.audit_events`
WHERE is_authentication_failure = true
  AND event_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR);
```

## Data Flow Summary

```
Source                    Processing              Storage              Analytics
──────                    ──────────              ───────              ─────────

                          ┌─ Flink SQL ─┐         ┌─ Iceberg ─┐        ┌─ Athena
Audit Log     ────────────┤             ├─────────┤           ├────────┤  Redshift
Topic                     │  OR         │         │  OR       │        │  QuickSight
                          │             │         │           │        │
                          └─ Python ────┘         └─ Parquet ─┘        └─ BigQuery
                                                      │
                                                      └─────────────────── MCP/AI
```
