# AuditLens — 360° Audit Report

Generated: 2026-05-15  
Stack: Next.js 15.5.15 / React 19.0.0 / FastAPI 0.115.6 / SQLAlchemy 2.0.30 / PostgreSQL 16  
Auditor: Claude Code (automated grep/AST analysis — read-only, no changes made)

---

## Executive Summary

AuditLens is a well-structured audit intelligence platform with strong security foundations in its core layers: zero CVEs in both Python and Node dependency trees, AES-256-GCM encryption for stored secrets, proper connection-pool configuration, and tight binding of all service ports to `127.0.0.1`. The most significant risk is that **API authentication is disabled by default** (`API_AUTH_ENABLED=false`), making all endpoints publicly accessible until the operator explicitly opts in — this is documented but constitutes a high-severity deployment risk if the API port is ever exposed externally. Secondary concerns are a small number of routes missing role guards when auth is enabled, an unbounded query in the narrative service, and the absence of a Content-Security-Policy header. Test coverage of individual service modules is thin; 13 service/route modules have no dedicated test files at all.

---

## Severity Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 1 |
| 🟠 High | 3 |
| 🟡 Medium | 11 |
| 🟢 Low | 9 |
| ℹ️ Info | 4 |

---

## Findings

### Security

| # | Severity | File:Line | Finding | Recommendation |
|---|----------|-----------|---------|----------------|
| S1 | 🔴 Critical | `backend/app/main.py:64,71-72` | **Auth disabled by default.** `API_AUTH_ENABLED` defaults to `"false"`. On any deployment that does not explicitly set this variable, every endpoint — including admin operations, settings with secrets, actor mappings, and all audit event data — is publicly accessible. The startup log warns about this, but the default should be the safe state. | Change the default to `API_AUTH_ENABLED=true` in `backend/app/core/config.py` and in `.env.example`. Provide a single-command way to generate and configure tokens so the path of least resistance is auth-enabled. |
| S2 | 🟠 High | `backend/app/api/routes/onboarding.py:128` | **`POST /onboarding/validate-cluster` has no rate limiter.** The sibling `POST /onboarding/discover` is protected at 5/minute (`onboarding.py:35`), but `validate-cluster` has neither a `@limiter.limit(...)` decorator nor an auth dependency. It accepts Confluent bootstrap credentials in the request body and makes outbound Kafka connections. | Add `@limiter.limit("5/minute")` immediately above the `@router.post("/onboarding/validate-cluster")` decorator at `onboarding.py:128`. |
| S3 | 🟠 High | `backend/app/api/routes/actor_mappings.py:143-146` | **DELETE actor-mapping requires only `_require_viewer`.** All four actor-mapping mutations (POST, PUT, DELETE) use `_require_viewer` instead of `_require_responder` or `_require_admin`. A viewer-role token should be read-only; destructive YAML writes demand a higher role. | Change `_auth: None = Depends(_require_viewer)` to `Depends(_require_admin)` at `actor_mappings.py:79,111,146` for POST/PUT/DELETE, keeping viewer for the GET. |
| S4 | 🟠 High | `backend/app/api/routes/feedback.py:69-84` | **`POST /feedback` has zero authentication.** The endpoint stores user-submitted title, description, email, and user-agent into the database with only an IP-based rate limiter. When auth is enabled, an unauthenticated caller can still write to the feedback table. | Add `_auth: None = Depends(_require_viewer)` to the `submit_feedback` signature (already imported from `patterns.py:21`). |
| S5 | 🟡 Medium | `backend/app/main.py:160-162` | **Missing Content-Security-Policy header.** The middleware adds `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy`, but not a `Content-Security-Policy`. The Next.js `next.config.ts` also has no `headers()` function configured. Without CSP, any XSS vulnerability cannot be mitigated by the browser. | Add `response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'")` in the middleware at `main.py:163`. Tighten the directive after testing. |
| S6 | 🟡 Medium | `Caddyfile:1` | **No HTTPS enforcement or HSTS in Caddyfile.** The reverse proxy listens on `:80` only. There is no TLS termination, HTTPS redirect, or `Strict-Transport-Security` header. Traffic between the browser and Caddy is plaintext, including any auth tokens. | Add a TLS site block: `example.com { redir http:// https:// permanent; header Strict-Transport-Security "max-age=31536000" }` or use Caddy's automatic HTTPS with a real domain. |
| S7 | 🟡 Medium | `backend/app/api/routes/tableflow.py:50,93,138` | **Tableflow routes bypass the standard auth dependency pattern.** `GET /tableflow/status`, `POST /tableflow/enable`, and `POST /tableflow/disable` call `_require_creds()` (which checks env vars) but have no `Depends(_require_admin)`. When `API_AUTH_ENABLED=true`, these routes are still open to any caller who doesn't need a valid role token. | Add `_auth: None = Depends(require_admin)` (imported from `backend.app.api.routes.admin`) to all three route signatures in `tableflow.py`. |
| S8 | 🟡 Medium | `backend/app/services/event_service.py:741-746` | **Audit events are mutable.** The retention cleanup nulls `raw_payload_json` on expired rows (`UPDATE audit_events SET raw_payload_json = NULL WHERE id IN ...`). The backfill service also UPDATEs `actor_display_name` and other enrichment columns on existing events (`backfill_service.py:1066,1077`). For a compliance audit store, mutability weakens the integrity guarantee. | Document the mutability scope in `SECURITY.md`. Consider a write-once policy for `timestamp`, `action`, `principal`, and `resource_name` columns enforced via a Postgres trigger. Mark enrichment columns explicitly in the schema as "derived, mutable." |
| S9 | 🟡 Medium | `backend/app/services/settings_service.py:30-38` | **AES-256-GCM key derived from `ENCRYPTION_KEY` env var with no key-rotation path.** Encryption is well implemented, but if the env var is compromised and must be rotated, there is no re-encrypt migration path. A decryption failure at line 38 logs `WARNING` and returns `None`, silently dropping a secret rather than raising. | Add a `re_encrypt_all(old_key, new_key)` utility. Change the silent `return None` on decrypt failure to raise a distinct exception so the caller can surface it to the operator. |
| S10 | 🟡 Medium | `backend/app/api/routes/onboarding.py:22-25` | **Onboarding endpoints accept Confluent Cloud `api_secret` in plain request body.** `DiscoverRequest` and `ValidateClusterRequest` carry credentials in JSON body. If transport is HTTP (see S6) or if request logs are enabled, secrets are exposed. | Enforce HTTPS (S6) as a prerequisite. Add a note in API docs that these endpoints must not be called over plaintext. Consider reading credentials from the stored settings DB instead of the request body for `discover`. |
| S11 | 🟢 Low | `backend/app/main.py:62`, `backend/app/services/event_service.py:261,289`, `backend/app/services/settings_service.py:69`, `backend/app/services/backfill_service.py:144,514`, `backend/app/api/routes/events.py:47`, `backend/app/services/pattern_service.py:21`, `backend/app/services/cold_storage_service.py:88,134,285` | **15 bare `except Exception:` clauses silently swallow errors.** Several services catch the top-level exception type and log at WARNING or below, making unexpected failures invisible. | Replace with specific exception types where possible. Where `except Exception` is truly needed (e.g., background threads), always log at ERROR with a full traceback: `logger.exception(...)`. |

