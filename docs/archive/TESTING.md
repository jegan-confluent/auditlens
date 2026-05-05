# Testing Guide - Confluent Cloud Audit Log Analyzer

This guide covers testing the Flink SQL-based Audit Log Analyzer.

---

## Understanding the Architecture

```
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│  AUDIT LOG CLUSTER              │     │  YOUR CLUSTER (Destination)     │
│  (Managed by Confluent)         │     │  (You provide this)             │
│                                 │     │                                 │
│  Topic:                         │     │  Topics we CREATE:              │
│  - confluent-audit-log-events   │────▶│  - audit_events_flattened       │
│                                 │     │  - audit_deletions              │
│  Get details via:               │     │  - audit_api_keys               │
│  confluent audit-log describe   │     │  - audit_security_events        │
│                                 │     │  - etc.                         │
└─────────────────────────────────┘     └─────────────────────────────────┘
         │                                           │
         │                                           │
         └──────────────┬────────────────────────────┘
                        │
                        ▼
              ┌─────────────────────────────────┐
              │  FLINK COMPUTE POOL             │
              │  - Reads from audit cluster     │
              │  - Transforms (flattens) data   │
              │  - Writes to your cluster       │
              └─────────────────────────────────┘
```

**Key Points:**
- Audit log cluster is **SEPARATE** and **READ-ONLY** (managed by Confluent)
- You provide **YOUR cluster** where output topics will be created
- Flink reads from audit cluster, writes to your cluster
- You need API keys for **BOTH** clusters

---

## Prerequisites

### 1. Install Confluent CLI

```bash
# macOS
brew install confluentinc/tap/cli

# Linux
curl -sL https://cnfl.io/cli | sh -s -- latest

# Verify installation
confluent version
```

### 2. Login to Confluent Cloud

```bash
confluent login

# Verify you're logged in
confluent environment list
```

### 3. Required Permissions

You need one of these roles:
- **OrganizationAdmin** - Full access
- **EnvironmentAdmin** - Environment-level access
- **FlinkDeveloper** - Flink-specific access

Check your roles:
```bash
confluent iam rbac role-binding list --principal User:<your-user-id>
```

---

## Step 1: Get Audit Log Cluster Details

The audit log cluster is **managed by Confluent** and separate from your clusters.

```bash
# Get audit log cluster details
confluent audit-log describe

# This returns:
# - Cluster ID (e.g., lkc-audit123)
# - Bootstrap servers
# - Topic name (confluent-audit-log-events)
```

Save these details:
```bash
# Parse the output (or note them manually)
AUDIT_INFO=$(confluent audit-log describe -o json)
AUDIT_CLUSTER_ID=$(echo $AUDIT_INFO | jq -r '.cluster_id')
AUDIT_BOOTSTRAP=$(echo $AUDIT_INFO | jq -r '.bootstrap_servers')
echo "Audit Cluster: $AUDIT_CLUSTER_ID"
echo "Bootstrap: $AUDIT_BOOTSTRAP"
```

If audit logging is not enabled, you'll get an error. Enable it in:
**Confluent Cloud Console > Organization Settings > Audit Logs**

---

## Step 2: Get API Key for Audit Log Cluster

```bash
# Create an API key for the audit log cluster
confluent api-key create --resource $AUDIT_CLUSTER_ID --description "Audit log reader"

# Save the key and secret securely!
export AUDIT_API_KEY="<key>"
export AUDIT_API_SECRET="<secret>"
```

### Validate Connectivity

```bash
# Test that you can connect to the audit cluster
# This uses the Confluent CLI's built-in consumer
confluent kafka topic consume confluent-audit-log-events \
    --cluster $AUDIT_CLUSTER_ID \
    --api-key $AUDIT_API_KEY \
    --api-secret $AUDIT_API_SECRET \
    --from-beginning \
    --print-key \
    --limit 1
```

If you see an event, connectivity is working!

---

## Step 3: Select Your Destination Cluster

This is YOUR existing cluster where output topics will be created.

