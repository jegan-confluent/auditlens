# Forwarder Classification Gap Analysis

Date: 2026-05-08
Scope: forwarder → DB writer → audit_events row classification (action_category, signal_type, resource_type) plus the parallel criticality routing in `src/classification/methods.py`.

## Executive summary

The forwarder runs **two independent classification systems**:

1. **`src/classification/methods.py`** — explicit-set criticality routing (CRITICAL / HIGH / MEDIUM / LOW). Powers the multi-topic routing in `audit_forwarder.py`. ~140 methods enumerated. `Register*` is recognised via the `CREATION_PATTERNS` regex.
2. **`src/product/event_normalization.py` + `event_intelligence.py` + `event_signals.py`** — pattern-based classification consumed by `db_writer.AuditEventDbWriter`. This is what populates the `action_category`, `signal_type`, `resource_type`, `impact_type`, `risk_level`, `change_type`, `resource_family` columns of `audit_events`. **No lookup table here — it's a substring-matching cascade.**

The two systems agree about ~70% of the time but diverge on ~30 methods. The DB-writer cascade has a "fail-quiet" tail: anything unrecognised falls to `action_category="Other"` and `signal_type="informational"` with `signal_reason="unknown"`. Nothing is dropped or errored.

The most consequential gap: **read/list/get methods that are not in the explicit Data marker set (`getstatement`, `liststatements`, `tableflowgettable`, `produce`, `fetch`, `consume`, `read`) get `action_category="Other"`**. So 30+ Get/List operations end up bucketed alongside truly unknown methods. The Events UI dropdown filter for `action_category=Data` will therefore miss most read traffic; users who pick "Other" get a soup of reads + unmapped methods. Live data confirms `"Other"` is one of the largest action_category buckets.

A second material gap: **`canonical_resource_type` only knows ~17 aliases**. Confluent now emits >25 distinct `cloudResources.resourceType` values; the unmapped ones (`byokkey`, `multifactorauthentication`, `notificationintegration`, `securitysso`, `supportplan`, `aichatcompletions`, `cloudapikey`, `customconnectorplugin`, `healthpluscluster`, `audit`, `billing`) reach the dashboard verbatim — lower-cased, underscore-stripped, no friendly label, and no consistent grouping. Live `/filters/options` confirms 26 distinct resource_type strings in the wild, of which 11 are unmapped.

---

## 1. How classification works today

### `action_category` (the dropdown column)

`derive_action_category(method_name, action)` in `src/product/event_normalization.py:101`. **Pattern-matching cascade, not a lookup table.** Joined `method action` text is lowercased, separators stripped, then evaluated in order — first match wins:

| Order | Marker(s) (substring or `\bacl\b` regex) | Returns |
|---|---|---|
| 1 | `apikey` / `api key` | `API Key` |
| 2 | `createacl(s)`, `deleteacl(s)`, `rolebinding`, `rbac`, `\bacl\b` | `Security` |
| 3 | `createtopic(s)` | `Create` |
| 4 | `deletetopic(s)` | `Delete` |
| 5 | `getstatement`, `liststatements`, `tableflowgettable`, `produce`, `fetch`, `consume`, `read` | `Data` |
| 6 | `authorize`, `authorization`, `authentication`, `authenticate` | `Security` |
| 7 | `delete` (substring) | `Delete` |
| 8 | `updatestatement`, `patchstatement`, `alter`, `update`, `modify`, `config` | `Modify` |
| 9 | `create` (substring) | `Create` |
| 10 | (default) | `Other` |

Possible values: `Create`, `Delete`, `Modify`, `Security`, `API Key`, `Data`, `Other`.

### `signal_type`

Two-stage. **First**, `event_intelligence.classify_event` derives semantic dimensions (also pattern-based, no lookup table):

- `change_type` ∈ {`denied`, `authenticated`, `authorized`, `deleted`, `created`, `configured`, `updated`, `read/listed`, `unknown`} from method/event-type word splits.
- `impact_type` ∈ {`destructive`, `access_change`, `configuration_change`, `authentication`, `authorization_check`, `read_only`, `operational`, `security_sensitive`, `constructive`, `unknown`} via cascading rules over change_type, family, and method markers.
- `risk_level` ∈ {`critical`, `high`, `medium`, `informational`, `low`} from impact + family.
- `resource_family` ∈ {`schema_registry`, `tableflow`, `connector`, `service_account`, `api_key`, `rbac`, `acl`, `topic`, `ksql`, `flink`, `cluster`, `environment`, `user`, `network`, `billing`, `organization`, `unknown`}.

**Then** `event_signals.classify_signal` (`src/product/event_signals.py:44`) collapses those into `signal_type` via this cascade (first match wins):

