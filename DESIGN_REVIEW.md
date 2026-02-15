# Confluent Audit Log Forwarder v2 - Design Review & Architecture

## Documentation Analysis Summary

Based on comprehensive review of Confluent Cloud audit logging documentation, here are the key insights that inform our improved architecture.

---

## Key Findings from Confluent Documentation

### 1. Event Types & Categories

| Service | Event Type Pattern | Events Captured |
|---------|-------------------|-----------------|
| Kafka | `io.confluent.kafka.server/*` | Authentication, Authorization, Request operations |
| Schema Registry | `io.confluent.sg.server/*` | Schema access, modifications |
| ksqlDB | `io.confluent.ksql.server/*` | Query execution, stream operations |
| Flink | `io.confluent.flink.server/*` | SQL statements, compute pool operations |
| Organization | `io.confluent.cloud/*` | User management, infrastructure, networking |
| Access Transparency | `io.confluent.cloud/access-transparency` | Confluent personnel access to customer resources |

### 2. CloudEvents Structure (v1.0)

**Required Root Fields:**
- `id` - UUID, unique per source
- `source` - CRN format URI
- `specversion` - "1.0"
- `type` - Event classification

**Optional Root Fields:**
- `subject` - Affected resource CRN
- `time` - RFC 3339 timestamp
- `datacontenttype` - "application/json"

**Data Payload Structure:**
```json
{
  "serviceName": "CRN of service",
  "methodName": "Operation type (e.g., kafka.Authentication)",
  "resourceName": "Target resource CRN",
  "authenticationInfo": {
    "principal": "User:123456",
    "principalResourceId": "sa-abc123",
    "identity": "CRN format when group mapping enabled",
    "metadata": {
      "identifier": "API key identifier",
      "mechanism": "Auth mechanism (SASL_SSL, etc.)"
    }
  },
  "authorizationInfo": {
    "granted": true/false,
    "operation": "Read/Write/Describe/etc.",
    "resourceType": "Topic/Cluster/Group/etc.",
    "resourceName": "Resource identifier",
    "patternType": "LITERAL/PREFIX",
    "rbacAuthorization": {
      "role": "Role name",
      "scope": {"outerScope": ["scope-values"]},
      "actingPrincipal": "Principal CRN"
    },
    "aclAuthorization": {
      "permissionType": "ALLOW/DENY",
      "host": "Source host",
      "actingPrincipal": "Principal CRN"
    }
  },
  "request": {
    "correlation_id": "Request correlation ID",
    "clientId": "Client identifier"
  },
  "requestMetadata": {
    "request_id": "Unique request ID",
    "connection_id": "Connection identifier",
    "client_address": "Client IP"
  },
  "result": {
    "status": "SUCCESS/FAILURE/UNAUTHENTICATED",
    "message": "Status description",
    "data": "Additional result data"
  },
  "clientAddress": [{"ip": "Client IP address"}]
}
```

### 3. Retention & Access Constraints

| Aspect | Constraint |
|--------|------------|
| Default Retention | 7 days |
| Cluster Location | AWS us-west-2 (public) |
| Cluster Type | Read-only, cannot produce/modify |
| API Keys | Max 2 per audit cluster |
| Encryption | KMS-managed, 3-year rotation |
| Access | API key provides read-only access |

### 4. Retention Strategies (from docs)

1. **Self-managed sink connector** - Deploy on Confluent Platform, requires `consumer.override.bootstrap.servers`
2. **Cluster Linking** - For Dedicated/Enterprise clusters
3. **Replicator** - For Standard clusters
4. **Custom consumer** - Current approach (our forwarder)

**Critical Limitation:** Fully-managed Confluent Cloud sink connectors CANNOT consume from audit log cluster.

---

## Current Implementation Gaps (vs. Documentation Best Practices)

### 1. Schema Handling

| Current | Recommended |
|---------|-------------|
| Partial field extraction | Full CloudEvents compliance |
| Missing `result.status` in flatten | Critical for security analysis |
| No `result.message` extraction | Important for failure diagnosis |
| Missing `authenticationInfo.metadata` | API key and mechanism tracking |

