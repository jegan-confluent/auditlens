# Runtime Architecture Audit

Date: 2026-04-28

## Scope

This audit focused on making AuditLens safe to run on a normal developer or customer machine without Docker consuming excessive CPU or memory.

Out of scope: product UI redesign, audit semantic changes, ingestion architecture changes, and investigation filter logic changes.

## Executive Summary

The main runtime risk was that the default Compose stack started the full local observability suite, not just the product path. On macOS this made Docker Desktop look like a roughly 10 GB runtime because AuditLens containers, observability volumes, Docker Desktop Kubernetes containers, and previously started profile containers were all resident together.

The forwarder was not a pure tight polling loop, but it had three resource risks:

- startup Kafka/DNS/auth failures exited the process and relied on Compose restart behavior, which could become a restart storm;
- Kafka client buffers and producer queues were sized for large throughput instead of local demo safety;
- empty polls and repeated consumer errors had no explicit runtime backoff state, retry metrics, or degraded state.

The dashboard memory risk was mostly from dataframe growth and raw JSON retention. The dashboard loaded and transformed records before consistently enforcing `max_events`, cached data without an entry bound, and carried raw payloads in the main dataframe used by all tabs.

## Docker Compose Architecture

Default `docker compose up` now starts the lite product path only:

- `auditlens-forwarder` - mandatory
- `dashboard` - mandatory

Optional services are behind profiles:

- `observability`: `prometheus`, `grafana`, `loki`, `promtail`
- `dev`: `prometheus`, `grafana`, `landing`, `loki`, `promtail`
- `future`: `mcp-server`, `schema-watcher`

Recommended commands:

```bash
docker compose up -d
docker compose --profile observability up -d
docker compose --profile dev up -d
```

Important Docker behavior: switching from a full/profile run back to default lite does not automatically stop already running profile containers. If optional services were started earlier, stop them explicitly:

```bash
docker stop audit-prometheus audit-grafana loki promtail auditlens-landing
```

## Compose Resource Controls

Lite mode:

- `auditlens-forwarder`: `384m` memory limit, `0.25` CPU limit, healthcheck enabled, `restart: on-failure:3`
- `dashboard`: `384m` memory limit, `0.75` CPU limit, `restart: unless-stopped`

Observability mode:

- `prometheus`: `768m`, `0.75` CPU
- `grafana`: `512m`, `0.50` CPU
- `loki`: `512m`, `0.50` CPU
- `promtail`: `256m`, `0.25` CPU

The forwarder restart policy was intentionally changed from unbounded `unless-stopped` to bounded `on-failure:3` because connection failures now back off in-process instead of relying on container restarts.

## Why Docker Desktop Looked Like 10 GB

The local Docker stats included more than the lite product path:

- AuditLens forwarder and dashboard
- previously started Prometheus, Grafana, Loki, Promtail, and landing containers
- persistent Docker volumes for SQLite, Prometheus, Grafana, and Loki
- Docker Desktop Kubernetes system containers
- Docker Desktop VM overhead and filesystem cache

The fix is to make lite mode the default and keep observability behind an explicit profile.

## Forwarder CPU Root Cause

The observed `auditlens-forwarder` CPU spike was caused by a combination of active backlog processing and unsafe retry behavior, not a single UI/filter bug.

Found risks:

- Kafka startup/connectivity failures could exit and rely on Docker restart loops.
- Consumer exceptions did not have exponential backoff.
- Empty polls did not sleep.
- Repeated errors did not have rate-limited logging.
- Kafka consumer and producer buffers were oversized for local operation.
- Runtime health did not expose enough polling/backoff state to distinguish idle, retry, and backlog processing.

Implemented controls:

- Kafka poll timeout default: `2.0s`
- empty poll sleep default: `0.25s`
- batch pacing sleep default: `0.25s`
- exponential backoff for startup and consume errors
- max backoff default: `60s`
- jitter on retry backoff
- degraded state after repeated failures
- rate-limited repeated error logs
- reduced Kafka consumer fetch buffers
- reduced Kafka producer queue buffers

Added runtime metrics:

- `poll_count`
- `empty_poll_count`
- `records_consumed_total`
- `retry_count`
- `consecutive_error_count`
- `last_error`
- `last_successful_poll`
- `backoff_seconds`
- `consumer_state`

These are exposed through `/health` under `observability.consumer_runtime`, the consumer component details, and `/metrics`.

## Dashboard Memory Root Cause

Found risks:

- raw JSON payloads were retained in the main dataframe;
- transformations could run before all `max_events` caps were enforced;
- Streamlit cache had a TTL but no entry bound;
- repeated refreshes could retain payloads in `session_state`;
- the default dashboard dataframe was shared across multiple tabs.