```bash
# List your environments
confluent environment list

# Set your environment
export DEST_ENV_ID="env-xxxxx"
confluent environment use $DEST_ENV_ID

# List your clusters
confluent kafka cluster list

# Select your destination cluster
export DEST_CLUSTER_ID="lkc-xxxxx"
confluent kafka cluster use $DEST_CLUSTER_ID

# Get bootstrap servers
confluent kafka cluster describe $DEST_CLUSTER_ID
```

### Get API Key for Destination Cluster

```bash
# Create or use existing API key
confluent api-key create --resource $DEST_CLUSTER_ID --description "Audit analyzer output"

export DEST_API_KEY="<key>"
export DEST_API_SECRET="<secret>"
```

---

## Step 4: Create Output Topics in Your Cluster

```bash
# Create the output topics
TOPICS=(
    "audit_events_flattened"
    "audit_deletions"
    "audit_creations"
    "audit_api_keys"
    "audit_security_events"
    "audit_user_activity"
    "audit_cluster_activity"
    "audit_by_resource_type"
    "audit_by_criticality"
)

for topic in "${TOPICS[@]}"; do
    confluent kafka topic create $topic \
        --cluster $DEST_CLUSTER_ID \
        --partitions 6 \
        --config cleanup.policy=compact
    echo "Created: $topic"
done

# Verify topics were created
confluent kafka topic list --cluster $DEST_CLUSTER_ID | grep audit
```

---

## Step 5: Create Flink Compute Pool

```bash
# Check existing compute pools
confluent flink compute-pool list

# Create a new compute pool (if none exists)
confluent flink compute-pool create audit-analyzer-test \
  --cloud AWS \
  --region us-east-1 \
  --max-cfu 5

# Note the compute pool ID
export POOL_ID="lfcp-xxxxx"

# Use the compute pool
confluent flink compute-pool use $POOL_ID
```

**Regions:** Choose a region close to your audit log cluster for best performance.

---

## Step 3: Test with Flink SQL Shell

### Open the Shell

```bash
confluent flink shell --compute-pool $POOL_ID
```

You should see the Flink SQL prompt:
```
Flink SQL>
```

### Test Basic Connectivity

```sql
-- List available catalogs (environments)
SHOW CATALOGS;

-- Use your environment catalog
USE CATALOG `<your-environment-name>`;

-- List databases (clusters)
SHOW DATABASES;

-- Use your cluster database
USE `<your-cluster-name>`;

-- List tables (topics)
SHOW TABLES;
```

### Test Reading Raw Audit Events

```sql
-- Read a few raw events (this confirms connectivity)
SELECT * FROM `confluent-audit-log-events` LIMIT 5;

-- If you see data, the connection works!
-- If empty, wait a few minutes or generate some events (see Step 6)
```

---

## Step 4: Test Schema Flattening

### Quick Test - Manual Flattening

```sql
-- Test extracting nested fields
SELECT
    `id` AS event_id,
    `time` AS event_time,
    `type` AS event_type,
    `data`.`methodName` AS method_name,
    `data`.`authenticationInfo`.`principal` AS principal,
    `data`.`result`.`status` AS result_status
FROM `confluent-audit-log-events`
LIMIT 10;
```

### Test CRN Parsing

```sql
-- Test extracting organization/environment/cluster from CRN
SELECT
    `source`,
    REGEXP_EXTRACT(`source`, 'organization=([^/]+)', 1) AS org_id,
    REGEXP_EXTRACT(`source`, 'environment=([^/]+)', 1) AS env_id,
    REGEXP_EXTRACT(`source`, 'kafka=([^/]+)', 1) AS cluster_id
FROM `confluent-audit-log-events`
WHERE `source` IS NOT NULL
LIMIT 10;
```

### Test Criticality Classification

