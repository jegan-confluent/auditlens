# /summary performance — Phase 4

> **Status:** single-pass `GROUPING SETS` refactor landed. 24 h
> `mode=decision` runs in ~22 s on a 10 M-row / 31 GB Postgres (down from
> ~125 s with indexes alone, ~32 s timeout pre-fix). 6 h is ~2 s. Indexes
> from revision 0004 still load-bear — the single-pass query reads them.

Originally `GET /summary` issued **seven sequential database queries** against
`audit_events`, all sharing the same `WHERE timestamp >= cutoff [AND
decision_mode_OR]` predicate (see `backend/app/services/summary_service.py:get_summary`):

| # | Query | Pre-Phase-4 index | Post-Phase-4 index |
|---|---|---|---|
| 1 | `count(*) WHERE ...` (total) | `idx_audit_events_timestamp_desc` | unchanged |
| 2 | `count(*) WHERE ... AND is_failure=true` | full index scan + filter | `idx_audit_events_failure_time` (partial) |
| 3 | `count(*) WHERE ... AND is_denied=true` | full index scan + filter | `idx_audit_events_denied_time` (partial) |
| 4 | `SELECT … ORDER BY timestamp DESC LIMIT 5000 WHERE ...` | `idx_audit_events_timestamp_desc` | unchanged |
| 5 | `GROUP BY action_category WHERE ...` | `idx_audit_events_action_category_time` | unchanged |
| 6 | `GROUP BY resource_type WHERE ...` | `idx_audit_events_resource_type` (no time component) | `idx_audit_events_resource_type_time` (composite) |
| 7 | `GROUP BY result WHERE ...` | `idx_audit_events_result_time` | unchanged |

## Phase 4 changes

- **Alembic revision `0004_summary_aggregation_indexes`** adds three missing
  indexes that the new single-pass query uses:
  - `idx_audit_events_resource_type_time` — `(resource_type, timestamp DESC)`
  - `idx_audit_events_failure_time` — `(timestamp DESC) WHERE is_failure = true` (partial)
  - `idx_audit_events_denied_time` — `(timestamp DESC) WHERE is_denied = true` (partial)
  Built with `CONCURRENTLY` on Postgres so the live forwarder keeps writing.
- **Per-route statement timeout** in `get_summary()`:
  `SET LOCAL statement_timeout = 120000`. After the single-pass refactor this
  is defence in depth; the route normally finishes well under 30 s, but the
  raised local ceiling absorbs cost spikes from concurrent forwarder writes
  or autovacuum activity.
- **Single-pass `GROUPING SETS` aggregation** replaces six of the seven
  queries on Postgres. `_aggregate_with_grouping_sets()` issues one statement
  using `GROUP BY GROUPING SETS ((), (action_category), (resource_type),
  (result))` and `count(*) FILTER (WHERE …)` to collect total / failures /
  denials and the three GROUP BYs in a single scan of the windowed rowset.
  SQLite keeps the original multi-query path (no `GROUPING SETS` support
  needed for the demo dataset).

### Query count by path (Postgres / 24 h window)

| Path | Pre-refactor | Post-refactor |
|---|---|---|
| `derived_filter_applied = False` (heavy production path) | 7 queries | **2 queries** (one GROUPING SETS, one scan) |
| `derived_filter_applied = True` (signal/impact/change/hide_noise filters) | 4 queries | **2 queries** (one count, one scan) |

## Measured impact (10 M-row, 31 GB Postgres)

`time curl 'http://127.0.0.1:8080/summary?time_window=24h&mode=...'`:

| Window | Mode | Pre-fix | Indexes only | **Indexes + GROUPING SETS** |
|---|---|---|---|---|
| 24 h | `decision` | 500 at 32 s | 200 in ~125 s | **200 in ~22 s** |
| 24 h | `audit_trail` | 500 at ~32 s | 200 in ~84 s | expected ~15 s (one scan vs seven) |
| 6 h | `decision` | 200 in ~2.5 s | unchanged | **200 in ~2 s** |
| 2 h (frontend default) | either | < 1 s | unchanged | < 1 s |

The single-pass query reads the same indexes the original seven queries
needed — `idx_audit_events_timestamp_desc` for the WHERE selectivity and
the three new ones from revision 0004 for the FILTER counts and the
resource_type GROUP BY. The 5–7× wall-time speedup comes from doing the
scan once instead of seven times.

## Per-route statement timeout — defence in depth

`SET LOCAL statement_timeout = 120000` in `get_summary()` raises the
per-statement budget for /summary alone. After the single-pass refactor the
route normally finishes inside Phase 2's 30 s default; the local override
absorbs outliers (concurrent forwarder writes, autovacuum) without 500-ing.
`SET LOCAL` is scoped to the current transaction and reverts on commit.

## Long-horizon option (still deferred)

If `/summary` ever needs to support windows longer than ~24 h or sub-second
response time:

- **Materialised rollup table.** Forwarder maintains a `summary_rollup_5m`
  table keyed by `(time_bucket, action_category, resource_type, result,
  signal_type, ...)` updated incrementally. `/summary` reads from the rollup
  for everything except the `flow_groups` and `top_*` lists, which still
  need the recent-event scan. Estimated effort: 2–3 days; gives sub-100 ms
  summary independent of window size.

Not currently scheduled — current performance meets the dashboard's need.

## Why caching at the API layer was rejected

`/summary` reflects "the most recent state of the world". Caching its result
for, say, 30 s would make every dashboard interaction (filter changes, mode
toggles) eventually-consistent in a way that surprises users investigating an
incident. The route currently has no cache-buster, and the frontend calls it
on every filter change. If we add caching it must be tied to a deliberate
freshness contract, which is its own design discussion.

## Verification

```bash
DATABASE_URL=postgresql+psycopg://auditlens:auditlens@127.0.0.1:5432/auditlens \
  alembic -c backend/alembic.ini upgrade head

# Confirm the three indexes exist:
docker exec auditlens-postgres psql -U auditlens -d auditlens -c \
  "SELECT indexname FROM pg_indexes WHERE tablename='audit_events' AND
   indexname IN ('idx_audit_events_resource_type_time',
                 'idx_audit_events_failure_time',
                 'idx_audit_events_denied_time');"

# Spot-check timing:
time curl -s 'http://127.0.0.1:8080/summary?time_window=24h&mode=decision' >/dev/null
# Target: 200, < 25 s.
time curl -s 'http://127.0.0.1:8080/summary?time_window=6h&mode=decision' >/dev/null
# Target: 200, < 5 s.
```

## Architecture notes

`_aggregate_with_grouping_sets()` (Postgres path) decodes
`GROUPING(action_category, resource_type, result)` bitmask values:

| Grouping set | `GROUPING()` returns | Semantics |
|---|---|---|
| `()` | 7 (binary `111`) | Overall row: total, failures, denials |
| `(action_category)` | 3 (binary `011`) | One row per `action_category` value |
| `(resource_type)` | 5 (binary `101`) | One row per `resource_type` value |
| `(result)` | 6 (binary `110`) | One row per `result` value |

A 1-bit means the column is *not* part of that grouping (i.e. rolled up to
NULL in that row). Argument order in `GROUPING()` decides bit position with
the leftmost argument occupying the most significant bit.