### 2. Event Type Coverage

| Current | Gap |
|---------|-----|
| Generic flattening | No event-type-specific handling |
| Missing Access Transparency events | Compliance requirement |
| No organization-level event parsing | `io.confluent.cloud/*` events under-processed |

### 3. Resource Name Parsing

| Current | Recommended |
|---------|-------------|
| Raw CRN storage | Parse into components: organization, environment, cluster, resource |
| No hierarchical extraction | Extract kafka cluster ID, environment ID separately |

---

## Improved Architecture Design

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              AUDIT FORWARDER v2                                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         INPUT LAYER                                          │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────────────┐ │   │
│  │  │ Kafka Consumer  │  │ Schema Registry │  │ Secrets Manager Client       │ │   │
│  │  │ (Multi-threaded)│  │ Client          │  │ (Vault/AWS SM/GCP SM)        │ │   │
│  │  └────────┬────────┘  └────────┬────────┘  └──────────────┬───────────────┘ │   │
│  │           │                    │                          │                  │   │
│  └───────────┼────────────────────┼──────────────────────────┼──────────────────┘   │
│              │                    │                          │                       │
│              ▼                    ▼                          ▼                       │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                      PROCESSING LAYER                                        │   │
│  │                                                                              │   │
│  │  ┌──────────────────────────────────────────────────────────────────────┐   │   │
│  │  │                    Event Router                                       │   │   │
│  │  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────────┐   │   │   │
│  │  │  │ Kafka      │ │ Schema     │ │ ksqlDB     │ │ Organization     │   │   │   │
│  │  │  │ Events     │ │ Registry   │ │ Events     │ │ Events           │   │   │   │
│  │  │  │ Handler    │ │ Handler    │ │ Handler    │ │ Handler          │   │   │   │
│  │  │  └────────────┘ └────────────┘ └────────────┘ └──────────────────┘   │   │   │
│  │  │  ┌────────────┐ ┌────────────┐ ┌──────────────────────────────────┐   │   │   │
│  │  │  │ Flink      │ │ Access     │ │ Dead Letter Queue Handler        │   │   │   │
│  │  │  │ Events     │ │ Transparen.│ │                                  │   │   │   │
│  │  │  │ Handler    │ │ Handler    │ │                                  │   │   │   │
│  │  │  └────────────┘ └────────────┘ └──────────────────────────────────┘   │   │   │
│  │  └──────────────────────────────────────────────────────────────────────┘   │   │
│  │                                                                              │   │
│  │  ┌──────────────────────────────────────────────────────────────────────┐   │   │
│  │  │                    Transformation Engine                              │   │   │
│  │  │  • Full CloudEvents parsing                                          │   │   │
│  │  │  • CRN decomposition (org/env/cluster/resource)                      │   │   │
│  │  │  • Event-type-specific enrichment                                    │   │   │
│  │  │  • Security classification tagging                                   │   │   │
│  │  └──────────────────────────────────────────────────────────────────────┘   │   │
│  │                                                                              │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         OUTPUT LAYER (Multi-Sink)                            │   │
│  │                                                                              │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │   │
│  │  │ Kafka Producer  │  │ S3 Sink         │  │ GCS Sink        │              │   │
│  │  │ (Destination)   │  │ (Parquet/JSON)  │  │ (Parquet/JSON)  │              │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘              │   │
│  │                                                                              │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │   │
│  │  │ Query Cache     │  │ Dead Letter     │  │ Webhook/Alert   │              │   │
│  │  │ (Redis/SQLite)  │  │ Queue           │  │ Sink            │              │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘              │   │
│  │                                                                              │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         MCP SERVER LAYER                                     │   │
│  │                                                                              │   │
│  │  Tools:                              Resources:                             │   │
│  │  • list_audit_events                 • audit://schema                       │   │
│  │  • search_audit_events               • audit://categories                   │   │
│  │  • get_security_events               • jobs://export/{id}                   │   │
│  │  • export_to_s3                      • metrics://forwarder                  │   │
│  │  • export_to_gcs                                                            │   │
│  │  • analyze_auth_failures                                                    │   │
│  │  • get_access_transparency                                                  │   │
│  │  • stream_events (SSE)                                                      │   │
│  │                                                                              │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### Enhanced Data Model

