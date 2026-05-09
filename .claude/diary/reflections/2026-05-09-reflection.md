# Diary Reflection: 2026-05-09

## Entries Analyzed

19 entries total in `.claude/diary/entries/`. This reflection focuses on the active May 2026 stretch (5 entries, ~3 sessions of work) since the prior reflection covered the Dec 2025 cycle. February 2025 entries surveyed for context only.

| Date | Slug | Focus |
|---|---|---|
| 2025-02-15 | critical-fixes-v3 | (older context) |
| 2025-02-19 | wizard-launch-fix | (older context) |
| ... | ... (Dec 2025 cycle covered in 2025-12-19-reflection.md) | ... |
| 2026-03-10 | handoff-deployment | Fargate / deployment hand-off |
| **2026-05-08** | **ui-sprint-classification** | Two-phase audit→fix; classification+routing+UI sprint; partial indexes; statement_timeout per route |
| **2026-05-08** | **action-feed-and-signals** | ActionFeed dashboard; signal-classifier early-returns; URL params on /events |
| **2026-05-08** | **handoff-action-feed-and-signals** | Hand-off (superseded same day) |
| **2026-05-08** | **handoff-final** | Definitive hand-off after the actor-display fix |
| **2026-05-08** | **unenriched-actor-fallthrough** | Mixed-enrichment bug; isEnrichedDisplay helper; two-priority labelers |
| **2026-05-09** | **consumer-thread-pool-and-perf-fixes** | This session's diary |
| **2026-05-09** | **handoff-consumer-thread-pool-and-perf** | This session's hand-off |

## Pattern Analysis

### High-confidence patterns (3+ supporting entries)

| Pattern | Frequency | Evidence |
|---|---|---|
| **"Read ALL of these files completely before touching anything"** as a hard precondition | 5/5 May entries | Repeated verbatim at top of multiple task briefs in `2026-05-08-action-feed-and-signals` ("the user keeps restating it"), `2026-05-08-handoff-final`, `2026-05-09-consumer-thread-pool-and-perf-fixes` |
| **`.env` is gitignored on purpose; never stage it** | 4/5 May entries | `2026-05-08-ui-sprint-classification`: "git status (confirm .env NOT staged)". Repeated in every commit instruction across May 2026. |
| **Phased / chunked commits over one big-bang commit** | 4/5 May entries | `2026-05-08-ui-sprint-classification` (4 commits/day), `2026-05-08-action-feed-and-signals` (4 commits, "Never asked to squash"), `2026-05-09-consumer-thread-pool-and-perf-fixes` (8 commits across 2 task briefs, both phased via AskUserQuestion) |
| **Pytest baseline is 487 passed + 3 pre-existing env-leakage failures**; treat as canonical, never claim "regression" without stash-checking pristine HEAD | 4/5 May entries | `2026-05-08-action-feed-and-signals` (root caused), reaffirmed in `handoff-final`, `2026-05-09-handoff` |
| **Live-state diagnostics BEFORE editing**: `curl /health`, `docker compose logs --tail`, `psql -c "SELECT count(*)..."` etc. at the top of every task | 5/5 May entries | Each task brief explicitly listed diagnostic commands; the diary entries credit them with catching premise mismatches (Issue 1 "forwarder idle" was 7.9 msg/s not 0; "NetworkError on /events" was actually `/filters/options` 500-ing) |
| **AskUserQuestion when scope > 3 files OR risk is high** | 3/5 May entries | `2026-05-09-consumer-thread-pool-and-perf-fixes`: used twice (sequencing the 7-issue task; sequencing the thread-pool task; parallel writers yes/no). User answered each in seconds; "cheaper than guessing wrong on a 400-line refactor" |
| **"docker compose restart" does NOT reload env vars** — must use `docker compose up -d --force-recreate <svc>` | 3/5 May entries | `2026-05-09-consumer-thread-pool-and-perf-fixes` (twice — once for `DB_WRITE_BATCH_SIZE`, once for `ANOMALY_WHITELIST_PRINCIPALS`); also `2026-05-08-action-feed-and-signals` (frontend container required `build` + `up -d` for source changes) |
| **Frontend container needs full `docker compose build <svc> && docker compose up -d <svc>`** for source changes (volumes are not mounted into all containers) | 3/5 May entries | `2026-05-08-action-feed-and-signals`, `2026-05-08-handoff-final`, `2026-05-09-handoff` |
| **`api` container has NO source mount — `docker cp` is the hot-patch path during a session, but image MUST be rebuilt before pushing** | 2/5 May entries | `2026-05-09-consumer-thread-pool-and-perf-fixes` flags this as a blocker; same pattern noted earlier with the alembic migration permission denial in the same container |