| Test | `signal_type` | `signal_reason` |
|---|---|---|
| `is_denied` | `action_required` | `denied_access` |
| `is_failure` | `action_required` | `failure_detected` |
| `risk=critical` OR `impact=destructive` OR `change=deleted` OR action contains `delete/remove/drop/destroy/terminate` | `action_required` | `destructive_change` |
| `impact=security_sensitive` AND action contains `access-transparency` | `action_required` | `security_sensitive_change` |
| `impact=access_change` OR action contains `grant/revoke/assignrole/remove role/rolebinding/createapikey/deleteapikey` | `attention` | `access_changed` |
| `impact=configuration_change` OR action contains `updateconfig/alterconfig/config/patch/set` | `attention` | `config_changed` |
| `risk in {high,medium}` OR `change in {created,updated,configured}` (security family) | `attention` | varies |
| `impact=authentication` | `noise` | `auth_noise` |
| `impact=authorization_check` | `noise` | `authorization_check` |
| `impact=read_only` OR `change=read/listed` OR action contains `list/get/describe/search` | `informational` | `read_only_lookup` |
| `impact in {constructive, operational}` | `informational` | `operational_event` |
| (default) | `informational` | `unknown` |

Possible values: `action_required`, `attention`, `noise`, `informational`.

### `resource_type`

`extract_resource_context` (`src/product/resource_intelligence.py:502`). Multi-source extraction, priority order:

1. `cloudResources.resource.resourceType` (highest confidence).
2. CRN parse via `parse_crn()` — recognises `topic`, `group`, `transactional-id`, `cluster-link`, `subject`, `connector`, `statement`, `compute-pool`, `service-account`, `user`, `api-key`, `identity-pool`, `identity-provider`, `network`, `peering`, `private-link`.
3. `/<type>=` markers in resource-name fields: topic, cloud-cluster, schema-registry, ksql, compute-pool, statement, connector, service-account, api-key, network, organization, environment.
4. Heuristic substring search across resourceName/summary fields (`topic`, `subject`, `connector`, `apikey`, `rolebinding`, `environment`, `tableflow`, `cluster`).
5. Fallback → `"unknown"`.

The result is then run through `canonical_resource_type` which uses `RESOURCE_TYPE_ALIASES` (17 entries). Unmapped values pass through as `lowercased_with_underscores` — see Section 3.

### Criticality routing (parallel system)

`src/classification/methods.py` defines four explicit sets:

- `CRITICAL_METHODS` — 31 methods (destructive: DeleteEnvironment, DeleteServiceAccount, DeleteAuditLogConfig, etc.)
- `HIGH_METHODS` — ~70 methods (credential ops, RBAC, network config)
- `MEDIUM_METHODS` — ~40 methods (config changes, non-destructive updates)
- `READ_ONLY_METHODS` — ~50 methods (Get/List/Describe + kafka.Produce/Fetch)
- `AUTHENTICATION_METHODS`, `AUTHORIZATION_CHECK_METHODS` — special-case sets.

Plus regex pattern fallbacks (`get_method_category`):
- `DELETION_PATTERNS = ('Delete', 'Remove', 'Purge', 'Drop')`
- `CREATION_PATTERNS = ('Create', 'Add', 'New', 'Register')`
- `MODIFICATION_PATTERNS = ('Update', 'Alter', 'Modify', 'Change', 'Set')`
- `READ_PATTERNS = ('Get', 'List', 'Describe', 'Fetch', 'Read', 'Find', 'Show')`

Loadable from `config/classification_rules.yaml` (full override) and unionable with schema-watcher additions (`schema_methods.json`).

This system feeds the multi-topic forwarder's routing decisions but **does not** populate any `audit_events` column — those come exclusively from the pattern cascade.

### Behaviour on unknown methodName

Both systems "fail open":

- `derive_action_category` → `Other`.
- `classify_event` → `change_type=unknown`, `impact_type=unknown`, `risk_level=low`.
- `classify_signal` → `signal_type=informational`, `signal_reason=unknown`, `recommended_action=Review if unexpected`, `decision_label=Info`.
- `extract_resource_context` → `resource_type=unknown` if no markers found.
- `get_method_category` → `other`.
- `db_writer.write_batch` writes the row regardless. **No drops, no errors.**

The `is_routine_noise` boolean is set when the methodName matches `authentication/authenticate/authorize/metadata/fetch/getkafkaclusters/listcomputepools` AND the action_category is not Create/Delete/Modify/API Key AND the event isn't failed/denied. Used downstream for "hide noise" filtering.

---

## 2 & 5. Per-method coverage

Legend: ✅ explicit handling • ⚠️ falls to pattern/substring (correct outcome) • ❌ falls to `Other` / `unknown` / wrong bucket.

