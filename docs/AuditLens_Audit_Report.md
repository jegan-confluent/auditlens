# AuditLens System Audit Report

## 1. System Overview

AuditLens is currently a single-instance, Kafka-native audit processing system for Confluent Cloud audit logs.

Implemented components:

| Component | Implementation | Current role |
|---|---|---|
| Forwarder | `audit_forwarder.py` in `auditlens-forwarder` container | Consumes source audit events, writes canonical Kafka topics, classifies events, generates alerts/signals, exposes API/health/metrics. |
| Destination Kafka topics | Configured in `docker-compose.yml` and `src/product/bootstrap.py` | Product contract topics: raw, normalized, enriched, denial signals, high-risk signals, alerts, DLQ. |
| SQLite persistence | `src/product/persistence.py`, mounted at `/var/lib/auditlens/auditlens.db` | Durable recent product/API storage for enriched events, high-risk events, denial summaries, alerts, and API audit logs. |
| Dashboard | Streamlit app under `dashboard/` | Reads Kafka topics directly and renders audit trail, failures, security, alerts, identity, export, and Welcome views. |
| Landing page | `scripts/landing_page.py`, `landing` Compose service | Local-only single entry point on `http://localhost:8088` with links and service status. |
| Observability | `/health`, `/metrics`, Prometheus, Grafana, Loki/Promtail | Runtime health, Prometheus metrics, dashboards, and log collection. |
| Bootstrap installer | `setup.sh`, `scripts/bootstrap_auditlens.py`, `src/product/bootstrap.py` | Template/interactive setup, connectivity validation, topic validation/creation, persistence preflight, startup validation. |

Data flow implemented today:

1. Source audit events are consumed from `AUDIT_TOPIC`, default `confluent-audit-log-events`.
2. Forwarder writes replay-safe raw wrappers to `audit.raw.v1`.
3. Forwarder flattens CloudEvents and writes normalized records to `audit.normalized.v1`.
4. Forwarder classifies and enriches records, then writes to `audit.enriched.v1`.
5. Denial aggregation writes summaries to `audit.signals.denials.v1`.
6. High-risk records are written to `audit.signals.highrisk.v1`.
7. Operator alerts are written to `audit.alerts.v1`.
8. Parse/processing failures are written to `audit.dlq.v1`.
9. Selected enriched/signals/alerts are persisted to SQLite for API search/export.
10. Dashboard reads destination Kafka topics directly; API reads SQLite first and falls back to in-memory recent cache.

Implemented vs implied:

- Implemented: Kafka consumer-group offset model, at-least-once processing, raw/normalized/enriched topics, high-risk signals, denial aggregation, SQLite persistence, API auth/RBAC/export controls, replay endpoint, landing page.
- Partially implemented: Kubernetes manifests and bootstrap renderers exist, but runtime testing has focused on Docker Compose.
- Future/non-core: MCP and schema watcher are present under Compose `profiles: ["future"]`; they are not core foundation runtime.
- Not implemented: high availability, multi-instance coordination, Flink/Tableflow default path, full decision engine, production-grade long-term search store.

### Control Plane vs Data Plane

Data plane:

- `auditlens-forwarder`
- Source audit Kafka consumer
- Destination Kafka producer
- Canonical Kafka topics: raw, normalized, enriched, signals, alerts, DLQ
- Classification, flattening, denial aggregation, high-risk signal generation
- Offset commit and replay/rebuild mechanics

Control plane:

- Forwarder API v1 on the metrics/API port
- SQLite product persistence
- Dashboard
- Landing page
- Export, health, freshness, lag, replay status, and API audit log surfaces

Product-mode source of truth:

- API + persistence must be treated as the single source of truth for search, export, UI, and operator investigation.
- Kafka topics are the evidence backbone and replay source, not the direct UI query layer.
- The current Streamlit dashboard still reads Kafka directly. That is acceptable for local/internal foundation testing, but not acceptable for product mode because it bypasses API auth, RBAC, export controls, API audit logging, and persistence coverage semantics.
- Product direction should be: dashboard -> API -> persistence, with Kafka used by the forwarder and controlled replay/rebuild paths.

