# Reflection: 2026-05-11

## Patterns Across Diary Entries

### Strong discipline on one-commit-per-fix
Every Phase 9A fix went through the same loop: read files → implement → TypeScript check → pytest → commit. No batching, no "I'll test later." This was the user's explicit protocol and it worked — caught nothing broken because each step was individually validated.

### Live DB diagnostics unlocked Fix 3
The CreateAPIKey bug was invisible from the codebase alone — the function read like it should work. Querying `raw_payload_json` from the live DB immediately showed that `cloudResources` was a list, not a dict. This saved at least 2-3 cycles of wrong-hypothesis edits.

### Daemon thread is the right primitive for forwarder extensions
Both PatternDetector and IpBaselineTracker use the same structure. Future per-event tracking (rate limiting, geo-enrichment, etc.) should follow this template rather than inventing new patterns.

### Next.js "use client" lesson is worth encoding permanently
This is a subtle production-only bug that doesn't appear in dev mode. The fix (remove the directive from child components of client parents) is counterintuitive. Worth keeping in memory for any future Next.js work.

## Potential CLAUDE.md Additions

Based on this session, these rules would prevent repeated issues:

```
78. **Live-data-first for normalization bugs:** Before diagnosing any payload normalization bug, run `docker exec auditlens-postgres psql -U auditlens -d auditlens -c "SELECT raw_payload_json FROM audit_events WHERE action ILIKE '%<method>%' LIMIT 3"` to see the actual payload shape. Spec and test fixtures drift from production Confluent emissions.

79. **Next.js "use client" child rule:** Never add `"use client"` to a component that is only imported by `"use client"` parents. Function props (onClick) are silently dropped in production builds across the client boundary. Child components of client parents are automatically client-side.

80. **cloudResources list handling:** Confluent audit events can emit `cloudResources` as a list (e.g., CreateAPIKey). `_cloud_resources()` in resource_intelligence.py handles this by picking the item with the richest scope. When adding new resource types, verify cloudResources format from live data before assuming dict structure.

81. **Daemon thread tracker pattern:** For new per-event forwarder tracking, copy IpBaselineTracker structure: in-memory set + `queue.put_nowait` (non-blocking) + background `_writer_loop` with dialect-guarded upsert. Never block `record()`, never let `_writer_loop` crash.
```

## State at End of Session

- Branch: master
- Tests: 616 passed, 5 skipped
- TypeScript: 0 errors
- Phase 9A: 100% complete (9/9 fixes committed)
- Ready for: Phase 9B, frontend rebuild, or whatever comes next

## Next Rebuild Commands

```bash
# After API changes (actors route, migration):
docker compose build api && docker compose up -d api

# After forwarder changes (IpBaselineTracker wiring):
docker compose build forwarder && docker compose up -d forwarder

# After frontend changes (ActorActivityPanel, globals.css):
docker compose build frontend && docker compose up -d frontend

# Migration for actor_ip_baseline:
# Happens automatically on API startup (Alembic auto-runs on init)
```