Based on documentation, the improved flattened schema should include:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        ENHANCED AUDIT EVENT SCHEMA                               │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  CLOUDEVENTS FIELDS (Standard)                                                  │
│  ├── id                    UUID, unique per source                              │
│  ├── specversion           "1.0"                                                │
│  ├── source                Full CRN                                             │
│  ├── subject               Affected resource CRN                                │
│  ├── type                  Event type                                           │
│  ├── time                  RFC3339 timestamp                                    │
│  └── datacontenttype       "application/json"                                   │
│                                                                                  │
│  PARSED CRN COMPONENTS (Enrichment)                                             │
│  ├── source_organization   Extracted from source CRN                            │
│  ├── source_environment    Extracted from source CRN                            │
│  ├── source_cluster_type   kafka/schema-registry/ksqldb/flink                   │
│  ├── source_cluster_id     Extracted cluster ID                                 │
│  ├── subject_resource_type Topic/Group/Connector/etc.                           │
│  └── subject_resource_id   Resource identifier                                  │
│                                                                                  │
│  SERVICE INFO                                                                   │
│  ├── service_name          Service CRN                                          │
│  ├── method_name           Operation (kafka.Authentication, etc.)               │
│  └── resource_name         Target resource CRN                                  │
│                                                                                  │
│  AUTHENTICATION INFO                                                            │
│  ├── principal             User:XXXXX format                                    │
│  ├── principal_resource_id sa-XXXXX format                                      │
│  ├── identity              Full identity CRN (group mapping)                    │
│  ├── auth_mechanism        SASL_SSL, etc.                                       │
│  └── api_key_identifier    API key used for authentication                      │
│                                                                                  │
│  AUTHORIZATION INFO                                                             │
│  ├── granted               Boolean                                              │
│  ├── operation             Read/Write/Describe/Create/Delete/etc.               │
│  ├── resource_type         Topic/Cluster/Group/TransactionalId/etc.             │
│  ├── authz_resource_name   Authorization target                                 │
│  ├── pattern_type          LITERAL/PREFIX                                       │
│  ├── rbac_role             Role name if RBAC                                    │
│  ├── rbac_scope            Scope if RBAC                                        │
│  ├── acl_permission_type   ALLOW/DENY if ACL                                    │
│  └── acl_host              Source host if ACL                                   │
│                                                                                  │
│  REQUEST METADATA                                                               │
│  ├── client_id             Kafka client ID                                      │
│  ├── correlation_id        Request correlation                                  │
│  ├── request_id            Unique request ID                                    │
│  ├── connection_id         Connection identifier                                │
│  └── client_ip             Source IP address                                    │
│                                                                                  │
│  RESULT INFO                                                                    │
│  ├── result_status         SUCCESS/FAILURE/UNAUTHENTICATED                      │
│  ├── result_message        Status description                                   │
│  └── result_data           Additional result payload                            │
│                                                                                  │
│  EVENT CLASSIFICATION (Enrichment)                                              │
│  ├── event_category        Authentication/Authorization/Request/AccessTransp.   │
│  ├── service_category      Kafka/SchemaRegistry/ksqlDB/Flink/Organization       │
│  ├── security_relevant     Boolean - high-value security event                  │
│  ├── is_failure            Boolean - failed operation                           │
│  └── is_access_transparency Boolean - Confluent personnel access                │
│                                                                                  │
│  RAW DATA                                                                       │
│  └── data_json             Original data payload as JSON string                 │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## MCP Server Tool Specifications

### Core Tools