---

### Code Quality

| # | Severity | File:Line | Finding | Recommendation |
|---|----------|-----------|---------|----------------|
| Q1 | 🟡 Medium | `backend/alembic/versions/` | **Migration 0008 is missing.** The sequence jumps from `0007_noise_table.py` to `0009_audit_event_patterns.py`. Alembic uses the `down_revision` chain, not filename numbers, so this won't break migrations — but it signals a migration was deleted after being applied, which is risky if it ever needs to be reapplied on a fresh database. | Document in `docs/DATABASE.md` what 0008 contained and why it was removed. If it was never applied to any environment, no action needed. If it was applied, add a no-op placeholder `0008_removed.py` to preserve the audit trail. |
| Q2 | 🟡 Medium | `backend/app/services/backfill_service.py:1` | **`backfill_service.py` is 1,116 lines with 8+ functions over 50 lines.** The largest function, `backfill_actor_display_names()` at line 863, is 166 lines. `backfill_source_fields_from_raw_payload()` (line 476) is 132 lines, and `backfill_resource_intelligence_from_raw_payload()` (line 611) is 120 lines. | Split into at least three modules: `backfill_source.py`, `backfill_resource.py`, `backfill_actor.py`. Each backfill job should own its query logic, batch loop, and progress reporting independently. |
| Q3 | 🟡 Medium | `backend/app/services/summary_service.py:227` | **`get_summary()` is 203 lines.** It handles SQLite vs. Postgres branching, grouping-sets aggregation, derived-filter scanning, and response assembly in a single function. | Extract `_postgres_aggregation()`, `_sqlite_aggregation()`, `_derived_filter_scan()`, and `_build_response()` as private helpers. The dispatcher `get_summary()` should be under 30 lines. |
| Q4 | 🟡 Medium | `frontend/app/settings/page.tsx:1` | **`settings/page.tsx` is 1,044 lines** — the largest frontend file. It mixes actor-mapping CRUD, resource catalog, notification config, cold storage, schema registry, and other unrelated settings in one component. | Split into `ActorMappingsTab.tsx`, `ResourceCatalogTab.tsx`, `NotificationsTab.tsx`, `ColdStorageTab.tsx`, `SchemaRegistryTab.tsx` co-located under `app/settings/components/`. |
| Q5 | 🟢 Low | `frontend/components/SignalBreakdown.tsx:116` | **`console.log` left in production component.** `console.log("[SignalBreakdown] tier selected:", next)` will print on every filter interaction in the browser. | Remove the line entirely. If tier-selection debugging is needed, gate it behind `process.env.NODE_ENV === 'development'`. |
| Q6 | 🟢 Low | `backend/app/main.py:127`, `backend/app/schemas/event.py:75`, `backend/app/db/models.py:404`, `backend/app/api/routes/settings.py:128,150`, `backend/app/api/routes/patterns.py:20`, `backend/app/api/routes/onboarding.py:131` | **7 `# type: ignore` annotations in production code.** Most suppress `import-untyped` for `confluent_kafka` (legitimate) or `prop-decorator` for Pydantic v2 `@computed_field` (framework quirk). | Add `types-confluent-kafka` or a stub file for the Kafka import to eliminate the `import-untyped` suppressions. The `prop-decorator` suppression is acceptable as a Pydantic v2 known issue. |
| Q7 | 🟢 Low | `backend/app/services/pattern_service.py:158` | **`_enrich_actor_display_names()` is a documented N+1 pattern** (one `LIMIT 1` query per actor). The comment acknowledges this: "N per-actor LIMIT 1 queries each take <10ms but together can exceed 2s on a busy host." `statement_timeout=10000` is set but does not prevent the loop from issuing many round-trips. | Replace the per-actor loop with a single `WHERE actor IN (:actors)` + `DISTINCT ON (actor)` query. Uses the existing `idx_audit_events_actor_display_enrichment` index and reduces N queries to 1. |

