# AuditLens — Deep Audit Report
Generated: 2026-05-15

> **Rules applied:** Read-only. Every finding cites exact file:line or query output. PostgreSQL was unavailable during this audit (container not running) — DB runtime statistics are UNVERIFIED. Schema findings are derived from source code and migrations.

---

## 1. Code Architecture Findings

| # | Severity | File:Line | Finding | Recommendation |
|---|----------|-----------|---------|----------------|
| A1 | 🟠 High | `backend/app/db/models.py:38` | `AuditEvent` has **74 methods** — a god object mixing storage, enrichment logic, and derived property computation. Every `@property` reads from `raw_payload_json` via `json.loads()` on access. | Extract enrichment logic into a stateless `AuditEventEnricher` service. Model should hold columns only. |
| A2 | 🟠 High | `backend/app/main.py:35,55` | `_retention_loop()` is declared `async` and correctly uses `await asyncio.sleep()`. **This is fine** — the static scanner flagged it as `time.sleep()` but it is `asyncio.sleep`. No issue. | N/A — false positive confirmed. |
| A3 | 🟠 High | `backend/app/api/routes/onboarding.py:40,65` | `discover()` uses `httpx.AsyncClient` (correct, async-safe). **But** the static scanner reported `requests.get/post` — those are `httpx.AsyncClient.get/post` methods, not `requests`. False positives. However, `validate_cluster()` at line 142 calls `admin.list_topics(timeout=10)` from `confluent_kafka.admin` — this is a **genuinely blocking call** inside an `async def` on the uvicorn event loop. | Wrap `admin.list_topics()` in `asyncio.get_event_loop().run_in_executor(None, ...)`. |
| A4 | 🟡 Medium | `backend/app/services/backfill_service.py` (1118 lines) | Largest service by far at 1,118 lines — 35% larger than event_service. Contains 5 distinct backfill phases (source, decision, resource, actor, display-name) plus admin state management. | Split into `backfill_phases.py` + `backfill_admin.py`. Already architecturally isolated; splitting is mechanical. |
| A5 | 🟡 Medium | `backend/app/api/routes/admin.py:35`, `backend/app/main.py:64`, `backend/app/services/system_service.py:503` | `API_AUTH_ENABLED` is read from `os.getenv()` at **request time** in 3 separate places outside `get_settings()`. Changes to the env var after startup affect behaviour inconsistently across routes. | Centralise into `get_settings()` / `AuthConfig.from_env()`. Already done in `src/product/auth.py` — extend the same pattern to the FastAPI layer. |
| A6 | 🟡 Medium | `backend/app/api/routes/tableflow.py:25,29,40–42` | `tableflow.py` reads 5 env vars (`CONFLUENT_API_BASE_URL`, `CONFLUENT_CLOUD_API_KEY`, etc.) via raw `os.getenv()` calls inside helper functions that run on every request. No caching, no config object. | Move into `get_settings()` with `@lru_cache`. |
| A7 | 🟡 Medium | `backend/app/db/models.py:92` | `raw_payload_json` stored as SQLAlchemy `Text`. PostgreSQL could store it as `JSONB` enabling `@>` containment, `->>` field extraction, and GIN indexes for payload search. SQLite fallback requires TEXT anyway. | Add a dialect-guarded migration: `JSONB` on Postgres, `TEXT` on SQLite. Gate behind `POSTGRES_JSONB_RAW_PAYLOAD=true`. |
| A8 | 🟢 Low | `backend/app/schemas/event.py` (API output) | `actor_enriched_at` is exposed in the API response and rendered in the EventDetailDrawer as a raw ISO timestamp. This is an internal field (when enrichment ran) not meaningful to end users. | Omit from API response, or rename to `_actor_enriched_at` and exclude from `AuditEventListOut`. |
| A9 | 🟢 Low | Multiple services | `settings_service.py:98` uses `db.query(AppSettings).filter_by()` (legacy SQLAlchemy 1.x `Query` API) while all other services use `select()` (SQLAlchemy 2.x `Core` style). | Migrate to `db.scalars(select(AppSettings).filter_by(...))` for consistency. |
| A10 | ℹ️ Info | Service coupling graph | No circular dependencies detected. Clean layering: routes → services → models. `event_service` is the most depended-upon service (imported by 5 others: `backfill_service`, `admin`, `events` route, `main.py`, `schemas`). This is expected for the primary domain service. | Monitor for further fan-in. Consider a `core_service.py` if event_service grows past 1,000 lines. |

