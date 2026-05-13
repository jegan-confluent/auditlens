# Changelog

All notable changes to AuditLens are documented in this file.

Session memory note:

- Historical versioned release notes below are preserved as-is.
- New Codex session entries should be appended only.
- New session entries must use the structured `Session [N]` format described in `AGENTS.md`.
- `VERSION` is the single source of truth; bump it and add a `[X.Y.Z]` entry
  here in the same commit. See `docs/VERSIONING.md`.

## [3.1.0] - 2026-05-07

Three-phase security and stability hardening pass following the codebase
audit captured in `AUDIT_REPORT.md`. Frontend behaviour and `audit_forwarder.py`
structure are unchanged; this is API-side, infrastructure, and data-integrity
work only.

### Phase 1 — Security hardening (commit bebb70e)

#### Added
- API token authentication: `API_AUTH_ENABLED=true` is the default in
  `.env.example`; constant-time `hmac.compare_digest` token matching
  (`src/product/auth.py`).
- Security response headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`) on every API response (`backend/app/main.py`).
- Bounded producer retries with `MAX_PRODUCE_RETRIES=10` and DLQ fallback
  on retry exhaustion (`audit_forwarder.py`).
- CI test gate: `.github/workflows/tests.yml` runs `compileall`, `pytest`,
  and the frontend build on every push/PR.

#### Changed
- `raw_payload_json` is redacted by default on `GET /events/{id}`; only
  authenticated admin tokens see the full payload.
- CORS allow-headers narrowed from `*` to `Content-Type, Authorization,
  X-Actor`.
- Slow-query log lines no longer include query strings.
- Generic 500 responses no longer echo `request.url.path`.

#### Security
- `.gitignore` extended to cover `**/*.backup*` and `**/*.bak`.
- DB write buffers stay intact until `write_batch()` succeeds, preserving
  at-least-once semantics on the offset-commit boundary.

### Phase 2 — Stability + data integrity (commit 8327e32)

#### Added
- **Alembic migrations**: three baseline revisions under `backend/alembic/`.
  `make migrate` is the production schema-change path; `_ensure_columns`
  remains the SQLite demo path.
- **DB pool tuning + `statement_timeout=30s`** on Postgres engines; SQLite
  gets `PRAGMA foreign_keys=ON` so the cascade FK is honoured in tests.
- **`ON DELETE CASCADE` FK** between `audit_event_triage.event_fingerprint`
  and `audit_events.event_fingerprint`. Retention cleanup also pre-deletes
  matching triage rows as a SQLite safety net.
- **Filter-options cap + cache**: `LIMIT 500` per column, 60-second
  `cachetools.TTLCache` keyed by engine identity.
- **Cached forwarder health snapshot** (5 s TTL, 0.5 s tight HTTP timeout)
  so `/ready` and `/pipeline/ready` are sub-millisecond on a cache hit.
- **slowapi rate limiting**: 200/min default per IP, 20/min on `GET /events`
  and `GET /events/{id}`. Probes (`/live`, `/ready`, `/pipeline/ready`,
  `/ingestion/ready`, `/health`) are exempt.
- **Keyset pagination** on `GET /events`: opaque `cursor` query param
  encoding `(timestamp, id)`, `next_cursor` field on the response envelope,
  backwards-compatible with the existing offset path.

### Phase 3 — Remaining security gaps (this release)

#### Added
- **`mask_sensitive_text()` in `audit_forwarder.py`**: scrubs free-form
  Kafka error messages, exception strings, and Authorization-header
  fragments before they reach the logger or `delivery_errors["last_error"]`.
- **Expanded redaction allowlist** in `mask_config_for_logging()` and
  `redact_value()` covering `authorization`, `bearer`, `cookie`,
  `client_secret`, `client_id`, `access_token`, `refresh_token`, `id_token`,
  `api_secret`, `private_key`, `passphrase`, and `x-api-key`.
- **Schema-watcher hardening**: the container now writes detected method
  changes to `/app/data/schema_methods.json` (writeable volume) and never
  rewrites Python source. `methods.py` reads the JSON at startup and unions
  it with the hard-coded defaults. `read_only: true` on the compose service.
- **K8s NetworkPolicy** (`deploy/kubernetes/networkpolicy.yaml`): default-
  deny baseline allowing only ingress-controller → 8080, Prometheus → 8003,
  egress to Confluent Cloud (TCP/9092, 443) and in-cluster Postgres (5432).
- **K8s deployment README** explaining sealed-secrets / external-secrets-
  operator policy, with a checklist for production cutover.
- **AWS Terraform `SECURITY_NOTES.md`** documenting the egress restriction
  and ALB HTTPS listener changes that are still pending.

#### Changed
- Silent `except: pass` in
  `backend/app/db/models.py` (`_resource_enrichment`, `_source_enrichment`)
  and `src/product/actor_enrichment.py` (`_identity_map`) replaced with
  `logger.debug(... exc_info=True)`.
- Kafka delivery errors masked at capture time inside `delivery_callback`
  *and* on the heartbeat log path.
- Kafka consume errors and DB-writer connection errors run through
  `mask_sensitive_text()` before being logged or recorded.
- `deploy/terraform/aws/vpc.tf` egress rule carries a `TODO(security)`
  block referencing `SECURITY_NOTES.md`.

#### Security
- `VERSION` is now the single source of truth. The current release matches
  the codified Alembic schema, the Phase 1+2 hardened API, and the Phase 3
  log-masking + supply-chain fixes.

## [2.2.0] - 2025-12-14

### Added

#### Forwarder
- **Dead Letter Queue (DLQ)**: Failed events are now sent to `audit.dlq.v1` topic for later reprocessing
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

## [2026-04-29] Session [Fresh Runability]

### Fixed
- Cleaned fresh-machine runability by ignoring local bundles, archives, env files, frontend build output, Python caches, data directories, and SQLite database files.
  Why: A fresh clone should not pick up local runtime artifacts or package backup files.
  Files: .gitignore, .dockerignore

- Made Docker Compose modes clearer: default product mode is forwarder/API/frontend, Postgres profile adds Postgres, observability profile adds only monitoring services, and Streamlit remains available behind the `streamlit` profile.
  Why: The production path should start cleanly without optional observability or legacy UI services unless explicitly requested.
  Files: docker-compose.yml

- Sanitized install templates and documentation token examples.
  Why: Safe templates must not contain real-looking credentials or copy-pasteable secret values.
  Files: install.template.yaml, docs/MCP_INTEGRATION_GUIDE.md

### Added
- Added a safe `.env.example` for SQLite demo, Postgres product mode, forwarder DB writer settings, and frontend API URL configuration.
  Why: A fresh user needs a known-good local template without real secrets.
  Files: .env.example

- Added operational scripts for SQLite demo startup, Postgres product startup, stop, health checks, and security scanning.
  Why: A fresh user should be able to copy `.env.example`, run one script, and verify API/UI health.
  Files: scripts/run_sqlite_demo.sh, scripts/run_postgres_product.sh, scripts/stop_all.sh, scripts/health_check.sh, scripts/security_scan.sh

- Rewrote README quickstart for SQLite demo, Postgres product mode, optional observability, health checks, stopping, troubleshooting, and security hygiene.
  Why: Fresh-machine setup should be command-driven and easy to validate.
  Files: README.md

### Removed
- Removed checked-in Terraform provider cache binaries from `deploy/terraform/aws/.terraform`.
  Why: Provider caches are local machine artifacts, are very large, and should be restored by Terraform rather than committed.
  Files: deploy/terraform/aws/.terraform/providers/registry.terraform.io/hashicorp/aws/5.100.0/darwin_arm64/LICENSE.txt, deploy/terraform/aws/.terraform/providers/registry.terraform.io/hashicorp/aws/5.100.0/darwin_arm64/terraform-provider-aws_v5.100.0_x5, deploy/terraform/aws/.terraform/providers/registry.terraform.io/hashicorp/random/3.7.2/darwin_arm64/LICENSE.txt, deploy/terraform/aws/.terraform/providers/registry.terraform.io/hashicorp/random/3.7.2/darwin_arm64/terraform-provider-random_v3.7.2_x5

### Architecture Decisions
- Keep Streamlit present but outside the default product startup path.
  Why: Streamlit is preserved for compatibility while the production path remains FastAPI + Next.js.
  Impact: Use `docker compose --profile streamlit up -d dashboard` when the legacy dashboard is needed.

### Known Issues / Not Done
- Postgres product mode was not started with real Kafka credentials in this pass.
  Why deferred: Local `.env` was intentionally removed for security hygiene; the script was validated to fail clearly when credentials are missing.

## [2026-04-29] Session [2]

### Fixed
- SQLite demo API startup now repairs fresh Docker named-volume ownership for `/var/lib/auditlens` before starting uvicorn.
  Why: Fresh volumes are root-owned, and the API must be able to create/open `/var/lib/auditlens/auditlens_api.db` while still serving as UID/GID 1000.
  Files: backend/docker_entrypoint.py, backend/Dockerfile, docker-compose.yml

- SQLite demo seeding now executes inside the API container as UID/GID 1000.
  Why: After the API service starts as root only long enough to drop privileges, exec commands default to root; with dropped capabilities, root could not read some app files during seed execution.
  Files: scripts/run_sqlite_demo.sh

### Added
- API Docker entrypoint that creates/prepares the runtime data directory, chowns it to UID/GID 1000, and then drops privileges before execing the API command.
  Why: Fixes the fresh-volume permission blocker without keeping the API server process root.
  Files: backend/docker_entrypoint.py

### Removed
- none
  Why: Streamlit dashboards and existing product architecture were intentionally preserved.
  Files: none

### Architecture Decisions
- Allow the API container to start briefly as root with only `CHOWN`, `SETUID`, and `SETGID` capabilities, then run the actual API process as UID/GID 1000.
  Why: Docker named volumes require startup ownership repair on first use, but the long-running API process should remain non-root.
  Impact: Future API container changes should preserve the entrypoint privilege drop and avoid reintroducing service-level `user: "1000:1000"` unless volume ownership is handled elsewhere.

### Known Issues / Not Done
- none for the SQLite fresh-volume permission blocker.
  Why deferred: Not applicable; validation passed with a fresh volume, seed data, health checks, and Topic/Create filtering.

## [2026-04-29] Session [3]

### Fixed
- `/ready` now reports strict operational readiness with HTTP 503 for DB, forwarder, or DB writer degradation and HTTP 200 only when all required product-path dependencies are ready.
  Why: Readiness probes must not mark the API ready when ingestion or DB writes are degraded.
  Files: backend/app/api/routes/readiness.py, backend/tests/test_api.py

- `/admin/retention/cleanup` now requires an admin token when `API_AUTH_ENABLED=true` while preserving unauthenticated dev mode when auth is disabled.
  Why: Retention cleanup can delete data and must not be exposed as an unauthenticated production endpoint.
  Files: backend/app/api/routes/admin.py, backend/tests/test_api.py

- Event fingerprints for timestamp-missing payloads no longer include wall-clock fallback time.
  Why: Restart/replay of malformed timestamp-missing events must not create duplicate rows.
  Files: src/product/event_normalization.py, tests/test_productization.py

### Added
- Final v1 session wrap for the next Codex/browser session.
  Why: The next session needs a concise handoff for real Kafka/Postgres demo validation without reconstructing the full thread.
  Files: docs/session-history/CODEX_SESSION_WRAP_2026_04_29_FINAL_V1.md

### Removed
- none.
  Why: This wrap/fix entry did not remove product code.
  Files: none

### Architecture Decisions
- Treat `/health` as process liveness and `/ready` as strict operational readiness.
  Why: Operators need a clear distinction between an API process that is alive and a full ingestion path that is ready.
  Impact: Demo scripts or deployments should use `/health` for liveness and `/ready` for full product-path readiness.

### Known Issues / Not Done
- Postgres product mode still needs the next live run with real Kafka credentials and create/delete topic evidence.
  Why deferred: This session focused on hardening, cleanup, validation, and handoff, not a new live Kafka demo run.

## [2026-05-05] Session [1]

### Fixed
- Source/IP display now uses actual audit payload source information and never falls back to cluster IDs.
  Why: The Events table was misleadingly showing values like `lkc-k9382g` in the Source/IP column when Confluent did not provide a client IP.
  Files: src/product/source_enrichment.py, src/product/event_normalization.py, src/product/event_intelligence.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/components/AuditEventTable.tsx, frontend/components/EventDetailDrawer.tsx, backend/tests/test_api.py, tests/test_event_intelligence.py

- Actor display now uses computed enrichment fields with manual mapping support and safe fallbacks for raw Confluent IDs.
  Why: Raw IDs such as `u-*` and `sa-*` are not enough for operators; mapped names/emails should be shown when available while preserving raw IDs for auditability.
  Files: src/product/actor_enrichment.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/components/AuditEventTable.tsx, frontend/components/EventDetailDrawer.tsx, backend/tests/test_api.py, tests/test_event_intelligence.py

- Resource type filtering now accepts mixed Confluent/UI values and returns canonical lowercase resource types.
  Why: Filtering was exact and case-sensitive, so values like `TOPIC`, `Topic`, and `topic` could produce confusing missing-data behavior.
  Files: src/product/event_normalization.py, backend/app/services/event_service.py, backend/app/services/filter_options_service.py, backend/app/services/summary_service.py, backend/app/schemas/event.py, backend/tests/test_api.py, tests/test_productization.py

- Destructive derived filtering now prefilters delete actions before bounded derived classification.
  Why: Older topic delete events could be hidden behind newer routine activity when derived filtering scanned only the latest bounded candidate set.
  Files: backend/app/services/event_service.py, backend/tests/test_api.py

- Triage state now caches file-backed status in memory instead of reading the triage JSON file per event.
  Why: Row rendering should not perform repeated file reads for every listed event.
  Files: src/product/triage_store.py

### Added
- Deterministic source enrichment fields: `source_display`, `source_reason`, `client_id`, `connection_id`, and `request_id`.
  Why: The UI needs a trustworthy Source/IP column and the drawer needs structured connection/request context without showing raw JSON by default.
  Files: src/product/source_enrichment.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/lib/types.ts, frontend/components/EventDetailDrawer.tsx

- Event-level `decision_reason`.
  Why: Operators need to understand why an event was classified as action-needed, review, info, or noise.
  Files: src/product/event_intelligence.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/lib/types.ts, frontend/components/AuditEventTable.tsx, frontend/components/EventDetailDrawer.tsx

- Lightweight triage lifecycle endpoint and UI controls.
  Why: Action-needed events should not stay visually action-needed forever after an operator acknowledges, approves, investigates, resolves, or marks them false positive.
  Files: src/product/triage_store.py, backend/app/api/routes/events.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/lib/api.ts, frontend/app/events/page.tsx, frontend/components/AuditEventTable.tsx, frontend/components/EventDetailDrawer.tsx, frontend/app/globals.css, backend/tests/test_api.py

- `/events?debug=true` diagnostic metadata.
  Why: Developers/operators need to explain filter behavior and distinguish DB filters from bounded derived filters.
  Files: backend/app/api/routes/events.py, backend/app/services/event_service.py, backend/app/schemas/response.py, backend/tests/test_api.py

- Audit Decision Engine session handoff.
  Why: The next session needs a compact continuation point with current state, validations, caveats, and next actions.
  Files: docs/session-history/CODEX_SESSION_HANDOFF_2026_05_05_AUDIT_DECISION_ENGINE.md

### Removed
- none.
  Why: This pass intentionally avoided architecture changes, Streamlit removal, schema migrations, and product refactors.
  Files: none

### Architecture Decisions
- Keep triage as an additive file-backed layer rather than modifying event classification or changing the DB schema.
  Why: Triage is an operator workflow state; it should not mutate the immutable audit event or require a migration during this hardening pass.
  Impact: Current triage is appropriate for single-instance product mode, not multi-instance HA.

- Canonicalize resource types at API/filter boundaries without migrating historical rows.
  Why: Historical data may contain mixed labels; compatibility is safer than an immediate data rewrite.
  Impact: New writes normalize resource types, while API responses and filters canonicalize old values.

- Keep derived signal/impact/change filters bounded unless backed by an indexed prefilter.
  Why: These fields are computed and not persisted, so scanning the entire DB synchronously would risk performance.
  Impact: Destructive filters are helped by `action_category=Delete`; other derived filters remain bounded.

### Known Issues / Not Done
- Full `pytest -q` currently fails during collection because `tests/test_bootstrap_setup.py` imports deleted `scripts/bootstrap_auditlens.py`.
  Why deferred: This appears tied to prior repo cleanup/deprecation work and should be handled deliberately by either updating the test or restoring a deprecated shim.

- Actor enrichment remains manual/fallback only.
  Why deferred: No Confluent IAM API lookup was added; avoiding external calls and extra product scope was intentional.

- Triage is file-backed and single-instance oriented.
  Why deferred: Multi-instance persistence would require a stronger storage contract and likely a DB table/migration, which was outside this pass.

- Existing DB rows may physically retain mixed-case resource types.
  Why deferred: API and filter layers now canonicalize them without a migration.
