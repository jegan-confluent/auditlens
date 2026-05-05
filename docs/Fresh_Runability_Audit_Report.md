# AuditLens Fresh Runability Audit Report

Date: 2026-04-29

Scope: inspect and validate fresh-machine readiness for SQLite demo mode, Postgres product-mode preflight, optional observability mode, and real Kafka readiness. No code fixes were made in this audit.

## Summary

AuditLens is close to fresh-machine runnable, but SQLite demo mode has a blocking fresh-volume permissions bug.

The API container runs as UID `1000`, while the Docker named volume mounted at `/var/lib/auditlens` is root-owned on a fresh volume. SQLite cannot create/open `/var/lib/auditlens/auditlens_api.db`, so seed data fails and `/events` returns `500`.

Recommended small fix: make `/var/lib/auditlens` writable before the API starts, either by adding an entrypoint that chowns the mounted directory then drops privileges, or by removing the fixed `user: "1000:1000"` for the local Docker API service.

## Workspace Hygiene

Commands:

```bash
git status --short
git log --oneline -1
git tag --list
find . -name "*.bundle"
find . -name "*.zip"
find . -name ".env"
find . \( -name "node_modules" -o -name ".next" -o -name "__pycache__" -o -name ".pytest_cache" \) -print
```

Results:

- Latest commit: `4837d95 v1: E2E validated, performance fixed, production-ready baseline`
- Tag present: `v1.0.0`
- No `*.bundle` files found in repo.
- No `*.zip` files found in repo.
- `.env` was absent before runtime testing, then created from `.env.example` for the SQLite/Postgres preflight checks.
- One Python cache directory was regenerated during validation and removed before final cleanup.
- Worktree contains intended runability changes, the appended changelog entry, and this audit report.

## Config Audit

Reviewed:

- `.env.example`
- `docker-compose.yml`
- `scripts/run_sqlite_demo.sh`
- `scripts/run_postgres_product.sh`
- `scripts/stop_all.sh`
- `scripts/health_check.sh`
- `scripts/security_scan.sh`
- `README.md`

Findings:

- SQLite demo mode is clearly documented and script-driven.
- Postgres product mode is clearly documented and script-driven.
- Observability is optional through the `observability` profile.
- Streamlit is preserved and moved behind the explicit `streamlit` profile.
- API uses `DATABASE_URL`.
- Forwarder receives `FORWARDER_DATABASE_URL` through container `DATABASE_URL`, which matches `audit_forwarder.py` / DB writer expectations.
- Frontend uses `NEXT_PUBLIC_API_BASE_URL`.
- `run_postgres_product.sh` maps `KAFKA_*` values into the forwarder-required `AUDIT_*` and `DEST_*` variables.
- No real-looking secrets were found by high-confidence scan after template/document sanitization.

Blocking issue:

- SQLite demo mode starts containers but cannot seed or query events on a fresh Docker volume because `/var/lib/auditlens` is not writable by UID `1000`.

Evidence:

```text
docker compose exec -T api id
uid=1000 gid=1000 groups=1000

docker compose exec -T api ls -ld /var/lib/auditlens
drwxr-xr-x 2 root root 4096 Apr 29 12:03 /var/lib/auditlens

docker compose exec -T api sh -c 'echo test >/var/lib/auditlens/write-test'
sh: 1: cannot create /var/lib/auditlens/write-test: Permission denied
```

## Security Scan

Commands:

```bash
scripts/security_scan.sh
rg -n "cflt[A-Za-z0-9+/=]{20,}|BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY|api_secret:\s*\"[^\"]+\"|api_key:\s*\"[A-Z0-9]{12,}\"|New token: [A-Za-z0-9]{24,}" .env.example install.template.yaml README.md docs docker-compose.yml scripts
```

Results:

- `scripts/security_scan.sh`: PASS
- Manual high-confidence scan: no matches.

## Compose Modes

Commands:

```bash
docker compose config --services
docker compose --profile postgres config --services
docker compose --profile observability config --services
```

Results:

```text
default:
api
auditlens-forwarder
frontend

postgres:
api
auditlens-forwarder
frontend
postgres

observability:
prometheus
loki
promtail
api
auditlens-forwarder
frontend
grafana
```

Assessment:

- Default compose excludes Prometheus, Grafana, Loki, and Promtail.
- Postgres profile includes Postgres.
- Observability profile starts monitoring only when explicit.
- Streamlit is not default.

## Local Validation

Commands:

```bash
python3 -m compileall audit_forwarder.py src/product/db_writer.py backend/app
API_AUTH_ENABLED=false pytest -q tests/test_productization.py backend/tests/test_api.py tests/test_foundation_contract.py
npm --prefix frontend test
npm --prefix frontend run build
```