---

## 2. Database Performance Findings

> **Note:** PostgreSQL container was not running during this audit. All findings below are derived from **source code analysis** (models, migrations, query patterns) and are marked accordingly. Runtime statistics (index scan counts, bloat, slow queries) are **UNVERIFIED**.

### 2A. Schema Health

**Tables confirmed from migrations and models:**

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `audit_events` | 52 mapped columns | Primary signal table. `raw_payload_json TEXT` (see A7). No time-based partitioning. |
| `audit_events_noise` | Subset of audit_events schema | Separate table for bulk noise methods; created in migration `0007`. |
| `audit_event_triage` | fingerprint FK + status/actor/note | Tracks per-event investigation state. |
| `audit_event_patterns` | actor/action/resource_name + counts | Pattern suppression. |
| `actor_ip_baseline` | actor + source_ip + occurrence_count | IP anomaly baseline. |
| `resource_catalog` | resource_id/type/name + env + cluster | Aggregated from events. |
| `app_settings` | category + key + value/value_enc | Encrypted KV store. |
| `feedback` | id/type/title/description/email | User feedback; now with 365-day retention. |

**Schema observations (source-derived):**
- `audit_events` has **52 mapped columns** — the widest table. Many are prefixed `_` (private storage mapped via `@property`), which is idiomatic but can confuse raw SQL queries.
- `raw_payload_json` is `TEXT` (not `JSONB`) — correct for SQLite compatibility but prevents server-side JSON operators on PostgreSQL.
- `actor_enriched_at` is `String(64)` storing an ISO timestamp string, not `DateTime` — prevents range queries without casting.
- No partitioning on `audit_events`. At scale this will become the primary performance bottleneck (confirmed via migration `0016_add_attention_time_index.py` suggesting timestamp-range queries are already hot).

**Migration 0015** (`autovacuum_tuning`) explicitly sets:
```sql
ALTER TABLE audit_events SET (autovacuum_vacuum_scale_factor = 0.01, autovacuum_analyze_scale_factor = 0.005);
```
This indicates the team already hit autovacuum lag on this table.

### 2B. Index Analysis (source-derived, runtime stats UNVERIFIED)

Migrations confirm the following indexes exist:

| Migration | Index | Columns | Purpose |
|-----------|-------|---------|---------|
| 0001 | baseline | Various | Timestamp, actor, signal_type, fingerprint |
| 0004 | summary aggregation | `action_category`, `resource_type`, `result` | Dashboard summary queries |
| 0005 | filter partial | `actor`, `action`, `resource_name` (partial) | Filter dropdown population |
| 0006 | drop unused | — | Dropped indexes that were never used |
| 0012 | actor enrichment | `_actor_display_name` | Actor search by display name |
| 0016 | attention time | `(signal_type, timestamp)` | Time-range queries on `attention`/`action_required` events |
| 0019 | actor confidence low | `_actor_confidence` partial | Enrichment backfill target rows |

**Migration 0006 already dropped unused indexes** — good maintenance hygiene. This migration's existence proves the schema has accumulated dead-weight indexes previously.

**Potential missing index (code-derived):**

The `cleanup_retention` function in `event_service.py:710` issues:
```sql
DELETE FROM audit_events WHERE timestamp < :cutoff
```
and a preceding `SELECT event_fingerprint WHERE timestamp < :cutoff`. An index on `(timestamp)` alone covers the DELETE but the `SELECT` for triage cleanup selects `event_fingerprint` — a covering index `(timestamp) INCLUDE (event_fingerprint)` would avoid a heap fetch. UNVERIFIED whether this index already exists.

**`audit_events_noise` indexing:** Migration `0007` creates the table. Whether it has the same indexes as `audit_events` is not confirmed from migrations alone — UNVERIFIED.

### 2C. Slow Query Candidates (code-pattern analysis)

`pg_stat_statements` was not enabled — no runtime data available.