## 2. Current Capabilities

Ingestion:

- Consumes source audit logs with `enable.auto.commit=false`.
- Commits offsets only after processing, persistence, Kafka produce, and producer flush succeed.
- Emits canonical topics defined in Compose and bootstrap constants.
- Writes DLQ records for JSON parse and processing failures.

Classification and signals:

- Central classification lives in `src/classification/criticality.py`.
- Auth/authz failures are mostly signal-driven rather than elevated per event.
- Destructive and sensitive methods are classified through explicit method sets and fallback patterns.
- Denial aggregation groups by principal, method, and resource over a configurable time window.
- High-risk records and operator alerts are produced for critical/destructive events and selected anomalies.

### Decision Engine

Current implementation:

- AuditLens does not yet implement a standalone decision engine.
- The current pipeline produces enriched events, denial summaries, high-risk signals, and operator alerts.
- Outputs are rule-based and heuristic, not ML-driven.
- Classification is deterministic for a given input event and rule set.
- Denial aggregation is deterministic for a given grouping key and window.
- Confidence today is policy confidence, not model confidence.

Operational meaning:

- `audit.enriched.v1` is the classified event stream.
- `audit.signals.denials.v1` and `audit.signals.highrisk.v1` are evidence-derived signal streams.
- `audit.alerts.v1` is the operator-facing alert stream.
- These outputs are explainable because they come from explicit method/resource/action rules and stable grouping logic.

Requirements before this becomes a real decision engine:

- Idempotency: signal and alert IDs must be deterministic so replay and duplicate delivery do not create divergent operator state.
- Replay safety: rebuild from raw evidence must regenerate the same outputs for the same policy version, or emit a clearly versioned policy boundary.
- Explainability: every alert must retain source event IDs, grouping keys, rule reason, and policy version.
- Separation of concerns: signals are evidence-derived observations; decisions are operator-action recommendations with lifecycle and feedback, which are not implemented yet.
- Determinism boundary: any future probabilistic or ML layer would require model versioning, confidence calibration, and fallback rules; none of that exists in the current repo.

Persistence and API:

- SQLite tables exist for `enriched_events`, `high_risk_events`, `denial_summaries`, `alerts`, `api_audit_log`, and `runtime_meta`.
- Persistence uses upsert by event/summary/alert IDs.
- API search/export reads persistence when healthy and falls back to in-memory buffers.
- API auth, roles, scope filtering, export limits, and API audit logging exist in the forwarder.

Health and metrics:

- `/health` and `/api/v1/health` expose top-level `freshness`, `coverage`, `offset_recovery`, `recovery`, `observability`, and `components`.
- `/metrics` exposes Prometheus-format counters/gauges for processing, lag, commits, persistence, API security, replay, delivery, signals, and data quality.
- Health JSON serialization now normalizes non-string dict keys before `orjson.dumps`.

Dashboard:

- Streamlit dashboard uses tabs for audit trail, failures, deletions, API keys, security, details, analytics, time insights, export, security alerts, topic-identity, and identity activity.
- Dashboard data path reads Kafka directly from `audit.enriched.v1` and signal topics.
- Welcome tab now normalizes current and legacy forwarder health payload shapes safely.

Landing page:

- Local-only HTTP server binds inside container to `0.0.0.0` and host maps to `127.0.0.1:8088`.
- Shows Dashboard, Grafana, Prometheus, Health, and Metrics links.
- `/status` probes internal service URLs and returns `ok`/`down`.
- Displays non-secret setup metadata and destination topic names.

What is working today based on code and recent runtime validation:

