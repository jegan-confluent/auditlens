# Audit Event Schema

## 1. Design Principles

AuditLens should use a dual event model:

- Raw evidence is immutable and replay-safe.
- Normalized/enriched records are query-optimized product views derived from raw evidence.

Raw model:

- Store the original CloudEvent without mutation.
- Add ingestion metadata: source topic, partition, offset, ingest timestamp, forwarder version.
- Use raw records as the rebuild source when local persistence is lost.

Normalized model:

- Flatten common identity, actor, action, resource, outcome, and request fields.
- Preserve source context such as CloudEvent `id`, `source`, `subject`, `type`, and `time`.
- Use stable field names across dashboard, API, persistence, and alerts.
- Avoid deriving decisions in the normalized schema; decisions/signals belong in separate records.

Enriched model:

- Add classification, risk, signal candidate, principal normalization, and high-risk flags.
- Preserve enough source evidence to trace back to raw records.

Control-plane contract:

- API + persistence is the product query contract.
- Kafka topics are evidence and pipeline contracts.
- Dashboard/product UI should consume API results in product mode, not Kafka topics directly.

## 2. Schema Governance

Versioning rules:

- Topic names carry major schema version: `audit.enriched.v1`, `audit.alerts.v1`.
- `schema_version` inside each record must match the topic contract.
- `event_contract_version` tracks product-level compatibility within the topic version.
- Raw records keep source CloudEvents immutable; only wrapper metadata may evolve.

Backward-compatible changes:

- Add nullable fields.
- Add enum values only when consumers are required to treat unknown values as `unknown` or display-safe strings.
- Add nested objects when absent objects are handled as `{}`.
- Add optional arrays when absent arrays are handled as `[]`.

Breaking changes:

- Renaming fields.
- Removing fields.
- Changing scalar type.
- Changing field meaning without changing name.
- Moving fields between top-level and nested objects without compatibility aliases.
- Changing identity normalization semantics.

Breaking change strategy:

- Create a new topic/schema version, for example `audit.enriched.v2`.
- Dual-write v1 and v2 during migration.
- Keep read adapters for v1 until downstream consumers are migrated.
- Do not mutate raw evidence to fit new schemas.

Schema Registry enforcement plan:

- Local development may run without Schema Registry.
- Product/customer mode should require schemas for raw wrapper, normalized, enriched, denial signals, high-risk signals, alerts, and DLQ.
- CI should validate sample payloads against JSON Schema before release.
- Runtime should count schema validation failures and send invalid derived records to DLQ.

## 3. Core Event Model

### A. Identity

| Field | Type | Source / derivation | Required | Notes |
|---|---|---|---|---|
| `schema_version` | string | Pipeline | Yes | Example: `audit.enriched.v1`. |
| `event_contract_version` | string | Pipeline | Yes | Current code uses `v1`. |
| `pipeline_stage` | string | Pipeline | Yes | `raw`, `normalized`, or `enriched`. |
| `event_id` | string | CloudEvent `id` | Yes | Current code stores this as `id`; canonical model should expose `event_id` and may retain `id` for compatibility. |
| `event_time` | string RFC3339 | CloudEvent `time` | Yes | Current code stores this as `time`. |
| `ingested_at` | string RFC3339 | Forwarder ingest time | Yes | Raw wrapper and persistence use ingest timestamps. |
| `visible_at` | string RFC3339 | Product/API visibility time | No | Useful for measuring UI/API delay; not consistently implemented today. |
| `cloud_event_type` | string | CloudEvent `type` | Yes | Current code stores `type`. |
| `cloud_event_source` | string | CloudEvent `source` | Yes | Current code stores `source`. |
| `cloud_event_subject` | string | CloudEvent `subject` | No | Current code stores `subject`. |
| `organization_id` | string | CRN extraction | No | Extracted from `source`, `resourceName`, or `subject`. |
| `environment_id` | string | CRN extraction | No | Extracted from CRN fields. |
| `cluster_id` | string | CRN extraction | No | Supports Kafka, Schema Registry, ksqlDB, Flink CRN tokens. |
| `source_topic` | string | Kafka metadata | Yes for persisted events | Source evidence pointer. |
| `source_partition` | integer | Kafka metadata | Yes for persisted events | Source evidence pointer. |
| `source_offset` | integer | Kafka metadata | Yes for persisted events | Source evidence pointer. |

