# Diary Entry: 2026-05-08

## Session Summary

Long, structured day. Five discrete sprints, four commits on `master`, nothing pushed.

1. Diagnosed and fixed two live-stack issues: browser "NetworkError" on `/events` (turned out to be `/filters/options` 30 s 500-ing on the 9.7 M-row table, surfaced via `getFilters().catch`) and the underlying timeout itself. Per-query 8 s `statement_timeout` + JIT off + 50K most-recent sample + graceful fallback + Alembic 0005 partial indexes. Cold dropped from 30 s → 1.5 s. (`3b7c766`)
2. Wrote `docs/FORWARDER_GAP_ANALYSIS.md` — full per-method audit covering 168 Confluent methods + the dual classification systems (criticality routing in `src/classification/methods.py` vs pattern cascade in `src/product/event_normalization.py`).
3. Implemented all the gap-analysis fixes: cascade rewrites (Get/List/Describe → Data via `\bget|list|describe[a-z]+\b`, revoke/grant/invite → Security, register/deregister → Create/Delete, pause/resume → Modify, GetAPIKey → Data, signin → Security), 30+ new `RESOURCE_TYPE_ALIASES`, methods.py + YAML promotions (`kafka.AlterConfigs` MEDIUM → HIGH; `DeleteNetwork` MEDIUM → CRITICAL; `RevokeRoleResourcesForPrincipal` HIGH → CRITICAL; etc.), catch-all log warning on `signal_reason="unknown"`, manual idempotent backfill script. Updated 2 tests whose assertions contradicted the new classification. (`d1557ee`)
4. Wrote `docs/UI_AUDIT.md` — frontend audit grading every UI element against the Kafka admin's "what changed today, who did it, what resource?" mental model. Found: dense default views, jargon labels, three overlapping filter levers, no `signal_type` dropdown, default time window of 2 h (forwarder is hours behind so first-paint = empty), `/dashboard` swallowing API errors, no `AbortController` anywhere, `frontend/lib/*` had been gitignored since project start.
5. Executed UI sprint A → F: defaults flip to "Needs Attention" (24 h + signal=action_required,attention + hide_noise=true), removed redundant 3-button mode-bar, hid Layout Lab from nav, added Signal/Cluster/Environment filters, hardcoded Result options, distinct row colour-coding by signal_type, "Why this matters" drawer block + "Technical details" disclosure, stale-event banner, lag warnings on dashboard, AbortController on every fetch, `resourceTypeForFamily` synced to the new aliases. Required 3 backend params (`cluster_name`, `environment_name`, `is_denied`) and a per-route 120 s `statement_timeout` so the new default landing query stops 500-ing. Fixed the `.gitignore` `lib/` swallowing `frontend/lib/`. (`2b52011`)
6. Fixed the 2 pre-existing `test_db_mode_scripts` failures by replacing literal `python3` with a venv-aware `PYTHON_BIN` resolver. (`f8a95bc`)
7. Wrote `docs/SESSION_HANDOFF_2026-05-08.md` + `docs/BACKLOG.md`.

End of day: 490 passed, 5 skipped, 0 failed (from 488 / 5 / 2). Frontend builds clean. Live `/events` works on 9.7 M rows but slow (~45 s) — composite index for the new default filter combo is the top backlog item.

## Key Decisions

- **Use a 50K most-recent-rows sample for `/filters/options`, not the full table.** Considered: tighter indexes, materialised view, async refresh. Sample wins because (a) dropdowns don't need exhaustive coverage, (b) 50K events from the last few hours capture every value a user is likely to filter on, (c) keeps the cold-cache wall-clock < 2 s, (d) doesn't require new infrastructure. The trade-off — a value that hasn't appeared in recent traffic is invisible — is acceptable for a dropdown.
- **Two classification systems stay in place; sync both rather than collapse them.** The criticality routing in `src/classification/methods.py` and the pattern cascade in `src/product/event_normalization.py` could in theory be merged. They aren't, because (a) the criticality system feeds Kafka topic routing inside the forwarder and changing it touches the multi-topic forwarder logic, (b) the dashboard cascade is purely Python in-process, (c) one is set-based with YAML override, the other is regex-based. Synced naming and additions across both.
- **YAML override is the runtime source of truth, not the Python defaults.** Discovered mid-sprint when the methods.py edits "didn't take effect" — `_get_methods()` lets the YAML fully override the Python set. From now on, every classification change must touch both `src/classification/methods.py` AND `config/classification_rules.yaml`.
- **Default landing state = filter, not full audit trail.** Considered keeping the default as `mode=decision` with no signal filter so users see "everything that's not noise". Picked `signal=action_required,attention + hide_noise=true` so the page is "what needs your eyes" by default. The "Show full audit trail" chip is one click away. The trade-off — first-time users may not realise they're seeing a filtered view — is mitigated by the highlighted "Needs Attention 🔴" chip and the active-filters summary line.
- **Bumped `/events` per-route `statement_timeout` to 120 s rather than rewriting the count query.** The new default's count query crosses the OR-heavy `_decision_mode_condition()` and seq-scans 9.7M rows. Properly fixing it means a partial composite index — too big for the sprint, deferred to BACKLOG. The 120 s bump matches the existing `/summary` treatment and keeps the route returning 200.
- **`is_denied=true` query param instead of forcing "Denied" through `result=Denied`.** The DB stores `result` as `{Success, Failure}` only — denied events carry `is_denied=true`. Adding a backend filter is cleaner than asking the operator to remember that "Denied" filters via two predicates.
- **Updated 2 existing tests that asserted `kafka.AlterConfigs == MEDIUM`** rather than skip the spec-mandated promotion. The user's spec said "all existing tests must stay green" — but the same spec also explicitly relocated `kafka.AlterConfigs` from MEDIUM to HIGH. The right call is updating the assertion, not skipping the relocation.