#### 1. `list_audit_events`
```yaml
name: list_audit_events
description: Retrieve audit log events with pagination and filtering
parameters:
  start_time:
    type: string
    format: ISO8601
    description: Start of time window
  end_time:
    type: string
    format: ISO8601
    description: End of time window
  event_type:
    type: string
    enum: [authentication, authorization, request, access-transparency]
    description: Filter by event category
  service:
    type: string
    enum: [kafka, schema-registry, ksqldb, flink, organization]
    description: Filter by service
  principal:
    type: string
    description: Filter by principal (User:ID or service account)
  granted:
    type: boolean
    description: Filter by authorization result
  cluster_id:
    type: string
    description: Filter by Kafka cluster ID
  environment_id:
    type: string
    description: Filter by environment ID
  limit:
    type: integer
    default: 100
    maximum: 1000
  offset:
    type: integer
    default: 0
returns:
  events: Array of flattened audit events
  total_count: Total matching events
  has_more: Boolean indicating more results
```

#### 2. `search_audit_events`
```yaml
name: search_audit_events
description: Full-text search across audit log fields
parameters:
  query:
    type: string
    description: Search query string
  fields:
    type: array
    items: string
    description: Fields to search (default: all text fields)
  time_range:
    type: object
    properties:
      start: ISO8601 timestamp
      end: ISO8601 timestamp
  include_raw:
    type: boolean
    default: false
    description: Include raw JSON in results
returns:
  events: Matching audit events
  highlights: Search term highlights
```

#### 3. `get_security_events`
```yaml
name: get_security_events
description: Retrieve security-relevant events (auth failures, denied access, access transparency)
parameters:
  time_range:
    type: object
    properties:
      start: ISO8601 timestamp
      end: ISO8601 timestamp
  severity:
    type: string
    enum: [all, high, critical]
    description: Filter by security severity
  include_access_transparency:
    type: boolean
    default: true
    description: Include Confluent personnel access events
returns:
  events: Security events
  summary:
    total_failures: Integer
    unique_principals: Integer
    top_failure_reasons: Array
```

#### 4. `export_to_s3`
```yaml
name: export_to_s3
description: Export audit logs to Amazon S3
parameters:
  bucket:
    type: string
    required: true
    description: S3 bucket name
  prefix:
    type: string
    default: "confluent-audit-logs/"
    description: Object key prefix
  start_time:
    type: string
    format: ISO8601
    required: true
  end_time:
    type: string
    format: ISO8601
    required: true
  format:
    type: string
    enum: [parquet, json, csv]
    default: parquet
  compression:
    type: string
    enum: [snappy, gzip, none]
    default: snappy
  partition_by:
    type: string
    enum: [hour, day, event_type, service]
    default: hour
  aws_region:
    type: string
    description: AWS region (if not default)
returns:
  job_id: Export job identifier
  status: pending/running/completed/failed
  manifest_path: Path to manifest file
  file_count: Number of files created
  record_count: Total records exported
```

#### 5. `export_to_gcs`
```yaml
name: export_to_gcs
description: Export audit logs to Google Cloud Storage
parameters:
  bucket:
    type: string
    required: true
    description: GCS bucket name
  prefix:
    type: string
    default: "confluent-audit-logs/"
  start_time:
    type: string
    format: ISO8601
    required: true
  end_time:
    type: string
    format: ISO8601
    required: true
  format:
    type: string
    enum: [parquet, json, csv]
    default: parquet
  compression:
    type: string
    enum: [snappy, gzip, none]
    default: snappy
  partition_by:
    type: string
    enum: [hour, day, event_type, service]
    default: hour
  project_id:
    type: string
    description: GCP project ID (if not default)
returns:
  job_id: Export job identifier
  status: pending/running/completed/failed
  manifest_path: Path to manifest file
```

#### 6. `analyze_auth_failures`
```yaml
name: analyze_auth_failures
description: Analyze authentication and authorization failures
parameters:
  time_range:
    type: object
    required: true
  group_by:
    type: string
    enum: [principal, cluster, client_ip, api_key, hour]
    default: principal
  min_failures:
    type: integer
    default: 1
    description: Minimum failure count to include
returns:
  summary:
    total_failures: Integer
    unique_principals: Integer
    time_range: Object
  by_group:
    - group_value: String
      failure_count: Integer
      failure_types: Array
      first_seen: Timestamp
      last_seen: Timestamp
  anomalies:
    - description: String
      severity: high/medium/low
      affected_principals: Array
```