### B. Actor

| Field | Type | Source / derivation | Required | Notes |
|---|---|---|---|---|
| `actor_type` | enum | Derived | No | `user`, `service_account`, `api_key`, `system`, `unknown`. Current code uses `principal_type` with `user`, `service_account`, `unknown`. |
| `actor_principal_raw` | string | `data.authenticationInfo.principal` | No | Current code uses `principal_raw` and `principal`. |
| `actor_principal` | string | Normalized principal | No | Strip `User:` prefix; current code uses `principal_normalized`. |
| `actor_email` | string | Principal object or identity | No | Current code stores `email` when found. |
| `actor_ip` | string | Client address extraction | No | Current code uses `clientIp`. |
| `principal_resource_id` | string | `authenticationInfo.principalResourceId` | No | Current code uses `principalResourceId`. |
| `identity` | object/string | `authenticationInfo.identity` | No | May be raw and inconsistent. |
| `auth_mechanism` | string | `authenticationInfo.metadata.mechanism` | No | Implemented in flattening. |
| `auth_identifier` | string | `authenticationInfo.metadata.identifier` | No | Implemented in flattening. |
| `impersonated_actor` | string/object | Future mapping | No | Not consistently implemented today. |

Identity normalization rules:

- Preserve `actor_principal_raw` exactly as received.
- Derive `actor_principal` by stripping the `User:` prefix and normalizing obvious service account/user IDs.
- Classify `actor_type` from normalized principal first: `sa-*` -> `service_account`, `u-*` -> `user`; otherwise `unknown`.
- API keys are authentication credentials, not actors by themselves. When only an API key identifier is available, store it in `auth_identifier` and map it back to the owning service account/user through enrichment when possible.
- Service account identity and API key identity must not be conflated in reports; an API key action should show both credential identifier and owning principal when known.
- Use `correlation_id`, `request_id`, `connection_id`, `network_id`, and `session_id` to group related activity. `session_id` is not consistently available today and should be derived only when there is a stable source signal.

### C. Action

| Field | Type | Source / derivation | Required | Notes |
|---|---|---|---|---|
| `action_category` | enum | Classification | No | `deletion`, `creation`, `modification`, `authentication`, `authorization`, `read`, `unknown`. Current code uses `method_category`. |
| `action_name` | string | Derived from method | No | Product-friendly action label; not consistently implemented today. |
| `method` | string | `data.methodName` | Yes | Current code uses `methodName`. |
| `service_name` | string | `data.serviceName` | No | Current code uses `serviceName`. |
| `outcome` | string | `data.result.status` and authz grant | No | Current code uses `resultStatus` and `granted`. |
| `error_code` | string | Result/status details | No | Not consistently separated today. |
| `result_message` | string | `data.result.message` | No | Implemented in flattening. |
| `granted` | boolean | `authorizationInfo.granted` | No | Important for authz denials. |
| `operation` | string | `authorizationInfo.operation` | No | Kafka ACL/action operation when present. |

### D. Resource

| Field | Type | Source / derivation | Required | Notes |
|---|---|---|---|---|
| `resource_type` | string | `authorizationInfo.resourceType` or CRN | No | Current code uses `resourceType`. |
| `resource_name` | string | `data.resourceName` or `authorizationInfo.resourceName` | No | Current code uses `resourceName` and `authzResourceName`. |
| `resource_id` | string | CRN parse | No | Should be separated from display name. |
| `resource_hierarchy` | object | CRN parse | No | Organization, environment, cluster, topic, connector, schema, etc. |
| `rbac_role` | string | `authorizationInfo.rbacAuthorization.role` | No | Current code uses `rbacRole`. |
| `rbac_scope` | string | RBAC scope extraction | No | Current code stores first outer scope. |
| `acl_permission_type` | string | `aclAuthorization.permissionType` | No | Current code uses `aclPermissionType`. |
| `acl_host` | string | `aclAuthorization.host` | No | Current code uses `aclHost`. |
| `pattern_type` | string | `authorizationInfo.patternType` | No | Current code uses `patternType`. |

