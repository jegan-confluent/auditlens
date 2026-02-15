# Confluent Cloud Audit Log Analyzer

**One-click deployment to analyze "who did what, when" in your Confluent Cloud organization.**

```
┌─────────────────────────────┐        ┌─────────────────────────────┐
│  AUDIT LOG CLUSTER          │        │  YOUR CLUSTER               │
│  (Managed by Confluent)     │        │  (You provide)              │
│                             │        │                             │
│  confluent-audit-log-events │        │  Output Topics:             │
│  (nested JSON, v1.2 schema) │───┐    │  • audit_events_flattened   │
│                             │   │    │  • audit_deletions          │
│  Get via:                   │   │    │  • audit_api_keys           │
│  confluent audit-log describe   │    │  • audit_security_events    │
└─────────────────────────────┘   │    │  • audit_user_activity      │
                                  │    │  • ...                      │
                                  │    └─────────────────────────────┘
                                  │                  ▲
                                  ▼                  │
                        ┌─────────────────────────────┐
                        │   PYTHON FORWARDER          │
                        │  • Reads from audit cluster │
                        │  • Flattens nested JSON     │
                        │  • Validates with Schema    │
                        │  • Writes to your cluster   │
                        │  • Prometheus metrics       │
                        └────────────┬────────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────────┐
                        │     FLINK COMPUTE POOL      │
                        │  • Reads flattened topic    │
                        │  • Creates aggregations     │
                        │  • Pre-computed summaries   │
                        │  • Windowed analytics       │
                        └─────────────────────────────┘
```

## What It Does (The Heavy Lifting)

1. **You provide**: Confluent Cloud API credentials + Schema Registry
2. **We forward**: Python app reads audit logs and flattens nested JSON
3. **We validate**: Schema Registry enforces data consistency
4. **We aggregate**: Flink creates pre-computed tables for dashboards
5. **You query**: Simple SQL for any question

## Quick Start (5 Minutes)

### Step 1: Run Setup Script

```bash
# Login to Confluent Cloud
confluent login

# Run setup (collects credentials, creates topics)
./setup.sh
```

The setup script will:
- Get audit log cluster details
- Ask for your destination cluster
- Collect Schema Registry credentials
- Create output topics
- Set up Flink compute pool
- Generate .env and .secrets files

### Step 2: Start the Forwarder

```bash
# Start Python forwarder in Docker
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Step 3: Deploy Flink Aggregations (Optional)

```bash
# Open Flink shell
confluent flink shell --compute-pool <pool-id> --environment <env-id>

# Run SQL files in order
# flink-sql/01_audit_events_source.sql
# flink-sql/02_audit_events_flattened.sql  (if not using Python)
# flink-sql/03_aggregation_tables.sql
```

### Alternative: Terraform

```bash
cd deploy/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your credentials
terraform init
terraform apply
```

## What Gets Created

### Flattened Events Table
All nested audit log data → flat columns:

| Column | Description |
|--------|-------------|
| `event_time` | When it happened |
| `principal` | Who did it |
| `principal_type` | User or ServiceAccount |
| `method_name` | What action |
| `resource_type` | Topic, Cluster, Connector, etc. |
| `resource_name` | Name of the resource |
| `cluster_id` | Which cluster |
| `result_status` | SUCCESS, PERMISSION_DENIED, etc. |
| `criticality` | CRITICAL, HIGH, MEDIUM, LOW |
| `is_deletion` | TRUE/FALSE |
| `is_security_event` | Auth failure or permission denied |
| `client_ip` | Source IP address |

### Pre-Computed Aggregation Tables

| Table | What It Contains |
|-------|------------------|
| `audit_deletions` | All deletion events |
| `audit_creations` | All creation events |
| `audit_api_keys` | API key lifecycle events |
| `audit_security_events` | Auth failures, permission denied |
| `audit_user_activity` | Activity summary per user |
| `audit_cluster_activity` | Activity summary per cluster |
| `audit_by_resource_type` | Activity grouped by resource |
| `audit_by_criticality` | Activity grouped by severity |

## Example Queries

### Who deleted topics?
```sql
SELECT event_time, principal, resource_name, cluster_id
FROM audit_deletions
WHERE method_name LIKE '%Topic%'
ORDER BY event_time DESC;
```

### Who deleted my cluster?
```sql
SELECT event_time, principal, cluster_id, client_ip
FROM audit_deletions
WHERE method_name LIKE '%Cluster%';
```

### Authentication failures (last 24h)
```sql
SELECT event_time, principal, client_ip, result_message
FROM audit_events_flattened
WHERE is_auth_failure = TRUE
  AND event_time > CURRENT_TIMESTAMP - INTERVAL '24' HOUR;