#### 7. `get_access_transparency`
```yaml
name: get_access_transparency
description: Retrieve Access Transparency events (Confluent personnel access)
parameters:
  time_range:
    type: object
  resource_type:
    type: string
    enum: [KAFKA_CLUSTER, ENVIRONMENT, ORGANIZATION]
  environment_id:
    type: string
returns:
  events: Access transparency events
  summary:
    total_accesses: Integer
    by_resource_type: Object
    by_reason: Object
```

#### 8. `get_forwarder_status`
```yaml
name: get_forwarder_status
description: Get current status and metrics of the audit forwarder
parameters: none
returns:
  status: healthy/degraded/unhealthy
  uptime_seconds: Integer
  metrics:
    processed_total: Integer
    processing_rate: Float
    error_count: Integer
    consumer_lag: Object
  sinks:
    kafka:
      status: String
      last_write: Timestamp
    s3:
      status: String
      last_write: Timestamp
    gcs:
      status: String
      last_write: Timestamp
```

### MCP Resources

```yaml
resources:
  - uri: "audit://schema/v1"
    name: audit_event_schema
    description: JSON Schema for audit log events
    mimeType: application/schema+json

  - uri: "audit://categories"
    name: event_categories
    description: List of all audit event types and categories
    mimeType: application/json

  - uri: "audit://methods"
    name: method_names
    description: List of all method names by service
    mimeType: application/json

  - uri: "jobs://export/{job_id}"
    name: export_job_status
    description: Status and details of an export job
    mimeType: application/json

  - uri: "metrics://forwarder"
    name: forwarder_metrics
    description: Current forwarder metrics in Prometheus format
    mimeType: text/plain
```

---

## Cloud Storage Integration Design

### S3 Storage Layout

```
s3://your-audit-bucket/
└── confluent-audit-logs/
    ├── _schemas/
    │   └── audit_event_v1.json
    ├── _manifests/
    │   └── {export_job_id}/
    │       ├── manifest.json
    │       └── _SUCCESS
    └── data/
        └── year=2025/
            └── month=05/
                └── day=02/
                    └── hour=14/
                        └── service=kafka/
                            └── event_type=authentication/
                                ├── part-00000-{uuid}.parquet
                                ├── part-00001-{uuid}.parquet
                                └── ...
```

### GCS Storage Layout

```
gs://your-audit-bucket/
└── confluent-audit-logs/
    ├── _schemas/
    │   └── audit_event_v1.json
    ├── _manifests/
    │   └── {export_job_id}/
    │       ├── manifest.json
    │       └── _SUCCESS
    └── data/
        └── dt=2025-05-02/
            └── hr=14/
                └── service=kafka/
                    └── event_type=authentication/
                        ├── part-00000-{uuid}.parquet
                        └── ...
```

### Parquet Schema

```
message AuditEvent {
  required binary id (STRING);
  required binary specversion (STRING);
  required binary source (STRING);
  optional binary subject (STRING);
  required binary type (STRING);
  optional int64 time_epoch_ms (TIMESTAMP(MILLIS, true));
  optional binary time_str (STRING);

  // Parsed CRN components
  optional binary source_organization (STRING);
  optional binary source_environment (STRING);
  optional binary source_cluster_type (STRING);
  optional binary source_cluster_id (STRING);

  // Service info
  optional binary service_name (STRING);
  optional binary method_name (STRING);
  optional binary resource_name (STRING);

  // Authentication
  optional binary principal (STRING);
  optional binary principal_resource_id (STRING);
  optional binary identity (STRING);
  optional binary auth_mechanism (STRING);
  optional binary api_key_identifier (STRING);

  // Authorization
  optional boolean granted;
  optional binary operation (STRING);
  optional binary resource_type (STRING);
  optional binary authz_resource_name (STRING);
  optional binary pattern_type (STRING);
  optional binary rbac_role (STRING);
  optional binary rbac_scope (STRING);
  optional binary acl_permission_type (STRING);
  optional binary acl_host (STRING);

  // Request metadata
  optional binary client_id (STRING);
  optional binary correlation_id (STRING);
  optional binary request_id (STRING);
  optional binary connection_id (STRING);
  optional binary client_ip (STRING);

  // Result
  optional binary result_status (STRING);
  optional binary result_message (STRING);
  optional binary result_data (STRING);

  // Classification
  optional binary event_category (STRING);
  optional binary service_category (STRING);
  optional boolean security_relevant;
  optional boolean is_failure;
  optional boolean is_access_transparency;

  // Raw
  optional binary data_json (STRING);
}
```

