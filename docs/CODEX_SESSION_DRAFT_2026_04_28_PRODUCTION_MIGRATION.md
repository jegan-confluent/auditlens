## [2026-04-28] Session [2]

### Fixed
- FastAPI readiness and system status now use the request-scoped database session instead of the module-global engine.
  Why: Tests and runtime dependency overrides must report the actual API database, not a stale default engine.
  Files: backend/app/db/database.py, backend/app/api/routes/readiness.py, backend/app/services/system_service.py

- FastAPI startup now logs database startup-check failures and continues serving health/readiness endpoints.
  Why: Operators need graceful failure and `/ready` diagnostics instead of process exit when DB is temporarily unavailable.
  Files: backend/app/main.py

- Next.js production start command now runs the standalone server emitted by `output: "standalone"`.
  Why: `next start` is not the correct production command for standalone builds and emitted a runtime warning.
  Files: frontend/package.json

### Added
- Backend API contract tests for pagination bounds, raw payload visibility, readiness/liveness, system DB health, retention cleanup, and duplicate batch upsert.
  Why: Production migration contracts need regression coverage before expanding the new product path.
  Files: backend/tests/test_api.py

- Postgres-capable backend batch upsert helper and retention cleanup logging.
  Why: The product DB path must deduplicate replayed events and expose safe retention behavior across SQLite demo mode and Postgres production mode.
  Files: backend/app/services/event_service.py

- Production migration docs for runtime architecture, DB design, API contract, frontend migration, and deployment modes.
  Why: Operators need clear guidance for SQLite demo mode, bundled Postgres PoC mode, external Postgres production mode, Docker lite mode, observability mode, and troubleshooting.
  Files: docs/Product_Runtime_Architecture.md, docs/DB_Design.md, docs/API_Contract.md, docs/Frontend_Migration.md, docs/Deployment_Guide.md

- Frontend lockfile generated for reproducible Next.js installs.
  Why: Docker and local validation should resolve the same dependency tree.
  Files: frontend/package-lock.json

### Removed
- None.
  Why: Streamlit dashboards and existing Kafka-native path were intentionally preserved.
  Files: none

### Architecture Decisions
- Keep the new FastAPI and Next.js product path alongside Streamlit while preserving Kafka-native ingestion and canonical topics.
  Why: The migration should be gradual and must not break existing Streamlit dashboards.
  Impact: Future work should continue improving `forwarder -> DB -> FastAPI -> Next.js` without removing Streamlit yet.

- Treat `raw_payload_json` as detail-only evidence.
  Why: List responses must remain fast and readable while preserving raw audit evidence for investigation.
  Impact: Future list/table APIs should continue excluding raw payload by default.

- Keep observability profile-gated in Docker.
  Why: Docker lite mode should remain lightweight.
  Impact: Prometheus, Grafana, Loki, and Promtail should remain optional unless explicitly started.

### Known Issues / Not Done
- Frontend dependency audit reported vulnerabilities in the current Next.js dependency set.
  Why deferred: The build passes, but upgrading Next.js may require a separate compatibility pass.

- Full Docker compose boot, live Kafka replay, and managed Postgres validation were not completed in this session.
  Why deferred: This stop point focused on backend/frontend contract hardening and local SQLite API validation.

- The repository remains broadly dirty with pre-existing uncommitted/untracked work outside this session.
  Why deferred: This session avoided reverting or rewriting unrelated user/workspace changes.
