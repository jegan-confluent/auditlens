# AuditLens Data Retention & Real-Time Expectations

This document explains what AuditLens retains, for how long, and what
"real-time" means in practice. Use it when answering customer or compliance
questions about freshness and data lifecycle.

## What AuditLens retains

| Data | Retention | Configurable | Storage |
|---|---|---|---|
| All audit events (Postgres) | 7 days | Yes — `EVENT_RETENTION_DAYS` | Postgres `audit_events` table |
| Action Required events | 30 days | Planned (not yet implemented) | Same table, future flag |
| Raw Kafka audit events (Confluent Cloud) | Per your Confluent plan | No (upstream of AuditLens) | Confluent Cloud |
| Forwarder hot cache (SQLite) | 24 h rolling | Yes — `PERSISTENCE_ROTATION_RETENTION_HOURS` | `/app/data/auditlens.db` |
| Mirrored Kafka topics (`audit.raw.v1`, `audit.enriched.v1`, etc.) | Per destination Kafka topic config | Yes (Kafka-side) | Destination Kafka |
| Identity enrichment cache | TTL `IAM_ENRICHMENT_CACHE_TTL_SECONDS` (default 3600s) | Yes | In-process |

**Implications:**

- **The dashboard shows the last 7 days by default.** Older data has been
  reclaimed and is not queryable from the UI. Re-ingest from the upstream
  Confluent Cloud audit log if longer history is needed.
- **The SQLite hot cache is a query accelerator, not durable storage.**
  Postgres is the source of truth. SQLite holds the most recent 24 h to
  back UI and API queries fast.
- **Compliance reports beyond 7 days require an external archive
  (e.g. S3 sink connector).** AuditLens does not currently archive to
  cold storage; that is on the roadmap.

## Real-time lag expectation

| Scenario | Expected lag | Notes |
|---|---|---|
| Normal operation | < 5 minutes | Steady-state after performance fixes |
| High-volume org (>500 events/sec) | 5-30 minutes | Bottleneck is DB write speed, not Kafka |
| After restart / catch-up | Up to 2 hours | Consumer replays from committed offset |
| First-time ingest of an active org | Up to 12 hours | Replays full retained Kafka topic |

## Event Freshness by Priority

The forwarder routes events into priority lanes so destructive operations
land in Postgres in seconds even when noise events are batching. Each lane
has its own writer thread, batch size, and wait budget — see
`audit_forwarder.py` (`WRITER_*_BATCH` / `WRITER_*_WAIT` env vars).

| Event type | Examples | Target freshness |
|---|---|---|
| 🔴 Critical | Topic deleted, Cluster deleted, DeleteServiceAccount, DeleteAPIKey | < 2 minutes |
| 🟡 High | CreateTopics, CreateAPIKey, RoleBinding changes, SignIn | < 5 minutes |
| 🔵 Normal | Schema changes, Connector ops, Flink jobs | < 15 minutes |
| ⚪ Noise | Auth checks, Fetch/Produce, Read-only ops | < 30 minutes |

This is the honest SLA. Customers don't care that routine auth checks are
30 minutes delayed — they care that "someone deleted our prod topic"
appears in two minutes. Operators can confirm the lanes are healthy via
`GET /health` (look at `queues.critical`, `queues.normal`, `queues.bulk`,
`queues.catalog`); a critical queue depth above ~100 means the critical
writer is degraded and destructive events are *not* meeting their SLA.

If observed lag exceeds these ranges by more than 2x, check the System page
or `GET /health` on the forwarder for the bottleneck — typical causes are
DB writer saturation, network latency to a cross-region Kafka cluster, or
storage pressure on the SQLite hot cache.

## What "real-time" means for AuditLens

AuditLens is **near-real-time**, not streaming-real-time. Events appear in
the dashboard within minutes of occurring on Confluent Cloud, not within
seconds. This is appropriate for compliance and audit use cases where
5-minute freshness is acceptable.

For sub-second alerting (e.g. immediate paging on a topic delete), use
**Confluent Cloud's native alerting** plus AuditLens for historical
investigation, root-cause review, and audit reporting.

## Why the lag, in one paragraph

