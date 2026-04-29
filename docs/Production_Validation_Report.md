# AuditLens Production Validation Report

Date: 2026-04-29

## Scope

Validated the product path:

```text
Kafka -> audit_forwarder -> audit_events DB -> FastAPI -> Next.js UI
```

Streamlit dashboards were not modified.

## SQLite E2E Summary

- Docker lite path with SQLite was already validated before this pass.
- Real Kafka data flowed through forwarder, DB, FastAPI, and Next.js UI.
- Duplicate fingerprint groups: `0`.
- DB writer backoff/recovery was exercised.
- `/events` and `/system` returned `200`.
- Playwright validated event filtering and detail drawer raw payload behavior.

## Postgres E2E Summary

Command used:

```bash
DATABASE_URL=postgresql://auditlens:auditlens@postgres:5432/auditlens \
FORWARDER_DATABASE_URL=postgresql://auditlens:auditlens@postgres:5432/auditlens \
POSTGRES_PORT=55432 \
docker compose --profile postgres up --build -d postgres auditlens-forwarder api frontend
```

Notes:

- Host port `5432` was already occupied, so Postgres was exposed on `127.0.0.1:55432`.
- Docker service-to-service traffic still used `postgres:5432`.

Validation:

- `auditlens-postgres`: healthy.
- `auditlens-api`: healthy.
- `auditlens-forwarder`: healthy.
- `auditlens-frontend`: healthy.
- `/ready` reported `database_mode=postgres`.
- `/system/status` reported DB writer connected.
- `/events?limit=1` returned real Kafka audit rows.
- `/events?resource_type=Topic&action_category=Create` returned real Topic/Create rows.

Postgres DB checks:

```text
total audit_events: 53,800 during initial Postgres proof
duplicate fingerprint groups: 0
oldest timestamp: 2026-04-28 11:15:43.947512+00
newest timestamp: 2026-04-28 17:28:32.102869+00
```

Top action categories at initial proof:

```text
Security 48603
Other 4977
Data 172
API Key 26
Create 21
Modify 1
```

Top resource types at initial proof:

```text
Unknown 19393
Cluster 14482
Schema Registry 10004
Compute Pool 7120
API Key 2608
Topic 187
Connector 4
ACL / RBAC 2
```

Final observed Postgres count after later validation: `141,952`.

## DB Failure And Recovery

Failure command:

```bash
docker compose --profile postgres stop postgres
```

Observed while Postgres was stopped:

- Forwarder stayed alive.
- Forwarder health returned `HTTP 200`.
- DB writer moved to degraded/backoff state.
- `/ready` returned `status=not_ready` with `database_mode=postgres` and DB connection error details.
- `/system/status` now returns `HTTP 200` with degraded DB health instead of a generic 500.
- CPU stayed bounded during DB outage:
  - forwarder: `0.38%` to `0.67%`
  - api: `0.11%` to `0.31%`

Recovery command:

```bash
POSTGRES_PORT=55432 docker compose --profile postgres start postgres
```

Observed after recovery:

- `/ready` returned `status=ready`.
- DB writer state returned to `connected`.
- Event count increased again.
- Duplicate fingerprint groups stayed `0`.

## Long-Run Stability

Ran a 10-minute short-run stability sample at 2-minute intervals.

Samples captured:

```text
sample 0: events=58000 duplicates=0
sample 1: events=64600 duplicates=0
sample 2: events=72300 duplicates=0
sample 3: events=79800 duplicates=0
sample 4: events=87100 duplicates=0
sample 5: events=94200 duplicates=0
```

CPU summary:

```text
forwarder avg=16.75% max=22.46%
api avg=0.22% max=0.38%
frontend avg=0.00% max=0.00%
postgres avg=1.95% max=3.21%
```

Memory start/end:

```text
forwarder 133.0MiB -> 150.4MiB / 384MiB
api 77.87MiB -> 80.68MiB / 384MiB
frontend 50.3MiB -> 50.3MiB / 384MiB
postgres 59.84MiB -> 155.6MiB / 768MiB
```

Container restart counts after validation:

```text
auditlens-forwarder restart=0 health=healthy
auditlens-api restart=0 health=healthy
auditlens-frontend restart=0 health=healthy
auditlens-postgres restart=0 health=healthy
```

Result:

