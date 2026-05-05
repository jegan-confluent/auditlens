## [2026-04-28] Session [3]

### Fixed
- Docker lite runtime now starts the forwarder, API, and Next.js frontend together for the product path.
  Why: The API image needed product modules, the shared SQLite volume needed compatible ownership, and the Next.js standalone server needed to bind on container interfaces for Docker healthchecks.
  Files: backend/Dockerfile, docker-compose.yml, frontend/Dockerfile, src/product/__init__.py

- Forwarder DB writer recovery state is visible through API readiness and system status.
  Why: Operators need to see DB writer connectivity, retry/backoff state, write counters, and last write time when ingestion is degraded.
  Files: audit_forwarder.py, backend/app/api/routes/readiness.py, backend/app/schemas/response.py, backend/app/services/system_service.py, frontend/components/SystemStatusPanel.tsx, frontend/lib/types.ts

### Added
- Real DB ingestion validation for the forwarder with batched writes, deduplication, retention cleanup metrics, and observable write-batch logs.
  Why: Proves the Kafka -> forwarder -> DB path writes normalized events without duplicate fingerprints and exposes enough state to diagnose failures.
  Files: audit_forwarder.py, src/product/db_writer.py, tests/test_productization.py

- Docker end-to-end validation evidence for the product path.
  Why: Confirms real Kafka audit events are available through FastAPI and displayed/filterable in the Next.js UI without touching Streamlit dashboards.
  Files: frontend/components/SystemStatusPanel.tsx, frontend/lib/types.ts

### Removed
- none
  Why: Streamlit dashboards and existing runtime audit improvements were intentionally left in place.
  Files: none

### Architecture Decisions
- Keep the new product path alongside the existing Streamlit path.
  Why: Product migration requires FastAPI and Next.js to mature without breaking current dashboards.
  Impact: Docker validation used explicit services `auditlens-forwarder api frontend`; Streamlit was not modified.

- Default validated runtime remains lightweight SQLite-based Docker lite mode.
  Why: The current end-to-end proof needed the smallest working path with real Kafka data.
  Impact: Postgres profile configuration is present but still needs a separate full runtime validation pass.

### Known Issues / Not Done
- Postgres profile was configuration-checked but not used for the live ingestion run.
  Why deferred: The session focused on proving real Kafka ingestion through the default/lite Docker path first.

- The current real Kafka dataset did not contain `resource=jegan-testing` for the requested Topic/Create filter.
  Why deferred: A real Topic/Create event was validated instead with `resource=error-lcc-59z2zg`.

- Local `npm --prefix frontend run build` could not run because `frontend/node_modules` is not installed in the workspace.
  Why deferred: Docker frontend build succeeded and is the production validation path.
