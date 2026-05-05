# AuditLens

AuditLens is real-time audit intelligence for Confluent/Kafka audit events.

Runtime path:

```text
Kafka -> audit_forwarder -> DB -> FastAPI -> Next.js UI
```

Streamlit dashboards are still present for compatibility, but the product path is the FastAPI + Next.js UI.

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

## Fresh Clone Setup

```bash
cp .env.example .env
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
