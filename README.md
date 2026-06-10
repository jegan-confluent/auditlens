# AuditLens

Self-hosted audit intelligence for Confluent Cloud. AuditLens consumes your organisation's audit log topic, classifies every event by signal priority (action required / attention / informational / noise), enriches actors with real display names, and surfaces what matters through a real-time dashboard built for security and operations teams.

**Repo:** https://github.com/jegan-confluent/auditlens

No data leaves your deployment. No telemetry. No phone-home.

---

## Features

Every row below is verified against the live codebase (see `Where` column for the file backing each capability). Items marked _opt-in_ require an env-var or YAML toggle; everything else is on by default.

### 1. Filtering & Search

| Feature | Notes | Where |
|---|---|---|
| Time-window filter (Nm / Nh, `7d`/`30d` translated to hours client-side) | Required-pattern validation at the backend; UI exposes 30m / 2h / 4h / 12h / 24h / 7d / 30d | `backend/app/services/event_service.py` `parse_time_window`; `frontend/components/FilterBar.tsx` |
| Service / Category / Method hierarchical filter | Three-level dropdown driven by `/filters/hierarchy`, derived from the live distinct method set | `backend/app/services/filter_options_service.py:196` (`_SERVICE_LABELS`) |
| Result filter (Success / Failure / Denied) | "Denied" maps to `is_denied=true`; everything else maps to the canonical `result` column | `frontend/lib/eventFilters.ts:63` (`RESULT_TO_QUERY`) |
| Actor / email search — case-insensitive, 300 ms debounce | Server-side `ILIKE` on `actor`; if the input contains `@`, the LIKE also covers `actor_email` | `frontend/components/FilterBar.tsx:8` (`ACTOR_DEBOUNCE_MS=300`); `backend/app/services/event_service.py:362-372` |
| Free-text search across event title, actor, resource_name, request_id (`q` parameter) | `max_length=200`, debounced 300 ms | `backend/app/services/event_service.py:385-395` |
| Production / non-production environment pill | `production_hint` column populated at ingest from resource intelligence | `frontend/components/FilterBar.tsx:359-374` |
| Control-plane / Data-plane pill | Resolution order: resource_family → action_category="data" → action prefix | `backend/app/services/event_service.py:45-68` `derive_plane_type` |
| Flink / Tableflow service quick-filter pills | One-click `action` substring match (`flink` / `tableflow`); covers dotted (`flink.X`) and bare-name (`FlinkJobFailed`) methods | `frontend/components/FilterBar.tsx:15-25` |
| Period-over-period comparison (`/api/events/compare`) | Side-by-side stats for two time windows: total, by signal, top actors, top methods | `backend/app/api/routes/events.py:346-361`; `backend/app/services/event_service.py:704-774` |
| Saveable filter presets (per browser, localStorage) | Up to 5 named filter combinations per operator | `frontend/components/FilterBar.tsx:82-128` |
| Deep link to a specific event (`?event_id=N` opens the detail drawer) | One-shot URL hydrator; drawer state survives until close | `frontend/app/events/page.tsx:302-321` |

**Not a filter:** source IP. The `source_ip` column is populated and visible in the event detail drawer and CSV/JSON export, but there is no dedicated IP filter — the free-text `q` field does not cover the IP column. Filter by IP indirectly via the actor pivot from the actor activity panel.

### 2. Enrichment & Intelligence