- `http://localhost:8088` returns HTML.
- `http://localhost:8088/status` returns service status JSON.
- `http://localhost:8003/health` returns valid JSON with top-level health sections.
- `http://localhost:8003/metrics` returns Prometheus text.
- `http://localhost:8503` returns Streamlit shell and dashboard container runs.
- Dashboard Welcome tab no longer crashes on current health schema.

## 3. Key Fixes Observed

| Fix | What broke | Why it broke | How it was fixed | Remaining risk |
|---|---|---|---|---|
| Landing page introduction | User had multiple local URLs and no single entry point. | Setup printed separate URLs; no local launch surface existed. | Added `scripts/landing_page.py` and `landing` Compose service on `127.0.0.1:8088`. | Landing status probes are shallow; they show HTTP reachability, not semantic readiness. |
| Landing service not initially reachable | `localhost:8088` refused connection. | Existing Compose stack was started before the new `landing` service existed. | Recreated/started Compose services and validated host port binding. | Setup reruns must recreate changed services reliably. |
| Prometheus link unreachable | Landing linked to `localhost:9090`, but host curl initially failed. | Prometheus container was running, but host-facing access was not effective in the current Compose state. | Prometheus attached to `frontend-network` and container recreated; host binding verified. | Prometheus admin API is enabled and exposed locally; acceptable for local use, risky beyond localhost. |
| Health endpoint serialization | Forwarder could crash on `orjson.dumps(payload)` with non-string dict keys. | `orjson` requires dict keys to be strings. | `_send_json()` now recursively converts keys to strings and falls back to a minimal serialization-error response. | Fallback hides details by design; operators need logs/metrics to diagnose serialization defects. |
| Dashboard health schema mismatch | Welcome tab crashed with `AttributeError: 'str' object has no attribute 'get'`. | Dashboard assumed `forwarder_health["details"]` was a dict; current health fields are top-level and error details may be strings. | Added `normalize_forwarder_health()` with type guards and priority: nested details, payload wrapper, top-level, default. | Other dashboard tabs still perform substantial local transformations and may have independent schema assumptions. |
| Port validation during rerun | Installer failed when AuditLens services were already running on expected ports. | Port validation treated current AuditLens-bound ports as generic conflicts. | Setup detects existing Compose service port bindings and allows those ports during rerun. | External process conflicts are still correctly rejected; Compose service renames could break detection. |
| Persistence preflight | Runtime failed with SQLite open/write errors after setup. | Docker volume ownership and later disk exhaustion were not fully caught by a simple `touch` preflight. | Installer now fixes volume ownership once and uses a real SQLite create/insert/commit/delete preflight. | Disk exhaustion remains possible because retention/cleanup is not automatically enforced at startup. |

## 4. Streamlit Usage Analysis

Why Streamlit is used:

- Fast implementation of interactive tables, filters, charts, and tabs.
- Low frontend engineering overhead.
- Useful for internal operator exploration and early product validation.

Repo structure:

- `dashboard/app.py` owns app layout, sidebar filters, tabs, and session state.
- `dashboard/tabs/*` contains tab-specific rendering.
- `dashboard/data/kafka_consumer.py` reads Kafka and returns pandas DataFrames.
- `dashboard/data/transformations.py` enriches and reshapes records for display.
- `dashboard/components/*` contains reusable UI helpers.

Rerun model implications:

- Streamlit reruns the script on UI interaction; cached functions reduce repeated Kafka reads but do not eliminate rerun cost.
- `@st.cache_data(ttl=15)` limits Kafka fetch frequency but can show stale data for up to 15 seconds.
- Session state must be initialized before use. Running `python /app/app.py` directly fails because Streamlit session state is unavailable; the app must run via `streamlit run`.

Session state risks:

- Direct session-state assumptions can crash outside Streamlit runtime.
- UI state and cached data are process-local; restart loses dashboard state.
- Multiple users share server process and cached data patterns, not isolated per tenant.

Performance limitations:

