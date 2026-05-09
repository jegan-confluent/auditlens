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
