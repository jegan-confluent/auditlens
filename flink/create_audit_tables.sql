-- ============================================================================
-- Confluent Cloud Audit Log - Tableflow Architecture
-- ============================================================================
-- Purpose: Pre-materialized tables for instant customer queries
-- Instead of scanning 1.5M+ events, query pre-filtered tables directly
-- ============================================================================

-- ============================================================================
-- 1. BASE TABLE: Source topic with proper schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_events_source (
    event_id STRING,
    time TIMESTAMP(3),
    methodName STRING,
    principal STRING,
    granted BOOLEAN,
    resourceType STRING,
    data_json STRING,

    -- Watermark for event time processing
    WATERMARK FOR time AS time - INTERVAL '5' SECOND,

    -- Primary key for deduplication
    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'connector' = 'confluent',
    'kafka.topic' = 'audit_events_flattened',
    'scan.startup.mode' = 'earliest-offset',
    'value.format' = 'json-registry'
);

-- ============================================================================
-- 2. DELETIONS TABLE: All delete operations (most critical for customers)
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_deletions (
    event_id STRING,
    deleted_at TIMESTAMP(3),
    principal STRING,
    methodName STRING,
    resource_type STRING,
    resource_id STRING,
    details STRING,

    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'connector' = 'confluent',
    'kafka.topic' = 'audit_deletions',
    'value.format' = 'json-registry',
    'kafka.cleanup-policy' = 'compact'
);

-- Populate deletions table
INSERT INTO audit_deletions
SELECT
    event_id,
    time AS deleted_at,
    principal,
    methodName,
    resourceType AS resource_type,
    -- Extract resource ID from data_json
    COALESCE(
        JSON_VALUE(data_json, '$.cloudResources[0].resource.resourceId'),
        JSON_VALUE(data_json, '$.request.data.id'),
        'unknown'
    ) AS resource_id,
    -- Extract meaningful details
    COALESCE(
        JSON_VALUE(data_json, '$.request.data.display_name'),
        JSON_VALUE(data_json, '$.request.data.name'),
        JSON_VALUE(data_json, '$.request.data.description'),
        ''
    ) AS details
FROM audit_events_source
WHERE methodName LIKE '%Delete%';

-- ============================================================================
-- 3. CREATIONS TABLE: All create operations
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_creations (
    event_id STRING,
    created_at TIMESTAMP(3),
    principal STRING,
    methodName STRING,
    resource_type STRING,
    resource_id STRING,
    details STRING,

    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'connector' = 'confluent',
    'kafka.topic' = 'audit_creations',
    'value.format' = 'json-registry',
    'kafka.cleanup-policy' = 'compact'
);

INSERT INTO audit_creations
SELECT
    event_id,
    time AS created_at,
    principal,
    methodName,
    resourceType AS resource_type,
    COALESCE(
        JSON_VALUE(data_json, '$.cloudResources[0].resource.resourceId'),
        JSON_VALUE(data_json, '$.result.data.id'),
        JSON_VALUE(data_json, '$.request.data.id'),
        'unknown'
    ) AS resource_id,
    COALESCE(
        JSON_VALUE(data_json, '$.request.data.display_name'),
        JSON_VALUE(data_json, '$.request.data.name'),
        ''
    ) AS details
FROM audit_events_source
WHERE methodName LIKE '%Create%';

-- ============================================================================
-- 4. API KEYS TABLE: All API key operations (high security value)
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_api_keys (
    event_id STRING,
    event_time TIMESTAMP(3),
    principal STRING,
    operation STRING,  -- Create, Delete, Get
    api_key_id STRING,
    description STRING,
    owner_id STRING,

    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'connector' = 'confluent',
    'kafka.topic' = 'audit_api_keys',
    'value.format' = 'json-registry',
    'kafka.cleanup-policy' = 'compact'
);

INSERT INTO audit_api_keys
SELECT
    event_id,
    time AS event_time,
    principal,
    CASE
        WHEN methodName LIKE '%Create%' THEN 'CREATE'
        WHEN methodName LIKE '%Delete%' THEN 'DELETE'
        WHEN methodName LIKE '%Update%' THEN 'UPDATE'
        ELSE 'READ'
    END AS operation,
    COALESCE(
        JSON_VALUE(data_json, '$.cloudResources[0].resource.resourceId'),
        JSON_VALUE(data_json, '$.request.data.id'),
        'unknown'
    ) AS api_key_id,
    COALESCE(
        JSON_VALUE(data_json, '$.request.data.spec.description'),
        ''
    ) AS description,
    COALESCE(
        JSON_VALUE(data_json, '$.request.data.spec.owner.id'),
        ''
    ) AS owner_id
FROM audit_events_source
WHERE methodName LIKE '%APIKey%' OR methodName LIKE '%ApiKey%';

-- ============================================================================
-- 5. SECURITY EVENTS TABLE: Auth, RBAC, Access Denied
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_security (
    event_id STRING,
    event_time TIMESTAMP(3),
    principal STRING,
    methodName STRING,
    granted BOOLEAN,
    operation STRING,
    resource_name STRING,
    client_ip STRING,

    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'connector' = 'confluent',
    'kafka.topic' = 'audit_security',
    'value.format' = 'json-registry',
    'kafka.cleanup-policy' = 'compact'
);