---

### Performance

| # | Severity | File:Line | Finding | Recommendation |
|---|----------|-----------|---------|----------------|
| P1 | 🟡 Medium | `backend/app/services/narrative_service.py:80` | **Unbounded query in `get_actor_narrative()`.** `query.order_by(...).all()` loads all events for an actor within the time window into memory. A high-activity service account with 50K+ events in 24h would load the full result set. No `LIMIT` is applied anywhere in the function. | Add `.limit(500)` before `.all()` and add a `truncated: bool` field to the response. Alternatively, push the `_build_chapter` aggregation into a SQL `GROUP BY` so only aggregate rows are transferred. |
| P2 | 🟡 Medium | `backend/app/services/summary_service.py:314` | **`get_summary()` scans up to 5,000 rows into Python memory** when `derived_filter_applied=True`. On a large dataset with an active signal-type filter, this materialises 5,000 ORM objects per request for in-memory filtering that could be done in SQL. | Push `_matches_derived_filters` logic into the SQL `WHERE` clause. `signal_types` and `hide_noise` are column predicates; `impact_types` and `change_types` reference `_impact_type` and `_change_type` columns that already have indexes. Eliminates the Python-side scan entirely. |
| P3 | 🟢 Low | `backend/app/api/routes/actors.py:75` | **Actor narrative endpoint has no pagination or max-events guard.** `GET /actors/{actor_id}/narrative` calls `get_actor_narrative()` (see P1) with no frontend-visible cap. An attacker or misconfigured client could hammer the endpoint and OOM the API container. | Add `time_window: str = Query(default="24h", pattern="^(1h|6h|12h|24h|7d)$")` to restrict window choices, and apply the LIMIT fix from P1. |
| P4 | 🟢 Low | `frontend/components/AuditEventTable.tsx:1` | **No virtualisation for the event table (442 lines).** The component renders all rows returned by the API. The API caps at `limit=500` by default, but rendering 500 DOM rows can cause browser jank on low-powered devices. | Wrap the table body in `@tanstack/react-virtual` (already in the JS ecosystem). Only the visible rows need real DOM nodes. |
| P5 | ℹ️ Info | `backend/app/db/database.py:73-80` | DB connection pool is well configured: `pool_size=5`, `max_overflow=10`, `pool_recycle=1800`, `pool_pre_ping=True`. The in-code comment also flags the scaling path ("bump pool_size/max_overflow when running multiple replicas"). | No action needed. |

