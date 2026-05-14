# Diary Entry: 2026-05-12

## Session Summary
- Completed Phase 7: automatic pattern suppression wired into decision mode (FIX 5) + RecurringPatterns UI section (FIX 6)
- Applied three focused fixes: IP baseline bool type (FIX 1), User:/SA: prefix stripping in display names (FIX 2), forwarder stability (FIX 3)
- Ran adversarial bug hunt (Hunter → Skeptic → Referee) across the full AuditLens codebase — produced 23 verified bugs

## Key Decisions

### Pattern suppression: module-level TTL cache, not DB call per request
- 60s TTL cache (`_suppression_cache`, `_suppression_lock`) at `event_service.py` module level
- In decision mode, matched events are *excluded*; in audit_trail mode they are marked `_suppressed=True` for visibility
- Alternative considered: query on every request — rejected for latency; Redis — rejected as new dependency

### Alembic migration for INTEGER→BOOLEAN: query information_schema before ALTER
- Migration 0013 checks `information_schema.columns` for current data_type, skips if already boolean or table missing
- Avoids error on clean installs where 0001_baseline ran `create_all()` before the column existed
- PostgreSQL dialect guard ensures SQLite test runs are no-ops

### RecurringPatterns: returns null when total === 0
- Component renders nothing when backend reports zero active patterns
- Collapsible by default (collapsed state), shows count badge in header

### Forwarder restart: `unless-stopped` replaces `on-failure:3`
- `on-failure:3` silently gave up after 3 crashes → 7-hour outage
- `unless-stopped` ensures recovery regardless of crash count; crash traceback now logged at CRITICAL before re-raise

## Challenges & Solutions

### Suppression cache stampede on DB errors
- **Problem**: Exception branch returned `set()` without updating `_suppression_cache`, so every subsequent call re-queried a broken DB
- **Solution**: Cache the empty set even on error: `_suppression_cache = (now, set())` in except branch
- This was confirmed as BUG-4 (Medium) in the bug hunt — already present in codebase

### Migration conflict: 0001_baseline create_all vs later migrations
- `0001_baseline` calls `Base.metadata.create_all()` which creates *all* ORM tables including new ones added later
- Downstream migrations that attempt `CREATE TABLE` for those tables would then fail with "table already exists"
- Pattern: always wrap CREATE TABLE in `if table_name not in inspector.get_table_names()` checks; same for indexes

### git add from wrong working directory
- Attempted `git add frontend/components/...` from inside `frontend/` subdirectory
- Fix: always use absolute paths or ensure CWD is repo root before staging

## Patterns Noticed

### Adversarial bug hunt is high-value
- Hunter maximizes findings (31 raw bugs, 148 pts)
- Skeptic calculates EV (eliminated 10 false positives)
- Referee reads code independently (confirmed 23, upgraded 1, downgraded 1 vs Skeptic)
- Total session cost: ~3 subagent spawns; output: actionable prioritized list with file:line references

### Auth posture gaps surface in parallel with feature work
- BUG-1 (auth disabled → ADMIN role) and BUG-2 (triage endpoint no auth) are both Critical
- These were invisible to normal development flow — only surfaced via dedicated security lens
- Pattern: run bug-hunt at end of each major phase before declaring "done"

### Display name stripping needs to happen at the last moment
- Multiple places accumulated User:/ServiceAccount: prefix strip logic independently
- Correct pattern: strip only for *display*, never for filter/query keys; canonical form is "User:xxx"

## User Preferences Learned
- Expects one commit per logical fix, pytest baseline before and after each
- Wants adversarial review (Hunter/Skeptic/Referee) not just a single-pass audit
- Prefers `unless-stopped` over `on-failure:N` for critical infrastructure containers

## Code Patterns Worth Remembering

### Module-level TTL cache with lock (suppression pattern)
```python
_lock = threading.Lock()
_cache: tuple[float, set[tuple]] | None = None
_TTL = 60.0

def _get_cached(db) -> set[tuple]:
    now = time.monotonic()
    with _lock:
        if _cache and now - _cache[0] < _TTL:
            return _cache[1]
    try:
        result = _fetch_from_db(db)
    except Exception:
        result = set()
    with _lock:
        _cache = (time.monotonic(), result)  # cache even on error
    return result
```

### Safe Alembic migration for column type change
```python
def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa_inspect(bind)
    if "table_name" not in inspector.get_table_names():
        return
    row = bind.execute(text("SELECT data_type FROM information_schema.columns WHERE ...")).fetchone()
    if row is None or row[0].lower() == "target_type":
        return
    op.execute("ALTER TABLE ... ALTER COLUMN x TYPE boolean USING x::boolean")
```

## Feedback Received
- No explicit corrections this session — user approved the adversarial bug hunt approach without pushback

## Confirmed Bugs Pending Fix (23 total)
Priority order:
1. **BUG-1** (Critical): `auth_disabled` path grants `Role.ADMIN` — should return `VIEWER`/`RESPONDER`
2. **BUG-2** (Critical): `POST /events/{id}/triage` has no auth decorator
3. **BUG-4** (Medium): Suppression cache doesn't cache empty set on DB error — `event_service.py`
4. **BUG-11** (Medium): `action` query param not forwarded to `list_events_result`
5. **BUG-14** (Medium): `result_limit_reached` AND condition logic incorrect
6. **BUG-15** (Medium): `noise_table_exists()` permanently caches `False`
7. **BUG-18** (Medium): `sa.text("now()")` in migration 0010 — SQLite incompatible
8. **BUG-19** (Medium): `EventListResponse` missing `next_cursor` field in TypeScript types
9. **BUG-8** (Medium): `occurrence_count` incremented by window count not by 1
10. **BUG-3** (Medium): Raw payload hidden when auth disabled

## Potential CLAUDE.md Rules
- Run `/bug-hunt` at the end of each major phase before declaring done
- For module-level TTL caches: always update the cache tuple in the exception branch — never return early with an uncached empty result
- `unless-stopped` is the correct Docker restart policy for any container that must recover from crashes; `on-failure:N` silently gives up
- Alembic migrations for column type changes must query `information_schema.columns` and skip if already at target type
- Auth decorators must be verified on *every* new route — check with grep before committing new endpoints