INSERT INTO audit_security
SELECT
    event_id,
    time AS event_time,
    principal,
    methodName,
    granted,
    COALESCE(
        JSON_VALUE(data_json, '$.authorizationInfo.operation'),
        JSON_VALUE(data_json, '$.authorizationInfo[0].operation'),
        ''
    ) AS operation,
    COALESCE(
        JSON_VALUE(data_json, '$.authorizationInfo.resourceName'),
        JSON_VALUE(data_json, '$.authorizationInfo[0].resourceName'),
        ''
    ) AS resource_name,
    COALESCE(
        JSON_VALUE(data_json, '$.requestMetadata.clientAddress[0].ip'),
        JSON_VALUE(data_json, '$.clientAddress[0].ip'),
        ''
    ) AS client_ip
FROM audit_events_source
WHERE methodName LIKE '%Authorize%'
   OR methodName LIKE '%RoleBinding%'
   OR methodName = 'SignIn'
   OR granted = FALSE;

-- ============================================================================
-- 6. CLUSTER OPERATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_clusters (
    event_id STRING,
    event_time TIMESTAMP(3),
    principal STRING,
    operation STRING,
    cluster_id STRING,
    cluster_type STRING,  -- Kafka, ksqlDB, SchemaRegistry, Flink
    environment_id STRING,

    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'connector' = 'confluent',
    'kafka.topic' = 'audit_clusters',
    'value.format' = 'json-registry',
    'kafka.cleanup-policy' = 'compact'
);

INSERT INTO audit_clusters
SELECT
    event_id,
    time AS event_time,
    principal,
    CASE
        WHEN methodName LIKE '%Create%' THEN 'CREATE'
        WHEN methodName LIKE '%Delete%' THEN 'DELETE'
        WHEN methodName LIKE '%Update%' THEN 'UPDATE'
        ELSE 'READ'
    END AS operation,
    COALESCE(
        JSON_VALUE(data_json, '$.cloudResources[0].resource.resourceId'),
        ''
    ) AS cluster_id,
    CASE
        WHEN methodName LIKE '%Kafka%' THEN 'Kafka'
        WHEN methodName LIKE '%KSQL%' OR methodName LIKE '%ksql%' THEN 'ksqlDB'
        WHEN methodName LIKE '%Schema%' THEN 'SchemaRegistry'
        WHEN methodName LIKE '%Flink%' OR methodName LIKE '%ComputePool%' THEN 'Flink'
        ELSE 'Other'
    END AS cluster_type,
    COALESCE(
        JSON_VALUE(data_json, '$.cloudResources[1].resource.resourceId'),
        ''
    ) AS environment_id
FROM audit_events_source
WHERE methodName LIKE '%Cluster%'
   OR methodName LIKE '%ComputePool%'
   OR methodName LIKE '%KSQL%';

-- ============================================================================
-- 7. TOPIC OPERATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_topics (
    event_id STRING,
    event_time TIMESTAMP(3),
    principal STRING,
    operation STRING,
    topic_name STRING,
    cluster_id STRING,
    partitions INT,

    PRIMARY KEY (event_id) NOT ENFORCED
) WITH (
    'connector' = 'confluent',
    'kafka.topic' = 'audit_topics',
    'value.format' = 'json-registry',
    'kafka.cleanup-policy' = 'compact'
);

INSERT INTO audit_topics
SELECT
    event_id,
    time AS event_time,
    principal,
    CASE
        WHEN methodName LIKE '%Create%' THEN 'CREATE'
        WHEN methodName LIKE '%Delete%' THEN 'DELETE'
        WHEN methodName LIKE '%Alter%' THEN 'ALTER'
        ELSE 'READ'
    END AS operation,
    COALESCE(
        JSON_VALUE(data_json, '$.cloudResources[0].resource.resourceId'),
        JSON_VALUE(data_json, '$.request.data.name'),
        JSON_VALUE(data_json, '$.request.data.topic'),
        ''
    ) AS topic_name,
    COALESCE(
        JSON_VALUE(data_json, '$.cloudResources[1].resource.resourceId'),
        ''
    ) AS cluster_id,
    COALESCE(
        CAST(JSON_VALUE(data_json, '$.request.data.numPartitions') AS INT),
        0
    ) AS partitions
FROM audit_events_source
WHERE methodName LIKE '%Topic%';

-- ============================================================================
-- EXAMPLE QUERIES (for customers)
-- ============================================================================

-- Find all deletions by a specific user:
-- SELECT * FROM audit_deletions WHERE principal LIKE '%jnagarajan%' ORDER BY deleted_at DESC;

-- Find all API key operations in last 24 hours:
-- SELECT * FROM audit_api_keys WHERE event_time > NOW() - INTERVAL '24' HOUR ORDER BY event_time DESC;

-- Find all access denied events:
-- SELECT * FROM audit_security WHERE granted = FALSE ORDER BY event_time DESC;

-- Find who deleted what API keys:
-- SELECT * FROM audit_api_keys WHERE operation = 'DELETE' ORDER BY event_time DESC;

-- Find all cluster deletions:
-- SELECT * FROM audit_clusters WHERE operation = 'DELETE' ORDER BY event_time DESC;