---

## Security Improvements

### 1. Secrets Management Integration

```yaml
secrets_backends:
  - type: hashicorp_vault
    config:
      address: ${VAULT_ADDR}
      auth_method: kubernetes  # or token, aws, gcp
      secrets_path: secret/data/audit-forwarder

  - type: aws_secrets_manager
    config:
      region: us-west-2
      secret_name: audit-forwarder/credentials

  - type: gcp_secret_manager
    config:
      project_id: ${GCP_PROJECT}
      secret_name: audit-forwarder-credentials
```

### 2. Credential Rotation

```
┌─────────────────────────────────────────────────────────────────┐
│                   CREDENTIAL ROTATION FLOW                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Secrets Mgr │───▶│ Forwarder   │───▶│ Health      │         │
│  │ Rotation    │    │ Hot Reload  │    │ Verification│         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│        │                   │                  │                  │
│        │                   │                  │                  │
│        ▼                   ▼                  ▼                  │
│  1. Generate new    2. Graceful        3. Validate new          │
│     credentials        reconnect          connection             │
│                                                                  │
│  4. If failed: Automatic rollback to previous credentials       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Network Security

```yaml
# Recommended network configuration
network:
  # Use private endpoints where available
  kafka_private_link: true
  schema_registry_private: true

  # TLS configuration
  tls:
    verify_hostname: true
    min_version: TLSv1.2

  # Egress restrictions
  allowed_destinations:
    - *.confluent.cloud:9092
    - *.confluent.cloud:443
    - s3.*.amazonaws.com:443
    - storage.googleapis.com:443
```

---

## Resilience Patterns

### 1. Dead Letter Queue

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Source Event │────▶│ Processing   │────▶│ Success Sink │
└──────────────┘     └──────┬───────┘     └──────────────┘
                           │
                           │ On Failure
                           ▼
                    ┌──────────────┐
                    │ DLQ Topic    │
                    │ (With retry  │
                    │  metadata)   │
                    └──────────────┘
```

DLQ Event Structure:
```json
{
  "original_event": { ... },
  "error": {
    "type": "SerializationError",
    "message": "Schema validation failed",
    "timestamp": "2025-05-02T14:30:00Z"
  },
  "retry_count": 0,
  "first_failure": "2025-05-02T14:30:00Z",
  "source_partition": 5,
  "source_offset": 12345678
}
```

### 2. Circuit Breaker

```
States:
┌─────────┐    Threshold    ┌─────────┐    Timeout    ┌───────────┐
│ CLOSED  │────exceeded────▶│  OPEN   │─────────────▶│ HALF-OPEN │
└─────────┘                 └─────────┘               └───────────┘
     ▲                                                      │
     │                                                      │
     └──────────────── Success ────────────────────────────┘

Configuration:
  failure_threshold: 5
  recovery_timeout: 30s
  half_open_requests: 3
```

### 3. Backpressure Handling

```python
# Adaptive batch sizing based on downstream latency
class AdaptiveBatcher:
    min_batch_size = 100
    max_batch_size = 1000
    target_latency_ms = 100

    def adjust_batch_size(self, current_latency_ms):
        if current_latency_ms > target_latency_ms * 1.5:
            self.batch_size = max(min_batch_size, batch_size // 2)
        elif current_latency_ms < target_latency_ms * 0.5:
            self.batch_size = min(max_batch_size, batch_size * 2)
```