| Feature | Notes | Where |
|---|---|---|
| 4-tier signal classification: `action_required`, `attention`, `informational`, `noise` | Every event lands in exactly one tier | `src/product/event_signals.py:151` `classify_signal` |
| Decision-reason prose + recommended-action stored per event | Specific reasons override the generic mapping for Flink runtime events and RTCE | `src/product/event_intelligence.py:474-496` `_SIGNAL_REASON_DECISION_REASON` |
| IAM actor name resolution (CRN → display name + email) — opt-in | 1-hour TTL cache, 55-minute proactive refresh; falls back to manual `actor_mappings.yml`, then raw ID | `src/identity/enricher.py:91` (`refresh_interval_seconds = 55 * 60`) |
| Manual actor overrides via `actor_mappings.yml` | Hot-reloaded on mtime change; highest priority in the resolution chain | `src/product/actor_enrichment.py` `ActorMappingFile` |
| Client tool detection: **Confluent Console / VS Code / CLI**, **librdkafka SDK**, **Confluent Python SDK**, **Java Kafka SDK**, **Go Sarama SDK**, **Kafka Admin Client** | Pattern-matched on `clientId` (`proxy:`, `rdkafka/`, `confluent-kafka-`, `Apache Kafka`, `sarama/`, `adminclient-`). Terraform provider clients fall through to raw `clientId` — no friendly mapping | `src/product/event_normalization.py:790-806` `_map_client_tool` |
| Cloud-provider IP tagging — AWS, GCP, Azure, Confluent management plane | Static CIDR table, no external API call | `src/product/ip_baseline_tracker.py:51-68` `_CLOUD_CIDRS` |
| Per-actor IP baseline tracking + new-IP detection | Thread-safe in-memory set seeded from Postgres on startup | `src/product/ip_baseline_tracker.py:106-184` |
| Internal Confluent system actor exclusion from "most active" / "recent activity" narrative | Skips `externalAccount`-prefixed JSON-blob actors and the `Confluent (internal)` display name | `frontend/lib/utils.ts:35` `isConfluentInternalActor` |
| Two-table noise split (`audit_events` vs `audit_events_noise`) | Bulk-noise methods (mds.Authorize, kafka.Fetch, schema-registry.Authentication, etc.) write to the lean noise table — ~83% volume saving on the main table | `src/product/event_normalization.py:27-40` `BULK_NOISE_METHODS` |
| Confluent platform automation override | Demoted to `informational` unless the method contains a security-mutation verb (grant/revoke/bind/unbind/deleteapi/…) | `src/product/event_signals.py:194-210` |
| Access Transparency events — always `action_required`, fires before all other rules | Matches CloudEvents `type` containing `"access-transparency"` at the very top of `classify_signal` | `src/product/event_signals.py:156-173` |
| Tableflow event classification — Create/Delete (CRITICAL/HIGH) + 6 explicit read-helper methods | `_ALWAYS_INFORMATIONAL_METHODS` covers `tableflowgettable`, `tableflowlisttables`, `tableflowcatalogconfig`, `listtableflowcatalog`, `tableflowgetcatalog`, `tableflowlistcatalogs` | `src/product/event_signals.py:67-76`; `src/classification/methods.py:180,433-435` |
| Flink control-plane CRUD classification | `CreateStatement` / `CreateFlinkCompute` etc → `attention`; `DeleteStatement` / `DeleteFlinkCompute` → `action_required/destructive_change` | `src/product/event_signals.py` generic cascade + `src/classification/methods.py:147-151, 414-422` |
| Flink job-lifecycle classification — Failed / Started / Cancelled / Checkpoint / Savepoint | Failures (`FlinkJobFailed`, `CheckpointFailed`, `FlinkRestartFailed`, `FlinkStatementFailed`, `FlinkJobException`) → `action_required`. Lifecycle (`Started`, `Finished`, `Restarting`, `CheckpointCompleted`, `SavepointCreated`, `SavepointRestored`) → `attention`. `FlinkJobCancelled` splits on `is_failure`. Heartbeats / metrics → `informational` | `src/product/event_signals.py:67-110` (3 frozensets + cascade) |
| Real-Time Context Engine (RTCE) classification — CRUD-aware dispatch | Substring match on methodName / serviceName (`contextengine`, `realtimecontext`, `rtce`); deletes → `action_required`, get/list/describe → `informational`, default → `attention`. First-encounter WARNING per unique method | `src/product/event_signals.py:113-170` (`_is_rtce_event` + dispatch) |
| Recurring-pattern panel — surfaces high-frequency (actor, action, resource) combinations | Configurable threshold; suppressed combos optionally excluded from decision-mode listing | `backend/app/services/pattern_service.py` |
| Actor activity narrative — per-actor 24h timeline with anomaly hints (off-hours, deletion spikes, multi-tool) | Drawer panel from any event row's actor link | `frontend/components/ActorActivityPanel.tsx` |

### 3. Dashboard & Analytics