Results:

- Python compile: PASS
- API/product/forwarder tests: `56 passed`
- Frontend smoke test: PASS
- Frontend build: PASS after `npm --prefix frontend install`

Note: fresh clone users need `npm install` only for local frontend builds. Docker frontend builds install dependencies inside the image.

## SQLite Demo Runtime

Commands:

```bash
scripts/stop_all.sh --volumes
cp .env.example .env
scripts/run_sqlite_demo.sh
scripts/health_check.sh
```

Results:

- API container starts.
- Frontend container starts.
- Seed data fails.
- `/ready`: PASS
- `/system/status`: PASS
- `/events?limit=1`: FAIL with `500`
- UI `/events`: route returns `200`, but API-backed data cannot load correctly because `/events` fails.
- Topic/Create/jegan-testing filter could not be validated because seed failed.

Blocking error:

```text
sqlite3.OperationalError: unable to open database file
```

Root cause:

```text
/var/lib/auditlens is root-owned and not writable by API container UID 1000.
```

## Postgres Product Preflight

Command:

```bash
scripts/run_postgres_product.sh
```

Result with blank `.env` Kafka credentials:

```text
FAIL: missing Kafka configuration: AUDIT_BOOTSTRAP AUDIT_API_KEY AUDIT_API_SECRET DEST_BOOTSTRAP DEST_API_KEY DEST_API_SECRET
Fill KAFKA_* values in .env, or set AUDIT_* and DEST_* runtime aliases.
```

`docker ps` after the failed preflight showed no running containers.

Assessment: PASS. The script fails fast and does not leave partial broken containers when Kafka credentials are missing.

## Real Kafka Readiness

Checked `.env`:

```text
KAFKA_BOOTSTRAP_SERVERS=<empty>
KAFKA_API_KEY=<empty>
KAFKA_API_SECRET=<empty>
KAFKA_AUDIT_TOPIC=<set>
```

Real Kafka product-mode testing was not run because credentials were not present.

Required next values:

```text
KAFKA_BOOTSTRAP_SERVERS
KAFKA_API_KEY
KAFKA_API_SECRET
KAFKA_AUDIT_TOPIC
```

If destination Kafka differs from source Kafka, also set:

```text
DEST_BOOTSTRAP
DEST_API_KEY
DEST_API_SECRET
```

## Failure / Recovery

Not run.

Reason: real Postgres product mode was not running because Kafka credentials were absent.

## PASS / FAIL Table

| Area | Result | Notes |
| --- | --- | --- |
| Workspace bundles/zips | PASS | No repo-local bundle or zip found |
| `.env` committed | PASS | `.env` ignored; only created temporarily for runtime checks |
| Security scan | PASS | No high-confidence leaked secrets |
| Compose default mode | PASS | No observability services by default |
| Compose Postgres profile | PASS | Includes Postgres |
| Compose observability profile | PASS | Monitoring appears only with explicit profile |
| Streamlit not default | PASS | Streamlit behind `streamlit` profile |
| Python compile | PASS | Compileall succeeded |
| Backend/API tests | PASS | 56 passed |
| Frontend smoke test | PASS | Passed |
| Frontend build | PASS | Passed after dependency install |
| SQLite demo startup | FAIL | API/frontend start, but SQLite DB is not writable |
| SQLite seed data | FAIL | `sqlite3.OperationalError: unable to open database file` |
| SQLite `/events` | FAIL | Returns 500 due DB open failure |
| Postgres preflight without Kafka | PASS | Fails fast with clear missing vars and no partial containers |
| Real Kafka product mode | NOT RUN | Credentials absent |
| DB failure/recovery | NOT RUN | Product mode not running |

## Blockers

1. SQLite demo fresh-volume permissions bug.
   - Impact: Fresh user cannot complete the one-script SQLite demo path.
   - Exact fix to apply next: make `/var/lib/auditlens` writable before API startup, or remove the fixed API `user: "1000:1000"` in the local Docker path.

## Exact Next Action

Apply the small Docker/API volume permission fix, then rerun:

```bash
scripts/stop_all.sh --volumes
cp .env.example .env
scripts/run_sqlite_demo.sh
scripts/health_check.sh
curl -s 'http://127.0.0.1:8080/events?resource_type=Topic&resource=jegan-testing&action_category=Create'
scripts/stop_all.sh --volumes
```

After that passes, fill real Kafka values in `.env` and run:

```bash
scripts/run_postgres_product.sh
scripts/health_check.sh
```
