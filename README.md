# AuditLens

Kafka-native audit intelligence for Confluent Cloud. AuditLens consumes your organisation's audit-log topic, classifies every event into four signal tiers (`action_required` / `attention` / `informational` / `noise`), enriches actors with real IAM display names, and surfaces the results through a real-time dashboard, a typed REST API, and a single-file CLI. Self-hosted: no data leaves your deployment, no telemetry, no phone-home. Built for security and operations teams that need DORA / SOX / GDPR / FCA-grade audit visibility over Confluent without sending raw logs to a SaaS vendor.

## Architecture

```
                         Confluent Cloud audit topic
                                    │
                                    ▼
                       Forwarder (auditlens-forwarder)
                                    │
                ┌───────────────────┼───────────────────┐
                ▼                                       ▼
        Postgres (audit_events                  Destination Kafka
        + audit_events_noise)                   (enriched / signals
                │                                / alerts / DLQ)
                ▼
    FastAPI backend (auditlens-api)
                │
                ▼
    Next.js frontend (auditlens-frontend)
                │
                ▼
          Caddy (TLS, :80/:443)
                │
                ▼
   ALB + Cognito (internal deployment only)
                │
                ▼
       Prometheus + Grafana + AlertManager (observability)
```

Every service is in `docker-compose.prod.yml`. Host ports bind to `127.0.0.1` by default; Caddy `:80`/`:443` are the only externally-reachable bindings.

| Service | Container | Host port | Purpose |
|---|---|---|---|
| Forwarder | `auditlens-forwarder` | 8003 | Kafka consumer, classification, enrichment, DB writer; `/health`, `/metrics` |
| API | `auditlens-api` | 8080 | FastAPI backend (events, summary, system, settings, admin) |
| Frontend | `auditlens-frontend` | 3000 | Next.js dashboard, events, settings, auth-analytics, access-transparency |
| Postgres | `auditlens-postgres` | 5432 | Event store (signal + noise + settings + admin-audit) |
| Caddy | `auditlens-caddy` | 80, 443, 8088 | Reverse proxy + automatic TLS |
| Prometheus | `audit-prometheus` | 9090 | Metric scraping |
| Grafana | `audit-grafana` | 3001 | Pre-provisioned dashboards |
| AlertManager | `audit-alertmanager` | 9093 | Metric-based alert routing |
| Postgres exporter | `auditlens-postgres-exporter` | 9187 | Postgres metrics for Prometheus |
| MCP server | `audit-mcp-server` | 8089 | Token-protected HTTP endpoint exposing AuditLens to LLM agents |
| Loki, Promtail | `loki`, `promtail` | 3100 | Log aggregation (opt-in via `--profile observability`) |

## Features

### Signal Classification

Every event lands in exactly one of four tiers. Classification is deterministic — same event in, same tier out — and the rules live in `src/product/event_signals.py`.

- `action_required` — destructive change, RTCE delete, Flink job failure, IP-filter denial, privilege-escalation role binding, Access Transparency operator access. Surface immediately.
- `attention` — significant create/update, Flink lifecycle, role-binding grants under threshold. Review during the day.
- `informational` — successful reads, routine config queries, Tableflow list/describe.
- `noise` — bulk-noise methods (mds.Authorize, kafka.Fetch, kafka.Produce, schema-registry.Authentication, kafka.Authentication, …) routed to `audit_events_noise` table with the lean column set. ~83% volume saving on the main table.

### Events Feed

Filter, search, and pivot every event the forwarder has classified. Time-window pills, hierarchical service / category / method filter, actor / email search with 300 ms debounce, result + signal pills, period-over-period compare, 5 saveable presets, deep-link `?event_id=N` to the detail drawer. Per-event triage controls (Acknowledge / Approved / Investigating / Resolved / False Positive) write back to the `audit_event_triage` table.

### Auth Analytics

`/auth-analytics` (page) and `GET /api/auth/analytics` (route) — top API keys + source IPs by `kafka.Authentication` volume. 1d / 7d toggle. Actor display names are read from `audit_events_noise.actor_display_name` (populated at ingest via the `principalResourceId` swap that maps Kafka MDS numeric `User:N` principals to IAM-shaped `u-xxx` / `sa-xxx` IDs), with a cross-join fallback into `audit_events` for legacy rows. Source IP rows carry a cloud-provider label (AWS, GCP, Azure, Confluent Internal) computed from a static `/8` table.