### Medium-confidence patterns (2 supporting entries)

| Pattern | Frequency | Evidence |
|---|---|---|
| **Test contracts can encode bugs**: when a fix conflicts with a test that pins the buggy behavior, update the test alongside the fix and call it out explicitly | 2/5 | `2026-05-08-ui-sprint-classification` (`kafka.AlterConfigs` MEDIUM→HIGH update); `2026-05-08-action-feed-and-signals` (`test_failed_read_only_404_uses_review_copy` rename) |
| **Backend `/system/status` proxy pattern** for browser → forwarder communication (avoids exposing forwarder ports + bypasses CORS) | 2/5 | This session's `/system/forwarder-health` and `/system/vacuum`; `2026-05-08-handoff-final` references `system_service.py` already proxying via `_ForwarderHealthCache` |
| **Pre-existing test failures must be explicitly disambiguated** in any session-end report (count baseline + reason + "not regressed by this session") | 2/5 | `2026-05-08-action-feed-and-signals`, `2026-05-09-handoff` both list the 487/3/5 baseline with the same root cause |
| **Two-priority data rendering for the same fact** is OK when surfaces have different ergonomic needs | 2/5 | `2026-05-08-unenriched-actor-fallthrough` (Who column = email-first, prose sentence = display-first); `2026-05-08-handoff-final` (anomaly dedup key = `(type, principal)` for log dedup vs. distinct alert per `(type, principal, source_ip)` was the wrong unit) |
| **Honest "we did not hit the target" reports are preferred over claimed-success-with-fudges** | 2/5 | This session (200 msg/s missed, flagged); `2026-05-08-ui-sprint-classification` (statement_timeout bumped instead of full query rewrite, deferred to BACKLOG) |
| **Construct config dataclasses via `from_env()`, NOT direct constructor** when env-derived fields exist | 2/5 | This session's `RateTrackerConfig` fix (the load-bearing one); identical risk surface in `EnrichmentConfig`, `PersistenceConfig` — both have `from_env()` and direct constructors |
| **librdkafka thread-safety claims need verification** — confluent-kafka's docs say "thread-safe except close()" but per-method behavior varies (e.g. consume()/commit() across threads requires explicit `store_offsets` or explicit-offset commits) | 2/5 | This session twice (the user's prescriptive note about `watermark_offsets` was wrong; `store_offsets(message=msg)` didn't fix the cross-thread `_NO_OFFSET`). Also relevant in older Kafka producer rules (rule #49). |

### Workflow patterns observed across May entries

| Pattern | Frequency | Notes |
|---|---|---|
| **Audit-then-fix cycles**: a structured audit doc precedes every implementation sprint | 3/5 | `forwarder-gap-analysis` → `forwarder-classification-fix`; `UI_AUDIT.md` → UI sprint; this session's diagnostics → thread-pool refactor |
| **Numbered fix specs** (`[A1]`, `[B3]`, "PART 5") with file paths are the user's standard request format | 5/5 | Every May task brief used numbered/labelled units |
| **End-of-session ritual**: `/diary` then `/handoff` then `/reflect` | 2/5 May explicit, observed in older too | Every long session ends with these three. Diary = ground-truth log; handoff = next-session bootstrap; reflect = drift detection |
| **"Do not push"** at the end of every commit instruction | 5/5 May entries | The user reviews + pushes themselves; this is non-negotiable |

### Successful strategies (positive feedback / "user accepted without pushback")

