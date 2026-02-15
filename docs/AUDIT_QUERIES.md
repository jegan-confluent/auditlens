# Confluent Cloud Audit Log Query Guide

Quick reference for answering common audit/compliance questions.

## Event Types Reference

| Event Type | What It Captures |
|------------|------------------|
| `io.confluent.kafka.server/authentication` | Login attempts (success/failure) |
| `io.confluent.kafka.server/authorization` | Permission checks (ACL evaluations) |
| `io.confluent.cloud/request` | API operations (create, delete, update) |
| `io.confluent.cloud/access-transparency` | Confluent personnel access |

## Common Queries

### 1. Who Created a Topic?

**Question:** "Who created topic 'orders' and when?"

```sql
-- Athena / Presto / Trino
SELECT
    time AS created_at,
    data.authenticationInfo.principal AS created_by,
    REGEXP_EXTRACT(source, 'kafka=([^/]+)', 1) AS cluster_id,
    data.request.topicName AS topic_name,
    data.requestMetadata.clientAddress AS from_ip
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND data.methodName = 'kafka.CreateTopics'
  AND data.request.topicName = 'orders'
ORDER BY time DESC
LIMIT 1;
```

### 2. Who Deleted a Topic?

**Question:** "Who deleted topic 'temp-data'?"

```sql
SELECT
    time AS deleted_at,
    data.authenticationInfo.principal AS deleted_by,
    data.request.topicName AS topic_name,
    data.result.status AS status,
    data.requestMetadata.clientAddress AS from_ip
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND data.methodName = 'kafka.DeleteTopics'
  AND data.request.topicName = 'temp-data';
```

### 3. Who Deleted a Cluster?

**Question:** "Who deleted cluster lkc-abc123?"

```sql
SELECT
    time AS deleted_at,
    data.authenticationInfo.principal AS deleted_by,
    REGEXP_EXTRACT(source, 'kafka=([^/]+)', 1) AS cluster_id,
    data.result.status AS status
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND data.methodName = 'DeleteKafkaCluster'
  AND source LIKE '%kafka=lkc-abc123%';
```

### 4. Who Created/Deleted Connectors?

**Question:** "Show all connector deletions in the last 7 days"

```sql
SELECT
    time,
    data.authenticationInfo.principal AS who,
    data.methodName AS action,
    data.request.connectorName AS connector_name,
    REGEXP_EXTRACT(source, 'connect=([^/]+)', 1) AS connect_cluster,
    data.result.status
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND data.methodName IN ('DeleteConnector', 'CreateConnector', 'UpdateConnector')
  AND time > CURRENT_TIMESTAMP - INTERVAL '7' DAY
ORDER BY time DESC;
```

### 5. When Was an API Key Created?

**Question:** "Show all API keys created for cluster lkc-xyz"

```sql
SELECT
    time AS created_at,
    data.authenticationInfo.principal AS created_by,
    data.request.spec.resource.id AS resource_id,
    data.request.spec.owner.id AS owner_id,
    data.response.id AS api_key_id
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND data.methodName = 'CreateApiKey'
  AND data.request.spec.resource.id = 'lkc-xyz'
ORDER BY time DESC;
```

### 6. API Key Deletions

**Question:** "Who deleted API key ABCD1234?"

```sql
SELECT
    time AS deleted_at,
    data.authenticationInfo.principal AS deleted_by,
    data.request.id AS api_key_id,
    data.requestMetadata.clientAddress AS from_ip
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND data.methodName = 'DeleteApiKey'
  AND data.request.id = 'ABCD1234';
```

### 7. Failed Authentication Attempts

**Question:** "Show all failed logins in the last 24 hours"

```sql
SELECT
    time,
    data.authenticationInfo.principal AS who_tried,
    REGEXP_EXTRACT(source, 'kafka=([^/]+)', 1) AS cluster_id,
    data.requestMetadata.clientAddress AS from_ip,
    data.result.message AS failure_reason
FROM audit_logs
WHERE type = 'io.confluent.kafka.server/authentication'
  AND data.result.status = 'UNAUTHENTICATED'
  AND time > CURRENT_TIMESTAMP - INTERVAL '24' HOUR
ORDER BY time DESC;
```

### 8. Authorization Denials (ACL Failures)

**Question:** "Who got permission denied and for what?"

```sql
SELECT
    time,
    data.authenticationInfo.principal AS who,
    data.authorizationInfo.resourceType AS resource_type,
    data.authorizationInfo.resourceName AS resource_name,
    data.authorizationInfo.operation AS operation,
    REGEXP_EXTRACT(source, 'kafka=([^/]+)', 1) AS cluster_id,
    data.requestMetadata.clientAddress AS from_ip
FROM audit_logs
WHERE type = 'io.confluent.kafka.server/authorization'
  AND data.result.status = 'PERMISSION_DENIED'
  AND time > CURRENT_TIMESTAMP - INTERVAL '7' DAY
ORDER BY time DESC;
```

### 9. Track Activity by IP Address

**Question:** "What did IP 10.0.1.100 do?"

