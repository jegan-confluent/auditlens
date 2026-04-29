## [2026-04-29] Session [1]

### Fixed
- Postgres DB writer batch results now report exact inserted counts instead of `-1`.
  Why: psycopg can return unreliable rowcount values for multi-row upserts, and operators need truthful batch-write evidence.
  Files: src/product/db_writer.py

- `/system/status` now returns degraded DB/storage diagnostics when Postgres is unavailable instead of a generic 500.
  Why: The system page must show infrastructure degradation clearly during DB outages.
  Files: backend/app/services/system_service.py

- Docker and git ignore local frontend build artifacts and dependencies.
  Why: Local `frontend/.next` and `frontend/node_modules` should not bloat Docker contexts or session drafts.
  Files: .dockerignore, .gitignore

### Added
- Production validation report covering Postgres E2E, DB failure/recovery, short-run stability, retention cleanup, frontend edge states, dependency audit, commands, risks, and readiness score.
  Why: Productization needs durable evidence for the full Kafka -> forwarder -> DB -> FastAPI -> Next.js path.
  Files: docs/Production_Validation_Report.md

- Frontend dependency remediation using Next.js 15.5.15 and a narrow PostCSS 8.5.10 override.
  Why: `npm audit` reported critical Next.js and moderate PostCSS vulnerabilities; final audit reports zero vulnerabilities.
  Files: frontend/package.json, frontend/package-lock.json

### Removed
- none
  Why: Streamlit dashboards and existing runtime audit improvements were intentionally preserved.
  Files: none

### Architecture Decisions
- Treat Postgres profile as validated for the product path with explicit `DATABASE_URL` and `FORWARDER_DATABASE_URL`.
  Why: Compose defaults still support SQLite lite mode, while Postgres mode requires explicit production-style DB URLs.
  Impact: Future Postgres runs should set both API and forwarder DB URLs.

- Keep failure-state reporting graceful at the API layer.
  Why: UI/system operators need degraded status payloads even when the database is down.
  Impact: Future system endpoints should avoid raising generic 500s for expected infrastructure outages.

### Known Issues / Not Done
- Stability run was 10 minutes, not 30 minutes.
  Why deferred: Short-run evidence was sufficient for this pass; an overnight soak is still recommended.

- Forwarder local SQLite hot-cache persistence reports storage pressure independently of the product Postgres DB writer.
  Why deferred: This belongs to existing runtime persistence tuning, which was outside the requested product-path scope.

- Kafka lag varied and increased during the constrained local Docker run.
  Why deferred: The local profile is resource-limited; production sizing still needs a longer throughput/capacity pass.