- **Trust-but-verify on every claim, including my own.** Each session credits live-data inspection with catching premise mismatches.
- **Surgical edits over rewrites** when the changes are localized. Handoffs explicitly note "preserve the per-message processing block verbatim, dedent it, and just wrap in the new outer thread structure."
- **Validation tables in summaries.** `| Metric | Value |` tables of rate / lag / processed / queue / errors at the end of every state-of-the-system report.
- **Detailed commit messages** documenting the WHY, the trade-offs, and what's still missing. Multiple entries note the user references commit SHAs in subsequent sessions.
- **Calling out spec deviations explicitly** rather than silent. Confirmed accepted in `2026-05-08-ui-sprint-classification`: "The user accepts spec deviations if (a) they're justified, (b) they're called out in the commit message or summary, (c) they're minimal in scope. Silent deviations are not okay."

## Proposed CLAUDE.md Updates

### New rules — High confidence (3+ supporting entries)

1. **Read every file the user lists FULLY before any edit.** When a task brief opens with "Read these files completely before touching anything," that is a hard precondition, not a hint. Do not Read only the symbol you think you need; read the whole file. The user has called this out across multiple sessions — treat as a load-bearing rule.
   - Evidence: `2026-05-08-action-feed-and-signals`, `2026-05-08-handoff-final`, `2026-05-09-consumer-thread-pool-and-perf-fixes`

2. **Run live diagnostics BEFORE editing**, even when the user's task brief gives a prescribed fix. The first 1–3 tool calls of any task should be `Read` + diagnostic `Bash` (`curl /health`, `docker logs --tail`, `psql -c "..."`, etc.). Premise mismatches surface here, not in the code review.
   - Evidence: `2026-05-08-ui-sprint-classification` (NetworkError was actually `/filters/options` 500), `2026-05-08-action-feed-and-signals`, `2026-05-09-consumer-thread-pool-and-perf-fixes` (Issue 1 "forwarder idle" was 7.9 msg/s)

3. **`.env` and `.secrets` are gitignored. Never stage them.** Confirm with `git status -s` before every commit. Live tuning of `.env` for a running container is fine; committing it is a hard "no."
   - Evidence: `2026-05-08-ui-sprint-classification`, `2026-05-08-action-feed-and-signals`, `2026-05-08-handoff-final`, `2026-05-09-handoff`

4. **`docker compose restart <svc>` does NOT reload env vars.** Use `docker compose up -d --force-recreate <svc>` after editing `.env`.
   - Evidence: `2026-05-09-consumer-thread-pool-and-perf-fixes` (encountered twice in one session); `2026-05-08-action-feed-and-signals` (frontend variant)

5. **Frontend / api container changes require `docker compose build <svc> && docker compose up -d <svc>`** — these images do NOT mount source from the host. The forwarder container DOES mount `audit_forwarder.py` and `src/` so a `restart` picks up code changes; the `api` and `frontend` containers do not.
   - Evidence: `2026-05-08-action-feed-and-signals`, `2026-05-08-handoff-final`, `2026-05-09-handoff` (the api `docker cp` hot-patch was load-bearing this session)

6. **Pytest baseline is 487 passed + 3 pre-existing env-leakage failures.** Before claiming any regression, stash + re-run on pristine HEAD. The 3 failures are `test_client_disabled_without_credentials`, `test_list_environments_disabled`, `test_enricher_disabled_without_credentials` — caused by `.env`/`.secrets` leaking `CONFLUENT_CLOUD_API_KEY` into the pytest process.
   - Evidence: `2026-05-08-action-feed-and-signals`, `2026-05-08-handoff-final`, `2026-05-09-handoff`

7. **Phased commits over one big-bang commit** when scope > 3 files. Use `AskUserQuestion` to confirm the sequencing — the user almost always picks the recommended phased option, and answers in seconds.
   - Evidence: `2026-05-08-ui-sprint-classification` (4 commits), `2026-05-08-action-feed-and-signals` (4 commits), `2026-05-09-consumer-thread-pool-and-perf-fixes` (8 commits across 2 phased plans)

8. **Construct config dataclasses via `from_env()`, NOT direct dataclass constructor**, when the dataclass has `from_env()` defined. The direct constructor silently drops env-only fields. Audit existing call sites: `RateTrackerConfig`, `EnrichmentConfig`, `PersistenceConfig` all have this risk surface.
   - Evidence: `2026-05-09-consumer-thread-pool-and-perf-fixes` (load-bearing fix for `RateTrackerConfig` — the whitelist had been silently empty in production); `2026-05-08-action-feed-and-signals` (anomaly threshold default routed through `from_env()` only by design)