- Dashboard reads Kafka directly, converts to DataFrame, deduplicates, filters, and enriches in the UI process.
- Large records and high partition counts increase Streamlit rerun latency.
- Table rendering and pandas transformations will become the bottleneck before Kafka.
- Dashboard polling recent offsets is not a durable query model.

When Streamlit will break at scale:

- Many concurrent users.
- Large audit volumes requiring historical search.
- Multi-tenant access control.
- Strict RBAC/audited UI access.
- Long-running analytical queries.
- Browser rendering of large DataFrames.

Streamlit exit criteria:

- More than one team uses the dashboard concurrently for incident response.
- Dashboard access must be role-gated or scoped by organization/environment/cluster.
- Export actions must be audited from the UI.
- Search must cover more than sampled recent Kafka records.
- UI response time exceeds 3 seconds p95 for common searches.
- Dashboard and API disagree on counts or returned records.

Target replacement architecture:

- Browser UI backed only by AuditLens API v1/v2.
- API enforces auth, RBAC, scope filtering, export controls, and audit logging.
- Persistence/search layer provides indexed query, pagination, and retention controls.
- Kafka remains the data-plane evidence backbone, not the interactive query path.

## 5. Performance Analysis

Data fetching patterns:

- Forwarder processes batches up to 5000 messages.
- Dashboard fetches latest offsets from Kafka partitions and pulls up to configured max events.
- Dashboard uses static consumer group IDs but manual assignment to recent offsets.
- API search uses SQLite when healthy, otherwise recent in-memory buffers.

Transformation location:

- Core flattening/classification happens in the forwarder.
- Dashboard still performs additional field extraction from `data_json`, display formatting, email cache enrichment, and filtering.
- This split creates duplicate logic and schema drift risk.

Expected bottlenecks:

- SQLite write amplification under sustained high audit volume.
- SQLite DB growth and WAL growth.
- Streamlit DataFrame transformations and rendering.
- Dashboard direct Kafka reads under high partition counts.
- Forwarder synchronous batch flush and offset commit latency.

Impact of large audit volumes:

- Consumer lag can accumulate quickly if destination Kafka or persistence slows down.
- Dashboard recent-window sampling may miss relevant events.
- In-memory API buffers cap visibility regardless of Kafka history.
- SQLite can become disk-bound; disk exhaustion was already observed in local testing.

Lag visibility vs actual processing:

- Health exposes `consumer_lag` and per-partition lag.
- Lag shows source consumption backlog, not complete product coverage.
- A `healthy` status can coexist with large lag; operators must interpret `coverage` and `freshness` separately.

Cost and performance tradeoffs:

- Direct Kafka reads by the dashboard are cheap to build but expensive operationally: every UI instance creates Kafka clients, reads partitions, performs local transforms, and bypasses product access control.
- API/persistence reads cost more upfront because storage and indexing must be operated, but they centralize auth, audit logging, pagination, retention, and query consistency.
- Replay is CPU, network, and Kafka-read intensive. It should be controlled, scoped by time window where possible, and should not publish derived topics by default.
- SQLite has low operational cost for single-instance use, but cost shifts to operational risk once DB size, WAL growth, or write latency becomes material.

## 6. Data Modeling Gaps

Current state:

- Raw evidence is preserved in `audit.raw.v1`.
- Normalized/enriched records include schema fields such as `schema_version`, `pipeline_stage`, and `event_contract_version`.
- Flattening extracts common CloudEvent fields, principal fields, auth metadata, authz fields, request metadata, CRN-derived IDs, result status/message, and classification fields.

Gaps:

- No formal canonical schema document existed before this audit.
- Normalized and enriched schemas are code-defined, not enforced by Schema Registry by default.
- Dashboard still has fallback extraction from raw `data_json`, indicating incomplete trust in forwarder-normalized fields.
- Schema drift already occurred: dashboard expected health fields under `details`, while forwarder emitted them top-level.
- Change-tracking fields such as before/after diffs and changed fields are not consistently modeled.
- Actor and resource identity are partially normalized but not fully canonical across all event families.
- `environment` vs `environment_id` naming is not fully standardized across UI, persistence, and proposed product schema.

