## [2026-05-05] Session [1]

### Fixed
- Source/IP display now uses actual audit payload source information and never falls back to cluster IDs.
  Why: The Events table was misleadingly showing values like `lkc-k9382g` in the Source/IP column when Confluent did not provide a client IP.
  Files: src/product/source_enrichment.py, src/product/event_normalization.py, src/product/event_intelligence.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/components/AuditEventTable.tsx, frontend/components/EventDetailDrawer.tsx, backend/tests/test_api.py, tests/test_event_intelligence.py

- Actor display now uses computed enrichment fields with manual mapping support and safe fallbacks for raw Confluent IDs.
  Why: Raw IDs such as `u-*` and `sa-*` are not enough for operators; mapped names/emails should be shown when available while preserving raw IDs for auditability.
  Files: src/product/actor_enrichment.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/components/AuditEventTable.tsx, frontend/components/EventDetailDrawer.tsx, backend/tests/test_api.py, tests/test_event_intelligence.py

- Resource type filtering now accepts mixed Confluent/UI values and returns canonical lowercase resource types.
  Why: Filtering was exact and case-sensitive, so values like `TOPIC`, `Topic`, and `topic` could produce confusing missing-data behavior.
  Files: src/product/event_normalization.py, backend/app/services/event_service.py, backend/app/services/filter_options_service.py, backend/app/services/summary_service.py, backend/app/schemas/event.py, backend/tests/test_api.py, tests/test_productization.py

- Destructive derived filtering now prefilters delete actions before bounded derived classification.
  Why: Older topic delete events could be hidden behind newer routine activity when derived filtering scanned only the latest bounded candidate set.
  Files: backend/app/services/event_service.py, backend/tests/test_api.py

- Triage state now caches file-backed status in memory instead of reading the triage JSON file per event.
  Why: Row rendering should not perform repeated file reads for every listed event.
  Files: src/product/triage_store.py

### Added
- Deterministic source enrichment fields: `source_display`, `source_reason`, `client_id`, `connection_id`, and `request_id`.
  Why: The UI needs a trustworthy Source/IP column and the drawer needs structured connection/request context without showing raw JSON by default.
  Files: src/product/source_enrichment.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/lib/types.ts, frontend/components/EventDetailDrawer.tsx

- Event-level `decision_reason`.
  Why: Operators need to understand why an event was classified as action-needed, review, info, or noise.
  Files: src/product/event_intelligence.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/lib/types.ts, frontend/components/AuditEventTable.tsx, frontend/components/EventDetailDrawer.tsx

- Lightweight triage lifecycle endpoint and UI controls.
  Why: Action-needed events should not stay visually action-needed forever after an operator acknowledges, approves, investigates, resolves, or marks them false positive.
  Files: src/product/triage_store.py, backend/app/api/routes/events.py, backend/app/db/models.py, backend/app/schemas/event.py, frontend/lib/api.ts, frontend/app/events/page.tsx, frontend/components/AuditEventTable.tsx, frontend/components/EventDetailDrawer.tsx, frontend/app/globals.css, backend/tests/test_api.py

- `/events?debug=true` diagnostic metadata.
  Why: Developers/operators need to explain filter behavior and distinguish DB filters from bounded derived filters.
  Files: backend/app/api/routes/events.py, backend/app/services/event_service.py, backend/app/schemas/response.py, backend/tests/test_api.py

- Audit Decision Engine session handoff.
  Why: The next session needs a compact continuation point with current state, validations, caveats, and next actions.
  Files: docs/session-history/CODEX_SESSION_HANDOFF_2026_05_05_AUDIT_DECISION_ENGINE.md

### Removed
- none.
  Why: This pass intentionally avoided architecture changes, Streamlit removal, schema migrations, and product refactors.
  Files: none

### Architecture Decisions
- Keep triage as an additive file-backed layer rather than modifying event classification or changing the DB schema.
  Why: Triage is an operator workflow state; it should not mutate the immutable audit event or require a migration during this hardening pass.
  Impact: Current triage is appropriate for single-instance product mode, not multi-instance HA.

- Canonicalize resource types at API/filter boundaries without migrating historical rows.
  Why: Historical data may contain mixed labels; compatibility is safer than an immediate data rewrite.
  Impact: New writes normalize resource types, while API responses and filters canonicalize old values.

- Keep derived signal/impact/change filters bounded unless backed by an indexed prefilter.
  Why: These fields are computed and not persisted, so scanning the entire DB synchronously would risk performance.
  Impact: Destructive filters are helped by `action_category=Delete`; other derived filters remain bounded.

### Known Issues / Not Done
- Full `pytest -q` currently fails during collection because `tests/test_bootstrap_setup.py` imports deleted `scripts/bootstrap_auditlens.py`.
  Why deferred: This appears tied to prior repo cleanup/deprecation work and should be handled deliberately by either updating the test or restoring a deprecated shim.

- Actor enrichment remains manual/fallback only.
  Why deferred: No Confluent IAM API lookup was added; avoiding external calls and extra product scope was intentional.

- Triage is file-backed and single-instance oriented.
  Why deferred: Multi-instance persistence would require a stronger storage contract and likely a DB table/migration, which was outside this pass.

- Existing DB rows may physically retain mixed-case resource types.
  Why deferred: API and filter layers now canonicalize them without a migration.