| Feature | Notes | Where |
|---|---|---|
| Live dashboard — narrative strip, signal summary, top actors, hourly heatmap | 24-bin UTC hourly chart (last 7d) shaded by event count | `frontend/app/dashboard/page.tsx:97-118, 187-233` |
| Time-window toggle on dashboard (1h / 6h / 24h / 7d) | Persisted to `localStorage` | `frontend/app/dashboard/page.tsx:131-136` |
| Environment breakdown bars | Hidden when only one environment is in view | `frontend/app/dashboard/page.tsx:78-95` |
| Authentication Analytics page at **`/auth-analytics`** | Top API keys + source IPs by `kafka.Authentication` volume; 1d / 7d toggle; cloud-provider column | `frontend/app/auth-analytics/page.tsx`; `backend/app/api/routes/auth_analytics.py:60` |
| Resource Catalog page — searchable inventory of every resource seen in audit events | Grouped by type; preserves last-seen timestamp | `frontend/app/resources/page.tsx`; `backend/app/services/resource_service.py` |
| System page — consumer lag, DB writer state, pipeline lag, queue depths, storage usage, effective retention | Polled at 30 s via a single shared subscriber | `frontend/app/system/page.tsx`; `frontend/lib/hooks/useSystemStatus.ts` |
| Settings page — tabs for Retention, Cold Storage, Notifications, Schema Registry, Tableflow, Actor Mappings, Stream Output | All admin-only writes go through the bearer-token auth chain | `frontend/app/settings/page.tsx` |
| Action alert banner when `action_required` events are present | Picks the top non-Confluent-system actor + most-recent event timestamp | `frontend/components/ActionAlertBanner.tsx` |
| Pipeline-lag banner when forwarder → DB write lag exceeds a threshold | Distinct from the Confluent-Cloud-to-forwarder lag shown on System | `frontend/components/PipelineLagBanner.tsx` |
| Schema-deletion warning in the **event detail drawer** | Renders on `schema-registry.DeleteSubject` or `DeleteSchemaVersion`; not a top-level page banner | `frontend/components/EventDetailDrawer.tsx:121-125` |
| Triage controls in every event drawer — Acknowledge / Approved / Investigating / Resolved / False Positive | Triage failures surface inline ("Failed to save — please try again") if the PATCH does not succeed; local state is NOT updated on failure | `frontend/components/EventDetailDrawer.tsx:198-205`; `frontend/app/events/page.tsx:380-395` |
| Raw payload preview in event drawer (8 KB cap) | Larger payloads truncate to the first 8 000 chars with a `[truncated — full payload available via CSV export]` marker; full payload available via the export endpoint | `frontend/components/EventDetailDrawer.tsx:94-110` |
| Group similar consecutive events (session-only toggle) | Collapses runs of `(actor, action, resource, env, signal, result)` with a 60-min ceiling from the first event | `frontend/components/AuditEventTable.tsx:130-163` |

### 4. Export & Alerting

| Feature | Notes | Where |
|---|---|---|
| Filter-aware CSV / JSON export — up to **50 000** rows per request | CSV header for the actor column is `actor_name` (resolved display name), backed by the internal `actor_display_name` field. Cloud-provider tag derived from `source_ip` at export time | `backend/app/services/event_service.py:27` `EXPORT_MAX_ROWS = 50_000`; `backend/app/api/routes/events.py:223-235` (`_EXPORT_COLUMNS`, `_CSV_HEADER_RENAMES`) |
| Slack notifications — realtime (per event) and daily digest modes — opt-in | Mode selectable per destination in `notifications.yml`; digest delivers a single Block Kit summary at `HH:MM` UTC | `src/notifications/notifier.py:133` `VALID_MODES`; `:834-947` `_digest_loop` / `_send_digest` |
| Microsoft Teams notifications (Adaptive Card) | Same filter + retry + dedup logic as Slack | `src/notifications/notifier.py:1248-1321` `_format_teams` |
| PagerDuty Events API v2 — severity routing + deduplication key | `action_required + critical` → critical, `action_required + other` → error, `attention` → warning, else → info. `dedup_key = event_fingerprint` so PagerDuty collapses duplicates within its own window | `src/notifications/notifier.py:147-167` (`_pagerduty_severity`); `:1115-1153` (`_format_pagerduty`) |
| Generic webhook destination (operator-supplied URL, SSRF-validated) | HTTPS-only; rejects URLs that resolve to private / loopback / link-local / reserved IPs | `src/notifications/notifier.py:201-218` `_validate_webhook_url` |
| Deep link in Slack alert ("View event →") | When `app_base_url` is set in `notifications.yml`, every realtime Slack/Teams alert renders a button to `{app_base_url}/events?event_id=<id>` | `src/notifications/notifier.py:1213-1246` `_event_deep_link` |
| Per-destination filters: signal_type, min_risk_level, action_category include-list, exclude_actions | All filters AND-combined; signal_type is required | `src/notifications/notifier.py:522-548` `should_notify` |
| Per-destination rate limiting with burst summarisation | Sliding 60 s window; excess events collapse into one "N events suppressed" summary per minute | `src/notifications/notifier.py:670-756` |
| Dedup across destinations — 5-minute fingerprint window | Per-destination dedup so the same event still reaches every channel exactly once | `src/notifications/notifier.py:111` `DEDUP_WINDOW_SECONDS` |
| Pipeline-silence watchdog — Slack/Teams alert at 30 min silence, **recovery alert** when events flow again | One alert on onset, one on recovery, then quiet. Default threshold is 30 min; configurable via `pipeline_silence_threshold_minutes` in `notifications.yml` | `audit_forwarder.py:1673-1751` `_pipeline_watchdog_loop` |
| `auditlens alerts test` CLI — fires a real test notification to every enabled destination | Bypasses dedup + rate limit but uses real formatters | `cli/auditlens.py:504`; `backend/app/api/routes/settings.py:99` |
| AlertManager included in production compose for metric-based alerting | Receives from Prometheus, separate from the audit-event notifier | `docker-compose.prod.yml:476-498` |

