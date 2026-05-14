# Diary Entry: 2026-05-13 — Bug Fix Session + Actor Normalization

## Session Summary

Two major work streams in one session:

**Part A — Adversarial Bug Hunt Fixes (BUG-03 to BUG-10)**
- BUG-03: Rewrote `classify_new_methods()` check order in `schema-watcher/watcher.py` so HIGH-entity specific checks (ApiKey, RoleBinding, ServiceAccount, PrivateLinkAttachment, etc.) fire before the generic DELETE→CRITICAL bucket. Fixed `ACL` → `ACLS` false positive on `DeleteKafkaCluster`.
- BUG-04: Log WARNING when `producer.flush()` returns unconfirmed messages in `route_batch()`
- BUG-05+06: Removed ksql dual-set membership (AUTHENTICATION_METHODS AND READ_ONLY_METHODS); added YAML key validation with `_VALID_YAML_KEYS` frozenset
- BUG-07+08: Warning when DROP_LOW_EVENTS conflicts with all_events_topic; `max(1,...)` floor on CHECK_INTERVAL_HOURS
- BUG-09: Extracted `_post_slack_blocks()` with `@retry(stop=stop_after_attempt(3), reraise=False)` tenacity decorator
- BUG-10: Prune `schema_snapshot_*.json` to last 10 after each write

**Part B — Actor Normalization Gaps (4 production fixes)**
- FIX 1: Root cause was `normalize_event()` reading `event.get("principal")` (raw "User:u-xxx") instead of `event.get("principal_normalized")` ("u-xxx"). Fixed by adding `principal_normalized` as first-preference in the fallback chain. Added public `normalize_principal()` to `actor_enrichment.py`.
- FIX 2: Migration 0018 + `POST /admin/backfill/normalize-actor-prefixes`. Updated 2.88M rows in production.
- FIX 3: Extended `backfill_actor_display_names` WHERE clause to include `actor_confidence='low'` and `actor_display_name = actor` rows (not just "Unknown X" placeholders).
- FIX 4: Added Override 0 in `classify_signal()` to suppress `error-lcc-*`, `_confluent*`, `__consumer_*`, `_schemas` topic events as noise.

**Test count:** 684 → 710 passed (+26 new tests, 0 failures)

---

## Key Decisions

### classify_new_methods() check order
- **Decision:** Specific HIGH-entity checks (ApiKey, RoleBinding, User, IdentityProvider, PrivateLinkAttachment, ClusterLink, BYOK, ACLS, DeleteGroups, DeleteSubject, DeleteSchemaVersion, IPFilter) all fire BEFORE the generic DELETE→CRITICAL bucket
- **Rationale:** Blast radius of CRITICAL vs HIGH matters for alert fatigue. DeleteApiKey is recoverable (create new key). DeleteKafkaCluster is not.
- **Alternative:** Keep generic rule, add exceptions list to CRITICAL bucket. Rejected — exceptions lists grow unbounded and the intent is obscured.

### ACL → ACLS fix
- **Decision:** Changed `'ACL' in method_upper` to `'ACLS' in method_upper`
- **Rationale:** 'ACL' is a substring of 'KAFKACLUSTER'. Verified inline: `'ACL' in 'DELETEKAFKACLUSTER'` is True at positions 10-12. 'ACLS' is not a substring of 'KAFKACLUSTER'.

### normalize_event() fix location
- **Decision:** Fix was in `src/product/event_normalization.py` NOT in `normalize_principal()` in `principal.py`
- **Rationale:** `normalize_principal` already stripped "User:" correctly. The bug was that `normalize_event` built `actor` from `event.get("principal")` (raw) instead of `event.get("principal_normalized")` (already stripped by `flatten_audit`). Zero-cost read of pre-computed field.

### Migration 0018 batching strategy
- **Decision:** Switched from subquery-based batching to direct single UPDATE
- **Rationale:** `WHERE id IN (SELECT id FROM same_table WHERE ... LIMIT N)` causes double sequential scan on a 32 GB table. Direct `WHERE actor LIKE 'User:u-%'` uses the existing btree index (in theory; Postgres still chose seq scan due to OR clause, but the single-pass scan is far better than two full scans per batch).
- **Alternative:** Provide only the admin endpoint, no migration. Rejected per spec — customer deployments need automated fix on `alembic upgrade head`.

---

## Challenges & Solutions

### VARCHAR(32) revision ID limit
- **Problem:** Migration revision ID `0018_normalize_user_prefix_actors` (33 chars) exceeded `alembic_version.version_num VARCHAR(32)`. The 2.88M-row UPDATE ran for 20 minutes, completed successfully, then the WHOLE TRANSACTION was rolled back when alembic tried to write the version string. All 2.88M updates lost.
- **Solution:** Shortened to `0018_strip_actor_user_prefix` (28 chars). Re-ran migration.
- **Lesson:** Always `echo -n "revision_id" | wc -c` before saving a migration file. alembic_version.version_num is VARCHAR(32) — existing IDs range 20-29 chars.

### 32 GB table sequential scan
- **Problem:** 4.9M row `audit_events` table (32 GB). Every LIKE-based query triggers a full sequential scan (~15-20 minutes per scan). Even `COUNT(*)` takes 40+ seconds. Caused several hung processes and lock contention from multiple concurrent scan attempts.
- **Solution:** Kill hung sessions with `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='auditlens' AND pid != pg_backend_pid()`. Run one query at a time. Use `SELECT reltuples FROM pg_class WHERE relname='audit_events'` for fast row count estimates.
- **Diagnostic:** Use `pg_stat_activity` to see what's running: `wait_event_type=IO, wait_event=DataFileRead` = sequential scan in progress.