### New rules — Medium confidence (2 supporting entries)

9. **When a test pins buggy behavior**, update the test alongside the fix and call it out as a "behavioral assertion change" — not a "regression."
   - Evidence: `2026-05-08-ui-sprint-classification` (`kafka.AlterConfigs` MEDIUM→HIGH); `2026-05-08-action-feed-and-signals` (`test_failed_read_only_404_uses_review_copy` rename)

10. **`consume()` and `commit()` on different threads in confluent-kafka requires explicit per-`(topic, partition)` offset tracking and `consumer.commit(offsets=[TopicPartition(t, p, off+1)])`.** librdkafka's auto-offset-store does not propagate reliably across threads, even with `consumer.store_offsets(message=msg)`.
   - Evidence: `2026-05-09-consumer-thread-pool-and-perf-fixes` (debugged across two iterations); generalisation of producer-flush rule #49

11. **Honest "we did not hit the target" reports beat fudged success.** When a numerical target is missed, report it explicitly with the bottleneck reason and the path forward. The user accepts this without pushback every time.
   - Evidence: `2026-05-08-ui-sprint-classification` (statement_timeout bumped, deferred full query rewrite to BACKLOG); `2026-05-09-consumer-thread-pool-and-perf-fixes` (200 msg/s missed, flagged with three architectural options)

### Strengthen existing rules

| # | Current | Strengthen to | Why |
|---|---|---|---|
| 25 | "Batch operations: 5000 messages per consume, flush offsets per batch; for cross-region Kafka use 30s socket timeout, 45s session timeout" | Add: "When splitting consume/process into separate threads, add `heartbeat.interval.ms=15000`, `max.poll.interval.ms=300000`, `group.instance.id=<stable-per-replica>`, and use `statistics.interval.ms=10000` + `stats_cb` for lag rather than synchronous `get_watermark_offsets`." | This session formalised the thread-pool tuning; rule #25 is the natural home |
| 29 | "Always verify changes work before reporting completion - use browser tools if available, check logs otherwise" | Add: "If you cannot do a real browser visual check, say so explicitly in the session summary — do not claim 'UI verified' from a TS build alone." | The user explicitly mentions this in CLAUDE.md harness-level rules but it's worth project-level reinforcement after this session's `/system` page work |
| 47 | "Test data loading with `docker exec <container> python3 -c "..."` before debugging UI layer" | Generalise: "When the user reports symptom X but your code reading suggests it should work, fetch live data via `curl` / `docker exec` for MULTIPLE rows of the same kind. Mixed-state (some enriched, some not) is a common cause of 'why doesn't this work for one user but does for others.'" | `2026-05-08-unenriched-actor-fallthrough` proved this |

### Rules to remove or weaken

None. All current rules continue to apply or have been reinforced.

### Drift between CLAUDE.md "Current State" section and reality

The `## Current State (Feb 19, 2025) - v3.0.1` section is now ~3 months stale and missing:
- The Postgres + Next.js + FastAPI architecture that's been the focus of all 2026 work
- New modules: `src/product/persistence.py`, `src/product/db_writer.py`, `src/product/event_signals.py`, `src/product/event_normalization.py`, `src/product/actor_enrichment.py`
- The `frontend/` Next.js app, the `backend/` FastAPI app
- The `audit_events` Postgres table + the alembic migrations
- The thread-pool consumer architecture introduced this session

Rather than try to re-write that section in a reflection, **propose a separate `## Current State (May 2026)` section** be added to CLAUDE.md that supersedes the Feb 2025 one without deleting it (history is useful).

## Summary Statistics

| Metric | Value |
|---|---|
| Entries analyzed (active May 2026) | 7 |
| Sessions covered | 3 (May 8 ×2, May 9 ×1) |
| New high-confidence rules proposed | 8 |
| New medium-confidence rules proposed | 3 |
| Existing rules to strengthen | 3 |
| Rules to remove | 0 |
| Total CLAUDE.md proposals | 14 |

## Next Reflection

Recommended cadence: after the next 5+ diary entries, or before starting a new project phase (e.g. before pushing the 8 May 2026 commits + the next major feature). Not weekly — the user's cadence is task-driven, not calendar-driven.

---
Created: 2026-05-09
