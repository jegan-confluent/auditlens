# AuditLens Final v1 Session Wrap - 2026-04-29

## 1. Executive Summary

AuditLens v1 is now a working product baseline for the path:

Kafka -> Forwarder -> DB -> FastAPI -> Next.js UI

The validated product path runs alongside the existing Streamlit dashboards. Streamlit is preserved for compatibility but is no longer part of the default product startup path. The current work focused on correctness, production-readiness, fresh-machine runability, Docker validation, and critical hardening rather than new features.

## 2. Final Architecture

- Forwarder: `audit_forwarder.py` consumes real Confluent/Kafka audit events, normalizes/enriches events, publishes canonical topics, exposes health/metrics, and can write normalized audit events into the product DB.
- DB writer: `src/product/db_writer.py` writes normalized audit events into `audit_events`, batches writes, deduplicates with stable fingerprints, exposes DB writer state, and runs retention cleanup.
- Postgres product mode: `scripts/run_postgres_product.sh` starts Postgres, forwarder, FastAPI, and Next.js for the production-style product path. It requires real Kafka credentials in `.env`.
- SQLite demo mode: `scripts/run_sqlite_demo.sh` starts API and frontend with SQLite and seeded demo data. The API container now repairs fresh Docker named-volume permissions before dropping to UID/GID 1000.
- FastAPI API: `backend/app` serves health, readiness, events, filters, summary, system status, and admin retention cleanup. `/events` excludes raw payloads; `/events/{id}` includes raw payloads.
- Next.js UI: `frontend/` provides `/dashboard`, `/events`, and `/system` for the new product path.
- Streamlit legacy profile: Streamlit dashboards are preserved and profile-gated, not started by default.
- Optional observability profile: Prometheus, Grafana, Loki, and Promtail remain optional and must not be reintroduced into the default path.

## 3. What Was Completed

- End-to-end validation for Kafka -> forwarder -> DB -> FastAPI -> Next.js UI.
- Postgres product-mode validation, including DB writer connectivity, event counts, duplicate checks, failure/recovery, and API/UI access.
- Duplicate prevention through event fingerprints and upsert/deduplicate writes.
- Query performance fixes and composite indexes for common event filters.
- Repository cleanup: historical docs archived, runtime artifacts archived, deprecated scripts moved, generated caches removed, and ignore rules updated.
- Fresh-machine runability with `.env.example`, SQLite demo, Postgres product scripts, health checks, stop script, and security scan script.
- SQLite Docker volume permission blocker fixed with API entrypoint that chowns `/var/lib/auditlens` and then drops privileges.
- Security scan cleanup by moving `install.local.yaml` with real-looking secrets out of the repo to `~/Backups/AuditLens/secrets/install.local.yaml`.
- `/ready` strict readiness fix: readiness now requires DB reachable, forwarder connected/idle, and DB writer connected.
- Admin auth fix: `/admin/retention/cleanup` is allowed in dev mode but requires an admin token when `API_AUTH_ENABLED=true`.
- Deterministic fingerprint fix for timestamp-missing events; missing timestamps no longer cause wall-clock fingerprint drift.

## 4. Current Validation Status

Latest known validation:

- Python compile: passed with `python3 -m compileall audit_forwarder.py src/product/db_writer.py backend/app`.
- Pytest: `60 passed` for `tests/test_productization.py backend/tests/test_api.py tests/test_foundation_contract.py`.
- Frontend smoke test: passed with `npm --prefix frontend test`.
- Frontend production build: passed after `npm --prefix frontend ci`; Next.js still warns about parent lockfiles outside this repo.
- Security scan: passed with `scripts/security_scan.sh`.
- SQLite demo: passed, seeded 9 events, `scripts/health_check.sh` passed.
- Postgres product mode readiness: previously validated; next live run still needs real Kafka credentials in `.env`.
- Docker compose modes:
  - default services: `api`, `auditlens-forwarder`, `frontend`
  - Postgres profile services: `api`, `auditlens-forwarder`, `frontend`, `postgres`
  - observability remains optional.

## 5. Known Behaviors

- `/health` is basic liveness/process health.
- `/ready` is strict operational readiness.
- `/ready` may return HTTP 503 when the forwarder is unreachable, degraded, idle without a connected DB writer, or the DB writer is not connected.
- `/system/status` is intended for diagnostic status and should remain graceful when infrastructure is degraded.
- `/events` list responses do not include `raw_payload_json`.
- `/events/{id}` includes `raw_payload_json`.
- Unfiltered event totals may be estimated in Postgres for performance.
- Streamlit dashboards are preserved but are not started by default.

## 6. Known Risks / Caveats

- `audit_forwarder.py` still has large monolithic functions. Do not refactor before the demo unless a critical bug forces it.
- Postgres product mode needs real Kafka credentials for the next live run.
- A long overnight soak has not yet been completed.
- Free-text resource substring search can still scan and may need trigram/full-text indexing later.
- `bootstrap_auditlens.py` is deprecated/legacy and has been moved under `scripts/deprecated/`.
- Next.js build warning persists because lockfiles exist outside the repo tree; build still passes.
- The current worktree is dirty due to cleanup, fresh-runability, SQLite permission, and critical hardening changes.

## 7. Current Run Commands

SQLite demo:

```bash
cp .env.example .env
scripts/run_sqlite_demo.sh
scripts/health_check.sh
```

Postgres product:

```bash
cp .env.example .env
# Fill Kafka credentials in .env:
# KAFKA_BOOTSTRAP_SERVERS
# KAFKA_API_KEY
# KAFKA_API_SECRET
# KAFKA_AUDIT_TOPIC
scripts/run_postgres_product.sh
scripts/health_check.sh
```

Stop:

```bash
scripts/stop_all.sh
scripts/stop_all.sh --volumes
```

## 8. Next Session Plan

1. Fill `.env` with real Kafka credentials.
2. Start Postgres product mode.
3. Create a test topic.
4. Confirm the Create Topic event appears in UI/API.
5. Delete the test topic.
6. Confirm the Delete Topic event appears.
7. Capture screenshots.
8. Prepare final demo script.

## 9. Do Not Touch

- Do not refactor `audit_forwarder.py` before demo.
- Do not add new features.
- Do not reintroduce Prometheus/Grafana/Loki into the default path.
- Do not push to official GitHub yet.
- Do not commit secrets.
- Do not remove Streamlit dashboards.

## 10. Git/Repo State

Commands run:

```bash
git status --short
git log --oneline -5
git tag --list
git branch --show-current
```

Summary:

- Current branch: `master`
- Latest commit: `4837d95 v1: E2E validated, performance fixed, production-ready baseline`
- Tag present: `v1.0.0`
- Worktree: dirty.
- Dirty state includes:
  - Fresh-runability and cleanup changes.
  - SQLite volume permission fix.
  - Critical fixes for `/ready`, admin auth, and deterministic timestamp-missing fingerprints.
  - Archived docs/runtime artifacts/deprecated scripts.
  - Existing tracked Terraform provider cache deletions from cleanup.