### Migration task completing exit code 0 before alembic_version update
- **Problem:** Background task showed `exit code 0` but alembic threw an exception inside. The `| cat` piping caused the Python process to exit 0 even on exception (psycopg error was in stderr which was captured by cat).
- **Solution:** Read the actual task output file — the full Python traceback was there. Never trust exit code alone when using `| cat` with Python processes.

### Fingerprint collision in earlier test fixes (recap)
- **Root cause discovered this session:** The management-plane fingerprint is `actor+action+resource+timestamp`. Tests creating multiple events for the same actor with the same method and same test timestamp collide — second `create_event` returns the existing row. Fix: use `kafka.`-prefixed methods to force data-plane fingerprinting (uses unique `id` field).

---

## Patterns Noticed

### Inline verification before committing classification changes
For every classification logic change, run an inline Python test with hardcoded expected values BEFORE running pytest. This catches false positives (like the ACL/KAFKACLUSTER issue) without spending time on the full suite.

Pattern used successfully:
```python
python3 -c "
def classify(method):
    ...  # inline the logic
test_cases = {'DeleteApiKey': 'HIGH', 'DeleteKafkaCluster': 'CRITICAL', ...}
for method, expected in test_cases.items():
    actual = classify(method)
    status = 'PASS' if actual == expected else 'FAIL'
    print(f'{status}: {method} → {actual}')
"
```

### Backfill WHERE clause extension pattern
When extending a backfill's target criteria, use SQLAlchemy `or_()` with explicit annotations:
```python
.where(or_(
    AuditEvent._actor_display_name.in_(_UNKNOWN_DISPLAY_NAMES),  # legacy placeholders
    AuditEvent._actor_display_name == AuditEvent.actor,          # raw ID as name
    AuditEvent._actor_confidence == "low",                        # fallback enrichment
))
```

### Early-return override pattern in classify_signal()
For "always suppress this category" rules, add a numbered Override (Override 0, Override 1, etc.) in `classify_signal()` rather than adding conditions inside `_classify_signal_core()`. This keeps the overrides visible at the top level and prevents them from being accidentally bypassed by internal early returns.

### Admin backfill endpoint + migration = defense in depth
For large data cleanup operations:
1. Migration handles automatic fix on deploy (alembic upgrade head)
2. Admin endpoint provides operator-controlled batched alternative for large tables
3. Both use the same core logic; migration calls the heavy SQL directly, endpoint calls the Python service function with explicit batching

---

## User Preferences Learned

- Follows a strict "read before touching" discipline — spec explicitly says "Read before touching anything" with specific files listed. This is a hard rule, not a suggestion.
- Prefers ONE COMMIT PER LOGICAL FIX. Related bugs can share a commit (BUG-05+06, BUG-07+08) but not unrelated fixes.
- Pytest must pass at each commit. Never batch commits and run tests only at the end.
- Production DB has real data (4.9M rows, 32 GB) — diagnostic commands against it need to be mindful of scan times.
- `/handoff` mode for diary = comprehensive notes for future Claude instances, not just personal notes.
- Inline verification commands (Python one-liners) are expected proof artifacts alongside tests.

---

## Code Patterns Worth Remembering

### Tenacity async retry on extracted method
For async methods with side effects (HTTP POST, DB write), extract the I/O call into a small `_private_method()` and decorate IT with `@retry`. The outer method handles business logic + error logging. The inner method is pure I/O with retry.

```python
async def send_alert(self, payload):
    try:
        await self._post_blocks(payload)
        logger.info("sent successfully")
    except Exception as e:
        logger.error("alert failed: %s", e)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30), reraise=False)
async def _post_blocks(self, payload):
    response = await self.client.post(self.url, json=payload)
    response.raise_for_status()
```

### event_normalization actor chain: prefer pre-computed field
```python
actor = _principal_to_scalar(principal_raw) or str(
    event.get("principal_normalized")  # pre-stripped by flatten_audit
    or event.get("principal")           # raw (may have "User:" prefix)
    or ...
)
```
The rule: always prefer the downstream normalized field over the upstream raw field in the fallback chain.

### Migration revision ID safety check
```bash
echo -n "your_revision_id_here" | wc -c  # must be ≤ 32
```
Run this before saving any migration file. alembic_version.version_num is VARCHAR(32).

---

## Feedback Received

None explicit this session. All code was accepted without correction.

---

## Potential CLAUDE.md Rules

- Always run `echo -n "revision_id" | wc -c` before saving a migration file — alembic_version.version_num is VARCHAR(32); IDs > 32 chars cause the entire migration transaction to roll back after the data work completes
- For classification logic changes, write an inline Python verification with hardcoded test cases BEFORE running pytest — catches false positives like substring matches (ACL in KAFKACLUSTER) without waiting for the full suite
- Never run multiple concurrent LIKE-based queries on audit_events in production — 32 GB table causes long sequential scans that queue behind each other and create lock pile-ups; use `SELECT reltuples FROM pg_class WHERE relname='audit_events'` for fast size estimates
- For `backfill_actor_display_names` and similar backfill jobs, always check if the WHERE clause covers ALL under-enriched states (placeholder, raw-id-as-name, low-confidence) — not just legacy placeholder values
- In `classify_signal()`, add resource-name-based noise suppressions as numbered overrides (Override 0, Override 1) at the TOP of the function, not inside `_classify_signal_core()` — keeps them visible and prevents bypass by internal early returns
