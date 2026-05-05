# AuditLens Session Handoff - 2026-05-05

## 1. Executive Summary

AuditLens is now positioned as a deterministic Audit Decision Engine over the path:

Kafka -> forwarder -> DB -> FastAPI -> Next.js UI

The current product path keeps Streamlit untouched and builds the product UI alongside it. The latest work focused on correctness, decision clarity, source/IP accuracy, actor display, triage lifecycle, and event filtering performance without changing architecture or adding an LLM.

## 2. Current Product State

- Latest Mode is implemented on `/events`.
- Default event filters are:
  - `time_window=2h`
  - `hide_noise=true`
  - `signal_type=attention,action_required`
- `/events` and `/summary` support:
  - `time_window`
  - `resource_type`
  - `resource`
  - `action_category`
  - `actor`
  - `result`
  - `signal_type`
  - `hide_noise`
  - `impact_type`
  - `change_type`
- Event list responses exclude raw payload.
- Event detail responses include raw payload.
- Raw payload remains collapsed in the drawer.

## 3. Key Work Completed

### Source/IP correctness

- Added `src/product/source_enrichment.py`.
- Source extraction now uses:
  - top-level `clientIp`
  - `source_ip`
  - `sourceIp`
  - `sourceAddress`
  - `data_json.requestMetadata.clientAddress[0].ip`
- Source/IP no longer falls back to:
  - `cluster_id`
  - `source_context`
- API now exposes computed source fields:
  - `source_display`
  - `source_reason`
  - `client_id`
  - `connection_id`
  - `request_id`
- UI Source/IP column uses `source_display`.
- Drawer separates:
  - Source IP
  - Cluster
  - Client ID
  - Connection ID
  - Request ID

### Actor enrichment

- Added `src/product/actor_enrichment.py`.
- API exposes:
  - `actor_display_name`
  - `actor_email`
  - `actor_type`
  - `actor_raw_id`
- Resolution order:
  1. `ACTOR_IDENTITY_MAP_JSON`
  2. fallback `u-*` -> `Unknown user`
  3. fallback `sa-*` -> `Unknown service account`
- UI Who column shows enriched name first and raw ID as secondary text.

### Decision explanation

- Event intelligence now returns `decision_reason`.
- Examples:
  - `Destructive operation: topic deletion`
  - `Authorization failure detected`
  - `Configuration change detected`
  - `Routine read activity`
- Drawer shows `Decision Reason`.

### Triage lifecycle

- Added `src/product/triage_store.py`.
- New endpoint:
  - `POST /events/{event_id}/triage`
- Supported statuses:
  - `open`
  - `acknowledged`
  - `approved`
  - `investigating`
  - `resolved`
  - `false_positive`
- Storage is file-backed by default:
  - `data/triage_state.json`
- Triage store now caches the file in memory and writes through on update.
- Triage status overrides visual decision label only; original `signal_type` remains unchanged.

### Resource type filtering

- Root cause fixed: resource filtering was exact/case-sensitive while data used mixed labels like `Topic` and upstream values can be `TOPIC`.
- Added canonical lowercase resource types in `src/product/event_normalization.py`.
- Canonical examples:
  - `topic`
  - `subject`
  - `connector`
  - `role_binding`
  - `environment`
  - `cluster`
  - `api_key`
  - `schema_registry`
  - `compute_pool`
- API output normalizes `resource_type` via schema validator.
- `/filters/options` returns canonical resource types and includes the expected core values.
- `/events?resource_type=TOPIC`, `Topic`, and `topic` now match consistently.

### Performance and visibility

- Frontend initial `/events` fetch reduced from 100 to 50 rows.
- DB-backed filters are applied before `LIMIT`.
- Derived filters remain bounded by `SIGNAL_FILTER_MAX_SCAN=5000`.
- Destructive derived filters now prefilter by `action_category=Delete` to avoid missing older delete events behind newer noise.
- `/events?debug=true` returns:
  - applied filters
  - row count before derived filtering
  - scanned event count
  - row count after derived filtering
  - whether derived filtering applied
  - resource type distribution
- UI now warns:
  - `Some events are hidden due to filters.`
- Active filter labels are human-readable:
  - `Last 2 hours`
  - `Only important activity`
  - `Routine noise hidden`

### UX/UI productization

- Events table remains six columns:
  - Time
  - Decision
  - Who
  - What happened
  - Resource
  - Source/IP
- Decision banner, narrative strip, signal summary, flow cards, triage controls, and detail drawer exist.
- `/layout-lab` exists as a visual playground only.

## 4. Important Files

Backend:

- `backend/app/api/routes/events.py`
- `backend/app/api/routes/summary.py`
- `backend/app/db/models.py`
- `backend/app/schemas/event.py`
- `backend/app/schemas/response.py`
- `backend/app/services/event_service.py`
- `backend/app/services/filter_options_service.py`
- `backend/app/services/summary_service.py`

Product helpers:

- `src/product/actor_enrichment.py`
- `src/product/event_intelligence.py`
- `src/product/event_normalization.py`
- `src/product/event_signals.py`
- `src/product/source_enrichment.py`
- `src/product/triage_store.py`

Frontend:

- `frontend/app/events/page.tsx`
- `frontend/components/AuditEventTable.tsx`
- `frontend/components/EventDetailDrawer.tsx`
- `frontend/components/FilterBar.tsx`
- `frontend/components/DecisionBanner.tsx`
- `frontend/components/SignalSummaryPanel.tsx`
- `frontend/lib/api.ts`
- `frontend/lib/eventFilters.ts`
- `frontend/lib/types.ts`