### E. Change Tracking

| Field | Type | Source / derivation | Required | Notes |
|---|---|---|---|---|
| `change_detected` | boolean | Derived | No | Not implemented consistently today. |
| `before` | object | Event payload or external lookup | No | Not implemented consistently today. |
| `after` | object | Event payload or external lookup | No | Not implemented consistently today. |
| `changed_fields` | array[string] | Derived diff | No | Not implemented consistently today. |
| `is_deletion` | boolean | Method classification | No | Implemented. |
| `is_creation` | boolean | Method classification | No | Implemented. |
| `is_modification` | boolean | Method classification | No | Implemented. |

Change tracking strategy:

- Audit events should first record that a change occurred, even when before/after values are unavailable.
- `change_detected=true` should be derived from method category or explicit event content.
- `before` and `after` should come from audit payload fields only when the source event contains them.
- If the audit event does not contain before/after, AuditLens must not invent them from current resource state without labeling the source as inferred.
- Future enrichment may call control-plane APIs to snapshot current state, but that should be stored as `observed_after`, not authoritative `after`, unless the API response is temporally tied to the audit event.
- `changed_fields` should be computed only when both before/after are present or when the event explicitly lists changed fields.
- Deletion events should preserve enough resource identity to support investigation even if after-state is absent.

Limitations today:

- The current forwarder mainly detects change category through method names.
- It does not consistently populate `before`, `after`, or `changed_fields`.
- Dashboard views should therefore say "what changed event occurred", not "exact field diff", unless diff fields are present.

### F. Observability

| Field | Type | Source / derivation | Required | Notes |
|---|---|---|---|---|
| `ingest_delay_ms` | integer | `ingested_at - event_time` | No | Not consistently implemented today. |
| `visibility_delay_ms` | integer | `visible_at - event_time` | No | Not consistently implemented today. |
| `processing_latency_ms` | integer | Pipeline timers | No | Not consistently implemented today. |
| `source_lag_at_ingest` | integer | Consumer watermark/position | No | Health exposes lag, but per-event lag is not modeled. |
| `dlq_reason` | string | DLQ only | No | Needed for DLQ records. |

### G. Enrichment