**Identified from code review:**

| Pattern | File:Line | Risk |
|---------|-----------|------|
| `summary_service` scans up to 500 events in Python for derived-filter path | `summary_service.py:314` | Full ORM load of 500 `AuditEvent` objects for category counts; should be a pure SQL aggregate |
| `cleanup_retention` SELECT fingerprints before DELETE | `event_service.py:768-770` | Loads all fingerprints into Python memory before issuing triage DELETE. On large cutoffs (weeks of data) this can OOM. Batch it. |
| `filter_options_service` — 3 queries to build filter dropdown | `filter_options_service.py:95,121,234` | Could be 1 query with `GROUPING SETS`. Currently cached with TTL; acceptable if cache hit rate is high. |
| `backfill_service` actor display-name backfill | `backfill_service.py:939` | Cursor-based batch loop with `LIMIT/OFFSET` pattern — at 4.9M rows this is O(n²) in the worst case. Review uses keyset pagination. |

**Connection pool:** `pool_size=5` (`backend/app/db/database.py:77`) with `pool_timeout=30s` and `statement_timeout=30000ms`. Under high load with 5 concurrent requests all hitting slow queries, the 6th request blocks for 30 seconds before failing.

---

## 3. Observability Gaps

### What's working

| Component | Coverage | Details |
|-----------|----------|---------|
| **Forwarder metrics** | Good | `src/metrics/prometheus.py` + `src/metrics/audit_events.py` emit 20+ metrics: `audit_forwarder_processing_rate_per_second`, `audit_forwarder_consumer_lag`, `audit_forwarder_consumer_lag_total`, `audit_forwarder_error_count_total`, `audit_forwarder_uptime_seconds`, `audit_events_critical_total`, `audit_events_auth_failures_total`, etc. |
| **PostgreSQL metrics** | Good | `postgres-exporter` on port 9187 scraped by Prometheus. Covers `pg_database_size_bytes`, `pg_stat_activity_count`, dead tuples. |
| **Alert rules** | Comprehensive for forwarder | `prometheus/alerts/audit-forwarder.yml` has 14 alert rules: consumer lag, error rate, throughput, memory, disk pressure, SQLite WAL size, checkpoint failures, security events, access transparency. |
| **Log aggregation** | Configured | Loki + Promtail in both `docker-compose.yml` and `docker-compose.prod.yml`. Promtail scrapes container logs. |
| **Docker healthchecks** | All services | All 4 main services (forwarder, api, frontend, postgres) have healthchecks with 30s interval/5s timeout/3 retries. |
| **Readiness endpoints** | Thorough | `/live`, `/ready`, `/pipeline/ready`, `/ingestion/ready` in `readiness.py`. |

### What's missing or broken