### Access Transparency

`/access-transparency` (page) and `GET /api/access-transparency` (route) — paginated view of Confluent personnel access events on customer Dedicated clusters. Surfaces operator + business justification per row. Compliance-facing: built for DORA / SOX / GDPR / FCA obligations. Always classified `action_required`. Default 7-day window, hard cap 90.

### IP Filter Denial Detection

`ipfilterAuthorization.{client_ip,resource_group}` extracted at ingest (migration 0028) and persisted on `audit_events`. Classifier fires `signal_reason=ip_filter_deny` *before* the generic `denied_access` cascade so the alert payload carries the actual blocked IP rather than just "access denied".

### Role-Binding Alerts

`rbacAuthorization.role` extracted at ingest (migration 0027) and persisted. Privilege-escalation grants of Org/Env/CloudClusterAdmin fire `signal_reason=privilege_escalation` with the role + target in `decision_reason`. `/events?auth_role=OrganizationAdmin` filters the feed.

### Auth Failure Burst Alerts

Per-actor sliding-window burst detector. When an actor crosses `AUTH_FAILURE_BURST_COUNT` (default 5) auth-failure events within `AUTH_FAILURE_BURST_WINDOW_SECONDS` (default 300), a single system alert fires via the notifier to every enabled destination — distinct from the Kafka-stream anomaly detector. Burst sends operator chat alerts; the anomaly detector emits to `audit.alerts.v1` for SIEM ingestion.

### Narrative Engine

`backend/app/services/narrative_service.py` builds a per-actor 24-hour timeline with anomaly hints (off-hours activity, deletion spikes, multi-tool use). Surfaced in the Actor Activity drawer panel from any event row's actor link.

### Notifications

Slack (realtime + daily digest), Microsoft Teams (Adaptive Card), PagerDuty Events API v2, generic webhook (SSRF-validated, HTTPS-only). Per-destination filters (`signal_type` required, `min_risk_level`, `action_category` include-list, `exclude_actions`), per-destination rate limiting with burst summarisation (60 s window), cross-destination dedup (5-min fingerprint window). Configured per-destination in `notifications.yml`; hot-reloaded on mtime change. Pipeline-silence watchdog alerts at 30 min and again on recovery.

### MCP Server

`audit-mcp-server` (port 8089) — token-protected HTTP endpoint exposing AuditLens data to LLM agents via the Model Context Protocol. Token in `MCP_AUTH_TOKEN`. Eight tools defined: query events, top actors, signal summary, etc.

### CLI (`auditlens`)