Implemented controls:

- enforce `max_events` before dataframe creation and after transformations;
- set Streamlit cache to `ttl=15, max_entries=2`;
- reduce dashboard Kafka fetch buffers;
- remove `data_json` from the table dataframe;
- keep at most 200 raw payloads in `st.session_state` for selected-row details;
- expose dataframe memory estimate in the dashboard advanced/runtime memory section;
- allow detail view to retrieve raw JSON from the bounded payload cache.

## Storage And Retention

SQLite:

- Current runtime health reported `/var/lib/auditlens/auditlens.db`.
- Current database plus WAL was about `972 MB`.
- The new local default cap is `1 GB` database and `128 MB` WAL.
- Health reported storage mode `critical` because the existing environment has a large hot cache from previous runs.

Prometheus:

- retention default changed to `7d`
- retention size default changed to `1GB`

Loki:

- retention changed to `7d`
- cache size reduced from `100 MB` to `32 MB`
- ingestion rate reduced to `4 MB/s`
- retention delete workers reduced from `150` to `4`

Docker volumes:

- `auditlens_data`, `prometheus_data`, `grafana_data`, and `loki_data` can grow across sessions.
- For a clean local demo, stop optional profile containers and prune only intentionally selected unused data.

Useful inspection commands:

```bash
docker system df
docker volume ls
curl -s http://localhost:8003/health
```

## Recommended Deployment Modes

Lite mode is the recommended customer default:

- forwarder
- dashboard
- SQLite bounded hot cache
- no Prometheus, Grafana, Loki, Promtail

Full mode is recommended for local observability demos:

- lite mode
- Prometheus
- Grafana
- Loki
- Promtail

Dev mode is for product development only:

- full mode
- local landing/testing helper
- future developer-only services when explicitly enabled

## Resource Budget

Lite target:

- idle CPU under `5%`
- total RAM under `1.5 GB`
- dashboard under `350 MiB`
- forwarder under `300 MiB`
- no hot CPU spikes during idle

Full target:

- idle CPU under `10%`
- total RAM under `4 GB`

## Validation

Commands run:

```bash
python3 -m py_compile audit_forwarder.py dashboard/app.py dashboard/app_clean.py dashboard/data/kafka_consumer.py dashboard/tabs/details.py
docker compose config --services
docker compose --profile observability config --services
docker compose --profile dev config --services
docker compose up -d --build
docker stats auditlens-forwarder dashboard
curl -s http://localhost:8003/health
```

Compose profile validation:

- default: `auditlens-forwarder`, `dashboard`
- observability: `prometheus`, `loki`, `promtail`, `auditlens-forwarder`, `dashboard`, `grafana`
- dev: `auditlens-forwarder`, `dashboard`, `prometheus`, `grafana`, `landing`, `loki`, `promtail`

Health validation after changes:

- status: `healthy`
- `consumer_state`: `connected`
- `retry_count`: `0`
- `consecutive_error_count`: `0`
- `last_error`: `null`
- consumer lag: `4592`

The nonzero lag means the forwarder was still actively catching up during the stats sample. The sample is therefore a catch-up workload measurement, not a clean idle measurement.

Lite stats sample after applying resource caps. This was a 24-sample run over roughly two minutes against only `auditlens-forwarder` and `dashboard`:

| Service | Avg CPU | Max CPU | Memory range |
| --- | ---: | ---: | ---: |
| `auditlens-forwarder` | `29.43%` | `41.38%` | `80.23-84.68 MiB / 384 MiB` |
| `dashboard` | `0.54%` | `12.33%` | `84.69-84.70 MiB / 384 MiB` |

Interpretation:

- dashboard memory is below the `350 MiB` target;
- forwarder memory is below the `300 MiB` target;
- forwarder CPU is bounded by Compose and no retry storm is visible;
- idle CPU still needs one more validation pass after consumer lag reaches zero.

## Files Changed

- `audit_forwarder.py`
- `docker-compose.yml`
- `dashboard/app.py`
- `dashboard/app_clean.py`
- `dashboard/data/kafka_consumer.py`
- `dashboard/tabs/details.py`
- `loki/loki-config.yaml`
- `docs/Runtime_Architecture_Audit.md`

## Remaining Follow-Up

- Re-run `docker stats auditlens-forwarder dashboard` after consumer lag reaches zero to confirm the idle CPU budget.
- Decide whether the customer demo `.env` should lower the existing 30-day SQLite effective retention values to match the new 1 GB local cap.
- Consider a documented local cleanup helper that stops profile containers and reports volume sizes before deleting anything.