---

## Performance Optimizations

### 1. Parallel Processing

```
┌─────────────────────────────────────────────────────────────────┐
│                    PARTITION-LEVEL PARALLELISM                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Consumer Group: audit-forwarder-v2                             │
│                                                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │ Worker Thread │  │ Worker Thread │  │ Worker Thread │       │
│  │ Partitions    │  │ Partitions    │  │ Partitions    │       │
│  │ 0, 3, 6, 9    │  │ 1, 4, 7, 10   │  │ 2, 5, 8, 11   │       │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘       │
│          │                  │                  │                 │
│          └──────────────────┼──────────────────┘                 │
│                             │                                    │
│                    ┌────────▼────────┐                          │
│                    │ Shared Producer │                          │
│                    │ (Thread-safe)   │                          │
│                    └─────────────────┘                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2. JSON Processing

```python
# Use orjson for 3-10x faster JSON parsing
import orjson

# Benchmark comparison (1M events):
# stdlib json: ~45 seconds
# orjson:      ~5 seconds
```

### 3. Schema Caching

```python
class SchemaCache:
    """Cache serializers to avoid repeated Schema Registry calls"""

    def __init__(self, ttl_seconds=3600):
        self.cache = {}
        self.ttl = ttl_seconds

    def get_serializer(self, subject):
        if subject in self.cache:
            entry = self.cache[subject]
            if time.time() - entry['timestamp'] < self.ttl:
                return entry['serializer']

        # Fetch fresh serializer
        serializer = self._create_serializer(subject)
        self.cache[subject] = {
            'serializer': serializer,
            'timestamp': time.time()
        }
        return serializer
```

---

## Monitoring & Alerting

### Enhanced Metrics

```prometheus
# Core processing metrics
audit_forwarder_events_processed_total{service, event_type, status}
audit_forwarder_events_failed_total{service, event_type, error_type}
audit_forwarder_processing_latency_seconds{quantile}
audit_forwarder_batch_size{quantile}

# Consumer metrics
audit_forwarder_consumer_lag{partition}
audit_forwarder_consumer_fetch_rate
audit_forwarder_consumer_records_per_fetch{quantile}

# Producer metrics
audit_forwarder_producer_queue_size
audit_forwarder_producer_batch_size{quantile}
audit_forwarder_producer_request_latency_seconds{quantile}

# Sink metrics
audit_forwarder_sink_writes_total{sink_type, status}
audit_forwarder_sink_bytes_written_total{sink_type}
audit_forwarder_sink_latency_seconds{sink_type, quantile}

# Circuit breaker metrics
audit_forwarder_circuit_breaker_state{sink_type}
audit_forwarder_circuit_breaker_failures_total{sink_type}

# Security events (high cardinality, use carefully)
audit_forwarder_security_events_total{event_type, service, result_status}
audit_forwarder_access_transparency_events_total{resource_type}
```

### Alerting Rules

```yaml
groups:
  - name: audit_forwarder_alerts
    rules:
      # High consumer lag
      - alert: AuditForwarderHighLag
        expr: sum(audit_forwarder_consumer_lag) > 100000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Audit forwarder falling behind"

      # Processing failures
      - alert: AuditForwarderHighErrorRate
        expr: rate(audit_forwarder_events_failed_total[5m]) > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High error rate in audit forwarder"

      # Circuit breaker open
      - alert: AuditForwarderCircuitOpen
        expr: audit_forwarder_circuit_breaker_state == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Circuit breaker open for {{ $labels.sink_type }}"

      # Security: unusual auth failures
      - alert: UnusualAuthFailures
        expr: sum(rate(audit_forwarder_security_events_total{result_status="UNAUTHENTICATED"}[15m])) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Unusual number of authentication failures detected"

      # Access transparency event
      - alert: ConfluentAccessTransparency
        expr: increase(audit_forwarder_access_transparency_events_total[1h]) > 0
        for: 0m
        labels:
          severity: info
        annotations:
          summary: "Confluent personnel accessed customer resources"
