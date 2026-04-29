# AuditLens API Contract

FastAPI exposes the product path used by the Next.js frontend.

## Runtime

- `GET /health`: process and configured DB mode.
- `GET /live`: liveness probe, returns process alive.
- `GET /ready`: readiness probe with DB reachability, event count, oldest/newest event, and storage usage.
- `GET /system/status`: DB health plus forwarder health details when the forwarder health endpoint is reachable.

## Events

- `GET /events`: paginated event list.
- `GET /events/{event_id}`: event detail, including `raw_payload_json`.
- `GET /failures`: failed events.
- `GET /deletions`: delete events.

Pagination defaults to `limit=100` and rejects limits above `500`.

Supported filters on `/events`:

- `time_window`
- `resource_type`
- `resource`
- `action_category`
- `actor`
- `result`
- `limit`
- `offset`

Raw payload contract:

- `/events` list responses do not include `raw_payload_json`.
- `/events/{event_id}` detail responses include `raw_payload_json`.

## Aggregates

- `GET /summary`: totals, failures, denials, and grouped counts.
- `GET /filters/options`: distinct resource types, action categories, results, and actors.

