# AuditLens

AuditLens is real-time audit intelligence for Confluent/Kafka audit events.

Runtime path:

```text
Kafka -> audit_forwarder -> DB -> FastAPI -> Next.js UI
```

**Current UI:** Next.js frontend at `frontend/` (port 3000) — this is the product path.

> **Legacy:** The Streamlit dashboard at `dashboard/` (profile `streamlit`) has been archived to `archive/dashboard/` (May 2026). It is no longer on the product path. Start it only with `docker compose --profile streamlit up -d dashboard` for historical reference.

## Modes

- SQLite demo mode: API + frontend with local SQLite and sample seed data.
- Postgres product mode: Kafka forwarder + Postgres + FastAPI + frontend.
- Observability mode: optional Prometheus, Grafana, Loki, and Promtail profile.

Default Docker Compose does not start Prometheus, Grafana, Loki, or Promtail.

## Prerequisites

- Docker Desktop
- Docker Compose v2
- Kafka/Confluent audit topic credentials for real ingestion
- Node.js and Python only if running pieces outside Docker

## Security

**Before exposing AuditLens to any network, set `API_AUTH_ENABLED=true`.**  
All API endpoints are publicly accessible by default. See [SECURITY.md](SECURITY.md) for the
full hardening guide including token setup, role permissions, and reverse-proxy configuration.

**Data privacy:** AuditLens is self-hosted. Audit events never leave your deployment. There is
no telemetry, no phone-home mechanism, and no third-party analytics. The only outbound
connections are to your Confluent Cloud Kafka endpoint (always) and to `api.confluent.cloud`
(only when `IAM_ENRICHMENT_ENABLED=true`).

**Mac / local evaluation:** Running locally with Docker Desktop on `127.0.0.1` is safe for
evaluation. Ports are bound to localhost only, so no traffic reaches external networks.

---

## Quick Start

**Prerequisites:** Python 3.11+, Docker Desktop

```bash
git clone <repo-url>
cd AuditLens
./setup
```

The setup wizard handles everything: validates your Confluent Cloud credentials, generates `.env` and `.secrets`, and starts all services. See [INSTALL.md](INSTALL.md) for full configuration options and [USER_GUIDE.md](USER_GUIDE.md) for how to use the dashboard.

When complete:

```text
✅  AuditLens is ready.
    Open http://localhost:3000
```

**Common commands** (after setup):

```bash
make start        # Start all services
make stop         # Stop all services
make status       # Check local service health
make health       # Check EC2 forwarder + API health
make deploy       # Rsync to EC2 + rebuild containers
make deploy-check # Dry-run rsync (shows what would change)
make logs         # Tail EC2 prod logs
make test         # Run the Python test suite
make help         # Show all available commands
```

Never commit `.env`, `.secrets`, API keys, tokens, or local database files.

## SQLite Demo Quickstart

SQLite demo mode does not require Kafka credentials. It starts the API and frontend, then seeds sample audit events.

```bash
scripts/run_sqlite_demo.sh
```

Open:

- UI: `http://127.0.0.1:3000/events`
- API: `http://127.0.0.1:8080`

Useful checks:

```bash
scripts/health_check.sh
scripts/db_status.sh
curl -s 'http://127.0.0.1:8080/events?resource_type=Topic&action_category=Create'
```

Expected demo data includes:

```text
u-75rw9o created topic 'jegan-testing'
```

## Postgres Product Quickstart

1. Copy the template:

```bash
cp .env.example .env
```

2. Fill Kafka values in `.env`:

```text
KAFKA_BOOTSTRAP_SERVERS=
KAFKA_API_KEY=
KAFKA_API_SECRET=
KAFKA_AUDIT_TOPIC=confluent-audit-log-events
```

If your destination Kafka cluster differs from the audit source, also set:

```text
DEST_BOOTSTRAP=
DEST_API_KEY=
DEST_API_SECRET=
```

3. Start product mode:

```bash
scripts/run_postgres_product.sh
```