| Field | Type | Source / derivation | Required | Notes |
|---|---|---|---|---|
| `criticality` | enum | `src/classification/criticality.py` | Yes for enriched | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`. |
| `classification_reason` | string | Classifier | Yes for enriched | Implemented. |
| `criticality_elevated` | boolean | Classifier | No | Implemented. |
| `is_security_event` | boolean | Classifier | No | Implemented. |
| `is_signal_candidate` | boolean | Classifier | No | Present in classification result but not fully preserved in normalized event. |
| `signal_type` | string | Classifier/aggregator | No | Used for auth failure and denial aggregation. |
| `risk_score` | number | Future scoring | No | Not implemented as numeric score today. |
| `anomaly_flags` | array[string] | Rate tracker/signals | No | Current anomalies are emitted as alerts/signals, not consistently embedded. |
| `correlation_id` | string | `request.correlationId` | No | Current code uses `correlationId` and `correlation_id`. |
| `request_id` | string | `requestMetadata.request_id/requestId` | No | Current code uses `requestId`. |
| `session_id` | string | Future/session metadata | No | Not implemented today. |
| `network_id` | string | `requestMetadata.network_id/networkId` | No | Implemented. |

## 4. Mapping Strategy

Raw CloudEvent to raw topic:

- `raw_event` contains the original event.
- `schema_version` is `audit.raw.v1`.
- Kafka source coordinates are added from the source message.
- Raw records are replay evidence and should not be edited.

Raw CloudEvent to normalized event:

- Copy CloudEvent identity fields: `id`, `specversion`, `source`, `subject`, `type`, `time`, `datacontenttype`.
- Extract `data.serviceName`, `data.methodName`, and `data.resourceName`.
- Extract `authenticationInfo.principal`, normalize the principal, classify principal type, and retain the raw principal.
- Extract auth metadata: mechanism and identifier.
- Extract authorization fields: granted, operation, resource type/name, pattern type, RBAC role/scope, ACL permission/host.
- Extract request/requestMetadata: correlation, request, connection, network, client ID, client IP.
- Serialize raw `data` as `data_json` for fallback and investigation.
- Extract organization/environment/cluster IDs from CRNs.

Normalized to enriched:

- Apply central classification.
- Add criticality, reason, method category, booleans, signal candidate metadata, and high-risk flag.
- Preserve source evidence and principal/resource fields.

Signals:

- Denials are aggregated by principal, method, resource, and time window.
- High-risk signals are produced for destructive or explicitly high-risk enriched records.
- Alerts are separate operator-facing records with recommended action and confidence.

## 5. Example Event

### Raw Event

```json
{
  "specversion": "1.0",
  "id": "7f5d2d21-3cc9-4c45-9a61-55df8e6df011",
  "source": "crn://confluent.cloud/organization=o-abc123/environment=env-prod/kafka=lkc-prod1",
  "subject": "crn://confluent.cloud/organization=o-abc123/environment=env-prod/kafka=lkc-prod1/topic=payments",
  "type": "io.confluent.kafka.server/authorization",
  "time": "2026-04-23T14:21:07.123Z",
  "datacontenttype": "application/json",
  "data": {
    "serviceName": "kafka",
    "methodName": "kafka.DeleteTopics",
    "resourceName": "crn://confluent.cloud/organization=o-abc123/environment=env-prod/kafka=lkc-prod1/topic=payments",
    "authenticationInfo": {
      "principal": "User:sa-prod-admin",
      "principalResourceId": "sa-prod-admin",
      "metadata": {
        "mechanism": "SASL",
        "identifier": "api-key-id-redacted"
      }
    },
    "authorizationInfo": {
      "granted": true,
      "operation": "Delete",
      "resourceType": "Topic",
      "resourceName": "payments",
      "patternType": "LITERAL"
    },
    "request": {
      "clientId": "admin-cli",
      "correlationId": "c-7788"
    },
    "requestMetadata": {
      "requestId": "req-123",
      "connectionId": "conn-456",
      "network_id": "n-789",
      "clientAddress": [
        {
          "ip": "203.0.113.10"
        }
      ]
    },
    "result": {
      "status": "SUCCESS",
      "message": "topic deleted"
    }
  }
}
```

### Normalized Event

```json
{
  "schema_version": "audit.enriched.v1",
  "event_contract_version": "v1",
  "pipeline_stage": "enriched",
  "event_id": "7f5d2d21-3cc9-4c45-9a61-55df8e6df011",
  "id": "7f5d2d21-3cc9-4c45-9a61-55df8e6df011",
  "event_time": "2026-04-23T14:21:07.123Z",
  "time": "2026-04-23T14:21:07.123Z",
  "ingested_at": "2026-04-23T14:21:08.004Z",
  "cloud_event_type": "io.confluent.kafka.server/authorization",
  "type": "io.confluent.kafka.server/authorization",
  "cloud_event_source": "crn://confluent.cloud/organization=o-abc123/environment=env-prod/kafka=lkc-prod1",
  "source": "crn://confluent.cloud/organization=o-abc123/environment=env-prod/kafka=lkc-prod1",
  "cloud_event_subject": "crn://confluent.cloud/organization=o-abc123/environment=env-prod/kafka=lkc-prod1/topic=payments",
  "organization_id": "o-abc123",
  "environment_id": "env-prod",
  "cluster_id": "lkc-prod1",
  "actor_type": "service_account",
  "actor_principal_raw": "User:sa-prod-admin",
  "actor_principal": "sa-prod-admin",
  "principal_raw": "User:sa-prod-admin",
  "principal_normalized": "sa-prod-admin",
  "principal_type": "service_account",
  "actor_email": null,
  "actor_ip": "203.0.113.10",
  "auth_mechanism": "SASL",
  "auth_identifier": "api-key-id-redacted",
  "action_category": "deletion",
  "method": "kafka.DeleteTopics",
  "methodName": "kafka.DeleteTopics",
  "service_name": "kafka",
  "outcome": "SUCCESS",
  "resultStatus": "SUCCESS",
  "result_message": "topic deleted",
  "granted": true,
  "operation": "Delete",
  "resource_type": "Topic",
  "resourceType": "Topic",
  "resource_name": "payments",
  "resourceName": "crn://confluent.cloud/organization=o-abc123/environment=env-prod/kafka=lkc-prod1/topic=payments",
  "authzResourceName": "payments",
  "resource_hierarchy": {
    "organization_id": "o-abc123",
    "environment_id": "env-prod",
    "cluster_id": "lkc-prod1",
    "topic": "payments"
  },
  "correlation_id": "c-7788",
  "request_id": "req-123",
  "network_id": "n-789",
  "criticality": "CRITICAL",
  "classification_reason": "Critical method: kafka.DeleteTopics",
  "is_security_event": false,
  "is_deletion": true,
  "is_creation": false,
  "is_modification": false,
  "is_high_risk": true,
  "source_topic": "confluent-audit-log-events",
  "source_partition": 3,
  "source_offset": 9918271
}
```

## 6. Indexing / Query Recommendations

SQLite/current store:

- Keep existing indexes on event time, scope, and principal.
- Add indexes for `method_name`, `criticality`, and `resource_name`.
- Add composite index for `(cluster_id, event_time)`.
- Add composite index for `(principal_normalized, event_time)`.
- Add composite index for `(criticality, event_time)`.

Kafka topic keys:

- Enriched event key should be `event_id` when present.
- Denial summary key should be `principal_normalized:method:resource`.
- High-risk signal key should be `event_id`.
- Alerts should key by source event ID or deterministic alert ID.

Query patterns:

- Investigation search: time range plus principal/method/resource filters.
- Security review: criticality/high-risk plus time range.
- Denial analysis: principal plus method/resource grouped by window.
- Compliance export: strict time range, scope filters, and source evidence coordinates.

Schema governance recommendations:

- Make `audit.normalized.v1` and `audit.enriched.v1` JSON Schema contracts mandatory.
- Treat additions as backward-compatible and removals/renames as version changes.
- Keep raw CloudEvent unchanged and always trace enriched records back to raw Kafka coordinates.

## 7. Correctness Guarantees

AuditLens event contracts should support these guarantees explicitly:

- Delivery is at-least-once from source audit Kafka into destination topics.
- Duplicate records are possible and must be handled by `event_id` plus source topic/partition/offset.
- Ordering is partition-local only; no global event ordering is guaranteed.
- Raw records are the authoritative replay source.
- Normalized and enriched records are deterministic functions of raw event, forwarder version, and classification policy version.
- Replaying the same raw record should produce the same normalized/enriched event ID and persistence row.
- Signal and alert generation must use deterministic IDs before replay can be considered fully idempotent.
- Completeness is bounded by source audit retention, destination raw-topic retention, and observed consumer lag.

## 8. Replay Strategy

Replay source priority:

- `audit.raw.v1` is the authoritative replay source because it preserves original CloudEvent evidence plus ingest metadata.
- `audit.enriched.v1` can be used for limited rebuild when normalization code has not changed, but it is not a substitute for raw evidence.

Replay modes:

- Full replay: rebuild all derived state from the earliest retained evidence.
- Partial replay: rebuild only a bounded time window, tenant scope, or affected incident range.
- Dry-run replay: validate counts, mappings, and expected outputs without mutating persistence or publishing derived topics.
- Publish replay: repopulate persistence and, when explicitly enabled, republish derived signals and alerts.

Schema requirements for replay safety:

- Raw wrapper records must retain source topic, partition, offset, ingest timestamp, and forwarder version.
- Derived records must carry stable IDs and policy version so rebuild can be compared to prior output.
- Signals and alerts must be keyed from deterministic evidence attributes plus policy version to avoid replay-created duplicates.
- Replay output should record whether it came from raw or enriched source and whether it was dry-run or publish mode.

Observability requirements:

- Replay should expose requested window, effective window, processed records, skipped records, failures, start time, end time, and derived publish mode.
- Operators need enough metadata to explain why a rebuilt record exists and whether it replaced or duplicated prior derived state.