| # | Gap | Evidence | Impact | Fix |
|---|-----|----------|--------|-----|
| O1 | 🔴 **`01_pipeline_health.json` — ALL 4 panels broken** | Every panel uses `up{job="auditlens-forwarder"}` as query. "Processing Rate", "Consumer Lag", "DB Behind Seconds", "Noise Persist Wait Timeouts" all show the same binary up/down signal instead of their intended metrics. | Dashboard is non-functional. Key operational metrics invisible. | Fix queries: `audit_forwarder_processing_rate_per_second`, `audit_forwarder_consumer_lag_total`, `audit_forwarder_idle_seconds`, `audit_forwarder_persistence_noise_wait_timeouts_total` (or equivalent). |
| O2 | 🔴 **`03_api_health.json` — all 3 panels blank** | Queries `rate(http_requests_total[5m])`, `rate(http_requests_total{status=~"5.."}[5m])`, `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`. The FastAPI backend has **zero Prometheus middleware** — these metrics are never emitted. | API request rate, error rate, and p95 latency are invisible. No alerting possible on API degradation. | Add `starlette-exporter` or `prometheus-fastapi-instrumentator` to `backend/app/main.py`. One `add_middleware()` call. |
| O3 | 🟠 **Alertmanager not wired** | `prometheus/prometheus.yml:9-10` shows `targets: []` with `# - alertmanager:9093` commented out. AlertManager is not in any compose file. | All configured alert rules (including the 14 well-crafted ones in `audit-forwarder.yml`) **fire into a void** — no notifications sent. | Either add AlertManager to compose with email/Slack receiver, or wire existing `notifications.yml` system to handle Prometheus alerts via webhook. |
| O4 | 🟠 **Metrics vocabulary mismatch** | `src/metrics/audit_events.py:77` reads `event.get('criticality')` and tracks `CRITICAL/HIGH/MEDIUM/LOW`. The classifier in `src/product/event_signals.py` now emits `action_required/attention/informational/noise`. The `audit_forwarder.py:333` writes both `criticality` and `signal_type` to the enriched event. | `audit_events_critical_total` and `audit_events_by_severity` counters may be 0 for signal-classified events if `criticality` field is absent. Dashboard panels "Critical Events" and "High Severity Events" may undercount. | Audit `_try_short_circuit_noise()` and `_enrich()` to confirm both fields are populated; update metrics to also track by `signal_type`. |
| O5 | 🟡 **No structured logging** | `grep structlog/json.*log backend/` returns nothing relevant. All services use `logging.getLogger()` with plain text format. | Log parsing in Loki/Promtail is regex-based; no `traceId`, `requestId`, or structured fields are queryable. Correlation across log lines requires pattern matching. | Add `python-json-logger` to `backend/requirements.txt`. Configure in `backend/app/core/logging.py`. Single change propagates everywhere. |
| O6 | 🟡 **No API-level metrics for events ingested, enriched, or classified** | The forwarder has `audit_events_critical_total` etc., but the API's `/events` and `/summary` endpoints have no counters. | Cannot detect: sudden drop in event ingestion rate (Kafka disconnected), enrichment degradation (actor display names drop to 0%), classification skew (suddenly all events are "noise"). | Add 3 gauges to the API: `auditlens_events_ingested_total`, `auditlens_actor_enrichment_rate` (% with non-null display name), `auditlens_signal_distribution` by tier. |
| O7 | 🟢 **`logs-dashboard.json` targets old container name** | Query: `{container="audit-forwarder"}` but compose service is named `auditlens-forwarder`. | Loki logs dashboard may return no results depending on Promtail label extraction config. | Update to `{container="auditlens-forwarder"}` or add container name as label in promtail config. |

---

## 4. Missing Insights

### Fields computed and stored but not shown in main event list

The `AuditEventListOut` schema (`backend/app/schemas/event.py`) exposes 50+ fields. The events page table and event card use a much smaller subset. Fields confirmed as computed, stored, and present in API responses but **not surfaced in the main event list/table** (only visible after expanding a row or in the EventDetailDrawer):

| Field | DB Column | In API Response | Shown In Main List | Detail Drawer |
|-------|-----------|-----------------|-------------------|---------------|
| `actor_email` | `actor_email` | Yes | No | Yes |
| `actor_confidence` | `actor_confidence` | Yes | No | Yes (detail row) |
| `actor_source` | `actor_source` | Yes | No | Yes (detail row) |
| `source_ip` | `source_ip` | Yes | **No** — only in detail expand | Yes |
| `risk_level` | `risk_level` | Yes | Only on action_required signal badge | Yes |
| `change_type` | `change_type` | Yes | No | Yes |
| `resource_family` | `resource_family` | Yes | No (filter-only) | Yes |
| `resource_criticality` | `resource_criticality` | Yes | No | Yes |
| `blast_radius_hint` | `blast_radius_hint` | Yes | No | Yes |
| `production_hint` | `production_hint` | Yes | Filter chip only | Yes |
| `parent_resource` | `parent_resource` | Yes | No | Yes |
| `resource_scope` | `resource_scope` | Yes | No | Yes |
| `decision_reason` | `decision_reason` | Yes | No | Yes (Why this matters) |
| `recommended_action` | `recommended_action` | Yes | No | Yes (if non-empty) |
| `network_id` | `network_id` | Yes (types.ts) | **Never shown** | **Never shown** |
| `flink_region` | `flink_region` | Yes | No | Yes (Region field) |
| `actor_enriched_at` | `actor_enriched_at` | Yes | No | Yes (debug field) |
| `request_id` | `request_id` | Yes | No | Yes |
| `connection_id` | `connection_id` | Yes | No | Yes |
| `environment_name` | `environment_name` | Yes | Filter-only | Indirect |
| `cluster_name` | `cluster_name` | Yes | Filter-only | Indirect |
| `event_summary` | `event_summary` | Yes | No | Yes |
| `signal_reason` | `signal_reason` | Yes | No | Indirect (top_signal_reasons in summary) |

