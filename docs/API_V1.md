# AuditLens API v1

AuditLens API v1 is intentionally small. It exists to expose health, recent
searchable events, and recent security signals without introducing a separate
query service or MCP dependency.

## Why API v1 Is Enough

- Health, lag, and freshness belong with the running forwarder.
- Operators need simple search and export before they need a larger API surface.
- MCP can later sit on top of API v1 rather than becoming the core interface.

## Endpoints

### `GET /api/v1/health`

Authentication required.

Returns:

- health status
- RFC3339 timestamps
- consumer lag
- freshness markers
- coverage notes
- component-level status

### `GET /api/v1/events/search`

Searches recent enriched events held in the forwarder's in-memory API buffer.
When persistence is healthy, results come from durable product storage first.

Supported query params:

- `q`
- `criticality`
- `principal`
- `method`
- `resource`
- `limit`

### `GET /api/v1/events/high-risk`

Authentication required.

Returns recent high-risk enriched events.

Supported query params:

- `q`
- `criticality`
- `principal`
- `method`
- `resource`
- `limit`

### `GET /api/v1/signals/denials`

Authentication required.

Returns recent aggregated denial summaries from `audit.signals.denials.v1`.

Supported query params:

- `limit`

### `GET /api/v1/export`

Authentication and export role required.

Exports recent enriched search results.

Supported query params:

- same filters as `/api/v1/events/search`
- `format=json|jsonl|csv`

Controls:

- scope-filtered by role
- row-capped by `API_EXPORT_MAX_ROWS`
- time-window capped by `API_EXPORT_MAX_HOURS`
- export activity audited in persistence

### `POST /api/v1/replay`

Authentication and admin role required.

Triggers a controlled replay/rebuild from Kafka evidence without changing the
steady-state ingestion contract.

Request body:

- `source_mode`: `raw` or `enriched`
- `hours`: replay the last N hours
- `from_earliest`: replay from the earliest retained Kafka offsets
- `publish_topics`: optional override to republish derived topics during replay

Returns:

- `202 Accepted` when replay starts
- replay mode and requested window metadata

Notes:

- Replay updates persistence, regenerated signals, and replay status in `/health`
- Replay is single-instance and intentionally operationally explicit
- Admins should treat replay as a controlled maintenance action

## Coverage Note

API v1 primarily serves durable product persistence and falls back to recent
in-memory buffers only when persistence is unavailable. Historical completeness
still depends on Kafka retention and the persistence window you operate.
