# Operational Risks

## 0. Operating Model Boundaries

Data plane:

- Forwarder, source Kafka consumer, destination Kafka producer, canonical Kafka topics, classification, signals, DLQ, replay.
- Primary objective: preserve evidence and produce derived records with at-least-once semantics.

Control plane:

- API, SQLite persistence, dashboard, landing page, export, health/freshness/coverage views.
- Primary objective: provide consistent, authorized, auditable investigation workflows.

Required product boundary:

- API + persistence must become the product-mode source of truth.
- Dashboard direct Kafka reads are a foundation/testing path only.
- Customer-facing UI must not bypass API auth, RBAC, scope filtering, export limits, or API audit logging.

## 1. Data Pipeline Risks

| Risk | Evidence in current repo | Impact | Priority | Mitigation |
|---|---|---|---|---|
| Lag accumulation | `/health` exposes high-level and per-partition lag, but no automatic throttling/remediation. | Dashboard/API may show recent processed data while source audit backlog remains large. | High | Add lag SLOs, alert thresholds, lag trend dashboards, and explicit "coverage delayed" UI state. |
| At-least-once duplicates | Forwarder commits offsets only after persistence and Kafka flush; health documents duplicate replay risk. | Duplicate events can appear after crash/rebalance between produce success and offset commit. | Medium | Ensure all product stores and signal IDs are idempotent; use deterministic IDs for derived alerts/signals. |
| Partial batch failure blocks commits | Batch commit is skipped if processing fails or delivery errors increase. | Poison events can cause repeated reprocessing and lag growth. | High | Strengthen DLQ isolation, add poison-event skip policy after DLQ success, and expose repeated DLQ/retry counts. |
| Replay/backfill side effects | Replay can rebuild from raw/enriched and optionally publish derived topics. | Incorrect replay options can duplicate downstream signals/alerts. | Medium | Keep replay controlled/admin-only, default publish off, and expose replay coverage/window clearly. |
| Ordering assumptions | Multiple Kafka partitions and derived topics are used. | Cross-resource or cross-principal ordering is not guaranteed. | Medium | Avoid UI claims that imply global ordering; sort by event time and show source partition/offset. |

Correctness guarantees and limits:

- Guaranteed: at-least-once processing when source offsets are committed only after downstream success.
- Not guaranteed: exactly-once delivery to destination topics.
- Not guaranteed: global ordering across partitions or topics.
- Replay guarantee is limited by raw/enriched topic retention and deterministic derived IDs.
- Audit completeness is not guaranteed when source audit retention expires before ingestion or when lag exceeds retention window.

## 2. Storage Risks

| Risk | Evidence in current repo | Impact | Priority | Mitigation |
|---|---|---|---|---|
| SQLite growth | Persistence stores enriched payload JSON and uses WAL mode; local disk exhaustion was observed. DB size, WAL size, free disk bytes, configured DB max, cleanup state, checkpoint state, and storage status are now exposed in health/metrics and surfaced in the landing page and Welcome tab. | Forwarder can still fail if operators ignore the new storage signals or retention windows are too large. | High | Review the new Prometheus storage alerts, then tune thresholds and retention windows against expected ingest volume. |
| Retention config not operationally visible enough | `cleanup_expired()` runs in the periodic maintenance path and now records last cleanup time and deleted row count. | Operators can still choose retention windows that are unsafe for real ingest volume. | Medium | Add alerting and retention sizing guidance based on observed ingest rates. |
| Single local DB | SQLite path is `/var/lib/auditlens/auditlens.db` in a Docker named volume. | Loss of the Docker volume removes API/search/export state until replay rebuilds. | Medium | Document backup/replay procedure; expose "persistence lost/rebuilt" status; keep Kafka raw retention assumptions visible. |
| SQLite write bottleneck | Forwarder persists enriched events and derived artifacts synchronously in processing path. | High audit volume can slow processing and increase source lag. | High | Batch SQLite writes or move persistence to a production store before customer scale. |
| WAL file expansion | SQLite uses `PRAGMA journal_mode=WAL`; the forwarder now performs startup and periodic WAL checkpoints and exposes checkpoint state. | WAL can still grow too quickly under sustained write pressure or if checkpointing stalls. | Medium | Alert on WAL size growth and checkpoint failure, not just on DB file size. |

SQLite operating limits:

- Suitable for single-instance, single-customer foundation deployments.
- Unsafe as the long-term store for high-volume audit logs, multi-user analytics, or HA requirements.
- Breaks operationally when DB/WAL growth threatens disk, write latency increases consumer lag, or replay rebuild time exceeds source retention.
- Migration direction should be Postgres or an equivalent managed transactional store first. Search/lakehouse systems should be introduced only when query requirements exceed indexed relational storage.