### Kafka

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `kafka.CreateTopics` | ⚠️ | `Create` | `attention` (constructive→risk medium) | `topic` | none |
| `kafka.DeleteTopics` | ✅ (CRITICAL) | `Delete` | `action_required` | `topic` | none |
| `kafka.AlterConfigs` | ✅ (MEDIUM) | `Modify` | `attention` (config_changed) | `cluster`/`topic` | none |
| `kafka.IncrementalAlterConfigs` | ✅ (MEDIUM) | `Modify` | `attention` | `cluster`/`topic` | none |
| `kafka.CreateAcls` | ✅ (HIGH) | `Security` | `attention` (access_changed) | `role_binding` | none |
| `kafka.DeleteAcls` | ✅ (HIGH) | `Security` | `action_required` | `role_binding` | none |
| `kafka.DeleteGroups` | ✅ (MEDIUM) | `Delete` | `action_required` | varies | minor: classified as Delete but consumer-group deletion isn't truly destructive in the way DeleteTopic is |
| `kafka.CreatePartitions` | ✅ (MEDIUM) | `Create` | `attention` | `topic` | none |
| `kafka.CreateClusterLinks` | ⚠️ | `Create` | `attention` | `cluster` | none (but no entry in CRITICAL/HIGH set — `CreateClusterLink` is HIGH but the `kafka.` prefix variant isn't) |
| `kafka.DeleteClusterLinks` | ⚠️ | `Delete` | `action_required` | `cluster` | similar — only `DeleteClusterLink` (no `s`) is in HIGH |
| `kafka.AlterMirrors` | ⚠️ | `Modify` | `attention` | `cluster` | none |
| `kafka.Fetch` | ✅ (READ_ONLY) | `Data` | `informational`/`noise` | `topic` | none |
| `kafka.Produce` | ✅ (READ_ONLY) | `Data` | `informational` | `topic` | none |
| `kafka.Authentication` | ✅ (AUTHENTICATION) | `Security` | `noise` (auth_noise) | varies | none |
| `kafka.ShareFetch` | ⚠️ | `Data` (matches `fetch`) | `informational` | `topic` | none |

### RBAC / Authorization

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `CreateRoleBinding` | ✅ (HIGH) | `Security` (rolebinding marker) | `attention` (access_changed) | `role_binding` | none |
| `DeleteRoleBindingById` | ⚠️ (only `DeleteRoleBinding` in HIGH) | `Security` | `action_required` | `role_binding` | naming inconsistency — Confluent API emits `DeleteRoleBindingById` but criticality table has `DeleteRoleBinding` only. Falls through to pattern-match → 'deletion'. Fine but not enumerated. |
| `RevokeRoleResourcesForPrincipal` | ✅ HIGH | ❌ `Other` | `attention` (`revoke` → impact=`access_change`) | `role_binding` (heuristic) | **action_category WRONG — falls to "Other".** action_category cascade has no marker for `revoke`. signal_type is correct. |
| `GrantRoleResourcesForPrincipal` | ⚠️ (HIGH-equivalent — not in set) | ❌ `Other` | `attention` (`grant` matched in event_signals) | `role_binding` (heuristic) | **same gap — `grant` not in action_category cascade. Also missing from criticality HIGH set.** |
| `mds.Authorize` | ✅ (AUTHORIZATION_CHECK) | `Security` (authorize marker) | `noise` (authorization_check) | varies | none — explicitly demoted from CRITICAL even on denial. |

### Organization (API key / SA / env / cluster / user / SSO / billing)

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `CreateAPIKey` | ✅ (HIGH as `CreateApiKey`) | `API Key` | `attention` (access_changed) | `api_key` | naming: criticality table uses `CreateApiKey` (lower-case `i`), Confluent emits `CreateAPIKey`. Pattern-match catches it but explicit set misses. |
| `DeleteAPIKey` | ✅ (HIGH as `DeleteApiKey`) | `API Key` | `action_required` | `api_key` | same case mismatch |
| `UpdateAPIKey` | ✅ (HIGH as `UpdateApiKey`) | `API Key` | `attention` | `api_key` | same |
| `GetAPIKey` | ✅ READ_ONLY (as `GetApiKey`) | `API Key` (apikey marker matches first) | `informational` | `api_key` | minor: Get becomes "API Key" not "Data" — debatable. |
| `GetAPIKeys` | ✅ READ_ONLY (as `GetApiKeys`) | `API Key` | `informational` | `api_key` | same |
| `CreateServiceAccount` | ✅ HIGH | `Create` | `attention` | `service_account` | none |
| `DeleteServiceAccount` | ✅ CRITICAL | `Delete` | `action_required` | `service_account` | none |
| `UpdateServiceAccount` | ✅ HIGH | `Modify` | `attention` | `service_account` | none |
| `CreateEnvironment` | ✅ MEDIUM | `Create` | `attention` | `environment` | none |
| `DeleteEnvironment` | ✅ CRITICAL | `Delete` | `action_required` (risk=critical) | `environment` | none |
| `UpdateEnvironment` | ✅ MEDIUM | `Modify` | `attention` | `environment` | none |
| `CreateKafkaCluster` | ✅ MEDIUM | `Create` | `attention` | `cluster` | none |
| `DeleteKafkaCluster` | ✅ CRITICAL | `Delete` | `action_required` | `cluster` | none |
| `UpdateKafkaCluster` | ✅ MEDIUM | `Modify` | `attention` | `cluster` | none |
| `CreateSchemaRegistryCluster` | ⚠️ | `Create` | `attention` | `schema_registry` | none |
| `DeleteSchemaRegistryCluster` | ⚠️ | `Delete` | `action_required` | `schema_registry` | not in CRITICAL set despite SR cluster deletion being destructive |
| `CreateKSQLCluster` | ✅ MEDIUM (`CreateKsqldbCluster`) | `Create` | `attention` | `cluster` | naming: KSQL vs Ksqldb |
| `DeleteKSQLCluster` | ✅ CRITICAL (`DeleteKsqldbCluster`) | `Delete` | `action_required` | `cluster` | same |
| `PauseKSQLCluster` | ✅ MEDIUM (`PauseKsqldbCluster`) | ❌ `Other` | `informational` (impact=operational via `pause`) | `cluster` | **`pause` not in action_category cascade.** |
| `UpdateKSQLCluster` | ✅ MEDIUM (`UpdateKsqldbCluster`) | `Modify` | `attention` | `cluster` | naming |
| `CreateUser` | ✅ HIGH | `Create` | `attention` | `user` | none |
| `DeleteUser` | ✅ HIGH | `Delete` | `action_required` | `user` | none |
| `UpdateUser` | ✅ HIGH | `Modify` | `attention` | `user` | none |
| `InviteUser` | ⚠️ HIGH has `CreateInvitation` | ❌ `Other` | `attention` (`invite` matches in event_intelligence) | `user` (heuristic) | **`invite` not in action_category cascade. Confluent may emit `InviteUser` separately from `CreateInvitation`.** |
| `DeleteInvitation` | ✅ HIGH | `Delete` | `action_required` | `user` | none |
| `CreateSSOConnection` | ⚠️ (not in sets — only `CreateSSOGroupMapping`) | `Create` | `attention` | `unknown`/raw | resource_type fallthrough |
| `DeleteSSOConnection` | ⚠️ | `Delete` | `action_required` | `unknown`/raw | same |
| `UpdateSSOConnection` | ⚠️ | `Modify` | `attention` | `unknown`/raw | same |
| `SignIn` | ✅ READ_ONLY | ❌ `Other` | `informational` (impact=operational via `signin`) | `user`/heuristic | **`signin` not in action_category cascade — should likely be `Security` or a new `Auth` category.** |
| `UpdateBillingProfile` | ⚠️ | `Modify` | `attention` | `billing` (heuristic) | none |
| `UpdatePaymentMethod` | ⚠️ | `Modify` | `attention` | `billing` (heuristic) | none |
| `UpdateSupportPlan` | ⚠️ | `Modify` | `attention` | raw `supportplan` | resource_type alias missing |

### Connectors

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `CreateConnector` | ✅ HIGH | `Create` | `attention` | `connector` | none |
| `DeleteConnector` | ✅ CRITICAL | `Delete` | `action_required` | `connector` | none |
| `CreateOrUpdateConnector` | ⚠️ (not in any set, but matches `CreateConnector` pattern) | `Create` | `attention` | `connector` | minor: upsert classified as Create even when it's actually an update |
| `PauseConnector` | ✅ HIGH | ❌ `Other` | `informational` (operational) | `connector` | **`pause` not in cascade.** |
| `ResumeConnector` | ⚠️ (not in any set) | ❌ `Other` | `informational` (operational) | `connector` | **`resume` not in cascade. Missing from HIGH set.** |
| `GetConnector` | ✅ READ_ONLY | ❌ `Other` | `informational` (read_only) | `connector` | **`get` not in Data marker set.** |
| `GetConnectors` | ✅ READ_ONLY | ❌ `Other` | `informational` | `connector` | same |

### Schema Registry

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `schema-registry.Authentication` | ✅ AUTHENTICATION | `Security` | `noise` | varies | none |
| `schema-registry.RegisterSchema` | ⚠️ (`Register` is in CREATION_PATTERNS regex) | ❌ `Other` | `informational` (catch-all unknown) | `subject` | **`register` not in cascade. Misclassified semantically — RegisterSchema is a create.** |
| `schema-registry.DeleteSubject` | ✅ CRITICAL | `Delete` | `action_required` (risk=critical) | `subject` | none |
| `schema-registry.DeleteSchemaVersion` | ⚠️ | `Delete` | `action_required` | `subject` | none (not enumerated but matches Delete pattern) |
| `schema-registry.DeleteSubjectMode` | ⚠️ | `Delete` | `action_required` | `subject` | none |
| `schema-registry.UpdateSubjectMode` | ✅ HIGH (`UpdateMode`) | `Modify` | `attention` | `subject` | naming inconsistency |
| `schema-registry.UpdateSubjectConfig` | ✅ HIGH (`UpdateConfig`) | `Modify` | `attention` | `subject` | naming |
| `schema-registry.UpdateGlobalConfig` | ✅ HIGH (`UpdateConfig`) | `Modify` | `attention` | `schema_registry` | naming |
| `schema-registry.UpdateGlobalMode` | ✅ HIGH (`UpdateMode`) | `Modify` | `attention` | `schema_registry` | naming |
| `schema-registry.CreateTagDefs` | ⚠️ | `Create` | `attention` | `schema_registry` | none |
| `schema-registry.UpdateTagDefs` | ⚠️ | `Modify` | `attention` | `schema_registry` | none |
| `schema-registry.CreateTags` | ⚠️ | `Create` | `attention` | varies | none |
| `schema-registry.DeleteTag` | ⚠️ | `Delete` | `action_required` | varies | none |
| `schema-registry.DeleteTagDef` | ⚠️ | `Delete` | `action_required` | varies | none |
| `schema-registry.CreateExporter` | ✅ HIGH | `Create` | `attention` | `schema_registry` | none |
| `schema-registry.DeleteExporter` | ✅ CRITICAL | `Delete` | `action_required` | `schema_registry` | none |
| `schema-registry.UpdateExporter` | ⚠️ | `Modify` | `attention` | `schema_registry` | none |
| `schema-registry.PauseExporter` | ✅ MEDIUM | ❌ `Other` | `informational` (operational) | `schema_registry` | **`pause` not in cascade.** |
| `schema-registry.ResumeExporter` | ✅ MEDIUM | ❌ `Other` | `informational` (operational) | `schema_registry` | **`resume` not in cascade.** |
| `schema-registry.RegisterDek` | ⚠️ | ❌ `Other` | `informational` (catch-all) | varies | **`register` gap — semantically a create.** |
| `schema-registry.RegisterKek` | ⚠️ | ❌ `Other` | `informational` | varies | same |
| `schema-registry.DeregisterDek` | ⚠️ | ❌ `Other` | `informational` | varies | **`deregister` gap — semantically a delete.** |
| `schema-registry.DeregisterKek` | ⚠️ | ❌ `Other` | `informational` | varies | same |
| `schema-registry.UpdateKek` | ⚠️ | `Modify` | `attention` | varies | none |
| `schema-registry.CreateBusinessMetadataDefs` | ⚠️ | `Create` | `attention` | varies | none |
| `schema-registry.DeleteBusinessMetadataDef` | ⚠️ | `Delete` | `action_required` | varies | none |
| `schema-registry.PartialEntityUpdate` | ⚠️ | `Modify` | `attention` | varies | none |

### Flink

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `CreateStatement` | ✅ MEDIUM (`CreateFlinkStatement`) | `Create` | `attention` | `statement` | naming: with/without `Flink` prefix |
| `DeleteStatement` | ✅ CRITICAL | `Delete` | `action_required` | `statement` | none |
| `UpdateStatement` | ✅ MEDIUM (`UpdateFlinkStatement`) | `Modify` | `attention` | `statement` | naming |
| `CreateComputePool` | ✅ MEDIUM (`CreateFlinkCompute`) | `Create` | `attention` | `compute_pool` | naming |
| `DeleteComputePool` | ✅ CRITICAL (`DeleteFlinkCompute`) | `Delete` | `action_required` | `compute_pool` | naming |
| `UpdateComputePool` | ✅ MEDIUM (`UpdateFlinkCompute`) | `Modify` | `attention` | `compute_pool` | naming |
| `CreateWorkspace` | ⚠️ | `Create` | `attention` | varies | none |
| `DeleteWorkspace` | ✅ CRITICAL | `Delete` | `action_required` | varies | none |
| `UpdateWorkspace` | ⚠️ (`PatchWorkspace` is MEDIUM) | `Modify` | `attention` | varies | naming |
| `flink.Authenticate` | ✅ AUTHENTICATION | `Security` | `noise` | varies | none |
| `flink.Authorize` | ✅ AUTHORIZATION_CHECK | `Security` | `noise` | varies | none |

### Identity

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `CreateIdentityProvider` | ✅ HIGH | `Create` | `attention` | `unknown`/raw | resource_type unmapped |
| `DeleteIdentityProvider` | ✅ CRITICAL | `Delete` | `action_required` | `unknown`/raw | same |
| `UpdateIdentityProvider` | ✅ HIGH | `Modify` | `attention` | `unknown`/raw | same |
| `CreateIdentityPool` | ✅ HIGH | `Create` | `attention` | `identity_pool` (raw) | not in alias map |
| `DeleteIdentityPool` | ✅ CRITICAL | `Delete` | `action_required` | `identity_pool` (raw) | same |
| `UpdateIdentityPool` | ✅ HIGH | `Modify` | `attention` | `identity_pool` (raw) | same |

### Networking

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `CreateNetwork` | ✅ MEDIUM | `Create` | `attention` | `network` | none |
| `DeleteNetwork` | ✅ MEDIUM | `Delete` | `action_required` | `network` | severity: Delete on network is arguably HIGH/CRITICAL |
| `CreatePeering` | ✅ HIGH | `Create` | `attention` | `peering` (raw) | resource_type unmapped |
| `DeletePeering` | ✅ CRITICAL | `Delete` | `action_required` | `peering` | same |
| `CreatePrivateLinkAttachment` | ✅ HIGH | `Create` | `attention` | `unknown`/raw | unmapped |
| `DeletePrivateLinkAttachment` | ✅ HIGH | `Delete` | `action_required` | `unknown`/raw | same |
| `CreatePrivateLinkAttachmentConnection` | ✅ HIGH | `Create` | `attention` | `unknown`/raw | same |
| `DeletePrivateLinkAttachmentConnection` | ✅ HIGH | `Delete` | `action_required` | `unknown`/raw | same |
| `CreatePrivateLinkAccess` | ✅ HIGH | `Create` | `attention` | `unknown`/raw | same |
| `DeletePrivateLinkAccess` | ✅ CRITICAL | `Delete` | `action_required` | `unknown`/raw | same |
| `CreateDnsForwarder` | ✅ HIGH | `Create` | `attention` | `unknown`/raw | unmapped |
| `DeleteDnsForwarder` | ✅ HIGH | `Delete` | `action_required` | `unknown`/raw | same |
| `UpdateDnsForwarder` | ⚠️ | `Modify` | `attention` | `unknown`/raw | same |

### Custom Connector

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `CreateCustomConnectorPlugin` | ⚠️ | `Create` | `attention` | `customconnectorplugin` (raw) | resource_type alias missing |
| `DeleteCustomConnectorPlugin` | ⚠️ | `Delete` | `action_required` | same | same |
| `UpdateCustomConnectorPlugin` | ⚠️ | `Modify` | `attention` | same | same |
| `CreatePresignedUrl` | ⚠️ | `Create` | `attention` | `unknown` | semantically not a Create — it issues a transient URL. Misleading bucket. |

### Tableflow

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `TableflowCreateTable` | ✅ MEDIUM (`CreateTableflow`) | `Create` | `attention` | `tableflow` | naming |
| `TableflowCatalogConfig` | ⚠️ | `Modify` (matches `config`) | `attention` (config_changed) | `tableflow` | misleading — could be a read of catalog config; cascade can't tell read from write |
| `TableflowListTables` | ⚠️ | ❌ `Other` | `informational` (read_only via `list`) | `tableflow` | **`tableflowlisttables` not in Data marker set.** |
| `TableflowGetTable` | ✅ explicit in cascade | `Data` | `informational` | `tableflow` | none |
| `TableflowOAuthTokens` | ⚠️ | ❌ `Other` | `informational` (catch-all) | `tableflow` | **unrecognised; signal_reason="unknown".** |

### Other (Read / List / Get / misc)

| Method | In forwarder? | action_category | signal_type | resource_type | Gap |
|---|---|---|---|---|---|
| `GetStatement` | ✅ explicit in cascade | `Data` | `informational` | `statement` | none |
| `ListWorkspaces` | ⚠️ | ❌ `Other` | `informational` (impact=read_only via `list`) | varies | **`listworkspaces` not in Data marker set.** |
| `ListStatements` | ✅ explicit in cascade | `Data` | `informational` | `statement` | none |
| `ListComputePools` | ✅ READ_ONLY | ❌ `Other` | `informational`/`noise` (is_routine_noise=true) | `compute_pool` | **`listcomputepools` not in Data set even though it's explicitly noise-flagged.** |
| `ListFlinkRegions` | ⚠️ | ❌ `Other` | `informational` | varies | same gap |
| `ScheduledJwksRefresh` | ⚠️ | ❌ `Other` | `informational` (catch-all) | `unknown` | **operational background job — unrecognised.** |
| `GetServiceAccounts` | ✅ READ_ONLY | ❌ `Other` | `informational` | `service_account` | **read gap.** |
| `GetUsers` | ✅ READ_ONLY (`GetUsers`) | ❌ `Other` | `informational` | `user` | same |
| `GetKafkaClusters` | ✅ READ_ONLY (`is_routine_noise=true`) | ❌ `Other` | `noise` | `cluster` | same |
| `GetEnvironments` | ✅ READ_ONLY | ❌ `Other` | `informational` | `environment` | same |
| `ListSchemaRegistryClusters` | ✅ READ_ONLY | ❌ `Other` | `informational` | `schema_registry` | same |
| `GetPrivateLinkAttachments` | ✅ READ_ONLY | ❌ `Other` | `informational` | `unknown`/raw | same + resource gap |
| `ListCustomConnectorPlugins` | ⚠️ | ❌ `Other` | `informational` | `customconnectorplugin` | same |
| `ListEndpoints` | ⚠️ | ❌ `Other` | `informational` | varies | same |
| `ListIdentityPool` | ⚠️ | ❌ `Other` | `informational` | `identity_pool` (raw) | same |
| `GetServiceAccount` | ✅ READ_ONLY | ❌ `Other` | `informational` | `service_account` | same |
| `GetWorkspace` | ⚠️ | ❌ `Other` | `informational` | varies | same |
| `GetKafkaCluster` | ✅ READ_ONLY | ❌ `Other` | `informational` | `cluster` | same |
| `GetEnvironment` | ✅ READ_ONLY | ❌ `Other` | `informational` | `environment` | same |
| `GetPrivateLinkAttachmentConnections` | ✅ READ_ONLY | ❌ `Other` | `informational` | `unknown`/raw | same |
| `GetNetworks` | ✅ READ_ONLY | ❌ `Other` | `informational` | `network` | same |
| `GetKSQLClusters` | ✅ READ_ONLY | ❌ `Other` | `informational` | `cluster` | same |
| `GetTransitGateways` | ⚠️ | ❌ `Other` | `informational` | `unknown` | same; also no resource alias |
| `GetAPIKey` | ✅ READ_ONLY | `API Key` (apikey marker) | `informational` | `api_key` | OK but bucketed as API Key, not Data — debatable |
| `GetAPIKeys` | ✅ READ_ONLY | `API Key` | `informational` | `api_key` | same |
| `schema-registry.GetAllTagDefs` | ✅ READ_ONLY | ❌ `Other` | `informational` | `schema_registry`/raw | read gap |
| `schema-registry.GetEntityByTypeAndName` | ✅ READ_ONLY | ❌ `Other` | `informational` | varies | same |
| `schema-registry.GetDek` | ⚠️ | ❌ `Other` | `informational` | varies | same |
| `ksql.Authenticate` | ✅ AUTHENTICATION | `Security` | `noise` | varies | none |
| `ksql.Authorize` | ✅ AUTHORIZATION_CHECK | `Security` | `noise` | varies | none |

---

## 3. resource_type normalization

### Values the forwarder can emit

**Mapped (via `RESOURCE_TYPE_ALIASES` in `resource_intelligence.py:11`)** — 17 canonical values:
`topic`, `subject`, `schema_registry`, `connector`, `role_binding`, `environment`, `cluster`, `api_key`, `service_account`, `compute_pool`, `ksqldb`, `statement`, `tableflow`, `organization`, `network`, `user`, `unknown`.

**Pass-through (raw `cloudResources.resourceType` lower-cased, dashes/underscores collapsed)** — observed in live data:
`aichatcompletions`, `audit`, `billing`, `byokkey`, `cloudapikey`, `customconnectorplugin`, `healthpluscluster`, `identity_pool`, `multifactorauthentication`, `notificationintegration`, `peering`, `securitysso`, `supportplan`.

(Confirmed against the live `/filters/options` output: 26 distinct strings, 11 of which are unmapped.)

### Inconsistencies

| Logical type | Strings observed | Issue |
|---|---|---|
| API key | `api_key` (alias path), `cloudapikey` (raw path) | **Two strings for same concept.** Confluent emits both `API_KEY` and `CLOUD_API_KEY` in different events; only the former hits the alias. |
| Cluster | `cluster` covers Kafka, schema-registry, ksql, flink, connect | Overloaded — the `_resource_family` heuristic separates them downstream but `resource_type` collapses them. |
| Schema registry "subject" vs "schema" | Aliased to `subject` | Confluent docs use both interchangeably; alias correctly normalises. |
| Identity provider | unmapped | Falls to `unknown` since alias map has no `identity_provider` (only `identity_pool` passes through raw). |
| Peering / private-link / transit-gateway / dns-forwarder | unmapped or raw | No aliases; CRN parser recognises `peering`, `private-link` but `canonical_resource_type` doesn't map them to friendly canonical names. |
| Custom connector plugin | `customconnectorplugin` (raw) | No alias; should map to `custom_connector_plugin` or similar. |

### Confluent resource types with no mapping

From CRN parser keys (`resource_intelligence.py:236`) NOT in `RESOURCE_TYPE_ALIASES`:
- `group` (Kafka consumer group)
- `transactional-id`
- `cluster-link`
- `identity-pool` (passes through raw, not aliased to a friendly name)
- `identity-provider`
- `peering`
- `private-link`

Plus the live-data unmapped strings listed above (byok, multifactor, notification, sso, support, etc.).

---

## 4. signal_type assignment summary

(Cascade detail in Section 1.) Key facts:

### Hardcoded as `noise`
- `impact_type=authentication` (kafka/flink/ksql/schema-registry Authentication, kafka.Authenticate)
- `impact_type=authorization_check` (mds.Authorize, flink.Authorize, ksql.Authorize, schema-registry.Authorize)

`is_routine_noise=true` is also set (separate boolean column) when methodName matches `authentication/authenticate/authorize/metadata/fetch/getkafkaclusters/listcomputepools` AND not Create/Delete/Modify/API Key AND not failed/denied.

### Hardcoded as `action_required`
- `is_denied`
- `is_failure`
- `risk=critical` OR `impact=destructive` OR `change=deleted` OR action contains `delete/remove/drop/destroy/terminate`
- `impact=security_sensitive` AND action contains `access-transparency`

### Hardcoded as `attention`
- `impact=access_change` OR action contains `grant/revoke/assignrole/remove role/rolebinding/createapikey/deleteapikey`
- `impact=configuration_change` OR action contains `updateconfig/alterconfig/config/patch/set`
- `risk in {high, medium}` OR `change in {created, updated, configured}` (mostly for security-family resources)

### Hardcoded as `informational`
- `impact=read_only` OR `change=read/listed` OR action contains `list/get/describe/search`
- `impact=constructive` OR `impact=operational`

### Catch-all (`informational` + `signal_reason="unknown"`)
Everything else. Recommended action: "Review if unexpected". Decision label: "Info".

So unrecognised methods are silently bucketed as `informational/unknown` — which **dilutes the informational bucket** and gives no analyst signal that classification failed. There is no metric/log warning when this fallback fires.

---

## 6. Recommended fixes (priority order)

### Critical (data classification incorrect — UI / filter / alert quality affected)

1. **Add `get/list/describe` markers to the `Data` step of `derive_action_category`.** Today only `getstatement`, `liststatements`, `tableflowgettable`, `produce`, `fetch`, `consume`, `read` map to Data — so 30+ Get*/List*/Describe* methods land in `Other`. Fix: add `\bget\w+`, `\blist\w+`, `\bdescribe\w+` markers (or move ahead of the catch-all). Without this fix, the Events UI dropdown filter for `action_category=Data` is structurally broken.
2. **Add `revoke/grant/invite` markers to the `Security` (or new `Access`) step.** `RevokeRoleResourcesForPrincipal`, `GrantRoleResourcesForPrincipal`, `InviteUser` currently bucket as `Other` despite being access-grants/revocations.
3. **Add `register/deregister` markers (Schema Registry DEK/KEK).** Today they bucket as `Other`; semantically they are Create/Delete equivalents. The criticality table's `CREATION_PATTERNS` already handles `Register` — the cascade is the divergent one.
4. **Map missing resource types in `RESOURCE_TYPE_ALIASES`.** At least: `identity_pool`, `identity_provider`, `peering`, `private_link`, `transit_gateway`, `dns_forwarder`, `custom_connector_plugin`, `byok_key`, `cloud_api_key` (alias to `api_key`). Without this, dashboard chips/counts split the same logical concept across multiple raw strings.
5. **Emit a metric / debug log when the classification cascade reaches the catch-all.** Currently `signal_reason="unknown"` is silent. Add a counter (`audit_unknown_method_total{method=...}`) so unmapped methods are observable rather than invisible.

### Important (semantic accuracy)

6. **Unify naming between `src/classification/methods.py` (PascalCase: `CreateApiKey`, `DeleteRoleBinding`, `CreateFlinkStatement`) and Confluent's actual emissions (`CreateAPIKey`, `DeleteRoleBindingById`, `CreateStatement`).** Today the explicit set misses many variants and only the regex fallback rescues them — opaque to maintainers.
7. **Add `pause/resume` markers to the action_category cascade as `Modify`** (or a new `Operational` category). Affects PauseConnector, ResumeConnector, schema-registry.PauseExporter/ResumeExporter, PauseKsqldbCluster.
8. **Audit the `kafka.X` vs `X` set membership.** `kafka.CreateClusterLinks` / `kafka.DeleteClusterLinks` are not in HIGH/CRITICAL even though `CreateClusterLink` / `DeleteClusterLink` (no `s`) are. Same situation for `kafka.CreateMirrorTopic` (set has `CreateMirrorTopic`).
9. **Reclassify `GetAPIKey`/`GetAPIKeys` from `API Key` to `Data`.** Pattern order puts the apikey rule first, so reads of API keys land in the API Key category — a Data event in the API Key bucket is misleading.
10. **Promote `DeleteSchemaRegistryCluster`, `DeleteNetwork` to CRITICAL.** Currently MEDIUM/HIGH respectively despite irreversible impact.
11. **Add `SignIn` to a new `Auth`/`Security` action_category** rather than `Other`. Confluent's `SignIn` is already in `READ_ONLY_METHODS` for criticality but the action_category cascade doesn't see it.

### Nice to have

12. **Make `CreateOrUpdateConnector` honour both halves.** Currently always `Create`. Either emit `Modify` when the resource pre-exists (requires state) or default to `Modify` (more conservative for deduped change detection).
13. **Distinguish `kafka.DeleteGroups` from CRITICAL deletes.** Deleting a consumer group is recoverable; today it's `Delete` + `action_required` like `DeleteTopic`.
14. **Reclassify `CreatePresignedUrl`** out of `Create` — it issues a short-lived URL, not a persistent resource.
15. **Add a `tableflowlisttables` marker** (or generalise the Data step) so `TableflowListTables` and other Tableflow read methods land in `Data`.
16. **Record `cloudResources.resourceType` raw value in a separate column** (`raw_resource_type`) so dashboards can choose between canonical and raw without losing information when the alias map is updated retroactively.
17. **Single source of truth for classification.** The criticality table (`src/classification/methods.py`) and the action_category cascade (`event_normalization.py`) have overlapping but divergent knowledge of the method universe. Move to one canonical list (YAML config already supports overrides — extend it to drive both).
