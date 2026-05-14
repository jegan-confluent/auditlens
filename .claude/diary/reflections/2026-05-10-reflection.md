# Diary Reflection: 2026-05-10

## Entries Analyzed

This cycle covers two new diary entries since the 2026-05-09 reflection:

| Date | Slug | Focus | Commits |
| --- | --- | --- | --- |
| 2026-05-10 | phase1-phase2-handoff | Noise short-circuit + two-table query path + SQLite guard + pipeline lag visibility | 10 |
| 2026-05-10 | phases-3-4-5 | One-command setup; configurable notifications (slack/teams/webhook); actor display name fix + backfill | 11 |

That brings the May 2026 active stretch to **9 entries** across **5 sessions**. Combined with the previous reflection's evidence base, the May 9 proposals now have **even stronger** evidence; they have not yet been merged into `.claude/CLAUDE.md` (last touched on commit `4837d95` in March).

## Status of the May 9 reflection

The 14 proposals from `2026-05-09-reflection.md` are **still all pending**. No CLAUDE.md update has been made. Each of those rules has now picked up additional supporting entries in the 2026-05-10 cycle:

| May 9 rule | Old support | New support adds | Total |
| --- | --- | --- | --- |
| #1 — Read every listed file fully | 3 | Phase 1+2 ("Rule 1 is a hard rule"), Phase 3-4-5 (stopped on bootstrap.py mismatch) | 5 |
| #2 — Live diagnostics before editing | 3 | Phase 1+2 (status before bulk-queue bump), Phase 3-4-5 (live `make status`, live admin endpoint test) | 5 |
| #3 — `.env` / `.secrets` are gitignored | 4 | Phase 1+2 (env edits noted as runtime-only), Phase 3-4-5 (`.env` skipped from staging) | 6 |
| #4 — `docker compose restart` does not reload env | 2 | (no new occurrence) | 2 |
| #5 — Frontend / api containers need rebuild | 3 | Phase 3-4-5 explicitly hit this on the api container after the admin-route addition | 4 |
| #6 — pytest baseline + creds wrapper | 3 | Phase 1+2, Phase 3-4-5 — both use the same wrapper verbatim | 5 |
| #7 — Phased commits over big-bang | 3 | Phase 1+2 (10 commits), Phase 3-4-5 (11 commits, 4+4+3 across three phases) | 5 |
| #8 — `from_env()` over direct dataclass constructor | 2 | (no new occurrence) | 2 |
| #9 — Update tests that pin buggy behavior | 2 | Phase 5 (test_event_intelligence.py:237 updated alongside `Unknown principal` removal) | 3 |
| #10 — Cross-thread Kafka offset commit pattern | 2 | (no new occurrence) | 2 |
| #11 — Honest "missed target" reports | 2 | Phase 3-4-5 (statement_timeout firing on 2.7M rows reported, not glossed) | 3 |

**Recommendation**: batch all 14 May 9 proposals + the new 2026-05-10 proposals (below) into a single CLAUDE.md update before the next session.

## New patterns from the 2026-05-10 cycle

### High-confidence (3+ occurrences within May 2026)

**A. STOP-and-report on premise mismatches via `AskUserQuestion`.** The pattern is now established across multiple sessions:
- May 9: `2026-05-09-consumer-thread-pool-and-perf-fixes` — twice in one session for sequencing decisions
- May 10 Phase 1+2: ambiguity reports in lettered options ("A, A, A, B — proceed")
- May 10 Phase 3-4-5: stopped on missing `bootstrap.py`, used AskUserQuestion with two header'd questions

The user pays this back with crisp single-letter answers in seconds. Worth promoting to a CLAUDE.md rule:
> When a multi-fix prompt asserts a fact about disk state that turns out to be wrong (file path, function name, flag name), STOP and use AskUserQuestion. Present 2–3 options with a recommended one. The user almost always picks the recommended option in seconds. Cheaper than guessing wrong.

**B. Hot-reload pattern: mtime + `threading.Lock` + atomic dict swap.** This shape was used twice in 2026-05-10 alone:
- Phase 4: `notifications.yml` reload via `_maybe_reload`
- Phase 5: `actor_mappings.yml` reload via `_reload_if_changed`

Pattern shape:
```python
def _maybe_reload(self) -> None:
    try:
        mtime = os.path.getmtime(self._path)
    except OSError:
        return
    if self._mtime is None or mtime != self._mtime:
        self._load()  # lock-guarded swap inside
```

This is now a project convention. Recommended CLAUDE.md rule:
> For optional config files (notifications.yml, actor_mappings.yml, future): gitignore the live file, commit a `.example.yml`, and hot-reload via `os.path.getmtime` change detection inside a `threading.Lock`-guarded swap. The handler must never raise — bad YAML logs WARNING and returns empty config.

### Medium-confidence (2 occurrences)

**C. Single-flight admin async-job + GET status pattern.** Used in:
- Phase 5: `backfill_actor_display_names` POST endpoint + GET status endpoint
- Pre-existing pattern: `cleanup_retention` (POST), `denial_aggregator` flush (background)

The new shape — module-level `threading.Lock` + state dict + daemon thread that builds its own `sessionmaker(bind=engine, ...)` session — is a clean addition. Worth recording:
> Admin async-job pattern: single `threading.Lock`-guarded module-level state dict; POST returns `{"status": "started"}` (or the in-flight state if a job is running); GET returns `{status, started_at, completed_at, dry_run, progress, error}`. Worker thread builds its own SQLAlchemy session via `sessionmaker(bind=engine_captured_in_request, ...)` — never reuse the request's session across thread boundaries.

