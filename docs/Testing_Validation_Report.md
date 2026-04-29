# AuditLens Testing Validation Report

Date: 2026-04-29

## Scope

Testing mode validation for the product path:

```text
Kafka -> audit_forwarder -> Postgres -> FastAPI -> Next.js UI
```

No Streamlit dashboards were modified.

## Extended Soak Test

Duration: 30 minutes.

Sampling interval: 5 minutes.

Source log: `/tmp/auditlens_30m_soak.log`

Results:

```text
sample 0: events=205003 duplicates=0 ui=200 ready=ready
sample 1: events=212150 duplicates=0 ui=200 ready=ready
sample 2: events=219550 duplicates=0 ui=200 ready=ready
sample 3: events=230550 duplicates=0 ui=200 ready=ready
sample 4: events=246550 duplicates=0 ui=200 ready=ready
sample 5: events=259550 duplicates=0 ui=200 ready=ready
sample 6: events=270850 duplicates=0 ui=200 ready=ready
```

Count delta: `65,847`.

Container restart counts stayed `0`.

CPU and memory summary:

```text
auditlens-forwarder cpu_avg=12.45% cpu_max=25.85% mem=162.9MiB -> 175.7MiB max=175.7MiB / 384MiB
auditlens-api       cpu_avg=0.61%  cpu_max=1.61%  mem=76.38MiB -> 79.23MiB max=79.23MiB / 384MiB
auditlens-frontend  cpu_avg=0.09%  cpu_max=0.65%  mem=37.8MiB -> 39.59MiB max=39.59MiB / 384MiB
auditlens-postgres  cpu_avg=1.01%  cpu_max=3.60%  mem=171.8MiB -> 203.1MiB max=203.1MiB / 768MiB
```

Assessment:

- No duplicate fingerprints.
- No container restarts.
- API stayed ready.
- UI stayed accessible.
- No memory runaway observed.

## High Load Test

Method:

- Restarted forwarder with larger runtime batches:

```bash
KAFKA_CONSUME_BATCH_SIZE=500
DB_WRITE_BATCH_SIZE=500
```

Source log: `/tmp/auditlens_high_load.log`

Results:

```text
sample 0: events=277695 duplicates=0 events_latency=0.057s topic_create_latency=7.757s
sample 1: events=280695 duplicates=0 events_latency=0.113s topic_create_latency=1.863s
sample 2: events=283304 duplicates=0 events_latency=0.050s topic_create_latency=3.155s
sample 3: events=285909 duplicates=0 events_latency=0.030s topic_create_latency=1.737s
```

Observed:

- DB writer stayed connected.
- DB write errors stayed `0` during high-load run.
- Duplicate fingerprint groups stayed `0`.
- Postgres CPU spiked to `65.87%` during one sample but stayed below its configured limit.
- API remained ready and UI containers stayed healthy.

After the high-load pass, the forwarder was restored to default batch settings.

## Chaos Testing

Source log: `/tmp/auditlens_chaos.log`

### Forwarder Stop/Start

Action:

```bash
docker compose --profile postgres stop auditlens-forwarder
docker compose --profile postgres up -d auditlens-forwarder
```

Observed:

- API remained reachable.
- UI remained reachable.
- DB remained reachable.
- Duplicate groups stayed `0`.
- After restart, forwarder reconnected, but if no messages were processed after restart, health could report `503`.

### API Stop/Start

Action:

```bash
docker compose --profile postgres stop api
docker compose --profile postgres up -d api
```

Observed:

- API endpoints returned connection failure while stopped.
- Frontend still served its page.
- DB stayed healthy.
- API recovered after restart.
- Duplicate groups stayed `0`.

### Frontend Stop/Start

Action:

```bash
docker compose --profile postgres stop frontend
docker compose --profile postgres up -d frontend
```

Observed:

- UI returned connection failure while stopped.
- API remained ready.
- DB remained healthy.
- Frontend recovered after restart.
- Duplicate groups stayed `0`.

### Postgres Intermittent Failure

Action:

```bash
docker compose --profile postgres stop postgres
docker compose --profile postgres start postgres
```

Repeated twice.

Observed:

- `/ready` returned `status=not_ready` while Postgres was stopped.
- `/system/status` returned `HTTP 200` with DB health `can_connect=false`.
- Forwarder stayed alive.
- DB writer state moved to `backoff`.
- After Postgres restart, DB writer returned to `connected`.
- Event count increased after recovery.
- Duplicate groups stayed `0`.

## Edge Case API Testing

Direct curl checks:

```text
/events?limit=0                         -> 422 in 0.079s
/events?limit=-1                        -> 422 in 0.081s
/events?limit=9999                      -> 422 in 0.083s
/events?resource_type=DefinitelyNotAType&limit=10
                                          -> 200 in 4.431s
/events?action_category=DefinitelyNotACategory&limit=10
                                          -> 200 in 4.436s
/events?resource=&actor=&result=&limit=10
                                          -> 200 in 1.277s
/events?resource=<long string>&limit=10  -> 200 in 3.817s
/events?limit=abc                       -> 422 in 0.006s
/events?offset=abc                      -> 422 in 0.023s
/events?time_window=not-a-window&limit=10
                                          -> 200 in 1.105s
```