Schema governance requirements:

- Each product topic must have an explicit schema contract: `audit.raw.v1`, `audit.normalized.v1`, `audit.enriched.v1`, `audit.signals.denials.v1`, `audit.signals.highrisk.v1`, `audit.alerts.v1`, `audit.dlq.v1`.
- Additive nullable fields are backward-compatible.
- Renaming, removing, changing type, or changing semantics of existing fields is breaking and requires a new topic/schema version.
- Raw events remain immutable; schema evolution applies only to wrapper metadata and derived records.
- Schema Registry should be optional during local bootstrap but required in customer/product mode.
- Dashboard/API contract tests must use real payload samples for health and event records.

## 7. Audit Correctness Guarantees

Delivery semantics:

- Current forwarder semantics are at-least-once.
- `enable.auto.commit=false`; offsets are committed only after downstream processing, persistence writes, Kafka produce calls, and producer flush succeed.
- If the process crashes after successful downstream writes but before offset commit, events may be replayed.

Duplication handling:

- SQLite enriched/high-risk/alert tables use primary keys and upsert behavior for known IDs.
- Kafka destination topics may contain duplicates after crash, rebalance, or replay.
- Denial summaries and alerts require deterministic IDs to be fully idempotent; any UUID-based generated alert can duplicate under replay.

Ordering:

- Ordering is only meaningful within a single Kafka partition.
- No global ordering is guaranteed across partitions, topics, resources, or principals.
- UI and exports must sort by event time and retain source partition/offset for evidence traceability.

Replay correctness:

- Raw Kafka records are the authoritative rebuild evidence.
- Replay can rebuild persistence from raw or enriched topics.
- Replay correctness depends on raw topic retention, schema compatibility, idempotent persistence writes, and deterministic signal/alert IDs.
- Replay should default to rebuilding persistence without republishing derived topics unless explicitly requested.

Audit completeness limitations:

- AuditLens cannot recover source audit events that have expired from the source audit cluster and were never ingested into raw evidence.
- A healthy forwarder does not prove full audit coverage.
- Coverage depends on source lag, raw topic retention, destination topic retention, persistence health, replay state, and UI/API query path.

## 8. SLO Targets

These are proposed foundation targets for a single-instance deployment. They should be exposed in health and alerting before customer use.

| Measure | Target | Breach condition |
|---|---:|---|
| Consumer lag | < 10,000 records sustained | High if > 50,000 for 10 minutes or increasing for 30 minutes. |
| Visibility delay p50 | < 30 seconds from event time to enriched visibility | Medium if > 2 minutes. |
| Visibility delay p95 | < 5 minutes from event time to enriched visibility | High if > 15 minutes. |
| DLQ rate | < 0.1% of processed events | High if > 1% for 10 minutes. |
| Persistence write failure rate | 0 sustained | High on any sustained non-zero failures. |
| Replay throughput | Rebuild last 24 hours within 60 minutes for foundation-scale clusters | High if replay cannot keep pace with source retention window. |
| Health endpoint latency | < 500 ms p95 locally | Medium if > 2 seconds. |

## 9. Storage Strategy

SQLite is acceptable for the current single-instance foundation, but it is not a long-term customer analytics store.

Current SQLite role:

- Recent API search/export.
- High-risk event lookup.
- Denial summary lookup.
- Alert lookup.
- API audit log.
- Runtime metadata.

Practical limits:

- Single writer bottleneck.
- Local disk/WAL growth.
- No native horizontal scaling.
- Manual backup/restore unless wrapped by platform tooling.
- Risk increases sharply with high-volume audit clusters, long retention, or many concurrent API/UI queries.

When SQLite breaks:

- DB or WAL growth threatens disk capacity.
- Persistence write latency increases source lag.
- Dashboard/API needs multi-user historical search.
- Customer requires HA or multi-instance runtime.
- Retention requirements exceed local disk planning.

Migration direction:

- Keep Kafka as evidence backbone.
- Move product persistence to a managed transactional/query store for product mode.
- Candidate direction: Postgres for foundation customer deployments; search/analytics store only if query patterns require full-text/high-cardinality analytics.
- Tableflow/lakehouse is not justified for the current foundation unless long-term analytical retention and batch/audit reporting become primary requirements.

## 10. Replay Strategy

Current replay model:

- Replay can rebuild derived product state from Kafka evidence.
- The credible replay sources are `audit.raw.v1` first and `audit.enriched.v1` second.
- Raw replay is the authoritative rebuild path because it preserves original evidence and reruns normalization, classification, and signal generation.
- Enriched replay is a recovery shortcut, not the preferred correctness path, because it skips normalization defects fixed after the original run.

Replay modes that should be supported operationally:

- Full replay: rebuild persistence and derived outputs from the earliest retained evidence.
- Partial replay: rebuild only a bounded time window, tenant scope, or affected topic partition range.
- Dry-run replay: process and validate counts, errors, and would-be outputs without publishing derived topics or mutating persistence.
- Publish replay: repopulate persistence and, when explicitly enabled, republish derived signals and alerts.

Replay isolation requirements:

- Dry-run must be the default for investigation and verification.
- Publish replay must be admin-scoped and explicit because it can regenerate signals and alerts.
- Replay should record start time, end time, requested window, source topic, processed counts, failure counts, and whether derived topics were published.
- Replay status should remain visible in `/health` and `/metrics` until completion.

Replay impact on signals and alerts:

- Without deterministic IDs, replay can create duplicate signal and alert rows even when the underlying event set is unchanged.
- High-risk signals and denial summaries must therefore be keyed from stable evidence attributes plus policy version.
- Operator-facing alerts should carry a replay marker or origin so responders can distinguish real-time generation from rebuild output.

Replay correctness limits:

- Replay cannot recover evidence that aged out of source or destination retention before rebuild.
- Replay preserves correctness only if the same policy version and normalization logic are applied, or the replay explicitly records a new policy version boundary.
- Replay does not provide exactly-once guarantees; it provides deterministic rebuild when IDs, policies, and source evidence are stable.

## 11. Data Lifecycle Model

Current lifecycle:

- Ingestion: source audit events consumed from `confluent-audit-log-events`.
- Hot: recent derived records in destination Kafka topics and SQLite persistence.
- Warm: replay-safe raw wrappers in `audit.raw.v1` and enriched records in `audit.enriched.v1` while retained by Kafka.
- Cold: not implemented as a separate tier in the current repo.
- Delete: currently driven by Kafka retention and partial SQLite cleanup configuration, not by a complete product lifecycle policy.

Implications:

- AuditLens currently has a hot-plus-warm model, not a full lifecycle-managed archive model.
- If SQLite data is pruned and Kafka retention has expired, historical search is gone.
- Compliance retention beyond Kafka plus SQLite windows is not yet implemented.

Required lifecycle policy direction:

- Define explicit retention by data class: raw evidence, enriched records, signals, alerts, API audit logs.
- Separate operator convenience retention from compliance evidence retention.
- Make delete behavior explicit and auditable; silent expiry is not acceptable for compliance-sensitive data.
- Add a cold-storage path before customer deployments require retention beyond Kafka plus relational persistence windows.

Cost implications:

- Keeping everything hot in SQLite and Kafka is operationally simple but does not scale economically or safely for long retention.
- Raw evidence should be the last data class deleted, because it is the only authoritative replay source in the current design.

## 12. Multi-tenant and Isolation Model

Current implementation state:

- AuditLens is explicitly a single-instance, single-customer deployment model.
- API role and scope concepts exist for organization, environment, and cluster filtering.
- Dashboard direct Kafka reads bypass those controls.

Isolation requirements for credibility:

- Organization-level isolation: query results, exports, and alerts must never cross org boundaries.
- Environment-level isolation: lower-scope users should not see unrelated environments in shared organizations.
- Cluster-level isolation: RBAC and query filters must apply consistently to API search, alerts, exports, and replay operations.

Current gaps:

- SQLite is not modeled as a shared multi-tenant store.
- Dashboard direct Kafka access breaks query isolation because Kafka topic readers can see all events available to that credential.
- Export controls only become meaningful when all user-facing access is forced through the API.

Practical conclusion:

- Multi-tenant product mode is not credible until the UI reads only from the API and persistence layer, not directly from Kafka.
- Tenant boundaries must be enforced in persistence queries, export generation, replay scoping, and API audit logs before a shared deployment model is considered.

## 13. Security Hardening

Current security posture:

- Kafka connections use TLS/SASL based on supplied cluster credentials.
- Local secrets are written through bootstrap flows rather than hardcoded in code.
- SQLite persistence stores sensitive audit-derived data locally.
- API auth, RBAC, and export controls exist in the forwarder.

Required hardening areas:

- Encryption in transit: all Kafka, API ingress, and any future external DB connections must require TLS. Local HTTP on localhost is acceptable for developer mode only.
- Encryption at rest: SQLite volume encryption is not handled by AuditLens and must be provided by the host or deployment platform. That limitation should be stated explicitly.
- Audit log integrity: raw evidence is replay-safe only if Kafka retention, ACLs, and topic immutability are controlled. AuditLens itself does not provide cryptographic integrity proofs or tamper-evident storage.
- Audit of audit access: API audit logging exists, but dashboard direct Kafka reads are not captured as product access logs. That is a material control gap.
- Secret hygiene: generated secrets must remain out of Git, out of terminal dumps, and out of `docker compose config` output.

What security reviewers should conclude now:

- AuditLens has a reasonable local foundation posture for a single-customer deployment.
- It does not yet satisfy stronger control requirements around encrypted persistent storage, tamper evidence, or complete auditability of who viewed which audit records.

## 14. Observability and Health

Health endpoint exposes:

- Top-level status, timestamp, version, uptime, processed count, error count, idle seconds, lag, processing rate.
- `freshness`: last enriched event time, ingest time, denial flush time, commit time.
- `coverage`: mode, coverage note, recent API window counts.
- `offset_recovery`: offset model, commit behavior, delivery semantics, duplicate risk.
- `recovery`: replay availability and replay state.
- `observability`: commit counts, rebalance count, restart count, parse errors, DLQ counts, API auth/export counters, replay counters, signal counts, data quality counts.
- `components`: config, consumer, producer, persistence, API auth, replay.

Healthy vs covered:

- `healthy` means runtime conditions are acceptable by current checks.
- It does not mean audit coverage is complete.
- Coverage depends on source lag, persistence state, retention, replay state, API buffers, and dashboard sampling.

Missing or misleading signals:

- No explicit percent coverage against source audit retention.
- No disk-free metric in forwarder health despite SQLite disk exhaustion being observed.
- No SQLite file size/WAL size metric.
- Dashboard may show no recent data while forwarder is healthy because event times are older than UI filter windows.
- Landing `/status` reports HTTP reachability only.

## 15. Testing Strategy

Current test posture:

- The repo has targeted tests for bootstrap validation, landing page behavior, and dashboard health normalization.
- Recent fixes were validated with live `curl`, `docker compose ps`, and targeted pytest runs.
- That is useful, but still narrow relative to the product’s correctness claims.

Required testing layers:

- Schema contract tests: validate raw, normalized, enriched, signal, alert, DLQ, and health payloads against versioned examples.
- Replay validation tests: prove that replay regenerates the same persistence rows, signal IDs, and alert IDs for the same policy version.
- Failure injection tests: Kafka auth failure, destination produce failure, SQLite write failure, disk full, DLQ spike, restart before commit, restart after commit, and replay interruption.
- Load and performance tests: sustained ingest throughput, SQLite write latency under load, lag growth behavior, dashboard/API response time under expected operator query patterns.
- UI/API consistency tests: same filters should return equivalent results once the dashboard is API-backed.

Gap that remains today:

- The repo has correctness-oriented spot tests, not a full production qualification suite.

## 16. UX Evaluation

Landing page:

- Effective as a local entry point.
- Shows useful setup summary and links.
- Does not expose secrets.
- Status cards are easy to understand but shallow.

Dashboard:

- Good breadth of views for exploratory investigation.
- Welcome tab now warns that no visible enriched events should not be treated as full coverage.
- Filters are useful for local exploration but depend on sampled/recent Kafka reads.
- User may confuse dashboard freshness with pipeline completeness.

Potential confusion:

- API health endpoint may require auth while `/health` does not.
- Grafana requires login and may use default credentials unless changed.
- Streamlit dashboard reads Kafka directly rather than via the API, so dashboard and API may disagree.
- The term `healthy` can be over-trusted when lag is high.

## 17. Evolution Roadmap

Phase 1: Hardening (current -> stable)

- Remove dashboard direct Kafka dependency for product mode.
- Enforce schema contracts and add replay correctness tests.
- Close SQLite retention, disk, and cleanup visibility gaps.
- Tighten security posture around dashboard access, Prometheus admin exposure, and audit-of-audit access logging.

Phase 2: Productization

- Make API-first UI the default operator surface.
- Strengthen auth, RBAC, scoped search, and export workflows.
- Move persistence to a more durable indexed relational store once SQLite operating limits are reached.
- Add lifecycle-managed storage classes for hot, warm, and cold retention.

Phase 3: Scale

- Add multi-instance coordination and HA.
- Introduce stronger tenant isolation and shared-deployment controls.
- Add analytics/storage layers only when query, retention, or concurrency requirements exceed the relational product path.
- Evaluate a true decision engine only after deterministic signal, replay, and explainability guarantees are already strong.

## Readiness Documents

Implementation readiness should be checked against these companion documents:

- [Deployment_Prerequisites.md](Deployment_Prerequisites.md)
- [Implementation_Gap_Matrix.md](Implementation_Gap_Matrix.md)
- [Security_Audit_Checklist.md](Security_Audit_Checklist.md)

Important:

- Documentation does not imply implementation.
- The gap matrix is the source of truth for what is implemented, partial, documented only, or missing in the current repo.
- Any readiness claim should be backed by the validation commands in those documents, not by architecture intent alone.

## 18. Summary Assessment

Scores are for the current implementation, not the intended product.

| Area | Score | Assessment |
|---|---:|---|
| Architecture | 6.5/10 | Solid Kafka-native foundation and topic contracts, but dashboard/API data paths are split and future components remain in repo. |
| Reliability | 5.5/10 | At-least-once offset model is sound, but SQLite storage, single-instance runtime, and disk exhaustion risk limit reliability. |
| Observability | 7/10 | Health and metrics are substantially improved; coverage and disk/storage visibility remain incomplete. |
| Product readiness | 5.5/10 | Useful internal foundation. Not customer-ready without retention controls, stronger UI auth, clearer coverage semantics, and production storage strategy. |

Overall assessment:

- AuditLens is beyond a demo: it has real ingestion, classification, signal generation, persistence, API, health, and dashboard surfaces.
- It is still a single-instance foundation, not a production-grade customer platform.
- The strongest part is the Kafka-native forwarder pipeline with explicit offset/produce/commit semantics.
- The weakest part is the product serving layer: Streamlit direct Kafka reads, SQLite growth risk, and incomplete coverage semantics.