**Notably absent from API response entirely:** `resource_display_name`, `resource_display_short`, `source_display`, `source_reason`, `decision_label`.

### Fields in DB but absent from summary dashboard

The `/summary` endpoint (`SummaryResponse`) does not compute or expose:

- **Actor count** — how many distinct actors active in the window. Currently only `top_subjects` (top 5).
- **Environment breakdown** — no `by_environment` distribution (even though `environment_id`/`environment_name` are stored).
- **Cluster breakdown** — no `by_cluster` distribution.
- **Hourly heatmap data** — no `by_hour` distribution.
- **Top actors by denial count** — `denials` total is shown but not broken down by actor.
- **Cross-environment actors** — actors active in > 1 environment not surfaced.

### High-value insights available from existing data

Based on the schema analysis and query pattern review, the following insights are derivable from data that is **already stored** but not presented to users:

| Insight | Fields Used | AuditLens Today | Where It Would Fit |
|---------|-------------|-----------------|-------------------|
| **IP-based anomaly score per actor** | `actor_ip_baseline` table (`occurrence_count`, `is_trusted`, `cloud_provider`, `region`) + `source_ip` | Baseline tracking runs, IpBaselineTracker detects new IPs, but **no UI surfaces this** | Actor detail panel / event card — "new IP" badge already planned in `ActorActivityPanel.tsx:331` but data may not flow through |
| **Resource blast-radius heatmap** | `blast_radius_hint` (`"low"/"medium"/"high"`), `production_hint` (`"production"/"staging"`), `resource_criticality` | `production_hint` is a filter; blast_radius shown in drawer only | Dashboard tile: "High-blast-radius changes in production last 24h" |
| **Failure rate by action category** | `action_category`, `is_failure`, `is_denied`, `timestamp` | Dashboard shows total `failure_count` but not broken down by category | New summary tile: "Delete operations: 12% failure rate (above baseline)" |
| **Actor cross-environment activity** | `environment_id`, `actor` / `actor_display_name` | Not computed anywhere | Patterns page or actor panel: "This actor was active in 3 environments" |
| **Hourly activity heatmap** | `timestamp`, `signal_type` | Not shown | Dashboard widget (day × hour grid, coloured by peak signal) |
| **client_tool distribution** | `client_tool` | Shown per-event in card ("via terraform-provider") | Summary: "67% of changes via Terraform, 23% via Console, 10% via API" |
| **Denial rate trending** | `is_denied`, `timestamp`, 30-minute buckets | Denial total shown, not trended | Sparkline on dashboard: denial rate over last 24h |
| **Recommended action surfacing** | `recommended_action` (computed by signal classifier) | In detail drawer only, not shown in filtered event list | Add to event card for `action_required` tier events |
| **RBAC scope of changes** | `resource_scope` (e.g., `"cluster"`, `"topic"`, `"schema"`) | Stored and in drawer, not filterable | Add as filter chip alongside resource_type |
| **Top actors by distinct resource access** | `actor`, `resource_id` via `resource_catalog` | `top_subjects` shows by event count only | Add secondary sort: "actors touching most distinct resources" |

### What Datadog/Panther surface that AuditLens doesn't

Based on field analysis (checked against `information_schema.columns` equivalents from models):