## 3. Schema Risks

| Risk | Evidence in current repo | Impact | Priority | Mitigation |
|---|---|---|---|---|
| Forwarder/dashboard schema drift | Welcome tab expected health fields under `details`; forwarder emits them top-level. | Dashboard crash or misleading empty sections. | High | Keep dashboard behind normalization adapters and add contract tests using real `/health` payload shape. |
| No enforced event schema | Normalized/enriched schema is defined in code, not enforced by Schema Registry by default. | Producers/consumers can drift silently. | High | Publish JSON Schemas for `audit.raw.v1`, `audit.normalized.v1`, `audit.enriched.v1`, signals, alerts, and DLQ. |
| Dashboard fallback extraction from `data_json` | `dashboard/data/transformations.py` extracts fields from raw JSON as fallback. | UI may disagree with forwarder-normalized fields. | Medium | Move display-critical derivations into forwarder schema; keep UI transforms presentation-only. |
| Mixed field names | Current code uses both `methodName` and proposed `method`, `resourceName` and `authzResourceName`, `principal` and `principal_normalized`. | Query bugs and inconsistent exports. | Medium | Define canonical names and keep compatibility aliases until v2. |
| Silent UI defaults | Malformed health sections now default to `{}` or `[]`. | UI may omit data without showing why. | Medium | Show "health payload missing coverage fields" warning when status is healthy but normalized sections are empty. |

Schema governance risks:

- Current contracts are mostly code-defined; they need explicit JSON Schemas.
- Backward-compatible changes should be additive and nullable.
- Field renames, removals, type changes, and semantic changes require new topic/schema versions.
- Schema Registry can remain optional for local development but should be required for customer/product mode.
- CI should validate representative payloads for health, raw, normalized, enriched, signals, alerts, and DLQ.

## 4. Performance Risks

| Risk | Evidence in current repo | Impact | Priority | Mitigation |
|---|---|---|---|---|
| Streamlit rerun model | Dashboard script reruns on interactions and uses session/cache state. | UI latency and inconsistent state under concurrent use. | Medium | Keep Streamlit for internal/single-user use; build API-backed UI for customer multi-user usage. |
| Direct Kafka reads from dashboard | `dashboard/data/kafka_consumer.py` reads recent offsets and creates DataFrames. | UI performance depends on Kafka partitions, event size, and network latency. | High | Route dashboard search through API/persistence for product use. |
| Large DataFrame rendering | Dashboard transforms, deduplicates, filters, and renders pandas DataFrames. | Browser and server memory spikes. | Medium | Enforce page sizes, server-side filtering, and API pagination. |
| Duplicate transformations | Forwarder flattens/classifies; dashboard extracts additional fields from `data_json`. | Wasted CPU and inconsistent outputs. | Medium | Centralize normalization in forwarder and remove UI-side fallback logic gradually. |
| Batch flush latency | Forwarder flushes producer with 30s timeout before offset commit. | Destination Kafka slowdown directly increases processing latency. | Medium | Track flush latency and queue depth; add alerts for produce latency/failures. |

Cost and scaling tradeoffs:

- Kafka-read dashboard path has low implementation cost but high operational cost: duplicate clients, repeated partition scans, local DataFrame transformations, and inconsistent access control.
- API-read dashboard path adds persistence/indexing cost but centralizes RBAC, audit logging, pagination, and query consistency.
- Replay consumes source/destination Kafka read capacity and CPU; broad replay from earliest should be treated as a controlled maintenance operation.
- SQLite is low-cost until write throughput, retention, or concurrency grows; then operational cost appears as lag, disk pressure, and manual recovery.

SLO targets to operationalize:

| Metric | Target | Page/alert threshold |
|---|---:|---|
| Consumer lag | < 10,000 records sustained | > 50,000 for 10 minutes or monotonically increasing for 30 minutes. |
| Visibility delay p50 | < 30 seconds | > 2 minutes. |
| Visibility delay p95 | < 5 minutes | > 15 minutes. |
| DLQ rate | < 0.1% | > 1% for 10 minutes. |
| Persistence write failures | 0 sustained | Any sustained non-zero failure. |
| Replay 24h rebuild | < 60 minutes for foundation-scale deployment | Cannot complete before source/destination retention risk. |

## 5. UX Risks

