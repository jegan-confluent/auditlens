## [2026-04-28] Session [3]

### Fixed
- Forwarder DB writer failure state now reports explicit `backoff` during database write failures and returns to `connected` after recovery.
  Why: Operators need to distinguish DB retry/backoff from normal connected ingestion state.
  Files: audit_forwarder.py

- Next.js system status now displays DB event count and DB writer health fields from the API.
  Why: The product UI must show whether ingestion is connected, retrying, or failing.
  Files: frontend/components/SystemStatusPanel.tsx, frontend/lib/types.ts

### Added
- Forwarder DB writes now support time-based flushing in addition to batch-size flushing.
  Why: Low-volume Kafka streams should still reach the product database promptly instead of waiting for a full batch.
  Files: audit_forwarder.py

- Product DB writer now enforces event retention with configurable retention days, cleanup interval, dry-run cleanup, cleanup logs, and cleanup health metadata.
  Why: The DB path needs actual retention enforcement, not only API-side cleanup logging.
  Files: src/product/db_writer.py, audit_forwarder.py

- FastAPI readiness and system status now include forwarder DB writer ingestion state.
  Why: `/ready`, `/system/status`, and the UI need to reflect DB plus ingestion health.
  Files: backend/app/api/routes/readiness.py, backend/app/services/system_service.py, backend/app/schemas/response.py

- Focused productization tests for DB writer normalization, duplicate replay, retention deletion, DB failure backoff, and recovery.
  Why: End-to-end correctness depends on no duplicate events, usable normalized rows, and graceful DB outage handling.
  Files: tests/test_productization.py

### Removed
- None.
  Why: Streamlit dashboards and existing runtime audit improvements were intentionally preserved.
  Files: none

### Architecture Decisions
- Keep forwarder-to-DB writes on the existing normalized `audit_events` schema shared with FastAPI.
  Why: The product path should be `Kafka -> forwarder -> DB -> API -> UI` without a parallel schema or extra architecture.
  Impact: Future ingestion work should extend the shared DB writer/API schema carefully rather than adding another persistence path.

- Treat Docker validation as blocked in this environment, but validate the same DB writer, API, and UI chain locally with SQLite.
  Why: Docker daemon and Compose were unavailable, while source-level and local HTTP validation were executable.
  Impact: Full Docker/Kafka validation remains the next required environment-level proof.

### Known Issues / Not Done
- Full Docker Compose and live Kafka ingestion validation were not completed.
  Why deferred: Docker daemon socket was unavailable, `docker compose` was not supported by the installed Docker CLI, and `docker-compose` was not installed.

- Frontend dependency audit still reports vulnerabilities in the current Next.js dependency set.
  Why deferred: Build and smoke checks pass, but upgrading Next.js should be handled as a separate compatibility/security pass.

- The repository remains broadly dirty with pre-existing unrelated changes.
  Why deferred: This session intentionally avoided modifying or reverting Streamlit dashboards and unrelated runtime audit work.