After product mode is running, a safe source-field backfill dry run is:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/backfill_event_fields.py --source-fields --dry-run
```

## Backfill Source Fields Safely

Use historical source-field backfill only when upgrading from an older version that did not persist `source_ip` or source context fields. New customers do not need a historical backfill.

Start with a dry run:

```bash
DATABASE_URL="postgresql+psycopg://auditlens:auditlens@127.0.0.1:5432/auditlens" \
PYTHONPATH=. ./.venv/bin/python scripts/backfill_event_fields.py --source-fields --dry-run --hours 4 --limit 10000
```

For a recent production window, prefer the safe wrapper:

```bash
DATABASE_URL="postgresql+psycopg://auditlens:auditlens@127.0.0.1:5432/auditlens" ./scripts/backfill_recent_source_fields.sh
```

For progressive batches, keep the window tight and let the runner advance in smaller chunks:

```bash
DATABASE_URL="postgresql+psycopg://auditlens:auditlens@127.0.0.1:5432/auditlens" \
BACKFILL_HOURS=4 BACKFILL_LIMIT=10000 BACKFILL_SLEEP_MS=250 ./scripts/backfill_recent_source_fields.sh
```

To backfill a specific older window:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/backfill_event_fields.py --source-fields --since 2026-05-05T00:00:00Z --until 2026-05-05T04:00:00Z --limit 10000
```

Run a cron job every 5 minutes only if you need a slow catch-up for historical rows:

```cron
*/5 * * * * cd /Users/jegan/playground/AuditLens && DATABASE_URL="postgresql+psycopg://auditlens:auditlens@127.0.0.1:5432/auditlens" BACKFILL_HOURS=4 BACKFILL_LIMIT=10000 ./scripts/backfill_recent_source_fields.sh >> logs/backfill_recent_source_fields.cron.log 2>&1
```

Stop cron by removing that entry from your crontab:

```bash
crontab -e
```

Monitor progress with:

```bash
scripts/db_status.sh
```

Do not run millions of rows in one shot. Keep the time window short and advance in batches until the coverage stabilizes.

## Backfill Resource Intelligence Safely

Use historical resource backfill when older rows were written before the resource snapshot and catalog fields were available. New installs do not need a historical resource backfill.

Start with a dry run:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/backfill_resource_intelligence.py --dry-run --hours 24 --limit 10000
```

For a limited batch against a recent window:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/backfill_resource_intelligence.py --hours 24 --batch-size 250 --limit 1000
```

For a force recompute when you intentionally want to refresh existing non-placeholder resource fields:

```bash
PYTHONPATH=. ./.venv/bin/python scripts/backfill_resource_intelligence.py --force --since 2026-05-05T00:00:00Z --until 2026-05-06T00:00:00Z --limit 5000
```

The script updates missing resource snapshot columns and reconciles `resource_catalog` in the same pass. It commits per batch, skips malformed rows, and logs counts only. Keep the time window short and use `--limit`/`--batch-size` to avoid large one-shot updates.

Open:

- UI: `http://127.0.0.1:3000/events`
- API: `http://127.0.0.1:8080`
- Forwarder health: `http://127.0.0.1:8003/health`

## Observability Mode

Observability is optional and not started by default.

```bash
docker compose --profile observability up -d prometheus grafana loki promtail
```

Grafana requires a non-default admin password via `.secrets`:

```text
GF_SECURITY_ADMIN_PASSWORD=<set-a-local-password>
```

## Health Checks

```bash
scripts/health_check.sh
```

The script checks:

- `docker compose ps`
- API `/ready`
- API `/system/status`
- API `/events?limit=1`
- UI `/events`

## Stop Everything

Preserve volumes:

```bash
scripts/stop_all.sh
```

Remove volumes too:

```bash
scripts/stop_all.sh --volumes
```

## Security Check

Run before pushing or packaging:

```bash
scripts/security_scan.sh
```

## Local Security Posture

AuditLens defaults to a local, single-customer deployment. Docker ports are bound
to `127.0.0.1` where the local compose file exposes them. Do not expose the API,
frontend, metrics, or observability ports publicly without network controls and
API authentication.

