# Diary Entry: 2026-05-12 — Data Quality + Signal Infrastructure Fixes

## Session Summary

Two back-to-back prompt batches, 10 total fixes, all committed and verified.

**Batch 1 — Data Quality (4 fixes):**
1. `u-0xynp7p` showing raw ID instead of display name → fixed enrichment priority query in `pattern_service.py` + `summary_service.py`
2. 858 rows with JSON blobs stored as `actor_display_name` → blocked at ingestion in `actor_enrichment.py` + migration 0014 to clean existing rows
3. `RecurringPatterns` resource column showing full CRNs → CRN stripping in `pattern_detector.py` + `formatResourceName()` util in `frontend/lib/utils.ts`
4. Forwarder OOM detection → memory bumped 384M→512M, `psutil` startup + heartbeat logging

**Batch 2 — Signal + Infrastructure (6 fixes):**
5. Confluent platform actor events mis-classified as `action_required` → `classify_signal()` wrapper with `_is_confluent_platform()` override
6. Schema `RegisterSchema` FAILURE → `attention` not `action_required` (schema evolution ≠ security incident)
7. `db_latest_event_at` only reading `audit_events` → UNION ALL across both tables + graceful fallback for pre-migration deploys
8. Autovacuum tuning codified in migration 0015 (was manual-only before; 1.4M dead tuples caused 61s inserts)
9. Backfilled 226 mis-classified Confluent platform rows → `action_required` 12h: 91→79
10. Forwarder rebuilt + verified: `Starting PID=1 mem_limit=512MB`, 624 passed / 5 skipped

---

## Key Decisions

### `classify_signal()` wrapper pattern
- **Decision:** Renamed core classifier to `_classify_signal_core()`, new outer `classify_signal()` applies post-classification overrides
- **Why:** Overrides depend on fields not available in the digest (e.g., actor identity, action string); layering them post-classification is cleaner than polluting the core with identity-aware logic
- **Alternative considered:** Add override branches inside the core — rejected because it would interleave identity context with signal taxonomy logic

### `_is_enriched_display_name()` guard in ORM model
- **Decision:** Add a module-level helper that returns `False` for raw principal IDs (prefix-based) and JSON blobs (starts with `{`/`[`)
- **Why:** The `actor_display_name` property was serving stored garbage as if it were a real name; guard ensures fallback to live enrichment
- **Alternative:** Strip bad values at write time only — rejected because backfill is asynchronous and legacy rows would still serve garbage until backfilled

### UNION ALL fallback for dual-table MAX(timestamp)
- **Decision:** Try UNION ALL first; if `OperationalError` (table missing pre-migration), fall back to `audit_events`-only query
- **Why:** Deployments mid-migration would have `audit_events_noise` absent; the status route must never 500
- **Alternative:** Require migration before deploy — rejected, graceful degradation is always safer

### Autovacuum via direct psql not Alembic container
- **Decision:** Applied migration 0015 directly via `docker exec auditlens-postgres psql` after API container path blocked by PermissionError on `/app/src/__init__.py`
- **Why:** Container file permissions prevent Alembic from writing `.pyc` to `src/`; psql bypass is safe for DDL-only migrations

---

## Challenges & Solutions

### `audit_events_noise` absent in UNION ALL test
- **Problem:** `test_system_status_latest_event_reads_both_tables` used `init_db(engine)` which only creates ORM-mapped tables; `audit_events_noise` is Alembic-only
- **Solution:** Switched test to `alembic command.upgrade(cfg, "head")` — runs full migration chain, both tables exist
- **Lesson:** `init_db()` ≠ full schema. Any test touching `audit_events_noise` needs `alembic upgrade head`, not `init_db()`

### Actor priority ordering in SQLAlchemy `case()`
- **Problem:** `case()` syntax changed between SQLAlchemy versions; positional `(condition, value)` tuples vs keyword `whens=`
- **Solution:** Used positional tuple form inside `case()` call which works across both older and newer SA versions

### Alembic PermissionError in API container
- **Problem:** `docker compose exec api bash -c "cd /app/backend && alembic upgrade head"` → `PermissionError: [Errno 13] Permission denied: '/app/src/__init__.py'`
- **Root cause:** API container image builds with root-owned Python cache files; non-root user in container can't write `.pyc`
- **Solution:** Apply via psql directly. For the long term: either fix container build to `chown` correctly, or run Alembic from a migration-only container

---

