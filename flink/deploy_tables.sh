#!/bin/bash
# ============================================================================
# Deploy Audit Log Tableflow Tables
# ============================================================================
# Creates materialized tables for instant customer queries
# Run once to set up, Flink maintains them continuously
# ============================================================================

set -e

# Load config
source ../.env
source ../.secrets 2>/dev/null || true

echo "============================================"
echo "Deploying Audit Log Tableflow Tables"
echo "============================================"
echo ""
echo "Environment: $DEST_ENV_ID"
echo "Compute Pool: $FLINK_POOL_ID"
echo "Database: $DEST_CLUSTER_ID"
echo ""

# Version suffix to create unique statement names
VERSION="v6"

# Function to run Flink SQL statement
run_sql() {
    local name="$1-$VERSION"
    local sql="$2"

    echo "Creating: $name..."

    # Delete any existing statement with this name first
    confluent flink statement delete "$name" \
        --environment "$DEST_ENV_ID" \
        --cloud aws --region ap-south-1 2>/dev/null || true

    # Create statement with database context
    confluent flink statement create "$name" \
        --sql "$sql" \
        --compute-pool "$FLINK_POOL_ID" \
        --environment "$DEST_ENV_ID" \
        --database "$DEST_CLUSTER_ID" \
        --wait 2>/dev/null || echo "  (statement created or exists)"
}

# ============================================================================
# 1. DELETIONS TABLE (using new table name to avoid schema conflicts)
# ============================================================================
echo ""
echo "=== Creating Deletions Table ==="

run_sql "create-deletions-v2" "
CREATE TABLE IF NOT EXISTS deletions_v2 (
    id STRING PRIMARY KEY NOT ENFORCED,
    deleted_at STRING,
    principal STRING,
    methodName STRING,
    resource_type STRING,
    resource_id STRING,
    details STRING
) WITH (
    'changelog.mode' = 'upsert',
    'value.format' = 'json-registry'
)"

run_sql "populate-deletions-v2" "INSERT INTO deletions_v2
SELECT
    id,
    \`time\` AS deleted_at,
    principal,
    methodName,
    resourceType AS resource_type,
    COALESCE(
        JSON_VALUE(data_json, '\$.cloudResources[0].resource.resourceId'),
        JSON_VALUE(data_json, '\$.request.data.id'),
        'unknown'
    ) AS resource_id,
    COALESCE(
        JSON_VALUE(data_json, '\$.request.data.display_name'),
        JSON_VALUE(data_json, '\$.request.data.name'),
        ''
    ) AS details
FROM audit_events_flattened
WHERE methodName LIKE '%Delete%'"

# ============================================================================
# 2. API KEYS TABLE
# ============================================================================
echo ""
echo "=== Creating API Keys Table ==="

run_sql "create-apikeys-v2" "
CREATE TABLE IF NOT EXISTS apikeys_v2 (
    id STRING PRIMARY KEY NOT ENFORCED,
    event_time STRING,
    principal STRING,
    operation STRING,
    api_key_id STRING,
    description STRING,
    owner_id STRING
) WITH (
    'changelog.mode' = 'upsert',
    'value.format' = 'json-registry'
)"

run_sql "populate-apikeys-v2" "INSERT INTO apikeys_v2
SELECT
    id,
    \`time\` AS event_time,
    principal,
    CASE
        WHEN methodName LIKE '%Create%' THEN 'CREATE'
        WHEN methodName LIKE '%Delete%' THEN 'DELETE'
        WHEN methodName LIKE '%Update%' THEN 'UPDATE'
        ELSE 'READ'
    END AS operation,
    COALESCE(
        JSON_VALUE(data_json, '\$.cloudResources[0].resource.resourceId'),
        JSON_VALUE(data_json, '\$.request.data.id'),
        'unknown'
    ) AS api_key_id,
    COALESCE(
        JSON_VALUE(data_json, '\$.request.data.spec.description'),
        ''
    ) AS description,
    COALESCE(
        JSON_VALUE(data_json, '\$.request.data.spec.owner.id'),
        ''
    ) AS owner_id
FROM audit_events_flattened
WHERE methodName LIKE '%APIKey%' OR methodName LIKE '%ApiKey%'"

# ============================================================================
# 3. CREATIONS TABLE
# ============================================================================
echo ""
echo "=== Creating Creations Table ==="

run_sql "create-creations-v2" "
CREATE TABLE IF NOT EXISTS creations_v2 (
    id STRING PRIMARY KEY NOT ENFORCED,
    created_at STRING,
    principal STRING,
    methodName STRING,
    resource_type STRING,
    resource_id STRING,
    details STRING
) WITH (
    'changelog.mode' = 'upsert',
    'value.format' = 'json-registry'
)"

run_sql "populate-creations-v2" "INSERT INTO creations_v2
SELECT
    id,
    \`time\` AS created_at,
    principal,
    methodName,
    resourceType AS resource_type,
    COALESCE(
        JSON_VALUE(data_json, '\$.cloudResources[0].resource.resourceId'),
        JSON_VALUE(data_json, '\$.result.data.id'),
        'unknown'
    ) AS resource_id,
    COALESCE(
        JSON_VALUE(data_json, '\$.request.data.display_name'),
        JSON_VALUE(data_json, '\$.request.data.name'),
        ''
    ) AS details
FROM audit_events_flattened
WHERE methodName LIKE '%Create%'"

# ============================================================================
# 4. SECURITY TABLE (Access Denied, Auth, RBAC)
# ============================================================================
echo ""
echo "=== Creating Security Table ==="

run_sql "create-security-v2" "
CREATE TABLE IF NOT EXISTS security_v2 (
    id STRING PRIMARY KEY NOT ENFORCED,
    event_time STRING,
    principal STRING,
    methodName STRING,
    granted BOOLEAN,
    operation STRING,
    resource_name STRING,
    client_ip STRING
) WITH (
    'changelog.mode' = 'upsert',
    'value.format' = 'json-registry'
)"

run_sql "populate-security-v2" "INSERT INTO security_v2
SELECT
    id,
    \`time\` AS event_time,
    principal,
    methodName,
    granted,
    COALESCE(
        JSON_VALUE(data_json, '\$.authorizationInfo.operation'),
        ''
    ) AS operation,
    COALESCE(
        JSON_VALUE(data_json, '\$.authorizationInfo.resourceName'),
        ''
    ) AS resource_name,
    COALESCE(
        JSON_VALUE(data_json, '\$.requestMetadata.clientAddress[0].ip'),
        ''
    ) AS client_ip
FROM audit_events_flattened
WHERE methodName LIKE '%Authorize%'
   OR methodName LIKE '%RoleBinding%'
   OR methodName = 'SignIn'
   OR granted = FALSE"

echo ""
echo "============================================"
echo "Tableflow Tables Deployed!"
echo "============================================"
echo ""
echo "Now you can query directly:"
echo ""
echo "  # Find all deletions:"
echo "  SELECT * FROM deletions_v2 ORDER BY deleted_at DESC LIMIT 20;"
echo ""
echo "  # Find who deleted API keys:"
echo "  SELECT * FROM apikeys_v2 WHERE operation = 'DELETE';"
echo ""
echo "  # Find deletions by user:"
echo "  SELECT * FROM deletions_v2 WHERE principal LIKE '%jnagarajan%';"
echo ""
echo "  # Find access denied events:"
echo "  SELECT * FROM security_v2 WHERE granted = FALSE;"
echo ""