---

### Compliance & Data

| # | Severity | File:Line | Finding | Recommendation |
|---|----------|-----------|---------|----------------|
| C1 | 🟡 Medium | `backend/app/api/routes/feedback.py:76-77` | **User email and user-agent are stored in the feedback table without a documented retention or deletion policy.** `payload.email` and `request.headers.get("user-agent")` are persisted. Under GDPR, email is personally identifiable data. | Add `feedback` table to the retention cleanup loop in `event_service.cleanup_retention()`. Document the retention period in `docs/RETENTION_POLICY.md`. Make the `email` field opt-in with a clear consent notice in the UI. |
| C2 | 🟡 Medium | `backend/app/services/event_service.py:741-746` | **Raw payload nulling during retention is `UPDATE`, not `DELETE`.** Rows are kept in perpetuity with `raw_payload_json` set to `NULL`, meaning the event skeleton (timestamp, actor, action) persists beyond the configured retention window. This may conflict with data minimisation requirements. | Document in `RETENTION_POLICY.md` that skeletal rows are intentionally retained for aggregation, and that raw PII (payload) is deleted. If full deletion is required by policy, replace the null-out with a hard `DELETE`. |
| C3 | 🟢 Low | `backend/app/services/backfill_service.py:190` | **`client_ip` is extracted from audit payloads and stored in `audit_events`.** IP addresses are personal data under GDPR. The field is used for actor-narrative context and baseline tracking, but there is no dedicated IP retention policy separate from the main event retention. | Add `client_ip` to the fields nulled out during retention cleanup alongside `raw_payload_json`. |
| C4 | ℹ️ Info | `backend/app/core/config.py:13-15`, `backend/app/main.py:33-54` | Retention policy for events (7d default), raw payloads (7d), and noise (3d) is implemented and runs daily in an asyncio background task. Configurable per deployment. | No action needed — good practice confirmed. |

---

### UI/UX & Accessibility