- No container restarts.
- API stayed reachable.
- Frontend stayed reachable.
- Duplicate fingerprint groups stayed `0`.
- No memory runaway observed in the 10-minute window.

## Retention Cleanup

Seeded three `RetentionTest` rows into Postgres:

- 2 rows older than the 7-day retention window.
- 1 current row.

Dry-run result:

```text
before_old 2 before_current 1
dry_run deleted_count 2
after_dry_old 2
```

Real cleanup result:

```text
real deleted_count 2
after_old 0
after_current 1
duplicates 0
last_cleanup_deleted_count 2
```

Result:

- Dry-run reported old rows without deleting.
- Real cleanup deleted only old rows.
- Current rows were preserved.
- Duplicate fingerprint groups stayed `0`.

## Frontend Validation

Playwright validated:

- `/events` initial load.
- filter by `resource_type`.
- filter by resource text.
- filter by `action_category`.
- impossible filter empty state.
- reset filters.
- pagination.
- detail drawer opens.
- raw payload is visible only in detail drawer.
- `/system` healthy state.
- `/system` DB unavailable state.
- `/events` API unavailable error state.

Screenshots:

```text
/tmp/auditlens_pg_events_edge_states.png
/tmp/auditlens_pg_system_healthy.png
/tmp/auditlens_pg_system_db_unavailable.png
/tmp/auditlens_pg_events_api_unavailable.png
```

## Dependency Audit

Initial result:

- `next@15.1.6`: critical direct vulnerability group.
- `postcss@8.4.31`: moderate transitive vulnerability through Next.js.

Remediation:

```bash
npm --prefix frontend install next@15.5.15
npm --prefix frontend pkg set overrides.postcss=8.5.10
npm --prefix frontend install
```

Final result:

```text
npm audit: 0 vulnerabilities
```

Validation after remediation:

```bash
npm --prefix frontend test
npm --prefix frontend run build
docker compose build frontend
```

All passed.

Docker build context hardening:

- Added frontend build artifact ignores so local `frontend/.next` and `frontend/node_modules` do not bloat Docker context.
- Rebuilt frontend image after the ignore change; context transfer dropped to about `1.48kB` for the frontend build context.

## Commands Used

```bash
python3 -m compileall audit_forwarder.py src/product/db_writer.py backend/app
API_AUTH_ENABLED=false pytest -q tests/test_productization.py backend/tests/test_api.py
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend audit --json
docker compose config --services
docker compose --profile postgres config --services
docker compose --profile postgres up --build -d postgres auditlens-forwarder api frontend
curl -s http://127.0.0.1:8080/ready
curl -s http://127.0.0.1:8080/system/status
curl -s 'http://127.0.0.1:8080/events?limit=1'
curl -s 'http://127.0.0.1:8080/events?resource_type=Topic&action_category=Create'
docker exec auditlens-postgres psql -U auditlens -d auditlens
```

## Code Hardening Done During Validation

- Postgres DB writer now returns exact inserted counts for upserts using `RETURNING`.
- `/system/status` now returns degraded DB health and storage diagnostics when the DB is unavailable instead of returning a generic 500.
- Frontend dependency risk was remediated with a non-major Next.js upgrade and a narrow PostCSS override.
- Docker build context excludes local frontend build artifacts and dependencies.

## Remaining Risks

- Stability run was 10 minutes, not 30 minutes.
- Forwarder local SQLite persistence hot cache is near its configured size limit and reports storage pressure independently of the product Postgres write path.
- Postgres memory rose from `59.84MiB` to `155.6MiB` during the 10-minute run, consistent with cache growth but still worth watching in a longer soak.
- Kafka consumer lag varied and increased during the short run, indicating the test source was producing/replaying faster than this constrained local Docker profile could fully drain.
- Next.js local build warns about multiple parent lockfiles outside this repo; build succeeds, but `outputFileTracingRoot` can be set later if this warning becomes operationally noisy.

## Final Readiness Score

Recommendation: ready with caveats.

Score: 8/10.

Rationale:

- SQLite and Postgres E2E paths work with real Kafka data.
- DB failure and recovery are handled without process crash.
- Duplicate prevention held through restarts, replay, retention, and failure testing.
- API and UI expose healthy and degraded states.
- Frontend dependency audit is clean after remediation.
- A longer 30-minute or overnight soak is still recommended before calling the stack fully production-ready.