## Challenges & Solutions

- **Problem:** `/events` default landing state was 500-ing in 30 s after the UI sprint shipped. **Solution:** Live smoke caught it — bumped `EVENTS_ROUTE_STATEMENT_TIMEOUT_MS = 120000`, mirroring the existing `/summary` per-route timeout. **What didn't work:** initial assumption that the new params (cluster_name etc.) caused the slowdown — actually the new default filter combo did.
- **Problem:** Methods.py edits had no runtime effect. **Solution:** Discovered the YAML override at `config/classification_rules.yaml`. The `_get_methods()` resolver lets YAML fully override Python defaults. Now treating both as one canonical source.
- **Problem:** `frontend/lib/eventFilters.ts`, `api.ts`, `types.ts` were modified but `git status` showed clean. **Solution:** Found the Python-template `lib/` gitignore rule swallowing `frontend/lib/`. Added `!frontend/lib/**` negation. The three load-bearing modules had been tracked-as-ignored since project inception — fresh clones were broken.
- **Problem:** Building the partial index `idx_audit_events_resource_type_notnull` deadlocked when run concurrently with the actor index build. **Solution:** Built sequentially, then rebuilt the resource_type index because Postgres left it `indisvalid=f`. Lesson: don't kick off two `CREATE INDEX CONCURRENTLY` jobs against the same table at the same time.
- **Problem:** The `time_window` dropdown wanted `7d`/`30d` but the backend regex only accepts `Nm`/`Nh`. **Solution:** Translate `Nd → (N*24)h` at the frontend params layer. Avoided a backend regex/parser change.
- **Problem:** The user said "no backend files changed" in the UI sprint validation step but B4 explicitly required adding `cluster_name`/`environment_name` filters that didn't exist on the backend. **Solution:** Did the surgical backend additions (3 query params + filter conditions + statement_timeout bump) and documented the deviation explicitly in the commit message rather than silently breaking the feature.

## Patterns Noticed

- **The user runs in audit-then-fix cycles.** `/forwarder-classification-fix` was preceded by `/forwarder-gap-analysis`. `/UI sprint` was preceded by `/UI audit`. The audits are deliberate context-building, not just throat-clearing — they let the actual implementation prompt be terse and surgical.
- **Validation steps are mandatory, not optional.** Every fix-spec ends with explicit `pytest`, inline check scripts, manual smoke commands. The user trusts results, not promises.
- **Critical / Important / Nice-to-have tiering** in recommendations is the expected report shape. Saw this in audit reports and mirrored in BACKLOG.
- **Backfill / migration / large-scope changes are always manual** with `--dry-run` first. Never auto-run.
- **The user accepts spec deviations** if (a) they're justified, (b) they're called out in the commit message or summary, (c) they're minimal in scope. Silent deviations are not okay.
- **"Code first, explanation after" extends to commits.** Commit messages are long and structured because they ARE the changelog.

## User Preferences Learned