| Risk | Evidence in current repo | Impact | Priority | Mitigation |
|---|---|---|---|---|
| Misleading healthy state | `/health` can be healthy while lag is high or dashboard has no recent rows. | Operators may assume complete audit coverage. | High | Separate "runtime healthy" from "audit coverage current" in UI and landing page. |
| Delayed visibility | Health exposes freshness but dashboard uses time filters on sampled events. | Users may think no events exist when events are delayed or older than filter window. | Medium | Show forwarder freshness and source lag prominently in dashboard header. |
| Landing status is shallow | Landing `/status` checks HTTP reachability only. | Green status can hide auth, lag, data, or persistence problems. | Medium | Add lightweight semantic summary from `/health` on landing page. |
| Grafana login/default credentials | Installer now generates `GF_SECURITY_ADMIN_PASSWORD` and Grafana startup refuses missing or `admin` values. | Existing stale secret files can still break startup until regenerated. | Medium | Regenerate `.secrets` after upgrading older local setups and keep the password out of logs. |
| API/dashboard mismatch | Dashboard reads Kafka; API reads persistence or memory. | Different surfaces can return different records/counts. | Medium | Make API the canonical dashboard data path for product mode. |

Streamlit exit triggers:

- Concurrent use by multiple teams.
- Need for dashboard login, RBAC, or scoped access.
- Need for audited exports through the UI.
- Search must cover historical persisted records, not sampled Kafka records.
- Common dashboard searches exceed 3 seconds p95.
- Dashboard and API return inconsistent counts for the same filters.

## 6. Security Risks

| Risk | Evidence in current repo | Impact | Priority | Mitigation |
|---|---|---|---|---|
| Local ports exposed | Default Compose now binds forwarder, dashboard, Grafana, Prometheus, Loki, and landing to `127.0.0.1`. | Exposure risk remains when operators override port bindings or deploy behind shared hosts without ingress controls. | Medium | Keep localhost-only defaults and document any non-local exposure as an explicit hardening decision. |
| Prometheus admin API enabled | Default Compose no longer enables Prometheus admin API. | Risk remains if operators re-enable it or expose Prometheus beyond localhost. | Medium | Keep admin API off by default and require explicit troubleshooting-only override. |
| Dashboard lacks product auth | Streamlit dashboard access is not protected by AuditLens API auth. | Anyone with dashboard access can view audit data. | High | Put dashboard behind auth or make it API-backed with RBAC. |
| Sensitive audit data in UI/export | Audit data includes principals, IPs, API key events, resource names. | Compliance/privacy exposure. | High | Add masking policies, export audit review, and configurable redaction. |
| Secrets in Compose expansion | Full `docker compose config` expands `.secrets`. | Accidental terminal/log leakage. | Medium | Keep docs recommending `docker compose config --quiet`; avoid printing env dumps. |
| Logs may contain principals/IPs | Forwarder logs anomaly principals and source IPs. | Sensitive metadata can leak through logs. | Medium | Add configurable PII redaction for logs. |

## 7. Reliability Risks

| Risk | Evidence in current repo | Impact | Priority | Mitigation |
|---|---|---|---|---|
| Single instance only | No HA/multi-instance coordination by design. | Instance outage pauses ingestion and increases lag. | High | Document single-instance limits; add HA design before customer-critical deployments. |
| Container restart loses memory buffers | API has in-memory buffers in `ApiState`. | Recent API fallback data disappears on restart. | Medium | Treat persistence as required for product mode; show fallback mode clearly. |
| Dependency availability | Source Kafka, destination Kafka, SQLite volume, dashboard Kafka access, Grafana/Prometheus are all runtime dependencies. | Partial failures can produce inconsistent surfaces. | High | Add per-dependency readiness and user-facing degraded states. |
| Read-only container with writable volume | Forwarder root FS is read-only and SQLite uses mounted volume. | Good security posture but sensitive to volume permissions. | Medium | Keep permission preflight and add runtime permission diagnostics. |
| Bootstrap validation depends on network | Installer checks DNS/TCP/Kafka metadata. | Private networking or VPN mismatch can block setup. | Medium | Improve private networking diagnostics and document required egress paths. |

## 8. Mitigations

High priority:

- Keep the new SQLite storage alerts enabled and tune the thresholds to the actual disk budget for each environment.
- Enforce or clearly schedule SQLite retention cleanup.
- Keep Prometheus admin API disabled by default.
- Protect dashboard access or route dashboard through authenticated API.
- Make API + persistence the only product-mode query path.
- Add explicit "coverage current/stale/partial" state separate from "runtime healthy".
- Add schema contract tests for health and event payloads.
- Require Schema Registry validation in customer/product mode.
- Move dashboard search from direct Kafka reads to API/persistence for product mode.

Medium priority:

- Add server-side pagination and strict row limits to dashboard views.
- Add deterministic IDs for all generated signals/alerts.
- Add UI warnings when normalized health sections are missing.
- Tune WAL checkpoint cadence based on observed write load and WAL growth.
- Add log redaction options for principals, IPs, and resource names.
- Add replay dry-run/preview output before rebuild operations.