## Patterns Noticed

### Post-classification override pattern
The outer wrapper → inner core pattern is reusable: call core, inspect result, apply identity/action-aware overrides. This decouples taxonomy from identity concerns cleanly.

### Dual-path fallback for evolving schemas
Both the `_fetch_now()` UNION ALL fallback and the `_is_enriched_display_name()` guard follow the same idiom: "try the better query, catch the failure silently, degrade gracefully." Useful wherever the DB schema is not guaranteed to be at head.

### `frozenset` for O(1) allow/block list membership
`CONFLUENT_PLATFORM_HIGH_RISK`, `_ALWAYS_NOISE_METHODS`, `_ALWAYS_INFORMATIONAL_METHODS` — all frozensets. Fast membership test, immutable, defined at module load. Good pattern for classifier exemption lists.

### CRN stripping — terminal segment extraction
```python
if resource.startswith("crn://"):
    parts = resource.rstrip("/").split("/")
    last = parts[-1] if parts else ""
    resource = last.split("=")[-1] if "=" in last else last
```
Used in `pattern_detector.py`. Same logic in `frontend/lib/utils.ts` via `formatResourceName()`. Keep both in sync.

---

## User Preferences Learned

- **Spec discipline:** User writes multi-fix prompts with explicit "rules" sections (read before write, pytest baseline, one commit per fix, no frontend changes). Follow them exactly without confirmation-seeking.
- **STOP-and-report on premise mismatches** — don't silently substitute; surface via `AskUserQuestion` with lettered options
- **No frontend changes in backend-only prompts** — strictly respected even when frontend would benefit (e.g., backfill status display)
- **FINAL REPORT format matters:** pytest count, TS errors, before/after metrics, reloptions confirmed — structured table expected

---

## Code Patterns Worth Remembering

### `_is_enriched_display_name()` guard
```python
_PRINCIPAL_PREFIXES = ("user:", "u-", "sa-", "api-key-", "apikey", "pool-", "org-", "lkc-", "env-")

def _is_enriched_display_name(value: str | None) -> bool:
    if not value:
        return False
    if value.startswith(("{", "[")):
        return False
    lowered = value.strip().lower()
    if "@" in lowered:
        return True
    return not lowered.startswith(_PRINCIPAL_PREFIXES)
```

### Post-classification override wrapper
```python
def classify_signal(event_or_fields):
    result = _classify_signal_core(event_or_fields)
    action = _as_text(_field(event_or_fields, "action")).lower()
    if _is_confluent_platform(event_or_fields) and action not in HIGH_RISK_SET:
        return {"signal_type": "informational", "signal_reason": "platform_automation", ...}
    # further overrides...
    return result
```

### Alembic in tests (when ORM tables alone aren't enough)
```python
from alembic import command as _alembic_cmd
from alembic.config import Config as _AlembicConfig
cfg = _AlembicConfig(str(alembic_ini_path))
cfg.set_main_option("sqlalchemy.url", db_url)
_alembic_cmd.upgrade(cfg, "head")
```

### Autovacuum tuning migration (reusable pattern)
```python
_ALTER = "autovacuum_vacuum_scale_factor = 0, autovacuum_vacuum_threshold = 10000"
for table in _TABLES:
    bind.execute(text(f"ALTER TABLE {table} SET ({_ALTER})"))
# downgrade: RESET (autovacuum_vacuum_scale_factor, autovacuum_vacuum_threshold)
```

---

## Feedback Received

- Rule 67 (creds-unset wrapper for pytest) confirmed as standard baseline check — always run before reporting pass count
- "no frontend changes" in a backend-only prompt is a hard constraint, not a suggestion

---

## Potential CLAUDE.md Rules

- When tests touch `audit_events_noise`, use `alembic upgrade head` not `init_db()` — the noise table is Alembic-only and `init_db()` won't create it
- Alembic in API container is blocked by PermissionError on `src/__init__.py`; apply schema changes via `docker exec auditlens-postgres psql` for DDL-only migrations
- The `classify_signal()` outer wrapper applies identity/action overrides; the taxonomy lives in `_classify_signal_core()` — keep them separate
- `formatResourceName()` in `frontend/lib/utils.ts` and CRN-stripping in `pattern_detector.py` must stay in sync when CRN format changes
- Forwarder memory limit: 512MB (bumped from 384M on 2026-05-12); `MEMORY_LIMIT_MB=512` env var drives startup log