The path is: `Confluent Audit Log topic → forwarder Kafka consumer →
classification + enrichment → write to Postgres + SQLite + 5 internal
Kafka topics → API queries → dashboard render`. Every step is asynchronous
and durable. Lag accumulates when the forwarder's write side cannot keep
up with the upstream produce rate. The DB write is the dominant cost
per event, which is why we keep the Postgres index list lean and
batch INSERTs at 500 rows.

## Configuration knobs (for operators)

Set these in `.env` if you need to tune retention:

```bash
EVENT_RETENTION_DAYS=7                   # Postgres retention
PERSISTENCE_ROTATION_RETENTION_HOURS=24  # SQLite hot cache window
DB_WRITE_BATCH_SIZE=500                  # rows per Postgres INSERT
DB_WRITE_FLUSH_INTERVAL_SECONDS=2        # max age of a partial batch
```

After changing these, recreate the forwarder container so the new env
takes effect: `docker compose up -d --force-recreate auditlens-forwarder`.

## Consumer Architecture

AuditLens uses a thread-pool pattern in front of librdkafka:

- **Consumer thread (Thread A)** — calls `consumer.consume()` at full
  speed, hands message batches to a bounded `queue.Queue`, and never
  does enrichment, classification, or DB I/O. This keeps Kafka
  heartbeats flowing even during slow Postgres writes, so the broker
  doesn't trigger a rebalance.
- **Processor thread(s) (Thread B)** — pop batches off the queue,
  enrich, classify, write to Postgres + SQLite hot cache, produce to
  internal Kafka topics, and signal the consumer thread to commit
  offsets via a separate offset queue. Processors hold no consumer
  references.
- **IAM refresh (background daemon)** — `IdentityEnricher` runs a
  daemon thread that re-fetches Confluent Cloud service-account and
  user metadata every 50 minutes and atomically swaps the cache.
  Refresh failures keep the previous cache and log a WARN.
- **Lag (rdkafka stats callback)** — `statistics.interval.ms=10000`
  fires `stats_cb` in librdkafka's background thread; we read
  per-partition `consumer_lag` straight from the JSON blob, no extra
  network calls. Replaces synchronous `get_watermark_offsets` polling.

### Kafka consumer tuning applied

| Setting | Value | Why |
|---|---|---|
| `fetch.min.bytes` | 64 KB | Wait for real batches, not single events |
| `fetch.max.wait.ms` | 500 ms | Cap on how long the broker waits for those bytes |
| `fetch.max.bytes` | 50 MB | Large fetch for catch-up scenarios |
| `max.partition.fetch.bytes` | 1 MB | Per-partition cap; default-safe |
| `session.timeout.ms` | 45 s | Tolerate slow processing without rebalance |
| `heartbeat.interval.ms` | 15 s | One third of session timeout |
| `max.poll.interval.ms` | 5 min | Defence-in-depth limit on processor stalls |
| `group.instance.id` | static (per replica) | Static membership avoids full rebalance on restart |
| `queued.max.messages.kbytes` | 1 GB | Internal librdkafka buffer keeps fetch warm |
| `statistics.interval.ms` | 10 s | rdkafka stats for lag (no blocking polls) |

Set `KAFKA_GROUP_INSTANCE_ID` in `.env` to opt into static membership.
Pick a stable, unique-per-replica id (for example
`auditlens-forwarder-1`).

### Expected throughput

| Scenario | Target msg/s | Lag expectation |
|---|---|---|
| Normal operation | 200-500 | < 5 minutes |
| After restart | 500+ during catch-up | Drains in < 2 hours |
| With IAM refresh | 200+ (no spike) | Refresh runs in background |
| High-volume org > 500 ev/s | 5-30 minutes | DB write speed is the cap |

If observed sustained throughput is below 200 msg/s, the bottleneck is
almost always the Postgres `INSERT ... ON CONFLICT DO NOTHING` on
`audit_events`. Check `pg_insert_ms` in the "DB writer batch complete"
log line — if it dominates, options are: drop more unused indexes,
increase batch size, or run multiple processor threads each with its
own SQLAlchemy engine.