**D. Daemon-thread retry budget with `time.monotonic()` deadline.** Used in:
- Phase 4: `AuditLensNotifier._send_with_retry` (30s budget across 4 attempts)
- Phase 1: per-batch persistence barrier `_await_persisted` (deadline-bounded)

Pattern:
```python
deadline = time.monotonic() + BUDGET_SECONDS
for backoff in [0, 2, 4, 8]:
    if backoff: time.sleep(backoff)
    if time.monotonic() >= deadline:
        log("exceeded budget — abandoning"); return
    if try_once(): return
```

The deadline check makes the worst-case duration bounded regardless of retry count or HTTP timeout interactions. Worth recording.

**E. Dialect-guarded `SET LOCAL statement_timeout`.** Already used in `event_service.py`, `noise_service.py`, `filter_options_service.py`. New use in Phase 5 backfill. Pattern:
```python
if db.get_bind().dialect.name == "postgresql":
    db.execute(text(f"SET LOCAL statement_timeout = {ms}"))
```
Without the dialect guard, SQLite-based tests blow up. This is now in 4 backend services; should be a CLAUDE.md rule.

**F. Prefer "graceful absence" over forcing optional file mounts in compose.** Phase 4 deliberately did NOT add a bind mount for `notifications.yml` because compose v2's behavior on missing source files (creates an empty directory) would be worse than the notifier's "log INFO and continue" path. Recorded:
> When a customer-edited optional file is part of the design, prefer in-code "log + continue" handling over a docker-compose bind mount. Bind-mounting an absent file in compose v2 creates an empty directory at the source — worse than no mount.

### Cross-cutting "process" pattern reinforced

**G. Per-fix prescribed commit message + WHY-heavy commit body.** All 11 Phase 3-4-5 commits used the prompt's prescribed subject verbatim, with bodies expanded to explain the trade-offs and decisions. The user references commit SHAs in subsequent prompts, so commit messages are load-bearing documentation. The May 9 reflection already noted this; it's reinforced again.

## Strengthen existing CLAUDE.md rules (still pending from May 9)

These remain valid and now have additional support:

| # | Current | Strengthen to |
| --- | --- | --- |
| 25 | "Batch operations: 5000 messages per consume, flush offsets per batch; for cross-region Kafka use 30s socket timeout, 45s session timeout" | Add the thread-pool tuning (`heartbeat.interval.ms=15000`, `max.poll.interval.ms=300000`, `group.instance.id=<stable>`, `statistics.interval.ms=10000` + `stats_cb` for lag) per May 9 #25 |
| 29 | "Always verify changes work before reporting completion" | Add: "Frontend changes also need a `docker compose build frontend && docker compose up -d frontend` — the frontend image does not mount source." (May 9 #29 plus repeat hits this cycle on the api container.) |
| 47 | "Test data loading with `docker exec`" | Generalise per May 9 #47 — fetch live data for MULTIPLE rows when symptom is "works for some users, not others". Phase 3-4-5 reinforced when the live `make status` and `psql` queries surfaced the 2.7M-row scan timeout that no test could have predicted. |

## Drift between CLAUDE.md "Current State" and reality

Still stale at v3.0.1 / Feb 19, 2025. Now ~3 months out of date. Misses:
- Postgres + Next.js + FastAPI architecture (focus of all 2026 work)
- `src/product/event_signals.py`, `src/product/event_normalization.py`, `src/product/actor_enrichment.py`
- `src/notifications/` (NEW this cycle)
- `frontend/` (Next.js), `backend/` (FastAPI)
- `audit_events` + `audit_events_noise` two-table split
- Thread-pool consumer architecture (May 9)
- `notifications.yml`, `actor_mappings.yml` config files (this cycle)
- Pipeline lag visibility (Phase 2)
- Admin endpoints (`/admin/retention/cleanup`, `/admin/backfill/actor-display-names`)
- `./setup` single entry point (Phase 3)

Same recommendation as May 9: add a `## Current State (May 2026)` section that supersedes without deleting the Feb 2025 one.

## Net proposal for next CLAUDE.md update

A single batched edit covering:

1. **All 14 proposals from `2026-05-09-reflection.md`** — they all still apply with stronger evidence after this cycle.
2. **3 new high/medium-confidence rules from this cycle** (A, B, plus E since E is in 4 services already).
3. **3 strengthen-existing rules** (#25, #29, #47).
4. **Replace stale "Current State" section** with a May 2026 snapshot that lists the live architecture (forwarder + api + frontend + postgres, plus the two YAML config layers and the admin endpoints).

That's a single coherent CLAUDE.md edit instead of two separate ones. The user has not yet applied the May 9 batch — better to land both in one shot than to add to a backlog.

## Summary Statistics

| Metric | Value |
| --- | --- |
| Entries analyzed (this cycle) | 2 (2026-05-10 ×2) |
| Entries in active May 2026 stretch | 9 |
| Sessions covered (May 2026) | 5 |
| New high-confidence rules this cycle | 1 (B — hot-reload pattern) |
| New medium-confidence rules this cycle | 4 (A, C, D, F) |
| Existing rules to strengthen | 3 (carry forward from May 9: #25, #29, #47) |
| May 9 proposals still pending | 14 |
| Total CLAUDE.md proposals if batched | 18–20 rules + a Current State refresh |

## Next reflection

Cadence stays task-driven, not calendar. After the next 5+ diary entries OR before the next major architectural change. The user's diary→handoff→reflect cadence is consistently triggered at end-of-session, so a natural rhythm has emerged.

---
Created: 2026-05-10