| # | Severity | File:Line | Finding | Recommendation |
|---|----------|-----------|---------|----------------|
| U1 | 🟡 Medium | `frontend/app/settings/page.tsx:416,434,469,606,610,619,624,650,673,808,811,860,1024` | **~13 `<button>` elements in `settings/page.tsx` have no `aria-label`.** Screen reader users will encounter unlabelled interactive controls. `frontend/app/feedback/page.tsx:120,193` and `frontend/app/events/page.tsx:132,183,487,494` have additional unlabelled buttons. | Add descriptive `aria-label` to each button. For icon-only buttons (edit, delete, save), the aria-label is the only accessible name. e.g. `aria-label="Delete actor mapping"`. |
| U2 | 🟡 Medium | `frontend/` (all tsx files) | **Only 4 responsive breakpoint usages in the entire frontend.** `grep -rn "sm:\|md:\|lg:\|xl:"` returns 4 matches. An audit dashboard used on a variety of screen sizes (laptops, large monitors, incident-response tablets) needs more layout responsiveness. | Audit each page component for fixed-width layouts. Wrap primary content in responsive Tailwind grid/flex containers: `grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3`. |
| U3 | 🟡 Medium | `frontend/app/` | **No React error boundary anywhere in the application.** No `error.tsx` segment file exists, and no `<ErrorBoundary>` component was found. A runtime error in any component will crash the full page without a user-facing recovery option. | Create `frontend/app/error.tsx` (Next.js App Router error boundary) that shows a friendly error message with a "try again" button. For component-level isolation, add `<ErrorBoundary>` wrappers around data-heavy panels (event table, signal breakdown). |
| U4 | 🟢 Low | `frontend/app/` | **No 404 page.** No `not-found.tsx` found. Navigating to an unknown route returns the default Next.js 404, which does not match the application's visual style. | Create `frontend/app/not-found.tsx` with a styled message and a "Back to Dashboard" link. |
| U5 | 🟢 Low | `frontend/components/SignalBreakdown.tsx:116` | **Debug `console.log` in production** (same as Q5 — cross-listed here for UX signal-noise impact). | Remove. |

---

### Infrastructure

| # | Severity | File:Line | Finding | Recommendation |
|---|----------|-----------|---------|----------------|
| I1 | 🟡 Medium | `docker-compose.prod.yml` (forwarder, api, frontend service definitions) | **Forwarder, API, and frontend containers have no `user:` field** — they run as whatever user the Dockerfile's last `USER` instruction sets (or root if absent). Monitoring containers (Prometheus, Grafana, Loki) all correctly set non-root UIDs (65534, 472, 10001). | Add `user: "10001:10001"` (or match the Dockerfile's non-root user) to the `auditlens-forwarder`, `auditlens-api`, and `auditlens-frontend` service blocks. Verify the target UID owns the mounted data volumes. |
| I2 | 🟡 Medium | `Caddyfile:1` | **Caddy listens on `:80` only — no HTTPS, no HSTS.** (Cross-listed from S6.) Any network path between the end-user's browser and Caddy is unencrypted, including auth tokens. | See S6 recommendation. |
| I3 | 🟢 Low | `backend/alembic/versions/0015_autovacuum_tuning.py:1-5` | **Autovacuum tuning is a migration side-effect, not idempotent.** The migration `ALTER TABLE ... SET (autovacuum_vacuum_scale_factor = 0, autovacuum_vacuum_threshold = 10000)` is not applied on SQLite test databases. The CLAUDE.md notes this was applied manually first and then codified. | No action needed in code — the migration is Postgres-guarded correctly (`if bind.dialect.name != "postgresql": return`). Document in `DATABASE.md` that this is a manual recovery story for existing deployments that pre-date the migration. |
| I4 | 🟢 Low | `docker-compose.prod.yml:forwarder` | **CPU resource limit (`cpus: "0.25"`) is set twice** — once under `deploy.resources.limits.cpus` (swarm-only) and once at the top-level `cpus:` key (Compose v2 style). The effective limit is the top-level one for non-swarm deployments. | Remove the `deploy:` block's `cpus`/`memory` if not using Docker Swarm, leaving only the top-level `cpus:` and `mem_limit:` keys to avoid confusion. |
| I5 | ℹ️ Info | `docker-compose.prod.yml`, `docker-compose.yml` | All service ports are bound to `127.0.0.1` (e.g., `127.0.0.1:8080:8080`). No port is exposed on `0.0.0.0`. | No action needed — good practice confirmed. |
| I6 | ℹ️ Info | `docker-compose.prod.yml:forwarder` | Forwarder has `read_only: true`, `no-new-privileges: true`, and explicit `tmpfs` for `/tmp`. | No action needed — strong container hardening confirmed. |