```

### Suspicious IPs (multiple failures)
```sql
SELECT client_ip, COUNT(*) as failures
FROM audit_events_flattened
WHERE is_security_event = TRUE
GROUP BY client_ip
HAVING COUNT(*) >= 5;
```

### What did user X do?
```sql
SELECT event_time, method_name, resource_type, resource_name
FROM audit_events_flattened
WHERE principal = 'User:john@company.com'
ORDER BY event_time DESC;
```

### API key audit
```sql
SELECT event_time, principal, method_name, resource_name
FROM audit_api_keys
ORDER BY event_time DESC;
```

### Critical events
```sql
SELECT * FROM audit_events_flattened
WHERE criticality = 'CRITICAL'
ORDER BY event_time DESC;
```

### Activity by criticality (dashboard)
```sql
SELECT criticality, event_category, SUM(event_count) as total
FROM audit_by_criticality
WHERE window_start > CURRENT_TIMESTAMP - INTERVAL '24' HOUR
GROUP BY criticality, event_category;
```

See [flink-sql/04_dashboard_queries.sql](flink-sql/04_dashboard_queries.sql) for 30+ ready queries.

## Access Your Data

### Flink SQL Shell
```bash
confluent flink shell \
  --compute-pool <pool-id> \
  --environment <env-id>
```

### Confluent Cloud Console
Go to https://confluent.cloud/flink and run queries directly.

### Connect External Tools
The flattened tables are Kafka topics. Connect with:
- **Athena** (via Tableflow)
- **BigQuery** (via sink connector)
- **Dremio** (direct Kafka connection)
- **Grafana** (via Kafka datasource)
- **Any Kafka consumer**

## Architecture

```
Audit Log Topic (confluent-audit-log-events)
         │
         │ CloudEvents JSON (nested)
         ▼
┌─────────────────────────────────────────────┐
│            Flink Compute Pool               │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ 01_audit_events_source.sql          │   │
│  │ - Defines nested schema             │   │
│  └──────────────┬──────────────────────┘   │
│                 │                           │
│  ┌──────────────▼──────────────────────┐   │
│  │ 02_audit_events_flattened.sql       │   │
│  │ - Extracts all fields               │   │
│  │ - Parses CRN                        │   │
│  │ - Adds criticality flags            │   │
│  └──────────────┬──────────────────────┘   │
│                 │                           │
│  ┌──────────────▼──────────────────────┐   │
│  │ 03_aggregation_tables.sql           │   │
│  │ - Pre-computed summaries            │   │
│  │ - Windowed aggregations             │   │
│  └─────────────────────────────────────┘   │
│                                             │
└─────────────────────────────────────────────┘
         │
         ▼
    Kafka Topics (queryable via Flink SQL)
    ├── audit_events_flattened
    ├── audit_deletions
    ├── audit_creations
    ├── audit_api_keys
    ├── audit_security_events
    ├── audit_user_activity
    ├── audit_cluster_activity
    ├── audit_by_resource_type
    └── audit_by_criticality
```

## Files

```
├── deploy.sh                    # One-click deploy script
├── flink-sql/
│   ├── 01_audit_events_source.sql      # Source table definition
│   ├── 02_audit_events_flattened.sql   # Flattening transformation
│   ├── 03_aggregation_tables.sql       # Pre-computed aggregations
│   └── 04_dashboard_queries.sql        # Ready-to-use queries
├── deploy/terraform/
│   ├── main.tf                  # Terraform config
│   └── terraform.tfvars.example # Example variables
└── docs/
    ├── AUDIT_QUERIES.md         # Query reference
    └── QUICK_START.md           # Getting started
```

## Requirements

- Confluent Cloud account with audit logs enabled
- `confluent` CLI installed
- (Optional) Terraform for IaC deployment

## Costs

- **Flink Compute Pool**: Starting at 5 CFUs (~$0.35/hour)
- **Kafka Topics**: Standard topic pricing for aggregation tables
- Typical cost: ~$300-500/month for moderate audit log volume

## Why Flink SQL?

- **No infrastructure to manage**: Serverless Flink in Confluent Cloud
- **Real-time**: Events processed as they arrive
- **SQL**: Familiar query language, no code needed
- **Scales automatically**: Handle any audit log volume
- **Native integration**: Direct access to Confluent Cloud topics

## Support

- [Confluent Flink Documentation](https://docs.confluent.io/cloud/current/flink/)
- [Audit Log Schema Reference](https://docs.confluent.io/cloud/current/monitoring/audit-logging/audit-log-schema.html)