Tests:

- `backend/tests/test_api.py`
- `tests/test_event_intelligence.py`
- `tests/test_event_signals.py`
- `tests/test_productization.py`
- `frontend/tests/render-smoke.mjs`

## 5. Validation Status

Latest validation run:

- Compile passed:
  - `python3 -m compileall audit_forwarder.py src/product/db_writer.py src/product/event_intelligence.py src/product/event_signals.py backend/app`
- Frontend smoke passed:
  - `npm --prefix frontend test`
- Frontend build passed:
  - `npm --prefix frontend run build`
- Focused product/API suite passed:
  - `API_AUTH_ENABLED=false pytest -q tests/test_event_signals.py tests/test_event_intelligence.py tests/test_productization.py backend/tests/test_api.py tests/test_foundation_contract.py`
  - Result: `104 passed`

Known validation caveat:

- Full `pytest -q` fails during collection because this dirty workspace has `scripts/bootstrap_auditlens.py` deleted while `tests/test_bootstrap_setup.py` still imports it.
- This appears related to prior repo cleanup/deprecation work, not this Audit Decision Engine patch.
- Do not silently resurrect deprecated scripts without deciding whether bootstrap setup tests should be updated or the deprecated script restored as a compatibility shim.

## 6. Known Risks / Caveats

- Historical DB rows can still physically contain mixed-case resource types. API and filter layers canonicalize without DB migration.
- Derived filters other than destructive still rely on bounded scanning because `signal_type`, `impact_type`, and `change_type` are computed fields.
- Triage is file-backed and single-instance oriented. It is appropriate for current single-instance product mode, not multi-instance HA.
- Actor enrichment is manual/fallback only. No Confluent IAM API lookup is wired.
- `ACTOR_IDENTITY_MAP_JSON` must be provided by operators if display names/emails are desired.
- Source IP can only be shown if Confluent audit payload provides it. Otherwise UI correctly shows `Not provided by audit event`.
- `/layout-lab` is a visual playground and should not be treated as production workflow.

## 7. Current Git State

Latest commits:

- `4837d95 v1: E2E validated, performance fixed, production-ready baseline`
- `adf873a fix: critical production fixes v3.0.1`
- `05e95c8 feat: audit-forwarder-feb v3.0.0 — clean fork from v2.2.0`

Worktree is dirty with many changes from multiple sessions, including:

- productization code
- repo cleanup/archive moves
- docs/session history moves
- frontend product UI additions
- backend API hardening
- source/actor/triage/event intelligence helpers

Do not assume every dirty file belongs to the latest patch. Review `git status --short` before editing.

## 8. Recommended Next Session Plan

1. Start by running:
   - `scripts/session_start.sh`
   - `git status --short`
   - `git log --oneline -5`
2. Decide how to handle the full `pytest -q` blocker:
   - update/remove `tests/test_bootstrap_setup.py`, or
   - restore `scripts/bootstrap_auditlens.py` as a deprecated shim from `scripts/deprecated/bootstrap_auditlens.py`.
3. Re-run focused validation:
   - compile
   - product/API pytest suite
   - frontend test/build
4. If Docker is available, rebuild API/frontend and validate:
   - `/events?limit=50&time_window=2h&hide_noise=true&signal_type=attention,action_required`
   - `/events?resource_type=TOPIC&debug=true`
   - `/events?impact_type=destructive`
   - `/summary?time_window=2h&hide_noise=true`
   - UI `/events`
5. Test triage in browser:
   - open a drawer
   - mark event approved/resolved
   - confirm row decision label updates
6. Decide if triage file path needs explicit `.env.example` documentation.
7. Only after validation, prepare a concise changelog entry and ask for confirmation before appending.

## 9. Do Not Touch Without Explicit Request

- Do not refactor `audit_forwarder.py`.
- Do not remove Streamlit dashboards.
- Do not add LLM calls.
- Do not add charts.
- Do not introduce new architecture or distributed storage.
- Do not add DB schema migrations unless absolutely required.
- Do not push or commit secrets.
- Do not reintroduce observability into the default Docker path.

## 10. Useful Commands

Focused validation:

```bash
python3 -m compileall audit_forwarder.py src/product/db_writer.py src/product/event_intelligence.py src/product/event_signals.py backend/app
API_AUTH_ENABLED=false pytest -q tests/test_event_signals.py tests/test_event_intelligence.py tests/test_productization.py backend/tests/test_api.py tests/test_foundation_contract.py
npm --prefix frontend test
npm --prefix frontend run build
```

Runtime checks:

```bash
curl -s 'http://127.0.0.1:8080/events?limit=50&time_window=2h&hide_noise=true&signal_type=attention,action_required'
curl -s 'http://127.0.0.1:8080/events?resource_type=TOPIC&debug=true'
curl -s 'http://127.0.0.1:8080/events?impact_type=destructive'
curl -s 'http://127.0.0.1:8080/summary?time_window=2h&hide_noise=true'
```

SQLite demo:

```bash
cp .env.example .env
scripts/run_sqlite_demo.sh
scripts/health_check.sh
```

Postgres product mode:

```bash
cp .env.example .env
# fill Kafka credentials
scripts/run_postgres_product.sh
scripts/health_check.sh
```

