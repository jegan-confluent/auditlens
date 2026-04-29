# AuditLens Bounded Hot Cache Validation Report

AuditLens uses SQLite as a bounded hot cache for recent dashboard/API access. It is not a long-term archive. Older audit history requires a separate archive/Tableflow integration.

## Validation Command

Run:

```bash
bash scripts/validate_bounded_hot_cache.sh
```

## Required Runtime Evidence

- `docker compose ps` shows the forwarder, dashboard, landing page, and observability services running.
- `/health` exposes:
  - `data_retention_mode=bounded_hot_cache`
  - `current_db_size`
  - `max_db_size`
  - `storage_mode`
  - `hot_cache_retention_hours`
  - `archive_enabled=false`
  - `data_loss_possible`
  - `write_guard_active`
  - `storage_degraded`
  - `rotation_trigger`
  - `last_rotation_failure_time`
- `/metrics` exposes:
  - `audit_forwarder_storage_db_size_bytes`
  - `audit_forwarder_storage_mode`
  - `audit_forwarder_rotation_total`
  - `audit_forwarder_rotation_duration_ms`
  - `audit_forwarder_storage_write_dropped_total`
- Landing page and dashboard health endpoints return HTTP 200.
- SQLite `PRAGMA integrity_check` returns `ok`.
- `enriched_events.event_id` has no duplicate primary keys.
- `current_db_size < max_db_size`.

## Current Operational Contract

- SQLite is bounded by size-triggered hot-cache rotation.
- Rotation can be triggered by startup, periodic monitor, write path, cleanup path, or manual validation.
- Rotation does not depend on `VACUUM` for correctness.
- If rotation fails, health exposes degraded state and low-priority writes are guarded.
- Recent high-priority writes are preserved when possible.

## Known Limits

- Rotation needs enough free disk to create the replacement SQLite file.
- The hot cache intentionally does not preserve all historical audit data.
- Long-term retention remains deferred until archive/Tableflow integration is explicitly implemented.