Assessment:

- Numeric pagination validation behaves correctly.
- Invalid no-match filters return valid responses and do not crash.
- Long resource input returns a valid response and does not crash.
- `time_window=not-a-window` is accepted instead of rejected. This is a validation gap.
- No-match filter queries can take 3.8-4.4 seconds on the current data volume. This is a performance gap.

## Data Integrity

Manual SQL checks:

```text
total events: 296895 during integrity check
duplicate fingerprint groups: 0
required-field null count: 0
timestamp range: 2026-04-28 11:15:43.947512+00 -> 2026-04-29 05:35:02.08468+00
out-of-order rows in first 1000 timestamp-desc rows: 0
retention dry-run deleted_count: 0
```

Counts by action category:

```text
Security 268631
Other 27505
Data 535
API Key 145
Create 143
Delete 33
Modify 3
```

Counts by resource type:

```text
Unknown 100154
Cluster 88757
Schema Registry 59938
Compute Pool 39653
API Key 7733
Topic 643
Connector 93
ACL / RBAC 23
RetentionTest 1
```

Assessment:

- Fingerprint uniqueness held.
- Required normalized fields were populated.
- No timestamp ordering issue found in sampled descending query.
- Retention dry-run did not indicate current corruption risk.
- No partial insert evidence was found from required-field checks.

## Performance Baseline

Normal run:

```text
/events?limit=100 latency: 0.889s single baseline
/events?resource_type=Topic&action_category=Create&limit=100 latency: 5.483s single baseline
```

Parallel 5-request baseline:

```text
/events?limit=100:
  values: 1.185s, 1.182s, 1.179s, 1.174s, 1.189s
  avg: 1.182s
  max: 1.189s

/events?resource_type=Topic&action_category=Create&limit=100:
  values: 7.422s, 7.227s, 7.745s, 7.332s, 7.619s
  avg: 7.469s
  max: 7.745s
```

DB batch timing from recent forwarder logs:

```text
batch samples: 111
batch_ms_avg: 311.13
batch_ms_max: 1057.7
batch_size_avg: 51.35
batch_size_max: 100
```

Final runtime snapshot:

```text
auditlens-forwarder CPU=20.71% MEM=111.5MiB / 384MiB
auditlens-api       CPU=4.91%  MEM=82.36MiB / 384MiB
auditlens-frontend  CPU=0.00%  MEM=36.81MiB / 384MiB
auditlens-postgres  CPU=20.63% MEM=164.3MiB / 768MiB
```

## Bugs And Reliability Findings

1. Forwarder idle-after-restart health can report `503`.
   - Scenario: after forwarder restart, no messages processed after 60 seconds.
   - Impact: API `/ready` still reports DB ready but ingestion status can show `unknown` because the forwarder health endpoint returns 503.
   - Suggested follow-up: distinguish idle-but-connected from unhealthy when source lag is zero or no messages are available.

2. Invalid `time_window` is accepted.
   - Scenario: `/events?time_window=not-a-window&limit=10`.
   - Observed: `HTTP 200`.
   - Expected: likely `422` or documented ignore behavior.

3. No-match filter queries are slower than desired at current volume.
   - Unknown resource/action filters took ~3.8-4.4 seconds.
   - Parallel Topic/Create filter requests averaged ~7.47 seconds.
   - Suggested follow-up: inspect query plans and consider additional or adjusted indexes for combined filter paths and count queries.

4. Shell-scripted curl in this sandbox returned connection error while direct curl worked.
   - Impact: test harness issue, not an AuditLens runtime issue.
   - Mitigation used: direct curl commands for edge-case evidence.

## Final Validation Commands

Executed after the soak, high-load, chaos, edge-case, and integrity checks:

```text
python3 -m compileall audit_forwarder.py src/product/db_writer.py backend/app
API_AUTH_ENABLED=false pytest -q tests/test_productization.py backend/tests/test_api.py
npm --prefix frontend test
npm --prefix frontend run build
curl -s http://127.0.0.1:8080/ready
curl -s -o /tmp/auditlens_events_check.json -w '%{http_code} %{time_total}\n' 'http://127.0.0.1:8080/events?limit=1'
curl -s -o /tmp/auditlens_frontend_check.html -w '%{http_code} %{time_total}\n' 'http://127.0.0.1:3000/events'
```

Results:

```text
compileall: pass
backend/API tests: 45 passed
frontend smoke test: pass
frontend production build: pass
/ready: ready, database_mode=postgres, db_writer_state=connected
/events?limit=1: HTTP 200 in 0.560s
/events UI route: HTTP 200 in 0.036s
final audit_events count: 305595
final duplicate fingerprint rows: 0
```

## Final Confidence Level

Confidence: high for correctness and resilience, medium for query performance under larger data volumes.

Stability verdict: stable with caveats.

Success criteria status:

```text
no duplicates under all tests: pass
no crashes under chaos tests: pass
no memory runaway: pass in 30-minute soak
no major latency spikes: partial; broad filtered queries are slow
API always returns valid responses: partial; API is valid for tested cases, but invalid time_window is accepted
UI handles failure gracefully: pass for API/DB/frontend/forwarder scenarios tested
```