Low priority:

- Improve landing page with semantic health summary.
- Add richer onboarding hints for interpreting lag and freshness.
- Add documented maintenance commands for SQLite inspection and cleanup.
- Keep MCP/schema watcher isolated as future profiles until core product hardening is complete.

## 9. Operator Playbooks

### Lag spike

Detection signal:

- `/health` shows rising `consumer_lag` or `consumer_lag_by_partition`.
- `/metrics` shows sustained lag growth or falling processing rate.
- Freshness age increases while service status remains `healthy`.

Root cause possibilities:

- Destination Kafka produce latency or auth failures.
- SQLite write slowdown or disk pressure.
- Poison-event retry loop before successful DLQ isolation.
- Source traffic spike beyond single-instance processing capacity.

Exact operator steps:

1. Check `/health` freshness, lag, persistence, and recovery sections.
2. Check forwarder logs for produce failures, persistence errors, or repeated event-processing exceptions.
3. Check destination Kafka reachability and producer delivery error metrics.
4. Check SQLite DB size, WAL size, and free disk space.
5. If lag is caused by a poison event, confirm the event is isolated to DLQ before resuming normal processing.
6. If lag is caused by sustained volume, reduce UI load and plan a bounded replay/rebuild or scale-out redesign rather than repeated restarts.

Recovery validation:

- `consumer_lag` trends down.
- Freshness age returns within SLO.
- No sustained produce or persistence errors remain.
- Coverage reflects current ingestion, not stale cache only.

### DLQ spike

Detection signal:

- `/metrics` shows a sharp increase in DLQ writes or parse/processing failures.
- `/health` remains up, but processed records and successful derived outputs diverge.

Root cause possibilities:

- Upstream audit payload shape change.
- Bug in normalization, classification, or persistence serialization.
- Schema drift between current code and retained replay/raw records.

Exact operator steps:

1. Inspect representative DLQ records and group by reason.
2. Determine whether the failure is parse-time, transform-time, persistence-time, or produce-time.
3. Compare failing payload shape to current normalized/enriched assumptions.
4. If the issue is a code regression, stop broad replay/publish operations until the defect is fixed.
5. If the issue is an upstream schema change, add a compatibility handler before resuming normal processing.
6. Track the affected time window so a targeted replay can rebuild missing derived state later.

Recovery validation:

- DLQ rate returns to baseline.
- New incoming records process successfully.
- Targeted replay of the affected window completes without repeating the same DLQ reason.

### SQLite disk full

Detection signal:

- Forwarder logs show SQLite write failures or inability to open/create the DB.
- `/health` persistence section degrades.
- Host disk or Docker volume free space is exhausted.

Root cause possibilities:

- Retention cleanup not running or not deleting enough data.
- WAL growth exceeds checkpointing/cleanup.
- Audit ingest volume exceeds single-instance SQLite limits.

Exact operator steps:

1. Measure free disk, DB file size, and WAL file size.
2. Stop assuming the system is safe just because the process is running; persistence failure changes product coverage immediately.
3. Free disk space or rotate/move the volume as needed.
4. Run or verify retention cleanup and WAL checkpointing.
5. If persistence is corrupted or lost, preserve raw Kafka evidence and rebuild from replay after restoring writable storage.
6. Review export/search expectations because recent API data may be incomplete during the incident.

Recovery validation:

- SQLite opens and writes succeed again.
- `/health` reports persistence healthy.
- New enriched events, denial summaries, and alerts are persisted.
- Replay of the affected window restores missing control-plane state.

### Replay failure

Detection signal:

- Replay status remains in-progress too long, exits with failure, or processed/error counts diverge unexpectedly.
- `/health` recovery or replay fields show failure state.

Root cause possibilities:

- Source evidence retention expired for part of the requested window.
- Replay code hit the same normalization/persistence bug as live ingest.
- Publish replay generated duplicate conflicts because IDs were not deterministic.
- Destination Kafka or persistence target was unavailable during replay.

Exact operator steps:

1. Confirm requested replay source, window, and mode: dry-run vs publish.
2. Check whether the requested source data still exists in Kafka retention.
3. Inspect replay logs for the first failing record class, not just terminal summary output.
4. If the failure is code-related, fix the defect and rerun a dry-run replay first.
5. If the failure is storage-related, restore destination availability before any publish replay.
6. Compare rebuilt counts to expected source counts before declaring recovery complete.

Recovery validation:

- Replay completes with bounded failure count.
- Rebuilt persistence rows and derived outputs match the requested window.
- Alerts/signals do not multiply unexpectedly for unchanged evidence.
- `/health` shows replay complete and recovery status current.