```sql
-- Test criticality logic
SELECT
    `data`.`methodName` AS method,
    CASE
        WHEN `data`.`methodName` LIKE '%DeleteKafkaCluster%' THEN 'CRITICAL'
        WHEN `data`.`methodName` LIKE '%Delete%' THEN 'HIGH'
        WHEN `data`.`methodName` LIKE '%Create%' THEN 'MEDIUM'
        ELSE 'LOW'
    END AS criticality
FROM `confluent-audit-log-events`
WHERE `data`.`methodName` IS NOT NULL
LIMIT 20;
```

---

## Step 5: Deploy Full Solution

### Option A: Use Deploy Script

```bash
# Exit the Flink shell first
EXIT;

# Run the deploy script
cd /Users/jegan/playground/audit-forwarder
./deploy.sh
```

### Option B: Manual SQL Deployment

Deploy each SQL file in order:

```bash
# 1. Source table (defines nested schema)
confluent flink statement create \
  --sql "$(cat flink-sql/01_audit_events_source.sql)" \
  --compute-pool $POOL_ID \
  --statement-name "audit-source-table"

# 2. Flattened table (transforms data)
confluent flink statement create \
  --sql "$(cat flink-sql/02_audit_events_flattened.sql)" \
  --compute-pool $POOL_ID \
  --statement-name "audit-flattened-table"

# 3. Aggregation tables
confluent flink statement create \
  --sql "$(cat flink-sql/03_aggregation_tables.sql)" \
  --compute-pool $POOL_ID \
  --statement-name "audit-aggregations"
```

### Check Statement Status

```bash
# List all statements
confluent flink statement list --compute-pool $POOL_ID

# Check specific statement details
confluent flink statement describe <statement-name> --compute-pool $POOL_ID
```

---

## Step 6: Generate Test Events

Generate audit events by performing actions in Confluent Cloud:

```bash
# Create a test topic (generates CreateTopics event)
confluent kafka topic create test-audit-topic-$(date +%s) --cluster $CLUSTER_ID

# List topics (generates metadata events)
confluent kafka topic list --cluster $CLUSTER_ID

# Delete the test topic (generates DeleteTopics event)
confluent kafka topic delete test-audit-topic-* --cluster $CLUSTER_ID

# Create an API key (generates CreateApiKey event)
confluent api-key create --resource $CLUSTER_ID --description "Test key"

# List API keys
confluent api-key list --resource $CLUSTER_ID
```

Wait 1-2 minutes for events to appear in the audit log.

---

## Step 7: Verify Tables Are Working

Open Flink SQL shell and run verification queries:

```bash
confluent flink shell --compute-pool $POOL_ID
```

```sql
-- Check all tables exist
SHOW TABLES;

-- Expected tables:
-- audit_events_flattened
-- audit_deletions
-- audit_creations
-- audit_api_keys
-- audit_security_events
-- audit_user_activity
-- audit_cluster_activity
-- audit_by_resource_type
-- audit_by_criticality

-- Test flattened events
SELECT event_time, principal, method_name, criticality
FROM audit_events_flattened
ORDER BY event_time DESC
LIMIT 10;

-- Test deletions table
SELECT * FROM audit_deletions
ORDER BY event_time DESC
LIMIT 5;

-- Test creations table
SELECT * FROM audit_creations
ORDER BY event_time DESC
LIMIT 5;

-- Test API key tracking
SELECT * FROM audit_api_keys
ORDER BY event_time DESC
LIMIT 5;

-- Test user activity
SELECT * FROM audit_user_activity
ORDER BY window_start DESC
LIMIT 5;

-- Test security events
SELECT * FROM audit_security_events
ORDER BY window_start DESC
LIMIT 5;
```

---

## Step 8: Test Dashboard Queries

Run queries from `flink-sql/04_dashboard_queries.sql`:

```sql
-- Who did what today?
SELECT event_time, principal, method_name, resource_name
FROM audit_events_flattened
WHERE event_time > CURRENT_TIMESTAMP - INTERVAL '24' HOUR
ORDER BY event_time DESC
LIMIT 20;

-- Any deletions?
SELECT event_time, principal, method_name, resource_name
FROM audit_deletions
ORDER BY event_time DESC;

-- Critical events
SELECT * FROM audit_events_flattened
WHERE criticality = 'CRITICAL'
ORDER BY event_time DESC;

-- Activity summary
SELECT
    principal,
    COUNT(*) as total_actions,
    SUM(CASE WHEN is_deletion THEN 1 ELSE 0 END) as deletions
FROM audit_events_flattened
WHERE event_time > CURRENT_TIMESTAMP - INTERVAL '24' HOUR
GROUP BY principal
ORDER BY total_actions DESC;
```

---

## Troubleshooting

### Issue: "Topic not found"

```bash
# Check if audit log topic exists
confluent kafka topic list --cluster $CLUSTER_ID | grep audit

# If not found:
# 1. Audit logging may not be enabled
# 2. You may be looking at the wrong cluster
# 3. Check Confluent Cloud Console > Organization > Audit Logs
```

### Issue: "No data in tables"

```sql
-- Check if raw events are flowing
SELECT COUNT(*) FROM `confluent-audit-log-events`;

-- If 0:
-- 1. Wait 2-3 minutes (audit events have some delay)
-- 2. Generate events (see Step 6)
-- 3. Check audit logging is enabled for your org
```

### Issue: "Permission denied"

```bash
# Check your role
confluent iam rbac role-binding list --principal User:<your-id>

# You need FlinkDeveloper or higher
# Request access from your OrganizationAdmin
```

### Issue: "Statement failed"

```bash
# Get statement details
confluent flink statement describe <statement-name> --compute-pool $POOL_ID

# Common causes:
# 1. SQL syntax error - check the SQL file
# 2. Schema mismatch - audit log schema may have changed
# 3. Resource limits - increase CFUs
```

### Issue: "Schema mismatch"

```sql
-- Check actual schema of audit topic
DESCRIBE `confluent-audit-log-events`;

-- Compare with 01_audit_events_source.sql
-- Adjust if Confluent updated the schema
```

---

## Cleanup

### Stop Statements (Keep Compute Pool)

```bash
# List statements
confluent flink statement list --compute-pool $POOL_ID

# Delete specific statement
confluent flink statement delete <statement-name> --compute-pool $POOL_ID
```

### Delete Compute Pool (Full Cleanup)

```bash
confluent flink compute-pool delete $POOL_ID
```

### Delete Created Topics

```bash
# List audit-related topics (created by Flink)
confluent kafka topic list --cluster $CLUSTER_ID | grep audit

# Delete them if needed
confluent kafka topic delete <topic-name> --cluster $CLUSTER_ID
```

---

## Test Checklist

- [ ] Confluent CLI installed and logged in
- [ ] Can list environments and clusters
- [ ] Identified audit log cluster ID
- [ ] Flink compute pool created
- [ ] Can open Flink SQL shell
- [ ] Can query raw `confluent-audit-log-events` topic
- [ ] CRN parsing works (org_id, env_id, cluster_id extracted)
- [ ] Flattened table created and receiving data
- [ ] Aggregation tables created and populating
- [ ] Dashboard queries return results
- [ ] Generated test events visible in tables

---

## Quick Reference

```bash
# Environment setup
export ENV_ID="env-xxxxx"
export CLUSTER_ID="lkc-xxxxx"
export POOL_ID="lfcp-xxxxx"

# Open Flink shell
confluent flink shell --compute-pool $POOL_ID

# Deploy SQL
confluent flink statement create --sql "$(cat file.sql)" --compute-pool $POOL_ID

# Check statements
confluent flink statement list --compute-pool $POOL_ID

# Generate events
confluent kafka topic create test-topic --cluster $CLUSTER_ID
confluent kafka topic delete test-topic --cluster $CLUSTER_ID
```

---

## Next Steps After Testing

1. **Increase CFUs** for production workload
2. **Connect Grafana** for dashboards
3. **Set up alerts** for critical events
4. **Enable Tableflow** for Athena/BigQuery integration
5. **Share queries** with your security/compliance team