---

### Test Coverage

| # | Severity | File:Line | Finding | Recommendation |
|---|----------|-----------|---------|----------------|
| T1 | 🟡 Medium | `backend/app/services/summary_service.py`, `backend/app/services/backfill_service.py`, `backend/app/services/cold_storage_service.py`, `backend/app/services/pattern_service.py` | **Four of the largest service modules have zero dedicated test files.** `backfill_service.py` (1,116 lines) and `summary_service.py` (430 lines) are the highest-risk untested modules — they contain complex SQL and data transformation logic. | Create `tests/test_summary_service.py` and `tests/test_backfill_service.py`. Start with happy-path tests for the most complex functions: `get_summary()` under derived-filter mode, and `backfill_actor_display_names()` dry-run. |
| T2 | 🟡 Medium | `backend/app/core/encryption.py` | **AES-256-GCM encryption module has no tests.** `encrypt()`/`decrypt()` round-trips, key-cache behaviour, and the graceful-fallback path when `cryptography` is absent are all untested. | Create `tests/test_encryption.py` with: round-trip test, tampered-ciphertext raises `InvalidTag`, `reset_key_cache()` forces re-derivation. |
| T3 | 🟡 Medium | `backend/app/api/routes/onboarding.py`, `backend/app/api/routes/tableflow.py` | **Onboarding and Tableflow routes have no tests at all.** These routes make external HTTP calls to Confluent Cloud — they need mocked integration tests to verify error paths (bad credentials, 429 from Confluent, network timeout). | Add tests using `respx` or `httpx`'s MockTransport to simulate Confluent API responses. |
| T4 | 🟢 Low | `backend/app/services/narrative_service.py`, `backend/app/services/settings_service.py`, `backend/app/services/filter_service.py`, `backend/app/services/resource_service.py`, `backend/app/services/db_status_service.py` | **Five additional service modules have no test coverage.** | Add minimal smoke tests for each: one happy-path call with the test DB fixture. |

---

## Strengths

Evidence-backed strengths confirmed during the audit:

1. **Zero CVEs in both dependency trees.** `pip-audit` and `npm audit` returned clean results against current versions (FastAPI 0.115.6, SQLAlchemy 2.0.30, Next.js 15.5.15, React 19.0.0). No known vulnerabilities.

2. **AES-256-GCM encryption for secrets stored in DB.** `backend/app/core/encryption.py` uses `cryptography.hazmat.primitives.ciphers.aead.AESGCM` with a random 12-byte nonce per encryption. Secrets are never returned decrypted through the API layer — only masked `••••{last4}` values are returned (`settings_service.py:3-4`).

3. **DB connection pool is production-grade.** `backend/app/db/database.py:73-80` sets `pool_pre_ping=True`, `pool_size=5`, `max_overflow=10`, `pool_recycle=1800` — all appropriate for a single-replica deployment with headroom for bursts.

4. **All container ports bound to `127.0.0.1`.** No service exposes a port on `0.0.0.0`, making direct external access impossible without Caddy as the deliberate entry point (`docker-compose.prod.yml`).

5. **Role-based auth model is implemented end-to-end.** The three-tier role system (viewer → responder → admin) is consistently applied via `_require_viewer`, `_require_responder`, and `require_admin` FastAPI dependencies. Admin routes (`admin.py`), settings (`settings.py`), and system vacuum (`system.py:44`) all correctly guard with `require_admin`. Token comparison uses `hmac.compare_digest()` for constant-time comparison.

