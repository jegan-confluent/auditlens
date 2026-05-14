# Diary Entry: 2026-05-11

## Session Summary

Completed Phase 9A (9 ordered fixes) continuing from a context-compacted prior session. All 9 commits landed clean with 616 tests passing and 0 TypeScript errors at each step.

Prior-session work (completed before compaction):
- DecisionBanner clickable count numbers (fix "use client" boundary bug)
- Signal cards active/toggle state
- Flow card subject formatting
- Filter bar moved to top of Events page

Phase 9A fixes delivered this session:
1. NarrativeStrip category cards clickable → apply impact_type/result filters
2. Flow card titles resolve JSON subject blobs via formatSubject()
3. CreateAPIKey cloudResources list-format fix → extracts key ID not org UUID
4. Management-plane IAM dedup via content fingerprint (actor+action+resource+second)
5. actor_ip_baseline Alembic migration 0010 + SQLAlchemy model
6. IpBaselineTracker class with daemon background thread + forwarder wiring
7. ActorMappingFile extended to support dict format with trusted_ips/alert_on_new_ip
8. IP anomaly alerts — new IP → action_required notification (24h dedup, trust skip)
9. GET /actors/{id}/ip-baseline API + IP History section in ActorActivityPanel

## Key Decisions

**Fix 3: Handle cloudResources as list by picking richest-scope item**
- Problem: Confluent emits cloudResources as a JSON array for CreateAPIKey; _cloud_resources() only handled dict format, returned {}
- Decision: Pick item with most scope resources (most specific context)
- Rationale: Array items all have same resource (API key ID) but different scope depths; richest scope gives cluster/env context
- Alternative: Special-case CreateAPIKey by methodName — rejected as brittle

**Fix 4: Management-plane fingerprint on content, not message ID**
- Decision: `not method.startswith("kafka.")` as the management-plane predicate
- Rationale: Kafka-prefix events are data plane with unique IDs; management plane REST ops can double-emit same logical operation with different IDs
- Alternative: Explicit IAM method set — rejected because list would need constant maintenance

**Fix 8: IP alert suppression rules (no trusted CIDR, no whitelist, no private-without-config, 24h dedup)**
- Decision: Allow alerts only when: not whitelisted principal AND not in trusted CIDRs AND dedup window expired AND (alert_on_new_ip=true OR trusted_ips configured OR not private IP)
- Rationale: Private IPs without any trust config = internal network, low risk. Only alert when operator has opted in (via trusted_ips or alert_on_new_ip) or IP is public/cloud.

**Fix 9: IP baseline fetch as best-effort (`.catch(() => null)`)**
- Decision: getActorIpBaseline() failure doesn't block the actor panel from loading
- Rationale: actor_ip_baseline table may be empty or migration not yet run on older installs; the main panel content (summary + events) is more important

## Challenges & Solutions

**`_cloud_resources()` returning {} for list input**
- Root cause: Function checked `isinstance(value, dict)` then fell through to `_load_json()` which returns {} for non-string inputs (lists)
- Solution: Added list handling branch that picks the item with the most scope resources
- Discovered by querying live DB: `SELECT raw_payload_json FROM audit_events WHERE action ILIKE '%apikey%'`

**Live DB diagnostics were essential**
- Reading the actual CreateAPIKey payload from the DB clarified what `cloudResources` looks like in production vs what tests assumed
- Pattern: always curl/psql live data before guessing at payload structure for normalization bugs

**`_is_private_ip` import in forwarder**
- The function was defined in ip_baseline_tracker.py; imported it alongside IpBaselineTracker using `from src.product.ip_baseline_tracker import IpBaselineTracker, _is_private_ip`
- Using `__import__("ipaddress")` inline in the forwarder alert block for the CIDR check — messy but avoids a new module-level import for a single use

## Patterns Noticed

**Daemon thread pattern is reusable**
- PatternDetector → IpBaselineTracker: same structure (in-memory state, queue, background thread, upsert loop)
- Both use `queue.Queue(maxsize=N)` with `put_nowait` (non-blocking, drop on full)
- Both seed from DB on init; record() updates in-memory first for instant response

**Test-first on normalization fixes**
- For Fix 3: wrote regression test before verifying fix, confirmed test failed first, then implemented fix, test passed
- For Fix 4: wrote two tests (dedup test + non-dedup test) to pin both behaviors

**Migration + model always together**
- Fix 5 added migration file AND updated models.py in same commit
- This keeps the ORM and schema in sync at each commit boundary

**Best-effort degradation for optional features**
- IP baseline fetch in actor panel: `.catch(() => null)` so panel loads even if endpoint 404s
- IpBaselineTracker init in forwarder: try/except logs warning and disables feature
- ActorMappingFile on missing file: returns empty dict, never raises

## User Preferences Learned

- One logical fix = one commit, always (no batching)
- pytest must pass after every commit, not just at the end
- TypeScript 0 errors after every frontend change
- Read every file mentioned FULLY before editing — no assumptions
- Run live diagnostics (curl, psql, docker exec) before assuming premise is correct
- Implement exactly what spec says, no additional features beyond scope

## Code Patterns Worth Remembering

**cloudResources list-format handling (resource_intelligence.py)**
```python
if isinstance(value, list):
    best: dict[str, Any] = {}
    best_scope_len = -1
    for item in value:
        if isinstance(item, dict):
            scope_len = len((item.get("scope") or {}).get("resources") or [])
            if scope_len > best_scope_len:
                best_scope_len = scope_len
                best = item
    return best
```

**Management-plane predicate for fingerprint**
```python
def _is_management_plane(payload):
    method = _as_text(payload.get("methodName") or ...).lower()
    return not method.startswith("kafka.")
```

**Daemon thread upsert loop (reusable)**
```python
def _writer_loop(self):
    while True:
        try:
            item = self._queue.get(timeout=5.0)
        except queue.Empty:
            continue
        try:
            self._upsert(item)
        except Exception as exc:
            logger.warning("tracker: upsert failed: %s", exc)
```

**Next.js "use client" boundary rule**
- Never add `"use client"` to a child component that's imported by a `"use client"` parent — function props (onClick handlers) are silently dropped in Next.js production builds across client bundle boundaries
- Components of `"use client"` parents are automatically client-side without a directive

## Feedback Received

No direct corrections this session — all fixes were accepted without pushback. User gave a structured spec (Phase 9A prompt with 9 ordered fixes) and asked for strict adherence.

## Potential CLAUDE.md Rules

- When cloudResources is a list (Confluent pattern), pick item with richest scope, not first item
- Management-plane vs data-plane distinction: `method.startswith("kafka.")` = data plane; everything else = management plane
- Daemon thread pattern: in-memory set/dict → queue.put_nowait → background upsert loop — reuse for any new per-event tracker
- For optional panel data fetches: always `.catch(() => null)` so primary content loads even when supplementary endpoint fails
- Before diagnosing normalization bugs, query live DB for actual payload structure — never assume from spec alone
- When extending YAML config format, always support both old string format and new dict format in the same _load() pass for backward compatibility
