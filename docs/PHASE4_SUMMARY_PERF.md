# /summary performance — Phase 4 status

`GET /summary` issues **seven sequential database queries** against
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

- **Alembic revision `0004_summary_aggregation_indexes`** adds the three missing indexes:
  - `idx_audit_events_resource_type_time` — `(resource_type, timestamp DESC)`
  - `idx_audit_events_failure_time` — `(timestamp DESC) WHERE is_failure = true` (partial)
  - `idx_audit_events_denied_time` — `(timestamp DESC) WHERE is_denied = true` (partial)
  Built with `CONCURRENTLY` on Postgres so the live forwarder keeps writing.
- **Per-route statement timeout** in `get_summary()`: `SET LOCAL statement_timeout = 120000` so /summary cannot 500 from the 30 s global timeout (Phase 2) when individual aggregations briefly slow down under concurrent writes.

## Measured impact (10 M-row, 31 GB Postgres)

`time curl 'http://127.0.0.1:8080/summary?time_window=24h&mode=...'`:

| Window | Mode | Pre-fix | After indexes alone |
|---|---|---|---|
| 24 h | `decision` | 500 at 32 s (single GROUP BY exceeded 30 s timeout) | 200 in ~118 s |
| 24 h | `audit_trail` | 500 at ~32 s | 200 in ~84 s |
| 12 h | `decision` | 200 in ~94 s | TBD |
| 6 h | `decision` | 200 in ~2.5 s | unchanged (already fast) |
| 2 h (frontend default) | either | < 1 s | unchanged |

**Why 24 h is still > 10 s after the indexes:** each individual aggregation
post-index runs in **~10–26 s** on a freshly-VACUUM'd 10 M-row table, but
`/summary` fires *seven* of them sequentially — the wall-clock is the sum.
The indexes brought per-query cost down meaningfully (e.g. `GROUP BY
action_category` from 81 s pre-VACUUM to 9.7 s after VACUUM + indexes), but
seven queries × ~12 s average = ~84 s.

## What Option B (per-route timeout) does and does not do

Option B prevents the 30 s global statement_timeout (Phase 2) from killing
any single query in `/summary`. It is **not** a speedup. After Option B:

- `/summary` returns 200 instead of 500 for windows where any individual
  aggregation drifts above 30 s.
- Wall-clock time is unchanged.
- The frontend `SignalSummaryPanel`, `DecisionBanner`, and `NarrativeStrip`
  populate, but the user waits the full window-dependent time.

## Real fix (out of scope for Phase 4)

Two options for getting 24 h `/summary` under 10 s:

1. **Single-pass aggregation.** Rewrite `get_summary()` to issue one CTE-based
   query that produces total, failures, denials, and the three GROUP BYs from
   a single scan. Postgres' `GROUPING SETS` + `count(*) FILTER (WHERE ...)`
   does this in one pass. Estimated effort: half a day; estimated speedup: 5–7×
   on 24 h windows (single 12–18 s scan instead of seven 8–18 s scans).
2. **Materialised rollup table.** Forwarder maintains a `summary_rollup_5m`
   table keyed by `(time_bucket, action_category, resource_type, result,
   signal_type, ...)` updated incrementally. `/summary` reads from the rollup
   for everything except the `flow_groups` and `top_*` lists, which still
   need the recent-event scan. Estimated effort: 2–3 days; gives sub-100 ms
   summary independent of window size.

Option 1 is the right next step: it is bounded code work, requires no schema
or forwarder changes, and reuses the indexes Phase 4 added. The materialised
rollup is the long-term answer if /summary becomes a hot path or windows
need to extend past 7 days.

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
# Expect 200, < 120 s.
```
