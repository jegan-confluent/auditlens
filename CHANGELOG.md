# Changelog

All notable changes to AuditLens are documented in this file.

Session memory note:

- Historical versioned release notes below are preserved as-is.
- New Codex session entries should be appended only.
- New session entries must use the structured `Session [N]` format described in `AGENTS.md`.

## [2.2.0] - 2025-12-14

### Added

#### Forwarder
- **Dead Letter Queue (DLQ)**: Failed events are now sent to `audit_events_dlq` topic for later reprocessing
  - Includes original event, error message, source topic/partition/offset, timestamp
  - Configurable via `ENABLE_DLQ` and `DLQ_TOPIC` environment variables
- **DLQ metrics in heartbeat**: Logs now show `DLQ: X sent/Y failed` every 30 seconds
- **Bounded LRU offset cache**: Prevents memory leaks with `LRUCache(maxsize=500)`

#### Dashboard
- **Non-blocking auto-refresh**: Uses `streamlit-autorefresh` instead of blocking `time.sleep()`
- **orjson parsing**: 2-3x faster JSON parsing in Kafka consumer

#### Infrastructure
- **Complete AWS Fargate Terraform**: Production-ready deployment configuration
  - VPC with public/private subnets
  - ECR repositories with lifecycle policies
  - ECS cluster with Fargate/Fargate Spot support
  - Application Load Balancer
  - AWS Secrets Manager integration
  - CloudWatch logs, alarms, and dashboard
  - IAM roles with least-privilege policies

### Changed

#### Forwarder
- **Producer reliability**: Changed `acks="1"` to `acks="all"` for zero data loss
- **Idempotence enabled**: `enable.idempotence=True` for exactly-once semantics
- **Heartbeat logging**: Now includes DLQ statistics

#### Dashboard
- **Static consumer groups**: Changed from `dashboard-viewer-{timestamp}` to `auditlens-dashboard-viewer`
  - Prevents consumer group explosion in Confluent Cloud
  - Reduces API calls and improves monitoring clarity
- **Version bump**: v10.18 → v10.19

### Fixed
- Dashboard UI freeze during 60-second auto-refresh countdown
- Potential memory leak from unbounded offset cache dictionary
- Consumer group proliferation causing Confluent Cloud clutter

### Security
- Producer now uses `acks=all` + idempotence for audit data integrity
- Failed events preserved in DLQ instead of being lost
- Secrets stored in AWS Secrets Manager (Terraform)

---

## [2.1.0] - 2025-12-13

### Added
- Multi-topic routing (CRITICAL/HIGH/MEDIUM/LOW)
- Security alerts aggregation with denial pattern detection
- Webhook retry with tenacity
- Non-root container support
- Secrets management with 6 backend support

### Dashboard v10.18
- Theme toggle (Pastel/Clean/Professional)
- Filter presets (save/load)
- PDF compliance report export
- Clickable metric cards
- Activity heatmap in Time Insights
- Keyboard shortcuts

---

## [2.0.0] - 2025-12-08

### Added
- Initial multi-topic routing architecture
- Criticality-based event classification
- Prometheus metrics endpoint
- Docker Compose deployment
- Grafana dashboards

---

## Version Numbering

- **Major (X.0.0)**: Breaking changes, architecture changes
- **Minor (0.X.0)**: New features, non-breaking
- **Patch (0.0.X)**: Bug fixes, performance improvements

## [2026-04-28] Session [1]

### Fixed
- Clean dashboard investigation filters no longer hide valid topic creation rows when `Resource Type = Topic`, `Action Category = Create`, and routine auth/authz hiding is enabled.
  Why: Topic create events could disappear because routine auth/authz and metadata noise filtering ran too early and treated some create rows as routine authorization noise.
  Files: dashboard/app_clean.py, tests/test_dashboard_app_clean.py

- Clean dashboard table layout now preserves all key investigation columns while preventing ugly wrapping for actor, action, cluster, and source IP values.
  Why: Users needed rich detail visible without cluster IDs and IP addresses breaking across lines.
  Files: dashboard/app_clean.py, tests/test_dashboard_app_clean.py

- Audit Trail now avoids onboarding clutter above the investigation table.
  Why: Guided demo, focus strip, and helper cards pushed the table too far down for active investigations.
  Files: dashboard/app_clean.py, tests/test_dashboard_app_clean.py

### Added
- New clean dashboard entry point with simplified navigation, readable audit summaries, resource type filtering, action category filtering, row detail cross-checks, and built-in Help walkthrough.
  Why: First-time users needed a focused AuditLens experience for core workflows without the overloaded legacy dashboard surface.
  Files: dashboard/app_clean.py, tests/test_dashboard_app_clean.py, docs/AuditLens_Clean_Onboarding_Walkthrough.md

- Session handoff summary for the clean dashboard work.
  Why: Future sessions can restart from a concise Markdown summary instead of reconstructing context from chat history.
  Files: docs/CODEX_SESSION_WRAP_2026_04_28.md

### Removed
- None.
  Why: Legacy dashboard and existing dashboard files were intentionally preserved.
  Files: none

### Architecture Decisions
- Keep `dashboard/app_clean.py` as a separate clean dashboard entry point while leaving `dashboard/app.py` as the legacy full dashboard.
  Why: This reduces UX risk and preserves the existing investigation surface while the clean dashboard is tested.
  Impact: Clean dashboard changes should remain scoped to `dashboard/app_clean.py` and its tests unless explicitly promoted later.

- Treat SQLite/dashboard data as recent investigation data and make raw audit evidence available through row details rather than the default table.
  Why: Default tables must stay readable while still preserving raw-vs-normalized evidence for investigation.
  Impact: Future clean dashboard additions should keep raw CRNs and raw JSON out of default columns but available in details.

### Known Issues / Not Done
- Clean dashboard files remain untracked in git at session close.
  Why deferred: User requested a session wrap and changelog append, not a commit.

- Live manual validation for `jegan-testing` depends on that event being present in the currently loaded Kafka/dashboard window.
  Why deferred: The UI accepted the filter combination, and regression tests cover the exact topic-create filter bug, but the live event was not present in the current runtime window.

- Clean dashboard is not yet promoted as the default dashboard entry point.
  Why deferred: This session intentionally avoided changing backend, legacy dashboard, or deployment routing.

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

## [2026-04-29] Session [Testing Validation]

### Fixed
- No production code fixes were made in this testing-only session.
  Why: Testing mode limited work to validation, evidence capture, and reliability reporting.
  Files: none

### Added
- Added the AuditLens testing validation report covering Postgres soak, high-load, chaos, edge-case, data-integrity, and performance baseline results.
  Why: Provides evidence for end-to-end reliability of Kafka -> forwarder -> Postgres -> FastAPI -> Next.js UI under load and failure scenarios.
  Files: docs/Testing_Validation_Report.md

### Removed
- Nothing removed.
  Why: Testing mode did not require deletion.
  Files: none

### Architecture Decisions
- Kept validation focused on the existing product path and did not modify Streamlit dashboards.
  Why: The goal was confidence in the current end-to-end runtime rather than new functionality or UI changes.
  Impact: Future work should address only the documented reliability findings before expanding scope.

### Known Issues / Not Done
- Forwarder health can report `503` after restart when idle with no messages processed for 60 seconds.
  Why deferred: Requires a small health semantics change to distinguish idle-but-connected from unhealthy.
- Invalid `time_window` query values are accepted instead of rejected.
  Why deferred: Requires API validation change outside this testing-only pass.
- Broad or no-match filtered event queries are slow on the current Postgres dataset.
  Why deferred: Requires query-plan review and likely index/count-query tuning.