6. **Comprehensive index coverage for the hot query paths.** Twenty Alembic migrations create targeted partial indexes, composite indexes, and covering indexes. Autovacuum tuning (`0015`) prevents the observed 61-second insert regression on million-row tables.

7. **No hardcoded secrets anywhere in the codebase.** All credential access goes through `os.getenv()`, `pydantic_settings.BaseSettings`, or the settings DB. No `.env` files are committed (only `.env.example` and `docs/examples/offset-strategy-examples.env`).

8. **Rate limiting applied globally.** SlowAPI middleware enforces `200/minute` globally, with tighter per-route limits (60/min on patterns, 5/min on onboarding/discover). The probe paths (`/live`, `/ready`) are excluded from rate limiting via a custom wrapper (`main.py:120-135`).

9. **Zero `any` usages in source TypeScript.** Excluding the auto-generated `.next/` directory, the frontend has 0 `any` type usages in production source files — strict TypeScript is working.

---

## Recommended Fix Order

### Immediate (before any external exposure)

1. **S1** — Flip `API_AUTH_ENABLED` default to `true`. This is a one-line change with outsized security impact.
2. **S2** — Add `@limiter.limit("5/minute")` to `POST /onboarding/validate-cluster`.
3. **S3** — Upgrade actor-mapping POST/PUT/DELETE to `_require_admin`.
4. **S4** — Add `_require_viewer` to `POST /feedback`.
5. **S7** — Add `require_admin` to all three Tableflow routes.

### Short-term (within one sprint)

6. **S5** — Add Content-Security-Policy header in FastAPI middleware.
7. **S6 + I2** — Enable HTTPS in Caddyfile (requires a domain or self-signed cert for internal use).
8. **U3** — Add `frontend/app/error.tsx` error boundary segment.
9. **T1 + T2** — Bootstrap `test_summary_service.py` and `test_encryption.py`.
10. **P1** — Add `.limit(500)` to `get_actor_narrative()` query.

### Medium-term (tech debt)

11. **Q2** — Split `backfill_service.py` into three modules.
12. **Q3** — Extract `get_summary()` into sub-functions.
13. **Q4** — Split `settings/page.tsx` into tab components.
14. **P2** — Replace `get_summary()` Python-side scan with SQL predicates.
15. **U1** — Add `aria-label` to all unlabelled buttons in settings/events/feedback pages.
16. **C1** — Add feedback table to retention cleanup loop.
17. **I1** — Add non-root `user:` to forwarder/api/frontend containers.

### Low priority / Nice-to-have

18. **Q7** — Replace N+1 actor enrichment loop with a single `WHERE actor IN (...)` query.
19. **S8** — Document/enforce write-once columns in audit_events.
20. **Q1** — Document the missing migration 0008.
21. **U2** — Add responsive Tailwind breakpoints across pages.
22. **U4** — Create `not-found.tsx`.
23. **I4** — Remove duplicate CPU/memory resource declarations in prod compose.

---

## Tech Debt Log

Items confirmed in code that are not yet addressed:

| Item | Location | Notes |
|------|----------|-------|
| `get_summary()` 203-line god function | `summary_service.py:227` | SQLite vs. Postgres branching entangled with aggregation logic |
| `backfill_service.py` 1,116 lines | `backfill_service.py` | Four independent backfill jobs in one module |
| Pattern enrichment N+1 | `pattern_service.py:179-203` | Acknowledged in comment; bounded by `statement_timeout=10000` |
| No narrative result cap | `narrative_service.py:80` | High-frequency actors load full event set into memory |
| Settings page 1,044 lines | `settings/page.tsx` | 7+ unrelated settings features in one component |
| No frontend error boundary | `frontend/app/` | Full-page crash on any unhandled component error |
| Missing migration 0008 | `backend/alembic/versions/` | Gap in sequence; likely deleted post-apply |
| 13 service modules with no unit tests | `backend/app/services/` | Backfill, summary, cold storage, patterns, narrative, settings, filter, resource, db_status have no test files |