```

---

## Implementation Checklist

### Phase 1: Core Improvements
- [ ] Implement secrets management integration
- [ ] Add Dead Letter Queue
- [ ] Enhance event transformation (full CloudEvents + CRN parsing)
- [ ] Add circuit breaker pattern
- [ ] Implement atomic offset management

### Phase 2: Multi-Sink Architecture
- [ ] Refactor to multi-sink architecture
- [ ] Implement S3 sink with Parquet support
- [ ] Implement GCS sink with Parquet support
- [ ] Add query cache layer

### Phase 3: MCP Server
- [ ] Implement MCP server framework
- [ ] Add list_audit_events tool
- [ ] Add search_audit_events tool
- [ ] Add export tools (S3/GCS)
- [ ] Add security analysis tools
- [ ] Implement SSE streaming

### Phase 4: Production Hardening
- [ ] Multi-instance deployment support
- [ ] Kubernetes manifests
- [ ] Enhanced monitoring dashboards
- [ ] Alerting rules
- [ ] Runbook documentation

---

## File Structure for New Implementation

```
audit-forwarder-v2/
├── src/
│   ├── __init__.py
│   ├── main.py                    # Entry point
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py            # Configuration management
│   │   └── secrets.py             # Secrets backend integration
│   ├── consumer/
│   │   ├── __init__.py
│   │   ├── kafka_consumer.py      # Kafka consumer with threading
│   │   └── offset_manager.py      # Atomic offset management
│   ├── transformer/
│   │   ├── __init__.py
│   │   ├── event_router.py        # Route events by type
│   │   ├── cloudevents.py         # CloudEvents parsing
│   │   ├── crn_parser.py          # CRN decomposition
│   │   └── handlers/
│   │       ├── kafka_handler.py
│   │       ├── schema_registry_handler.py
│   │       ├── ksqldb_handler.py
│   │       ├── flink_handler.py
│   │       └── organization_handler.py
│   ├── sinks/
│   │   ├── __init__.py
│   │   ├── base_sink.py           # Abstract sink interface
│   │   ├── kafka_sink.py          # Kafka producer sink
│   │   ├── s3_sink.py             # S3 with Parquet
│   │   ├── gcs_sink.py            # GCS with Parquet
│   │   ├── dlq_sink.py            # Dead letter queue
│   │   └── cache_sink.py          # Query cache (Redis/SQLite)
│   ├── resilience/
│   │   ├── __init__.py
│   │   ├── circuit_breaker.py
│   │   ├── retry.py
│   │   └── backpressure.py
│   ├── metrics/
│   │   ├── __init__.py
│   │   ├── prometheus.py          # Prometheus metrics
│   │   └── health.py              # Health check endpoints
│   └── mcp/
│       ├── __init__.py
│       ├── server.py              # MCP server implementation
│       ├── tools/
│       │   ├── list_events.py
│       │   ├── search_events.py
│       │   ├── export_s3.py
│       │   ├── export_gcs.py
│       │   ├── security_analysis.py
│       │   └── forwarder_status.py
│       └── resources/
│           ├── schema.py
│           └── categories.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── deploy/
│   ├── docker/
│   │   ├── Dockerfile
│   │   └── docker-compose.yml
│   └── kubernetes/
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── configmap.yaml
│       └── secrets.yaml
├── grafana/
│   ├── dashboards/
│   └── provisioning/
├── prometheus/
│   ├── prometheus.yml
│   └── alerts/
├── docs/
│   ├── architecture.md
│   ├── mcp-tools.md
│   └── runbook.md
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Next Steps

1. **Review this design document** - Confirm architecture decisions
2. **Begin Phase 1 implementation** - Core improvements
3. **Set up development environment** - Docker, testing frameworks
4. **Implement incrementally** - One component at a time with tests