### 5. Infrastructure

| Feature | Notes | Where |
|---|---|---|
| FastAPI backend + Next.js (App Router) frontend | Backend at port 8080, frontend at 3000; both behind Caddy on prod | `backend/app/main.py:8`; `frontend/app/page.tsx` (redirects to `/dashboard`) |
| Docker Compose with Caddy reverse proxy on **`:80` / `:443`** in production (`docker-compose.prod.yml`) | `:8088` fallback for macOS dev where `:80` may be taken | `docker-compose.prod.yml:259-293` |
| Single-host EC2 deploy via `make deploy` (rsync + remote rebuild + migrations) | Image tags + `docker compose up -d --build --force-recreate --remove-orphans`; alembic upgrade head runs in the api container | `Makefile` (deploy target) |
| Postgres connection pool with explicit limits — `pool_size=5, max_overflow=10, pool_timeout=30, pool_recycle=1800` | Prevents silent stalls under load when all four DB-writer threads contend for connections | `src/product/db_writer.py:222-256` |
| Postgres tuning script runs at container start (`shared_buffers`, `work_mem`, etc. sized to available RAM) | Entrypoint override on the postgres service | `docker-compose.prod.yml:325` (`tune.sh` mount) |
| TimescaleDB hypertable conversion if the extension is detected | Idempotent; falls back to standard tables when the extension is absent | `src/product/db_writer.py:243-298` |
| Configurable retention per tier — signal events (default 7d), raw payloads (default 7d), noise events (default 3d) — minimum 1 day enforced | Daily background loop in the API process; runtime changes apply without restart | `backend/app/services/event_service.py:785-982` `cleanup_retention`; `backend/app/main.py:33-61` |
| Cold-storage archival to S3 or GCS before deletion — opt-in | Archive-before-delete is enforced — no silent data loss when cold storage is configured | `backend/app/services/cold_storage_service.py` |
| Bearer-token auth — `viewer` / `responder` / `exporter` / `admin` roles | Onboarding endpoints require `admin`. `_require_admin` adds an admin-audit-log row on every privileged write | `backend/app/api/routes/patterns.py:118-131`; `backend/app/api/routes/admin.py:52-79` |
| `postgres-exporter` reads its password from a Docker secret (`DATA_SOURCE_PASS_FILE`) | The DB password is never visible via `docker inspect` | `docker-compose.prod.yml:576-605` |
| Forwarder runs `read_only: true`, `cap_drop: ALL`, non-root | Other services drop capabilities except where strictly required | `docker-compose.prod.yml:108-117` |
| Per-IP rate limiting on every route, with admin endpoints capped tighter | `60/min` on `/events`; `10/min` on export; `5/min` on onboarding | `backend/app/core/limiter.py` |
| CLI: `events list`, `events export`, `events get`, `stats compare`, `pipeline status`, `pipeline indexes`, `alerts test`, `config set/show` | Configuration via `~/.auditlens.conf` (chmod 600) or `AUDITLENS_*` env vars | `cli/auditlens.py` |
| Flink SQL — **6 pre-materialized tables** maintained continuously: `audit_deletions`, `audit_creations`, `audit_api_keys`, `audit_security`, `audit_clusters`, `audit_topics` (+ the `audit_events_source` base table) | Pre-filtered queries against typed Flink tables — orders of magnitude cheaper than scanning the raw 1.5M-event topic. Deploy via `flink/deploy_tables.sh` | `flink/create_audit_tables.sql`; `flink/deploy_tables.sh` |
| Prometheus + Grafana pre-provisioned dashboards (processing rate, consumer lag, queue depths, write latency, error rates) | Login: `admin` / generated `GRAFANA_ADMIN_PASSWORD` | `docker-compose.prod.yml:408-475`; `grafana/dashboards/` |
| Loki + Promtail log aggregation — opt-in via the `observability` compose profile | Off by default | `docker-compose.prod.yml:500-575` |
| All container host ports bound to `127.0.0.1` by default | Caddy `:80`/`:443` are the only public binds; API and frontend are localhost-only for direct probes | `docker-compose.prod.yml` (port mappings) |
| Schema Registry integration — register the AuditLens Avro schemas (`audit.enriched.v1` + signal/alert/DLQ subjects), detect drift between `.avsc` and the registered version | All from the Settings UI; no SSH required | `backend/app/api/routes/settings.py:200-650` |

---

## Architecture

The forwarder (`auditlens-forwarder`, port 8003) consumes the Confluent Cloud audit log topic, runs each event through signal classification and actor enrichment, then writes to PostgreSQL. The FastAPI backend (`auditlens-api`, port 8080) serves `/events`, `/summary`, `/filters`, `/system`, `/settings`, and admin endpoints from that database. The Next.js frontend (`auditlens-frontend`, port 3000) renders the dashboard, events, and settings pages.

