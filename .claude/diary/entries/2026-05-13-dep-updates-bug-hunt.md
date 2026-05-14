# Diary Entry: 2026-05-13 — dep-updates-bug-hunt

## Session Summary

Two major pieces of work:

1. **Dependency update sweep** — Fixed Dockerfile.alpine (broken @sha256:xxx placeholders, alpine3.19→3.21), bumped 4 monitoring image tags in docker-compose.yml, bumped confluent-kafka 2.6→2.13.2, fastapi 0.111→0.115.6, pydantic 2.9→2.11.4, httpx 0.26→0.28.1, orjson, prometheus-client. All 3 commits landed cleanly. Pytest 669 passed before and after; TypeScript 0 errors.

2. **Adversarial bug hunt (READ-ONLY)** — 4 subsystems analyzed using Hunter/Skeptic/Referee 3-agent model. 13 confirmed bugs found, 5 rejected. Highest priority: DLQ topic inconsistency (3 different defaults across config files), `clear_actor_enrichment_cache()` leaks IAM background threads on every backfill, HTTP 429 silently serves partial identity data as complete, `_apply_derived_prefilters` over-restricts destructive impact filter, `func.lower()` on indexed columns forces full table scans.

## Key Decisions

- **cachetools bumped beyond spec (5.3.3→5.5.2)**: confluent-kafka 2.13.2 avro extra requires cachetools>=5.5.0. Discovered via `pip install --dry-run`; disclosed in commit message and report. Correct call — silent constraint violation was the alternative.

- **No sha256 digests for new image tags**: Per spec, only Prometheus and Grafana were getting new tags; old digests were removed since they tied to old versions. Postgres and postgres-exporter digests kept unchanged.

- **Hunter/Skeptic/Referee format**: Highly effective for adversarial analysis. Forces each finding through challenge and proof before confirmation. Produced a cleaner final list with explicit "proof" lines that make the bugs actionable.

## Challenges & Solutions

- **Problem:** `pip install -r requirements.txt --dry-run` reported cachetools conflict for confluent-kafka 2.13.2 avro extra.
  - **Solution:** Checked available versions with `pip index versions cachetools`, bumped to 5.5.2 (minimum satisfying). Applied to both requirements.txt and src/mcp/requirements.txt.

- **Problem:** System pip returned "externally-managed-environment" error.
  - **Solution:** Used `.venv/bin/pip install` consistently.

- **Problem:** Bug hunt: distinguishing genuine races from CPython-GIL-safe apparent races.
  - **Solution:** Skeptic agent explicitly challenged CPython-specific behavior. `dlq_stats` race was rejected because confluent-kafka callbacks run with GIL held. `delivery_errors["last_error"]` outside lock was confirmed MEDIUM because design intent is violated even if crash is unlikely.

## Patterns Noticed

- **3-file column rule is now 4-file**: Adding a DB column to AuditLens requires updating (1) models.py ORM, (2) db_writer.py Table definition, (3) column_spec.py AUDIT_EVENT_COLUMNS, (4) alembic migration with existence guard.

- **Pre-filter optimization anti-pattern**: `_apply_derived_prefilters` adds SQL pre-filters as an optimization for the derived-filter Python scan loop. These must be CONSERVATIVE subsets of the Python filter — if a SQL pre-filter is more restrictive than the Python post-filter, events silently disappear from results. The destructive→Delete mapping is an example where this went wrong.

- **lru_cache + daemon thread interaction**: `@lru_cache` on factory functions that create objects with background threads is dangerous. `cache_clear()` drops the reference to the old object but the daemon thread holds `self` alive. Every `cache_clear()` call leaks a thread. Pattern: add `stop()` method to objects with background threads; call before `cache_clear()`.

- **Single-trigger pattern detection limitation**: Enqueuing DB writes only when `count == THRESHOLD + 1` (exactly at threshold crossing) means ongoing high-volume patterns only update their DB record once per window. For accurate event counting, DB writes should happen on every event above threshold, or a separate periodic flush should write the in-memory count.

- **DLQ topic naming is load-bearing config**: Multiple compose files in different directories each set `DLQ_TOPIC` differently. The "official" deploy compose overrides the code default. This is a real operational hazard — events go to unmonitored topics.

## User Preferences Learned

- User enforces strict read-before-edit discipline: "Read these files completely before touching anything" is a hard constraint.
- User wants ALL changes in a session disclosed in the final report — including out-of-spec bumps like cachetools.
- User's bug hunt format requires: file:line citation, concrete triggering input, proof, and explicit CONFIRMED/REJECTED/NEEDS-TEST verdict per finding.
- User prefers concise commit messages that explain WHY something was broken, not just WHAT changed.
- READ-ONLY analysis tasks must have zero code changes — discipline must be maintained even when fixes are obvious.

## Code Patterns Worth Remembering

**Safe factory with background threads:**
```python
# Instead of @lru_cache on factories that start threads:
_enricher: IdentityEnricher | None = None

def get_enricher() -> IdentityEnricher:
    global _enricher
    if _enricher is None:
        _enricher = IdentityEnricher(...)
        _enricher.start_background_refresh()
    return _enricher

def reset_enricher() -> None:
    global _enricher
    if _enricher is not None:
        _enricher.stop()  # signals thread to exit
        _enricher = None
```

**Conservative pre-filter check:**
When adding SQL pre-filters as optimization for Python post-filters, always verify: `SQL_prefilter ⊆ Python_postfilter`. If any event could satisfy the Python filter but fail the SQL filter, the optimization is incorrect.

**cachetools.TTLCache for enrichment caches:**
```python
from cachetools import TTLCache
_CACHE: TTLCache = TTLCache(maxsize=50000, ttl=3600)
```

**PatternDetector occurrence tracking fix:**
To track actual occurrence count (not just threshold crossings), enqueue on every event above threshold (with periodic batching to avoid queue flooding), not only at exact crossing.

## Feedback Received

No direct corrections during this session. The cachetools out-of-spec bump was accepted after proactive disclosure. The READ-ONLY constraint was respected throughout Phase 2.

## Potential CLAUDE.md Rules

- When bumping Python packages, always run `pip install -r requirements.txt --dry-run 2>&1 | grep -i "error\|conflict"` before committing; disclose any transitive bumps required beyond spec.
- In adversarial bug hunts: use Hunter/Skeptic/Referee 3-agent model; each finding must have file:line + concrete triggering input + proof; explicitly state CONFIRMED/REJECTED.
- READ-ONLY analysis tasks (bug hunt, code review) must have zero file edits; if tempted to fix, note the fix in the output instead.
- `@lru_cache` on factory functions that spawn background threads is dangerous — `cache_clear()` orphans threads; always add `stop()` method and call it before clearing.
- Pre-filter optimizations (SQL→Python scan) must satisfy: SQL_prefilter ⊆ Python_postfilter; if violated, events silently disappear from user-facing results.
- DLQ topic names in deploy/test/docs config files must match the code default `audit.dlq.v1`; divergence causes silent event routing to unmonitored topics.
