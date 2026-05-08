# Backlog

Pending items from the 2026-05-08 session, in priority order. Tick items as they land; add new ones at the bottom of the relevant section.

## Now

- [ ] **Wait for the live backfill to finish** — `scripts/backfill_classification.py` running against the live Postgres (PID was 44170 at session end, watch `/tmp/backfill.log`). At ~5.75M / 9.7M rows. ETA 30–60 min from session end.
- [ ] **Add a composite partial index for the new default `/events` filter combo** — currently 45 s wall-clock, kept from 500-ing only by the 120 s `statement_timeout` bump. Run `EXPLAIN (ANALYZE, BUFFERS)` on:
  ```
  SELECT count(*) FROM audit_events
  WHERE timestamp >= now() - interval '24 hours'
    AND signal_type IN ('action_required','attention')
    AND is_routine_noise = false;
  ```
  Likely fix: `CREATE INDEX CONCURRENTLY idx_audit_events_attention_time ON audit_events (timestamp DESC, signal_type) WHERE is_routine_noise = false;`. Ship via Alembic 0006 + matching `Index()` in `backend/app/db/models.py`. Apply with `CREATE INDEX CONCURRENTLY` on the live DB.
- [ ] **`BindRoleForPrincipal`** — surfaced by the catch-all log during today's backfill, not in the original gap analysis. Add to `src/classification/methods.py` (HIGH; promotes role binding) and confirm it routes to `Security` action_category via the existing `rolebinding` marker.

## Next

- [ ] **URL-sync filters + pagination on `/events`** — use `useSearchParams` + `router.replace`; persist all filter keys + offset. Enables shareable links, browser back/forward, and reload-safe state. Per `docs/UI_AUDIT.md` §5 Medium item 1.
- [ ] **Free-text search box** — single backend `q=` param scanning summary/title/actor/resource. `docs/UI_AUDIT.md` §5 Medium item 10.
- [ ] **CSV / JSON export** for the current view.
- [ ] **Manual refresh button** on `/events` with a "Last loaded HH:MM" timestamp. `docs/UI_AUDIT.md` §5 Medium item 7.
- [ ] **First real deployment** — Terraform for AWS Fargate exists at `deploy/terraform/aws/` (last touched in 2026-05-07 Phase 3). Operator action required to `terraform apply`.

## Later

- [ ] **`docs/UI_AUDIT.md` §5 Simple items not yet implemented** — `SummaryCards` data freshness was done; remaining simple items still relevant: tooltips on quick-filter chips, sync `result` filter casing server-side (currently handled in eventFilters.ts client-side translation), …
- [ ] **`docs/UI_AUDIT.md` §5 Medium remaining** — inline triage buttons on table rows, group rapid event runs by actor+resource+action, persist last-used filter set in localStorage, "show only critical resources" toggle.
- [ ] **Streamlit dashboard retirement** — per `DASHBOARD_GAP_ANALYSIS.md`, the legacy Streamlit dashboards (`dashboard/app.py`, `app_clean.py`, `app_legacy_full.py`) duplicate the Next.js UI minus charts. Decide whether to keep for charts-only or retire.
- [ ] **Forwarder monolith split** — `audit_forwarder.py` is still a 152 KB single file (per Phase 3 deferred items). Split into 5–6 modules.
- [ ] **Materialised `summary_rollup_5m` table** — for sub-100 ms `/summary` independent of window size. Design sketched in `docs/PHASE4_SUMMARY_PERF.md`.
- [ ] **Live Confluent Cloud key rotation** — `.env` Confluent credentials still need operator action.
- [ ] **`Dockerfile.alpine` digest pin** — placeholder `@sha256:xxx` in the alpine variant.
- [ ] **Streamlit auth** — Streamlit dashboards have no auth.
- [ ] **Default Grafana password** in `deploy/docker/docker-compose.yml`.

## Done today (2026-05-08)

- [x] Frontend API URL + `/filters/options` 30 s 500 → 1.5 s 200 (`3b7c766`)
- [x] Forwarder classification gaps — action_category cascade, 30+ resource_type aliases, methods.py + YAML promotions, catch-all log warning, manual backfill script (`d1557ee`)
- [x] UI sprint — defaults, declutter, signal clarity, drawer cleanup, dashboard error notices, AbortController, freshness banners, lag warnings (`2b52011`)
- [x] `test_db_mode_scripts` 2 pre-existing failures (`f8a95bc`)