- **Concise running text, dense tables.** Updates between actions are 1-sentence; final summaries lean on Markdown tables.
- **`file_path:line_number` for code references.**
- **Numbered fix specs are the norm.** When the user wants something done, expect a numbered list (`[A1]`, `[B3]`) where each item has a labelled purpose and an exact file path.
- **Commit messages with sections per part.** `(P1) … / (P2) … / Validation` style.
- **The user rarely pushes.** Always commits, never pushes — pushes are explicit and rare.
- **Inline TS comments only when WHY is non-obvious.** No "this function does X" — yes to "this guards against Y because of incident Z".
- **Validation tables in summaries.** Most replies end with a `| Check | Result |` block.
- **The user respects pre-existing fail counts.** They tracked "488 / 5 / 2" across conversations and noticed when 2 became 0.
- **Cross-session memory matters.** The handoff doc in `docs/SESSION_HANDOFF_<date>.md` is treated as the canonical resumption record. Files left untracked across sessions on purpose.

## Code Patterns Worth Remembering

- **Per-query Postgres guards.** `db.execute(text(f"SET LOCAL statement_timeout = {N}"))` and `SET LOCAL jit = off` per request. SQLite path skipped via `dialect.name == "postgresql"` check. Lets `/events` and `/summary` survive otherwise-fatal cost spikes.
- **Recent-sample subquery for low-cardinality dropdowns.** `SELECT col, count(*) FROM (SELECT col FROM t ORDER BY ts DESC LIMIT 50000) sub GROUP BY col` is dramatically faster than `GROUP BY` over the full table when the column has < 200 distinct values.
- **Catch-all observability with seen-set guard.** Module-level `_unknown_methods_seen: set[str]` so each unique unclassified method emits exactly one warning per process. Avoids log floods.
- **Idempotent backfill skeleton.** `id > :last_id ORDER BY id LIMIT N`, batched, only `UPDATE` when recomputed value differs from stored. `--dry-run` flag at top. Re-runnable.
- **Frontend params translator.** `paramsFromFilters(filters)` is the single seam between frontend filter shape and backend query string. Translations like `signal → signal_type`, `Nd → (N*24)h`, `result=Denied → is_denied=true` all live here.
- **`AbortController` per `useEffect`.** Create controller, pass `signal` to fetcher, `return () => controller.abort()` cleanup. `isAbortError(err)` helper lets `.catch` differentiate user-cancellation from real errors.
- **`Panel<T> = { data: T | null; error: string | null }`.** Replaces silent `setState(emptyValue)` swallowing. Renders inline error notice when `error` is set.

## Feedback Received

- "Don't restructure the test file" — surgical changes only.
- "Keep every existing test green" — when an explicit classification change conflicts, update the assertion (don't skip the change).
- "Do NOT touch frontend" / "do NOT touch backend" — these scope boundaries hold tight unless explicitly negotiated by a numbered fix.
- "git status (confirm .env NOT staged)" — the validation step expects `.env` to never appear in `git status` output.
- The user manually corrected one diagnostic ("the NetworkError is actually the filter-options timeout"). Lesson: trace symptom-to-source through the actual call chain (`getFilters` → `/filters/options` → 500 → ErrorState renders "API unreachable") rather than treating the rendered title as the diagnosis.

## Potential CLAUDE.md Rules

- When editing classification or routing constants in `src/classification/methods.py`, also update `config/classification_rules.yaml` — the YAML override is the runtime source of truth.
- Never use a literal `python3` interpreter in shell scripts; resolve via `$PYTHON_BIN` → `$VIRTUAL_ENV/bin/python` → `./.venv/bin/python` → `python3` so subprocess invocations from pytest pick up venv deps.
- Frontend `time_window` dropdown values that aren't `Nm`/`Nh` must be translated at `paramsFromFilters` — backend regex is `^[1-9][0-9]*[mh]$`.
- When adding partial indexes via `CREATE INDEX CONCURRENTLY`, build them sequentially. Two concurrent builds against the same table can deadlock and leave one `indisvalid=f`.
- Decision-mode count queries on `audit_events` cross an OR-heavy predicate; budget per-route `statement_timeout = 120000` on Postgres rather than the default 30 s.
- Backfill scripts must be idempotent + have `--dry-run` + log progress every 10 K rows + stream UPDATEs only when recomputed value differs.
- Catch-all paths in classifiers must log a warning at first sight of each unknown method (seen-set guarded), so unmapped methods are observable.
- `frontend/lib/` is load-bearing TypeScript — the `.gitignore` `!frontend/lib/**` negation MUST stay; otherwise the three modules disappear from version control.
- After backend filter changes, always live-smoke the affected route (`curl -s -w '%{http_code} %{time_total}s'`) before declaring done — backend tests use SQLite and won't catch perf regressions on the live Postgres.
- Don't reintroduce: the 3-button mode-bar on `/events`, the Layout Lab nav link, the 2 h default time window, the literal `python3` in shell scripts.
