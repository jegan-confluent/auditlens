## [2026-04-29] Session [Fix Validated Issues]

### Fixed
- Event list queries now avoid loading raw payloads, align exact filters with indexes, and use a lightweight Postgres estimate for unfiltered totals.
  Why: Testing showed broad, filtered, and no-match `/events` queries were too slow at production-path data volume.
  Files: backend/app/services/event_service.py

- Added required event query indexes and ensured missing indexes are created during DB initialization.
  Why: Existing Postgres tables need newly declared indexes without recreating the table.
  Files: backend/app/db/models.py, backend/app/db/database.py

- Invalid `time_window` values now return FastAPI validation errors.
  Why: Testing showed `/events?time_window=not-a-window` returned `200`; invalid time windows should be rejected.
  Files: backend/app/api/routes/events.py, backend/app/services/event_service.py, backend/tests/test_api.py

- Forwarder health now treats connected idle state as healthy/idle instead of unhealthy.
  Why: Testing showed restart/idleness could report `503` even when the consumer was connected and not failing.
  Files: audit_forwarder.py, tests/test_foundation_contract.py

### Added
- Added regression tests for valid/invalid `time_window` values and idle connected forwarder health.
  Why: Prevents recurrence of the validated testing issues.
  Files: backend/tests/test_api.py, tests/test_foundation_contract.py

### Removed
- Nothing removed.
  Why: Fix mode did not require deletion.
  Files: none

### Architecture Decisions
- Kept the fixes scoped to the existing forwarder -> Postgres -> FastAPI -> Next.js path.
  Why: The request was to fix validated reliability issues only, without new features or unrelated refactors.
  Impact: Streamlit dashboards and unrelated runtime audit paths remain untouched by this fix.

### Known Issues / Not Done
- Unfiltered Postgres `/events` totals now use a planner estimate to meet latency targets.
  Why deferred: Exact `count(*)` on large Postgres tables was the dominant broad-query cost; exact count semantics would need a separate cached counter or pagination contract change.
- Resource text substring searches still use `lower(... LIKE '%text%')`.
  Why deferred: The validated slow paths were broad, Topic/Create, and no-match typed filters; substring search would need trigram/full-text indexing as a separate performance task.