For shared environments, set `API_AUTH_ENABLED=true` and provide
`API_AUTH_TOKENS_JSON` or `API_AUTH_TOKEN_FILE`. Raw audit payloads are available
only from the event detail endpoint, not from the event list endpoint.

## IAM and Metrics Enrichment

AuditLens enriches principals in a strict source order:

1. Manual mapping from `IAM_MAPPING_FILE` or `ACTOR_IDENTITY_MAP_JSON`
2. Confluent IAM/Admin lookup when `IAM_ENRICHMENT_ENABLED=true` and credentials are present
3. Audit-event-derived identity from the payload itself
4. Metrics correlation when `METRICS_ENRICHMENT_ENABLED=true`
5. Raw fallback using the principal ID already present in the event

Trust model:

- Manual mapping is authoritative.
- Confluent IAM/Admin lookup is authoritative when enabled and successful.
- Audit-event-derived identity is medium confidence.
- Metrics correlation is advisory only and stays low/medium confidence unless the source labels explicitly prove identity.
- Raw fallback preserves the principal ID instead of hiding it behind a generic unknown label.

UI behavior:

- The events table prefers enriched display name and email, then falls back to the raw principal ID.
- The drawer shows actor source and confidence.
- `Unknown principal` is only used when there is no usable ID to display.

Limits:

- Metrics correlation is not identity truth.
- IAM lookup depends on tenant credentials and API availability.
- Resource intelligence is deterministic and persisted, but cluster/environment display names are only populated when they are resolvable from the payload or catalog.
- This pass did not add a sync daemon.

## Resource Intelligence

AuditLens persists a resource snapshot alongside each event and maintains a lightweight resource catalog for investigation context.

Resource context includes:

- `resource_type`
- `resource_name`
- `resource_display_name`
- `resource_scope`
- `parent_resource`
- `cluster_id` and `cluster_name` when resolvable
- `environment_id` and `environment_name` when resolvable
- `resource_criticality`
- `blast_radius_hint`
- `production_hint`

The resource catalog is best-effort and event-derived. It is upserted during ingestion when resource parsing succeeds, and it stores durable resource identity, display name, hierarchy context, and raw metadata used to derive the snapshot. Hot list queries stay column-only and do not join the catalog. AuditLens does not run a sync daemon or claim an authoritative resource inventory.

The scan ignores `.git`, `node_modules`, `.next`, `data`, backup directories, and `.env.example` placeholders.

## Troubleshooting

Docker not running:

```bash
docker compose ps
```

Port already in use:

Set alternate ports in `.env`:

```text
BACKEND_PORT=18080
FRONTEND_PORT=13000
METRICS_PORT=18003
POSTGRES_PORT=15432
```

Kafka credentials missing:

```bash
scripts/run_postgres_product.sh
```

The script prints the missing variables. Fill `KAFKA_*` or the `AUDIT_*` and `DEST_*` aliases in `.env`.

DB not ready:

```bash
curl -s http://127.0.0.1:8080/ready
docker compose logs api
docker compose logs postgres
```

UI cannot reach API:

Confirm `.env` has:

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8080
```

Then rebuild the frontend:

```bash
docker compose up --build -d frontend
```

No events visible:

- SQLite demo: rerun `docker compose exec -T api python -m backend.scripts.seed_data`.
- Postgres product: check `http://127.0.0.1:8003/health` and Kafka credentials.

Estimated event counts:

For unfiltered Postgres event lists, AuditLens uses a lightweight planner estimate for the total count so `/events` stays fast on larger tables. Filtered totals remain exact.

## Validation Commands

```bash
python3 -m compileall audit_forwarder.py src/product/db_writer.py backend/app
API_AUTH_ENABLED=false pytest -q tests/test_productization.py backend/tests/test_api.py tests/test_foundation_contract.py
npm --prefix frontend test
npm --prefix frontend run build
docker compose config --services
docker compose --profile postgres config --services
docker compose --profile observability config --services
scripts/security_scan.sh
```
