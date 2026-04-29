# Path To 9 Readiness

Timestamp: 2026-04-27T10:11:45Z

This plan is anchored to the current validated runtime, not to the earlier local disk-full outage state.

## Current validated score recommendation

- Architecture: 7.5/10
- Observability: 8.8/10
- Reliability: 6.5/10
- Product readiness: 6.5/10

## Target score

- Architecture: 9/10
- Observability: 9/10
- Reliability: 9/10
- Product readiness: 9/10

## Architecture

Current gaps:

- Streamlit still reads Kafka directly for part of the product surface.
- SQLite is still operating as both hot cache and de facto investigation store.
- Derived signal and alert identifiers are not fully deterministic across every path.
- Tableflow is documented as the archive direction, but not yet part of the delivered product boundary.

Why this is not 9 today:

- The product query path is not fully consolidated behind API plus persistence.
- Long-term archive and hot operational state are not cleanly separated.
- Replay safety is directionally correct, but not yet strong enough to guarantee idempotent derived state everywhere.

Concrete changes needed:

1. Keep SQLite bounded as hot cache only.
2. Make API plus persistence the only product-mode query path.
3. Remove direct Kafka reads from the dashboard in product mode.
4. Position Tableflow as the standard long-term archive for `audit.raw.v1` and `audit.enriched.v1`.
5. Make signal and alert identifiers deterministic across replay and normal ingestion.

Implementation order:

1. Deterministic IDs for derived records.
2. API-first dashboard data path.
3. Remove product-mode direct Kafka reads.
4. Add archive integration boundary for long-range history.

Validation method:

- The dashboard no longer needs Kafka credentials in product mode.
- The same query returns the same answer from API and UI.
- Replay does not multiply derived alerts or summaries.

Expected score after completion:

- 9/10

## Observability

Current gaps:

- Runtime health, semantic coverage, and storage pressure are still easy to confuse.
- Landing `/status` is basic reachability plus semantic state, but it does not yet explain every degraded condition in operator language.
- Alert rules are live, but there is still limited end-to-end operator workflow around them.

Why this is not 9 today:

- The system exposes strong raw signals, but not every surface explains them consistently.
- Coverage and completeness are still easier to misread than they should be.

Concrete changes needed:

1. Keep storage, lag, cleanup, checkpoint, and replay visibility in `/health` and `/metrics`.
2. Keep Prometheus alert rules live and loaded by default.
3. Separate pipeline health from data coverage/completeness in every user-facing surface.
4. Improve landing and dashboard summaries so they explain warning versus critical versus unreachable states directly.

Implementation order:

1. Finish semantic health mapping across landing and dashboard.
2. Add lag and replay warning presentation.
3. Add operator-facing alert response links or next-action hints.

Validation method:

- `/health` and `/metrics` stay available during warning states.
- Prometheus rules API lists the expected storage alerts.
- Landing and dashboard show the same storage state as the forwarder health payload.

Expected score after completion:

- 9/10

## Reliability

Current gaps:

- The system is currently stable, but SQLite has already exceeded its configured maximum size while still reporting `storage_status=warning`.
- Retention is static and does not automatically adapt when the configured hot window no longer fits the disk budget.
- Replay exists, but dry-run and stronger deterministic rebuild guarantees are still missing.
- Failure-injection coverage is still narrow.

Why this is not 9 today:

- The product can detect storage pressure, but it still lacks prevention.
- Predictable local-failure modes remain operational rather than controlled.

Concrete changes needed:

1. Enforce bounded hot-cache limits relative to disk budget.
2. Add adaptive retention or explicit disk-budget guardrails.
3. Add safer degraded mode when persistence pressure rises.
4. Add replay dry-run and stronger deterministic replay guarantees.
5. Add failure-injection tests for disk-full, cleanup no-op, checkpoint failure, and replay interruption.
6. Keep Prometheus stable with validated rule loading in default local mode.

Implementation order:

1. Disk-budget enforcement and retention guardrails.
2. Safer degraded persistence mode.
3. Replay dry-run and deterministic rebuild semantics.
4. Failure injection and soak testing.

Validation method:

- SQLite can enter warning without crashing the whole service.
- Disk-pressure tests prove bounded behavior.
- Replay can be rehearsed without mutating live state.
- Persistence cleanup and checkpoint behavior remain observable.

Expected score after completion:

- 9/10

## Product readiness

Current gaps:

- Dashboard auth is still missing.
- Audit-of-audit is incomplete because UI reads are not fully API-backed.
- The product still depends on a local-operator deployment model rather than a hardened shared deployment boundary.

Why this is not 9 today:

- The control plane is not yet consistently secured and audited across every user-facing path.
- The current dashboard is useful, but not yet a product-grade authenticated surface.

Concrete changes needed:

1. Add dashboard auth or replace the dashboard path with an authenticated API-backed UI.
2. Enforce RBAC and scope filtering consistently through the UI.
3. Ensure audit-of-audit logging covers all read and export paths.
4. Keep deployment prerequisites and security controls tied to actual runtime checks.
5. Keep Tableflow positioned as archive path, not hot operational query DB.

Implementation order:

1. Authenticated UI path.
2. End-to-end RBAC and scope enforcement.
3. Audit-of-audit logging.
4. Shared-deployment hardening review.

Validation method:

- UI access follows the same roles and scopes as the API.
- Exports are role-gated and auditable.
- Customer deployment review can map every documented control to code and runtime behavior.

Expected score after completion:

- 9/10