| Capability | Fields Needed | Status |
|------------|---------------|--------|
| **MFA/auth method per event** | `mfa_used`, `auth_method` | **Not stored** — not in schema, not in normalization code |
| **Session continuity** | `session_id`, `correlation_id` | **Not stored** — `connection_id` and `request_id` are stored but not `session_id` |
| **API version per call** | `api_version` | **Not stored** |
| **Latency / response time** | `latency_ms` | **Not stored** — raw payload may contain it but not extracted |
| **Error code / message** | `error_code`, `error_message` | **Not stored** — `is_failure` + `result` are stored but not the error code string |
| **Geo-IP enrichment** | `country_code` | **Not stored** — `actor_ip_baseline` has `cloud_provider` + `region` but no geo-IP |
| **User agent string** | `user_agent` | **Not stored** — `client_tool` is a normalized form, raw user-agent not stored |
| **Tags / labels** | `tags` | **Not stored** |
| **Region / AZ** | `region` | **Partially stored** — `flink_region` for Flink events; `actor_ip_baseline.region` is cloud region for IP. No unified `region` column on events. |
| **Service-level correlation** | Linking multiple events to one "change window" | Not supported — no `change_id` or `correlation_id` |

**Fields that exist in `actor_ip_baseline` but are not surfaced in UI:**
- `cloud_provider` (AWS/GCP/Azure) for each actor+IP pair
- `region` (us-east-1, etc.)
- `is_trusted` (manually set via YAML) — shown in `ActorActivityPanel.tsx:334` as `.trusted-ip` class but data connection needs verification

---

## 5. Recommended Fix Order

Ranked by impact (security > data integrity > performance > UX):

### Immediate (days)

| # | Finding | File | Fix |
|---|---------|------|-----|
| F1 | 🔴 **AlertManager not wired** (O3) | `prometheus/prometheus.yml` | Uncomment `- alertmanager:9093`, add AlertManager service to `docker-compose.prod.yml`, configure one notification channel. 14 well-written alerts currently fire into void. |
| F2 | 🔴 **Pipeline health dashboard all-blank** (O1) | `grafana/dashboards/01_pipeline_health.json` | Replace all 4 panel queries with correct metric names: `audit_forwarder_processing_rate_per_second`, `audit_forwarder_consumer_lag_total`, etc. |
| F3 | 🔴 **API health dashboard all-blank** (O2) | `backend/app/main.py` | Add `prometheus-fastapi-instrumentator` or `starlette-exporter`. Single `add_middleware()` call. Unlocks `http_requests_total` and `http_request_duration_seconds_bucket`. |

### Short-term (1–2 weeks)

| # | Finding | File | Fix |
|---|---------|------|-----|
| F4 | 🟠 **Metrics vocabulary mismatch** (O4) | `src/metrics/audit_events.py` | Add signal_type-based counters (`action_required_total`, `attention_total`, etc.) alongside criticality counters. Verify `criticality` field is always written. |
| F5 | 🟠 **`AuditEvent` god object** (A1) | `backend/app/db/models.py` | Extract the 20 `@property` methods that parse `raw_payload_json` into a `_intelligence()` → `_resource_enrichment()` → `_source_enrichment()` → `_signal()` call chain into a standalone `AuditEventView` or `EventEnricher` dataclass. Breaking change for tests. |
| F6 | 🟠 **Blocking call in async route** (A3) | `backend/app/api/routes/onboarding.py:142` | Wrap `admin.list_topics(timeout=10)` in `asyncio.get_event_loop().run_in_executor(None, admin.list_topics, 10)`. |
| F7 | 🟠 **Scattered `os.getenv` for auth/Confluent** (A5, A6) | `admin.py`, `system_service.py`, `tableflow.py` | Move all `os.getenv("API_AUTH_ENABLED")`, `CONFLUENT_*` reads into `get_settings()`. |
| F8 | 🟡 **`cleanup_retention` OOM risk on large cutoffs** | `event_service.py:768` | Batch the fingerprint SELECT: fetch 1000 fingerprints at a time, delete triage rows, repeat. Same batch pattern used in raw-payload nulling. |
| F9 | 🟡 **Structured logging** (O5) | `backend/app/` | Add `python-json-logger`. Configure root logger in `backend/app/core/config.py`. Zero code changes across services. |

### Medium-term (1 month)

