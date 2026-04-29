# API Backend Foundation

Date: 2026-04-28

## Architecture

The new product backend path is:

```text
forwarder -> DB -> FastAPI -> future React/Next.js
```

This path is additive. The existing Streamlit dashboards remain unchanged and can continue to read from their current Kafka/dashboard paths while the FastAPI backend matures.

## Why Move Beyond Streamlit

Streamlit is useful for fast investigation workflows, but a production product needs a stable API boundary:

- frontend and backend can evolve independently;
- customer deployments can use SQLite for demos and Postgres for production;
- filtering, summaries, and system status become testable service contracts;
- a future React/Next.js frontend can consume the same API without embedding dashboard-specific state.

## Database Modes

The backend reads `DATABASE_URL`.

SQLite demo mode:

```bash
DATABASE_URL=sqlite:///./data/auditlens.db
```

Postgres production mode:

```bash
DATABASE_URL=postgresql://user:pass@host:5432/auditlens
```

Internally, `postgresql://` URLs are normalized to SQLAlchemy's `postgresql+psycopg://` driver URL.

## Schema

Initial table: `audit_events`

Columns:

- `id`
- `timestamp`
- `result`
- `actor`
- `action`
- `normalized_action`
- `action_category`
- `resource_type`
- `resource_name`
- `resource_display`
- `cluster_id`
- `source_ip`
- `summary`
- `raw_payload_json`
- `is_failure`
- `is_denied`
- `is_routine_noise`

Indexes:

- `timestamp`
- `actor`
- `resource_type`
- `resource_name`
- `action_category`
- `result`

## Normalized Fields

The backend stores the same investigation fields expected by the clean dashboard:

- `normalized_action`
- `action_category`
- `resource_type`
- `resource_name`
- `resource_display`
- `is_failure`
- `is_denied`
- `is_routine_noise`

Routine hiding is not applied in the API foundation. All rows remain visible.

## API Contract

### `GET /health`

Returns API health and active database mode.

### `GET /events`

Query parameters:

- `time_window`: examples `60`, `60m`, `24h`
- `resource_type`
- `resource`: partial case-insensitive match against `resource_name`, `resource_display`, and `summary`
- `action_category`
- `actor`
- `result`
- `limit`: default `100`, max `1000`
- `offset`: default `0`

### `GET /events/{event_id}`

Returns one event including `raw_payload_json`.

### `GET /summary`

Returns event totals and grouped counts by action category, resource type, and result.

### `GET /filters/options`

Returns distinct filter options for resource types, action categories, results, and actors.

### `GET /failures`

Returns failed or denied events.

### `GET /deletions`

Returns delete-category events.

### `GET /system/status`

Returns:

- `consumer_state`
- `last_successful_poll`
- `retry_count`
- `consecutive_error_count`
- `last_error`
- `consumer_lag`
- `records_consumed_total`
- `storage_usage`
- `database_mode`

The API uses forwarder health when available and degrades to an `unknown` consumer state when it cannot reach the forwarder.

## How To Run

SQLite demo:

```bash
DATABASE_URL=sqlite:///./data/auditlens_api.db uvicorn backend.app.main:app --host 127.0.0.1 --port 8080
DATABASE_URL=sqlite:///./data/auditlens_api.db python3 -m backend.scripts.seed_data
```

Docker optional API profile:

```bash
docker compose --profile api up -d api
```

Postgres:

```bash
DATABASE_URL=postgresql://user:pass@host:5432/auditlens uvicorn backend.app.main:app --host 127.0.0.1 --port 8080
```

## Sample Calls

```bash
curl -s http://127.0.0.1:8080/health
curl -s "http://127.0.0.1:8080/events?limit=10"
curl -s "http://127.0.0.1:8080/events?resource_type=Topic&resource=jegan-testing&action_category=Create"
curl -s http://127.0.0.1:8080/summary
curl -s http://127.0.0.1:8080/filters/options
curl -s http://127.0.0.1:8080/system/status
```

## Migration Plan

1. Keep the Streamlit dashboards as the current operator surface.
2. Seed and validate the FastAPI backend with SQLite.
3. Add a forwarder write path into `audit_events` once the backend contract is stable.
4. Validate Postgres mode against the same service tests.
5. Build the React/Next.js frontend against the FastAPI contract.
6. Promote the React frontend once parity with the clean dashboard investigation flows is proven.

## Current Foundation Status

Implemented now:

- FastAPI app structure
- SQLite/Postgres-capable DB layer
- `audit_events` model and indexes
- normalization service based on the clean dashboard behavior
- event, summary, filter, failures, deletions, health, and system status endpoints
- seed data with the `Topic + Create + jegan-testing` case
- API test coverage for health, data, filters, pagination, failures, and summary

Deferred:

- direct forwarder writes into `audit_events`
- Alembic production migration chain
- React/Next.js frontend