Signal classification assigns every event a `signal_type` (`noise` → `informational` → `attention` → `action_required`) and a `signal_reason` code. The dashboard and events page filter and surface events by these signals; `noise` events are stored separately in `audit_events_noise` and hidden by default.

---

## Managing your deployment

### Check status
```bash
make status
```
Shows running containers, consumer lag, and pipeline health.

### Restart after a reboot
```bash
make up
```
Containers are configured to restart automatically on reboot. If they don't, run `make up` to bring everything back.

### Update to the latest version
```bash
git pull
make deploy
```
Pulls the latest code, rebuilds containers, applies any database migrations, and restarts services. Your data is preserved.

### Stop and remove (guided)
```bash
make teardown
```
Interactive prompt — shows what's running, then asks whether you want to stop, remove, or fully wipe. Safe to run any time.

### Manual options (if you prefer)

| Goal | Command |
|---|---|
| Pause containers (keep data, restart later) | `docker compose stop` |
| Remove containers (keep data) | `docker compose down` |
| Remove containers + all data ⚠ | `docker compose down -v` |
| Restart paused containers | `docker compose start` |
| Restart and rebuild | `make up` |

### What happens to my data?
- `make teardown` option 1 and 2 — data is safe in the Postgres volume
- `make teardown` option 3 — deletes the Postgres volume permanently. All ingested events are gone. There is no undo.
- `git pull && make deploy` — always safe, data is never touched

### Uninstall completely
```bash
make teardown  # choose option 3 to wipe data
cd ..
rm -rf AuditLens
```

---

## Quick Start

**Host prerequisites:**

- Python 3.11 or higher
- Docker Desktop (or Docker Engine + Compose v2) with ≥ 6 GB RAM
- Free local ports: **8003** (forwarder), **8080** (API), **3000** (frontend); plus **9090** Prometheus, **3001** Grafana, **5432** Postgres in the default profile

**What you need before running `./setup`:**

```
┌─────────────────────────────────────────────────────────────────┐
│  What you need before running ./setup                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Audit Log Cluster credentials (SOURCE)                      │
│     These are NOT your regular Kafka cluster credentials.       │
│     Confluent Cloud routes all org audit events to a special    │
│     system cluster that is separate from any cluster you        │
│     created yourself.                                           │
│                                                                 │
│     Find your audit log cluster:                                │
│       → https://confluent.cloud/settings/audit_logs/cli         │
│     You will see:                                               │
│       Cluster   : lkc-xxxxx  (special system cluster)           │
│       Bootstrap : pkc-xxxxx.region.aws.confluent.cloud:9092     │
│       Topic     : confluent-audit-log-events                    │
│                                                                 │
│     Create a Kafka API key scoped to this cluster:              │
│       → Confluent Cloud → Cluster → API Keys → + Add key        │
│       Or: confluent api-key create --resource <lkc-xxxxx>       │
│                                                                 │
│  2. Destination Cluster credentials (where AuditLens writes)    │
│     This is a Standard or Dedicated Confluent Cloud cluster     │
│     you own or create — AuditLens writes processed events here. │
│     Bootstrap : pkc-yyyyy.region.aws.confluent.cloud:9092       │
│     Kafka API key + secret scoped to this cluster               │
│                                                                 │
│  3. Confluent Cloud API key (optional — for reference only)     │
│     A Cloud-scoped key (not a Kafka key) used only to display   │
│     eligible clusters in your org during setup.                 │
│     Create at: https://confluent.cloud/settings/api-keys        │
│     → Select "Cloud" scope (not a specific cluster)             │
│     You can skip this — it is purely informational.             │
└─────────────────────────────────────────────────────────────────┘
```

The wizard explains each of these in turn and validates the source and destination credentials before writing `.env` / `.secrets`.

**Step 1 — Clone:**

```bash
git clone <repo-url>
cd AuditLens
```

**Step 2 — Run the wizard:**

```bash
./setup
```

That's it. **You do not need to edit `.env` by hand.** The wizard collects every credential interactively, validates Kafka connectivity, writes `.env` + `.secrets` for you, and starts the stack. Phase 7 ends with a service-status panel and clickable links for the dashboard, API, and metrics.

**Step 3 — Open the dashboard:**

```
http://localhost:3000
```

You'll see the Dashboard with signal counts, top actors, and the event volume chart. Tables stay empty until the forwarder has consumed events from your audit topic.

---

## What the Setup Wizard Does

`./setup` runs through seven phases. On any failure it saves a checkpoint to `~/.auditlens_setup_checkpoint.json` so a re-run resumes from the last completed phase.