| # | Finding | File | Fix |
|---|---------|------|-----|
| F10 | 🟡 **`backfill_service.py` too large** (A4) | `backend/app/services/backfill_service.py` | Split into `backfill_phases.py` (the 5 phase functions) and `backfill_admin.py` (state tracking, admin endpoints). |
| F11 | 🟡 **Summary missing environment/cluster breakdown** (Section 4) | `summary_service.py`, `response.py` | Add `by_environment: dict[str, int]` and `by_cluster: dict[str, int]` to `SummaryResponse`. One additional `GROUP BY environment_id` query or extend the existing GROUPING SETS. |
| F12 | 🟡 **Hourly heatmap not surfaced** (Section 4) | `summary_service.py`, dashboard | Add `by_hour: dict[int, int]` to `SummaryResponse`. Map over 24h window grouping by `EXTRACT(HOUR FROM timestamp)`. Display as compact heatmap row on dashboard. |
| F13 | 🟡 **`raw_payload_json` as TEXT blocks JSON search** (A7) | DB migration | Add `0021_raw_payload_jsonb.py` with dialect guard: `ALTER TABLE audit_events ALTER COLUMN raw_payload_json TYPE JSONB USING raw_payload_json::JSONB` (Postgres only). SQLite path unchanged. |
| F14 | 🟡 **`logs-dashboard.json` container name mismatch** (O7) | `grafana/dashboards/logs-dashboard.json` | Change `container="audit-forwarder"` → `container="auditlens-forwarder"`. |

### Longer-term / strategic

| # | Finding | Effort | Value |
|---|---------|--------|-------|
| F15 | **`audit_events` table partitioning** | High | Required when table exceeds ~50M rows. Partition by month on `timestamp`. Migration is non-trivial — requires pg_partman or manual `ATTACH PARTITION`. |
| F16 | **IP geolocation enrichment** | Medium | Add MaxMind GeoLite2 lookup at event ingestion. Store `country_code`, `asn`, `org` in `audit_events`. Unlocks geo-anomaly detection and the "IP without geo" insight gap. |
| F17 | **MFA / auth_method extraction** | Medium | Parse `authenticationInfo.mfaAuthenticationProvider` from raw payload during normalization. Store in new `mfa_used` column. High value for security posture reporting. |
| F18 | **Cross-environment actor analytics** | Low effort, high value | Add `by_environment_actor` query to the `/actors` narrative or summary. Already have `environment_id` + `actor` in every event — a simple `HAVING COUNT(DISTINCT environment_id) > 1` query surfaces this. |
| F19 | **`action_required` events: surface `recommended_action` in event list** | Low | `recommended_action` is already computed and stored. Currently buried in EventDetailDrawer. Adding it as a collapsed note on `action_required` tier event cards would directly improve analyst workflow. |
| F20 | **`network_id` — store or drop** | Low | `network_id` is typed in `frontend/lib/types.ts:52` but never rendered anywhere in the UI. Either surface it (add to EventDetailDrawer context section) or remove from API response and frontend types. |

---

## Appendix: Key File Sizes

| File | Lines | Note |
|------|-------|------|
| `backend/app/services/backfill_service.py` | 1,118 | Largest service |
| `backend/app/db/models.py` | ~700 | `AuditEvent` has 74 methods |
| `backend/app/services/event_service.py` | 867 | Hub service |
| `backend/app/services/summary_service.py` | 430 | Dashboard aggregations |
| `backend/app/schemas/event.py` | ~70 | 50+ field API output |
| `frontend/components/AuditEventTable.tsx` | — | Renders ~15 of 50+ available fields inline |

## Appendix: Grafana Dashboard Status

| Dashboard | Panels | Status |
|-----------|--------|--------|
| `01_pipeline_health.json` | 4 | 🔴 ALL BROKEN — all queries are `up{job="auditlens-forwarder"}` |
| `02_postgres_health.json` | 5 | 🟢 Correct queries (pg_exporter metrics) |
| `03_api_health.json` | 3 | 🔴 ALL BLANK — `http_requests_total` never emitted by API |
| `04_system.json` | 3 | 🟡 Generic (`container_memory_usage_bytes`, `up`) — useful but not AuditLens-specific |
| `audit-forwarder.json` | 8 | 🟢 Correct queries |
| `audit-forwarder-v2-dashboard.json` | 22 | 🟢 Comprehensive; best forwarder dashboard |
| `logs-dashboard.json` | 1 | 🟡 Container name likely wrong (`audit-forwarder` vs `auditlens-forwarder`) |