Single-file Python CLI in `cli/auditlens.py`. No AuditLens codebase import — speaks to a running deployment over the REST API. Commands: `config`, `events list/get/export`, `stats compare`, `pipeline status/indexes`, `alerts test`, `doctor`. See [CLI Reference](#cli-reference).

### Observability

Prometheus scrapes the forwarder (`:8003/metrics`) and the API (FastAPI-instrumentator on `:8080/metrics`). Pre-provisioned Grafana dashboards for processing rate, consumer lag, queue depths, write latency, error rates. AlertManager wires Prometheus alerts; the AuditLens notifier handles audit-event alerts (different concern). Loki + Promtail are opt-in via the `observability` compose profile.

## Quick Start (Self-Hosted)

### Prerequisites

- Docker Engine + Compose v2 (or Docker Desktop) with ≥ 6 GB RAM
- Python 3.10+ on the host (for the CLI and the optional `./setup` wizard)
- A Confluent Cloud organisation with **audit logs enabled** — find your audit-log cluster + topic at https://confluent.cloud/settings/audit_logs/cli
- A destination Kafka cluster (Standard or Dedicated) for AuditLens to publish enriched / signal / alert / DLQ topics
- Free local ports: 80, 443, 3000, 3001, 5432, 8003, 8080, 8088, 8089, 9090, 9093, 9187

### Steps

```bash
git clone https://github.com/jegan-confluent/auditlens AuditLens
cd AuditLens

cp .env.example .env
cp .secrets.example .secrets        # if present; otherwise create .secrets manually
# Edit .env with your values — minimum required:
#   AUDIT_BOOTSTRAP, AUDIT_API_KEY, AUDIT_API_SECRET, AUDIT_TOPIC
#   DEST_BOOTSTRAP, DEST_API_KEY, DEST_API_SECRET
#   DATABASE_URL, POSTGRES_PASSWORD, GRAFANA_ADMIN_PASSWORD
#   CORS_ORIGINS, NEXT_PUBLIC_API_BASE_URL

pip install click httpx                                  # for the CLI / doctor

docker compose -f docker-compose.prod.yml up -d

python3 cli/auditlens.py doctor                          # verify
open http://localhost                                    # Caddy serves the UI
```

Or use the guided wizard which prompts for every credential, validates Kafka connectivity, generates secrets, and starts the stack:

```bash
./setup
```

The wizard is idempotent and resumable: failures save a checkpoint to `~/.auditlens_setup_checkpoint.json` and re-running picks up where it left off. See `scripts/bootstrap_auditlens.py` for the seven phases.

### Required env vars

| Variable | Purpose |
|---|---|
| `AUDIT_BOOTSTRAP` | Confluent Cloud audit-log Kafka bootstrap (e.g. `pkc-xxxxx.region.aws.confluent.cloud:9092`) |
| `AUDIT_API_KEY` / `AUDIT_API_SECRET` | Kafka API credentials scoped to the audit-log cluster |
| `AUDIT_TOPIC` | Audit-log topic name (default `confluent-audit-log-events`) |
| `DEST_BOOTSTRAP` | Destination Kafka cluster bootstrap for processed topics |
| `DEST_API_KEY` / `DEST_API_SECRET` | Destination Kafka API credentials |
| `DATABASE_URL` | Postgres connection string (`postgresql+psycopg://auditlens:…@postgres:5432/auditlens`) |
| `POSTGRES_PASSWORD` | Postgres admin password |
| `GRAFANA_ADMIN_PASSWORD` | Grafana login password |
| `CORS_ORIGINS` | Comma-separated origins the API allows (include your public URL) |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend → API base path; usually `/api` so Caddy reverse-proxies |
| `API_AUTH_ENABLED` | Bearer-token auth on every API endpoint (default `true` — keep on in any shared environment) |
| `API_AUTH_TOKEN_FILE` | Path to JSON token roster (default `/run/secrets/auditlens-api-tokens.json`) |

Full reference: `.env.example` (110 documented variables covering Kafka tuning, retention, queue sizing, IAM enrichment, Schema Registry, Tableflow, cold storage, MCP, AWS Secrets Manager).

## Internal Deployment (Confluent)

Specifics for the Confluent-internal deployment on `aws.cse.confluent.io`. **Skip this section if you are self-hosting.**

| Item | Value |
|---|---|
| Live URL | https://auditlens.aws.cse.confluent.io |
| Login | Cognito-fronted (Google IdP, restricted to `@confluent.io`) |
| EC2 host | `ec2-user@98.95.144.160` (key: `~/.ssh/auditlens.pem`) |
| AWS account | `937249942019` (CLI profile: `confluent`) |
| Region | `us-east-1` |
| ALB | `auditlens-alb`, DNS `auditlens-alb-1391223149.us-east-1.elb.amazonaws.com`, hosted zone `Z35SXDOTRQ7X7K` |
| ACM cert | `arn:aws:acm:us-east-1:937249942019:certificate/494299da-3244-4ba3-8ad1-e0142f1448d8` |
| Cognito pool | `us-east-1_ZLjjst7O8`, domain `auditlens-auth.auth.us-east-1.amazoncognito.com` |

### Two-tier secrets model

- **Self-hosted (default):** all secrets in `.env` / `.secrets` on the host. Works on any platform.
- **Internal hardening:** AWS Secrets Manager. Set `AWS_SECRETS_MANAGER_ENABLED=true` in `.env`, attach an EC2 IAM role with `secretsmanager:GetSecretValue` on `auditlens/*`. `src/core/secrets.py` overlays HIGH-sensitivity env values with ASM-sourced versions (15 min in-memory TTL).

The internal deployment uses ASM. The `auditlens/prod/confluent` secret holds the Kafka bootstrap + shared `cloud_api_key` / `cloud_api_secret`. `auditlens/prod/postgres` holds the DB password. `auditlens/prod/notifications` holds Slack/Teams webhook URLs.

### Deploy workflow

```bash
# From your Mac, after committing:
. $HOME/.cc-dotfiles/caas.sh && git push-external origin main && make deploy
```

`make deploy` rsyncs the working tree to `~/AuditLens/` on EC2 (excluding `.env`, `.secrets`, `data/`, `node_modules/`), rebuilds containers via `docker compose up -d --build --force-recreate`, waits 10s for the API to be ready, and runs `alembic upgrade head` inside the api container. `git push-external` is the Confluent-internal wrapper that enforces the proprietary-code check before pushing to public GitHub.

### `make secrets-create` workaround

The `make secrets-create` target currently has a path issue on EC2. Until that's fixed, push secrets to ASM directly:

```bash
AWS_PROFILE=confluent SECRET_DRY_RUN=false bash scripts/secrets/create_secrets.sh
```

After updating, containers see new values on the next ASM refresh (≤ 15 min) — no restart needed unless `AWS_SECRETS_MANAGER_ENABLED` itself was just turned on, in which case `docker compose up -d --force-recreate api forwarder`.

### Cognito setup scripts

`infra/aws/` (gitignored — internal only) contains five shell scripts that built the ALB + ACM cert + Cognito pool + Google IdP + pre-signup Lambda. Re-run idempotently if you ever need to recreate the infra. See the in-script docstrings.

## CLI Reference

The CLI is single-file (`cli/auditlens.py`) and depends only on `click` + `httpx`. Config lives in `~/.auditlens.conf` (`chmod 600`) and / or env vars `AUDITLENS_URL`, `AUDITLENS_TOKEN`, `AUDITLENS_PG_HOST`, `AUDITLENS_PG_USER`, `AUDITLENS_PG_DB`.

```bash
pip install click httpx
python3 cli/auditlens.py --help
```

### `config set` / `config show`

Persist deployment URL, optional bearer token, Postgres connection hints, and compose-file path. `show` masks the token.

```bash
python3 cli/auditlens.py config set --url http://localhost --token <bearer>
python3 cli/auditlens.py config show
```

### `events list`

Padded table — time | actor | action | signal | reason | risk.

```bash
python3 cli/auditlens.py events list                                  # last 24h, 20 rows
python3 cli/auditlens.py events list --signal action_required --since 7d
python3 cli/auditlens.py events list --actor jegan --limit 100 --json
```

### `events get <event_id>`

Pretty-print every field of one event as `key: value`. Nested dicts inline as JSON.

```bash
python3 cli/auditlens.py events get 77549
```

### `events export`

Stream the filtered list to CSV or JSON. Server cap is `EXPORT_MAX_ROWS = 50_000`; CSV gets a truncation marker if you hit the cap.

```bash
python3 cli/auditlens.py events export --since 7d --format csv --out events.csv
python3 cli/auditlens.py events export --signal action_required --format json > alerts.json
```

### `stats compare`

Side-by-side metric table for two windows. Calls `GET /api/events/compare`.

```bash
python3 cli/auditlens.py stats compare --period-a 24h --period-b 7d
```

```
Metric             Period A (24h)   Period B (7d)
Total events       1759             8625
Action required    120              540
Top actor          alice (94)       alice (430)
```

### `pipeline status`

API health + 5m / 60m counts + last-event freshness. Prints a red `WARNING` if last event is older than 30 min.

### `pipeline indexes`

Shells into postgres to print `\di audit_events*`. Must run from the deploy host.

### `alerts test`

POSTs to `/api/settings/notifications/test`. Fires a real test notification to every enabled Slack/Teams/PagerDuty/webhook destination in `notifications.yml`. Requires the `admin` role when `API_AUTH_ENABLED=true`.

### `doctor`

See [`make doctor`](#make-doctor) below.

## `make doctor`

End-to-end deployment health check. Seven independent checks, each wrapped — one broken check never crashes the run. Summary table at the end; exit code reflects the worst severity.

```bash
make doctor                       # or: python3 cli/auditlens.py doctor
```

| # | Check | What it does |
|---|---|---|
| 1 | Docker services | `docker compose ps`; flags non-running (critical), unhealthy (critical), starting (warn), or no-healthcheck (warn). Tails 5 log lines on critical. |
| 2 | Forwarder connectivity | `GET :8003/health`; warns if `last_event` > 30 min. |
| 3 | API health | `GET <URL>/health` (warns >2 s) + `/api/events?limit=1` smoke. |
| 4 | Postgres connectivity | `psql` for signal-row, noise-row, and last-hour counts; warns on zero events in last hour. |
| 5 | Dead-tuple bloat | `pg_stat_user_tables` top 5; warns when any table > 100 000 dead tuples. |
| 6 | Config sanity | Parses `.env`; verifies `AUDIT_BOOTSTRAP`, `AUDIT_TOPIC`, `DEST_BOOTSTRAP`, `DATABASE_URL`, `CORS_ORIGINS`, `NEXT_PUBLIC_API_BASE_URL` are non-empty. Values never printed. |
| 7 | Domain reachability | `GET https://auditlens.aws.cse.confluent.io/health` (5 s timeout). `skipped` (not critical) if the host has no internet. |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All green or skipped-only |
| 1 | Any warning (suitable for "investigate when free") |
| 2 | Any critical (suitable for cron / CI gates) |

### Live sample (internal deployment)

```
Component                     Status        Detail
─────────────────────────────────────────────────────────────────
Docker: api                   ✅ ok        healthy
Docker: auditlens-forwarder   ✅ ok        healthy
Docker: postgres              ✅ ok        healthy
Docker: caddy                 ✅ ok        healthy
Docker: frontend              ✅ ok        healthy
Docker: grafana               ✅ ok        healthy
Docker: prometheus            ✅ ok        healthy
Docker: mcp-server            ⚠️  warn     starting
Docker: alertmanager          ⚠️  warn     running (no healthcheck)
Docker: postgres-exporter     ⚠️  warn     running (no healthcheck)
Forwarder connectivity        ✅ ok        healthy
API health                    ✅ ok        17ms
API /events smoke             ✅ ok        OK (1 item(s) returned)
Postgres rows                 ✅ ok        19,710 signal + 3,464,108 noise
Pipeline freshness            ✅ ok        72 events in last hour
Dead-tuple bloat              ✅ ok        no tables over threshold
Config vars                   ✅ ok        all required vars set
Domain reachability           ✅ ok        HTTP 200 (28ms)
```

### Wire into cron

```cron
*/15 * * * * cd ~/AuditLens && AUDITLENS_URL=http://localhost python3 cli/auditlens.py doctor > /tmp/doctor.out 2>&1 || /usr/local/bin/alert "AuditLens doctor exit $?"
```

## Operations

### Deploy

```bash
make deploy                 # rsync + rebuild + migrate (EC2)
make deploy-check           # dry-run rsync only
make update                 # pull + rebuild + migrate (in-place)
make repair                 # heal a broken install (idempotent)
```

Self-hosted updates: `git pull && make update`. Existing `.env` / `.secrets` are preserved. The wizard re-execs on launch if behind `origin/main`; disable with `--no-update` or `AUDITLENS_NO_UPDATE=1` for CI.

### Logs

```bash
# Local
docker compose -f docker-compose.prod.yml logs -f auditlens-forwarder
docker compose -f docker-compose.prod.yml logs -f api

# EC2 (over SSH)
make logs
```

### Migrations

Migrations live in `backend/alembic/versions/`. `make deploy` runs `alembic upgrade head` inside the api container after rebuild. To run manually:

```bash
make migrate
# or:
docker compose -f docker-compose.prod.yml exec api \
  bash -c "cd /app/backend && python -m alembic upgrade head"
```

If the api container is read-only and the migration needs DDL that touches a path Alembic can't reach, apply it directly:

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U auditlens -d auditlens -c "ALTER TABLE …"
```

Then update `alembic_version` to record the manual application.

### Secrets rotation

**ASM-backed (internal):**

```bash
# Update the secret in ASM (e.g. via CLI or console), then:
# Forwarder + API pick up new values within 15 min (TTL cache).
# Or force a refresh:
docker compose -f docker-compose.prod.yml restart api forwarder
```

`make secrets-rotate` re-pushes current `.env` values into ASM. `make secrets-enable` flips `AWS_SECRETS_MANAGER_ENABLED=true` and recreates containers.

**Env-backed (self-hosted):**

```bash
vi .env                                                          # edit the value
docker compose -f docker-compose.prod.yml up -d --force-recreate # picks it up
```

### Scaling

A single t3.large (2 vCPU, 8 GB) handles ~3 M noise events/day + 20 k signal events/day with consumer lag under 30 s. Bottlenecks in order of likelihood:

1. **Postgres write throughput** — bump `DB_WRITE_BATCH_SIZE` and `WRITER_BULK_QUEUE_SIZE`; consider a larger instance if `pg_isready` latency climbs.
2. **Consumer lag on the audit topic** — multi-partition source clusters benefit from `KAFKA_CONSUME_BATCH_SIZE` increases plus a stable `group.instance.id`.
3. **Frontend response time** — Next.js is stateless; put two replicas behind the ALB if you outgrow one.

Cross-region Kafka (US West → AP South etc.) is the most common source of stalls — the forwarder is tuned for it (30 s socket timeout, 45 s session timeout, 15 s heartbeat) but you may need to bump those further. See `audit_forwarder.py` for the live values.

## Testing

### Running tests

```bash
# Default — runs the full suite (~50 s on a M-series Mac)
CONFLUENT_CLOUD_API_KEY="" CONFLUENT_CLOUD_API_SECRET="" \
CONFLUENT_API_KEY="" CONFLUENT_API_SECRET="" \
.venv/bin/pytest -q

# Subset
.venv/bin/pytest tests/test_event_signals.py -v
.venv/bin/pytest backend/tests/test_noise_api.py::test_summary_methods_returns_unified_distribution
```

Current count: **782 passing, 5 skipped, 0 failures**. The creds-unset prefix neutralises `.env` bleed-through into the test process (the dotenv loader uses `override=False` by default, so unsetting them BEFORE pytest imports keeps the test harness honest).

### `make doctor` as an integration test

```bash
make doctor && echo "deployment green"
# exit 0 → all checks ok; exit 1 → warnings; exit 2 → critical
```

Use in CI to gate post-deploy verification.

### Adding tests

- Forwarder + product modules: `tests/test_*.py`
- Backend API + DB models: `backend/tests/test_*.py`
- One test file per module under test. Use `pytest.mark.asyncio` for async tests (auto-mode is enabled in `pytest.ini`).
- Frontend currently has no Vitest/Jest harness — `frontend/package.json` ships only a `node tests/render-smoke.mjs` smoke. Adding a real frontend test framework is on the roadmap.

## Roadmap

| Item | Status | Notes |
|---|---|---|
| One-click AMI | Not started | Pack the stack into an AWS Marketplace AMI for a 5-minute install |
| Kubernetes / Helm chart | Templates exist | `deploy/kubernetes/` covers the forwarder only; no Helm chart |
| Flink windowed analytics | Not started | Sliding-window denial rate + cross-environment actor correlation as Flink SQL views over `audit.enriched.v1` |
| OIDC / SSO (API layer) | Cognito wired at ALB | App-layer OIDC remains bearer-token. Wiring Cognito JWTs into FastAPI is on the list |
| Frontend test framework | Not started | Vitest + React Testing Library. No tests in `frontend/` today |
| Pre-signup Lambda | Script ready, deferred | `infra/aws/04_wire_google_idp.sh` deploys it; waits on Google OAuth credentials |
| SaaS / multi-tenant | Long term | Would require row-level tenancy on every table + Cognito-driven tenant routing |

## Contributing

```bash
git clone https://github.com/jegan-confluent/auditlens
cd AuditLens

# Spin up the stack locally (Docker)
cp .env.example .env && vi .env
docker compose -f docker-compose.prod.yml up -d

# Backend dev (without rebuilding the api container):
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/pytest -q

# Frontend dev (hot-reload):
cd frontend && npm install && npm run dev
```

Branch naming: `feat/<short>`, `fix/<short>`, `chore/<short>`. PRs that touch ingest, classification, or DB schema require a migration + tests. See `CLAUDE.md` for the project-level conventions (signal classification rules, two-table noise split, retention defaults).

## License

Apache 2.0 — see [LICENSE](./LICENSE).