1. **Local prerequisites** — checks Python ≥ 3.11, Docker daemon reachable, Compose v2 available, disk space, required ports free. Offers to install missing tooling on Amazon Linux / Ubuntu / Debian / macOS.
2. **Source cluster** — points you at `https://confluent.cloud/settings/audit_logs/cli` (the only authoritative source for your org's audit-log cluster bootstrap, cluster id, env id, and topic name — the audit-log cluster is system-managed and not auto-discoverable via the public REST API). *(Optional)* If you provide a cloud-scoped Confluent Cloud API key (`https://confluent.cloud/settings/api-keys → Add key → Cloud scope`), the wizard validates it against `GET /org/v2/environments` and prints the Standard / Dedicated clusters in your org for reference — Basic clusters are filtered out because they cannot back audit logs. This listing is **informational only**, not a picker; the audit-log cluster bootstrap still comes from the audit-logs page above. Then collects the Kafka API key + secret for the audit-log cluster and validates connectivity by reading the audit topic.
3. **Destination cluster** — Kafka endpoint + credentials for the cluster that will hold the enriched / signal / DLQ topics. Topics are created if missing.
4. **Schema Registry** *(optional)* — URL + API key + secret; live `GET /subjects` validation.
5. **Product / API settings** — admin token (auto-generated or provided), API port, optional Slack webhook.
6. **Persistence** — SQLite path defaults match the deployment mode (`/app/data/auditlens.db` for Docker, the bind-mount path `./data/forwarder` is pre-created with current-user ownership).
7. **Startup** — `docker compose up -d --build`, then progress-ticked health checks against the forwarder, API, and frontend with a `Still waiting... (Ns elapsed)` heartbeat every 10 seconds. On success the wizard prints a status panel with both `localhost:*` links (for tunnel users) and EC2 public-IP links (IMDSv2-aware, falls back to localhost off-EC2). Successful runs clear the checkpoint.

Secrets generated for you: API admin token, `POSTGRES_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` — all written to `.env` / `.secrets` and on subsequent resumes restored from the checkpoint so the postgres data volume keeps working.

---

## Services & Ports

`docker compose -f docker-compose.prod.yml up -d` brings up:

| Service | Container | Host port | Role |
|---|---|---|---|
| Forwarder | `auditlens-forwarder` | **8003** | Kafka consumer → classification → enrichment → DB writer; serves `/health`, `/metrics` |
| API | `auditlens-api` | **8080** | FastAPI backend; serves `/events`, `/summary`, `/system`, `/settings`, `/health` |
| Frontend | `auditlens-frontend` | **3000** | Next.js dashboard, events, settings |
| Postgres | `auditlens-postgres` | 5432 | Event store + per-tenant settings |
| Caddy | `auditlens-caddy` | 80, 443 | Reverse proxy + automatic TLS (production) |
| Prometheus | `audit-prometheus` | 9090 | Metric scraping |
| Grafana | `audit-grafana` | 3001 | Pre-provisioned dashboards (login: admin / generated `GRAFANA_ADMIN_PASSWORD`) |
| AlertManager | `audit-alertmanager` | 9093 | Metric-based alert routing |
| Postgres exporter | `auditlens-postgres-exporter` | 9187 | Postgres metrics for Prometheus (password from Docker secret) |

All host ports bind to `127.0.0.1` by default. Caddy `:80` / `:443` are the only externally-reachable bindings in production.

---

## Updating or Repairing an Existing Install

If your install is broken after a code update (503 errors, missing config, containers not starting) — or you just want to pick up the latest code without re-entering credentials:

```bash
make repair
```

This pulls the latest code, patches any missing `.env` keys against the current `.env.example`, rebuilds containers, and runs migrations — never asks for credentials, never overwrites operator-set values, and is fully idempotent.

If `make repair` fails, run the full wizard:

```bash
./setup
```

You don't need to re-run the wizard to pick up code changes either. Existing `.env` / `.secrets` are preserved across `git pull`. Other lifecycle targets:

```bash
# Pull + rebuild + migrate (same flow as make repair but no .env patch)
make update

# Just check if an update exists, without applying it
make update-check

# Manual equivalent
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build

# EC2 (or any remote deploy target) — one-liner
git pull origin main && docker compose -f docker-compose.prod.yml up -d --build
```

`./setup` itself also self-updates on launch: if the local clone is behind `origin/main`, it pulls and re-execs before the wizard starts. Disable with `--no-update` (or `AUDITLENS_NO_UPDATE=1`) for offline / CI runs.

`make deploy` does the same flow remotely (rsync + rebuild) — see [docs/Deployment_Guide.md](docs/Deployment_Guide.md). Image updates are controlled rather than automatic: `make update` / `make deploy` pulls and recreates containers on demand. There is no background updater (no watchtower) because uncontrolled image pulls have surprised us on schema-incompatible upstream releases in the past.

### Windows / WSL2

The bash `./setup` wizard cannot run from CMD or PowerShell directly. Install WSL2 once and use the Ubuntu shell for everything:

```powershell
# In PowerShell (run as Administrator), one-time install:
wsl --install
```

Then open Ubuntu from the Start Menu and run:

```bash
git clone https://github.com/jegan-confluent/auditlens
cd auditlens
./setup
```

Docker Desktop for Windows with the WSL2 backend is also required (containers run inside the WSL2 VM). The repo includes a `setup.bat` stub that prints these instructions for anyone who accidentally double-clicks it from Explorer.

---

## Configuration

The most important variables in `.env`. The wizard writes all of these for you; this table is for operators who want to tune after the fact. Full reference in [INSTALL.md](INSTALL.md) and `.env.example`.

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `AUDIT_BOOTSTRAP` | — | Confluent Cloud audit-log Kafka bootstrap (required) |
| `AUDIT_API_KEY` / `AUDIT_API_SECRET` | — | Kafka API credentials for the audit topic (secret lives in `.secrets`) |
| `AUDIT_TOPIC` | `confluent-audit-log-events` | Audit log topic name |
| `GROUP_ID` | `auditlens-forwarder-v1` | Kafka consumer group ID |
| `AUTO_OFFSET_RESET` | `earliest` | `earliest` to replay retained history; `latest` to start from now |
| `DEST_BOOTSTRAP` / `DEST_API_KEY` / `DEST_API_SECRET` | — | Destination Kafka cluster + credentials for enriched / signal / DLQ topics |
| `DATABASE_URL` | `postgresql+psycopg://auditlens:…@postgres:5432/auditlens` | Postgres connection string; SQLite for demo mode only |
| `POSTGRES_PASSWORD` | auto-generated | Postgres admin password (kept stable across resumes) |
| `GRAFANA_ADMIN_PASSWORD` | auto-generated | Grafana login password |
| `API_AUTH_ENABLED` | `true` | Bearer token auth on every API endpoint |
| `EVENT_RETENTION_DAYS` | `7` | Days of signal events to keep |
| `NOISE_RETENTION_DAYS` | `3` | Days of noise events to keep |
| `IAM_ENRICHMENT_ENABLED` | `false` | Resolve actor display names via the Confluent Cloud IAM API (55-min refresh) |
| `CONFLUENT_CLOUD_API_KEY` / `_SECRET` | — | Cloud-scoped key for IAM lookups + Tableflow + the wizard's cluster picker |
| `SCHEMA_REGISTRY_URL` / `_API_KEY` / `_API_SECRET` | — | Schema Registry endpoint + credentials (required for Tableflow) |

---

## Secrets Management

### Default — environment variables

All secrets are read from `.env` on the host. This works on any platform: AWS, GCP, Azure, bare metal, or any Docker host. See `.env.example` for all required values.

### Optional hardening — AWS Secrets Manager

If you are running on AWS EC2, you can store secrets in AWS Secrets Manager instead of `.env`:

1. Run `make secrets-create` to push `.env` values to ASM
2. Set `AWS_SECRETS_MANAGER_ENABLED=true` in `.env`
3. Set `AWS_REGION` to your EC2 region
4. Attach an IAM role to your EC2 instance with `secretsmanager:GetSecretValue` on `auditlens/*` (see `infra/aws/setup_secrets_manager_role.sh`)

Secrets are cached in memory for 15 minutes and auto-refreshed. No restart needed after rotation — run `make secrets-rotate`.

> Note: GCP Secret Manager and Azure Key Vault are not yet supported. Contributions welcome.

---

## Tableflow

Settings → Tableflow shows a live prerequisite checklist before exposing the enable form. Tableflow has hard requirements on the Confluent side:

- **Cluster type** must be Dedicated, Enterprise, or Freight. Basic and Standard are not supported.
- **Cloud provider** must be AWS or Azure. GCP is not supported.
- **Schema Registry** must be configured — Tableflow does not support schemaless topics.
- **Region** eligibility follows the cloud provider (AWS = all Flink-supported regions, Azure GA).

The UI calls `GET /cmk/v2/clusters/{cluster_id}` with your `CONFLUENT_CLOUD_API_KEY`, evaluates each prerequisite, and only shows the enable form when all four pass. If the cloud API key isn't set, the UI shows a one-line hint and degrades to the form with a banner (the operator can still try, just without verification).

---

## Flink SQL Pre-Materialized Tables

`flink/create_audit_tables.sql` defines 6 pre-materialized tables (plus a source table) that Flink continuously maintains from `audit_events_flattened`:

| Table | Purpose |
|---|---|
| `audit_events_source` | Base CDC table watching the audit topic with watermarks and primary-key dedup |
| `audit_deletions` | Every delete operation across the org — most critical for incident review |
| `audit_creations` | Every create operation across the org |
| `audit_api_keys` | All API-key lifecycle events (create, delete, rotate) |
| `audit_security` | Auth, RBAC, and access-denied events |
| `audit_clusters` | Kafka / ksqlDB / Schema Registry / Flink cluster operations |
| `audit_topics` | Topic-lifecycle operations across the org |

Deploy with `flink/deploy_tables.sh` after setting `DEST_ENV_ID`, `FLINK_POOL_ID`, and `DEST_CLUSTER_ID`. Each `CREATE TABLE` is idempotent under the configured version suffix; re-running the script is safe.

---

## Kubernetes

The interactive setup wizard supports Docker only. If `deployment_mode: kubernetes` is set via `--config-file` the wizard prints a clear "not yet supported" notice and exits cleanly — no half-installed state.

Manual Kubernetes deployment uses the templates in [`deploy/kubernetes/`](deploy/kubernetes/README.md). The README there covers apply order, secret management policy (sealed-secrets / external-secrets / cloud-managed identity), NetworkPolicy notes, and a production checklist. Wizard-driven Kubernetes is on the roadmap; the current templates need registry-push handling, full-stack (api / postgres / frontend / caddy) coverage, and prereq gating in Phase 0 before they're production-ready.

---

## Deployment

For production deployment use `docker-compose.prod.yml`, which adds Caddy as an HTTPS reverse proxy with automatic certificate management and explicitly binds api / frontend to `127.0.0.1:8080` / `127.0.0.1:3000` so health checks work without going through caddy. See [docs/Deployment_Guide.md](docs/Deployment_Guide.md) for the complete EC2 setup and `make deploy` workflow.

Terraform configurations for AWS and GCP are in `deploy/`. They're provided as starting points and have not been tested in production by the maintainers.

---

## Security

- All container host ports are bound to `127.0.0.1` by default — Caddy on `:80` / `:443` is the only externally-reachable binding in production.
- API authentication (`API_AUTH_ENABLED=true`) is on by default. Three viewer roles plus an admin role; the onboarding endpoints require admin.
- The Postgres password lives in a Docker secret (`./secrets/postgres_password.txt`, chmod 600, gitignored) and is mounted into both the postgres and postgres-exporter containers via `_FILE` env var indirections — it is never visible in `docker inspect`.
- `.env` and `.secrets` are gitignored and never committed. Credentials stay on the host where AuditLens is deployed.
- AuditLens has no telemetry and no phone-home. The only outbound connections are to your Confluent Kafka endpoint and (when explicitly enabled) `api.confluent.cloud`.
- Admin audit log: every privileged write is appended to the `admin_audit_log` table automatically — auditor-ready trail.

See [SECURITY.md](SECURITY.md) for the full hardening guide.

---

## Roadmap

**Recently shipped (this session)**

- Flink job-lifecycle classification (Failed / Started / Cancelled / Checkpoint / Savepoint)
- Real-Time Context Engine (RTCE) CRUD-aware dispatch with first-encounter logging
- Flink + Tableflow service quick-filter pills in FilterBar
- Internal Confluent system actor excluded from "most active" and recent-activity narratives
- Triage-failure inline error surfaced in the event drawer (no more silent PATCH failures)
- Raw payload preview capped at 8 KB in the event drawer
- Postgres-exporter password moved to Docker secret (`DATA_SOURCE_PASS_FILE`)
- DB-writer connection pool given explicit limits (`pool_size=5`, `max_overflow=10`, `pool_timeout=30`, `pool_recycle=1800`)
- Onboarding endpoints now require admin auth + upstream error bodies sanitized
- `get_watermark_offsets` removed from the on-assign callback (per-partition lag already covered by `stats_cb`, removing the synchronous broker round-trip avoids cross-region rebalance hangs)
- Prose `decision_reason` strings wired for `flink_job_failure`, `flink_job_lifecycle`, `rtce_destructive_change`, `rtce_config_changed`

**Coming next**

- `make rollback` target — alembic downgrade + previous image tag in a single command
- Postgres-password rotation runbook (ALTER USER + `.env` + `DATABASE_URL` aligned in one step)
- OIDC / SSO authentication — current auth is bearer-token; OIDC upgrade planned

**Later**

- MCP server — expose AuditLens data to LLM agents via 9 defined tools
- Tableflow / Iceberg long-term retention queryable from Snowflake, Athena, Databricks
- Sliding-window denial-rate and cross-environment actor correlation as Flink SQL views over `audit.enriched.v1`

---

## Contributing

Bug reports, feature requests, and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development environment setup, test commands, and commit conventions.

---

## License

No license file is present in this repository. All rights reserved until a license is added.