```sql
SELECT
    time,
    type AS event_type,
    data.authenticationInfo.principal AS who,
    data.methodName AS action,
    data.result.status AS result
FROM audit_logs
WHERE data.requestMetadata.clientAddress = '10.0.1.100'
ORDER BY time DESC
LIMIT 100;
```

### 10. ACL Changes

**Question:** "Who modified ACLs on cluster?"

```sql
SELECT
    time,
    data.authenticationInfo.principal AS who,
    data.methodName AS action,
    data.request AS acl_details,
    REGEXP_EXTRACT(source, 'kafka=([^/]+)', 1) AS cluster_id
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND data.methodName IN ('CreateAcls', 'DeleteAcls')
ORDER BY time DESC;
```

### 11. Schema Registry Changes

**Question:** "Who registered/deleted schemas?"

```sql
SELECT
    time,
    data.authenticationInfo.principal AS who,
    data.methodName AS action,
    data.request.subject AS subject,
    REGEXP_EXTRACT(source, 'schema-registry=([^/]+)', 1) AS sr_cluster
FROM audit_logs
WHERE type LIKE '%schemaregistry%'
  AND data.methodName IN ('RegisterSchema', 'DeleteSubject', 'DeleteSchemaVersion')
ORDER BY time DESC;
```

### 12. Confluent Personnel Access (Access Transparency)

**Question:** "Did Confluent support access my environment?"

```sql
SELECT
    time,
    data.authenticationInfo.principal AS confluent_user,
    data.accessTransparency.reason AS reason,
    data.accessTransparency.caseNumber AS support_case,
    REGEXP_EXTRACT(source, 'organization=([^/]+)', 1) AS org_id
FROM audit_logs
WHERE type = 'io.confluent.cloud/access-transparency'
ORDER BY time DESC;
```

### 13. All DELETE Operations

**Question:** "Show all destructive operations in the last 30 days"

```sql
SELECT
    time,
    data.authenticationInfo.principal AS who,
    data.methodName AS action,
    source AS resource,
    data.result.status
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND (
    data.methodName LIKE 'Delete%'
    OR data.methodName LIKE '%Delete'
  )
  AND time > CURRENT_TIMESTAMP - INTERVAL '30' DAY
ORDER BY time DESC;
```

### 14. Environment/Org Level Changes

**Question:** "Who made organization-level changes?"

```sql
SELECT
    time,
    data.authenticationInfo.principal AS who,
    data.methodName AS action,
    data.result.status
FROM audit_logs
WHERE type = 'io.confluent.cloud/request'
  AND data.methodName IN (
    'CreateEnvironment',
    'DeleteEnvironment',
    'UpdateEnvironment',
    'CreateServiceAccount',
    'DeleteServiceAccount',
    'CreateRoleBinding',
    'DeleteRoleBinding'
  )
ORDER BY time DESC;
```

### 15. Activity by User

**Question:** "What did user john@company.com do?"

```sql
SELECT
    time,
    type AS event_type,
    data.methodName AS action,
    source AS resource,
    data.result.status
FROM audit_logs
WHERE data.authenticationInfo.principal = 'User:john@company.com'
ORDER BY time DESC
LIMIT 100;
```

---

## Method Names Reference

### Kafka Operations
| Method | Description |
|--------|-------------|
| `kafka.CreateTopics` | Topic creation |
| `kafka.DeleteTopics` | Topic deletion |
| `kafka.AlterConfigs` | Config changes |
| `kafka.CreateAcls` | ACL creation |
| `kafka.DeleteAcls` | ACL deletion |
| `kafka.Produce` | Message production |
| `kafka.Fetch` | Message consumption |

### Cluster Operations
| Method | Description |
|--------|-------------|
| `CreateKafkaCluster` | Cluster creation |
| `DeleteKafkaCluster` | Cluster deletion |
| `UpdateKafkaCluster` | Cluster modification |

### API Key Operations
| Method | Description |
|--------|-------------|
| `CreateApiKey` | API key creation |
| `DeleteApiKey` | API key deletion |

### Service Account Operations
| Method | Description |
|--------|-------------|
| `CreateServiceAccount` | SA creation |
| `DeleteServiceAccount` | SA deletion |

### Connector Operations
| Method | Description |
|--------|-------------|
| `CreateConnector` | Connector creation |
| `DeleteConnector` | Connector deletion |
| `UpdateConnector` | Connector modification |
| `PauseConnector` | Connector paused |
| `ResumeConnector` | Connector resumed |

### RBAC Operations
| Method | Description |
|--------|-------------|
| `CreateRoleBinding` | Role assignment |
| `DeleteRoleBinding` | Role removal |

---

## Result Status Values

| Status | Meaning |
|--------|---------|
| `SUCCESS` | Operation completed |
| `UNAUTHENTICATED` | Auth failed |
| `PERMISSION_DENIED` | ACL denied |
| `NOT_FOUND` | Resource doesn't exist |
| `ALREADY_EXISTS` | Duplicate resource |
| `INVALID_ARGUMENT` | Bad request |
