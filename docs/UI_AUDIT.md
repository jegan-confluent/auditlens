# Frontend UI Audit

Date: 2026-05-08
Scope: `frontend/` (Next.js 15 standalone build) — 5 routes, 12 components, 3 lib modules, ~935 lines of CSS. Plus a glance at `DASHBOARD_GAP_ANALYSIS.md` (Streamlit comparison, mostly out of scope here).

Mental model used throughout: **a Kafka admin opens AuditLens and asks "What changed in the last day, who did it, on what resource?"** Every UI element is graded against that question.

---

## 1. What the UI currently does

### Routes

| Route | Behaviour |
|---|---|
| `/` | 302 → `/dashboard` (`app/page.tsx`) |
| `/dashboard` | Overview. Five parallel fetches on mount (events 2h decision-mode limit 10, summary 2h decision-mode, failures limit 5, deletions limit 5, system status). Renders SummaryCards → "Recent Decision Events" table → 2-col grid (Failures, Deletions) → SystemStatusPanel. Drawer on row click. **No filters.** Hardcoded `time_window=2h`, `mode=decision`. |
| `/events` | Investigation page. DecisionBanner → mode-bar (3 buttons) → DecisionBanner CTA, NarrativeStrip (5 cards), SignalSummaryPanel (4 counts + flow groups) → FilterBar (11 quick-filter chips + 6 dropdowns/inputs) → "Active filters" line → AuditEventTable → Previous/Next pagination → Drawer with triage. |
| `/system` | SystemStatusPanel + raw `<pre>{JSON.stringify(db_health)}</pre>` + raw `<pre>{JSON.stringify(storage_usage)}</pre>`. |
| `/layout-lab` | Three static design mockups (hardcoded mock data). Visible in main nav. Not production behaviour. |

### Components (all under `frontend/components/`)

| Component | Renders | Actions |
|---|---|---|
| `HeaderStatus` | Pill in topbar showing Connected / Degraded / Down. Initial state `degraded` until `/ready` returns. | None — display only. |
| `SummaryCards` | 4 metric cards: Total Events, Failures (+denied), Top Action, Last Updated. | None. |
| `DecisionBanner` | Gradient-coloured panel. Title (Critical/Review/No action), counts message, sample-warning footer. CTA button applies a filter patch. | "Investigate critical events" / "Show changes to review" / "Show full audit trail". |
| `NarrativeStrip` | Up to 5 cards: Destructive, Configuration changes, Access changes, Failures/denied, Routine noise. Each shows count + meaning + suggested action. | None — read-only narrative. |
| `SignalSummaryPanel` | Headline count, short digest, sample warning, four signal counters (Noise / Info / Review / Action Needed), top-5 flow groups. | "Filter by this activity" button per flow group. |
| `FilterBar` | 11 preset chips (Decision mode, Show full audit trail, Action Needed, Review, Hide Noise, Show Noise, Failed/Denied, Destructive, Config Changes, Access Changes, Clear Filters) + 6 controls (time window dropdown 5 options, resource_type dropdown, resource text, action_category dropdown, actor text, result dropdown) + active-filters summary. | Apply preset / set per-control filter. |
| `AuditEventTable` | 6-col table: Time, Decision badge + reason subline, Who (display + email/raw_id), What happened (event_title + summary), Resource, Source/IP. Row coloured by `signal-{type}` class. | Click row → open drawer. |
| `EventDetailDrawer` | Right-side overlay. Title + summary. **26 detail fields** in grid. 5-button triage row. Fingerprint + copy. Collapsible raw JSON with copy. | Acknowledge / Mark Approved / Investigate / Resolve / Mark False Positive; copy fingerprint; copy raw payload. |
| `SystemStatusPanel` | 8 metrics: DB Mode, DB Events, Consumer state, Lag, Retries, DB Writer, DB Write Errors, Last DB Write. Plus error lines. | None. |
| `EmptyState` | "No events found" + active-filter chips + 2 reset buttons. | Reset / Show all activity. |
| `LoadingState` | Two shimmer skeleton bars + label. | None. |
| `ErrorState` | Title ("API unreachable" or "System degraded") + detail text. | None. |

### `lib/`

- `api.ts` — 8 fetch wrappers + `getReadinessStatus`. All client-side (`use client`); `cache: "no-store"`. `API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8080"` (baked at build time).
- `eventFilters.ts` — `EventFilters` shape (10 keys), defaults (`mode: "decision"`, `time_window: "2h"`, everything else empty), `paramsFromFilters`, `summaryParamsFromFilters`, `activeFilterLabels` translator, `applyQuickFilter`.
- `types.ts` — Single source of truth for AuditEvent (~60 fields), EventListResponse, SummaryResponse (incl. flow_groups[]), FilterOptions, SystemStatus.

---

## 2. Complexity audit — too complex for end users?

### Too many controls visible at once on `/events`

Counted on first paint of `/events` with default filters:

- 4 nav links in the topbar.
- 1 connection status pill.
- 1 "Decision" headline + 1 CTA button (DecisionBanner).
- Up to 5 narrative cards.
- 4 signal-count tiles + up to 5 flow-group cards (each with its own button).
- 3 buttons in the mode-bar ("Back to decision mode" / "Show all activity" / "Show only destructive changes").
- 11 preset chips in the FilterBar.
- 6 filter controls (5 dropdowns + 2 text inputs).
- 1 "Active filters" line.
- 6-column event table.
- 2 pagination buttons.

**That's ~50 interactive elements before a single event is read.** A Kafka admin who wants "what changed today" has to ignore most of it.

### Three independent levers for the same idea

`mode`, `signal`, and `hide_noise` overlap heavily:

- `mode=decision` already hides routine activity backend-side.
- `hide_noise=true` is a separate knob that does similar filtering.
- `signal=action_required,attention` is a third way to suppress noise.

Quick-filter chips combine these inconsistently:
- "Decision mode" sets `mode=decision, hide_noise=false, signal=""`
- "Action Needed" sets `mode=decision, signal=action_required, hide_noise=true`
- "Hide Noise" sets `mode=decision, hide_noise=true, signal=""`
- "Show Noise" sets `mode=audit_trail, hide_noise=false, signal=""`

A user who toggles "Hide Noise" then clicks "Action Needed" then clicks "Show full audit trail" has no mental model of what each lever changed. The active-filters summary line shows the resulting state but not which preset is active (the chip *can* be highlighted, but only when **every** patch field matches exactly — switching `time_window` deactivates the active state of an unrelated preset).

### Confusing labels (jargon for a non-expert)

| Label visible to user | Where | Problem |
|---|---|---|
| "Decision mode" / "Audit trail mode" | mode-bar, banner, chips | Internal terms. A non-expert reads "decision" and asks "whose decision?" |
| "Routine noise" | NarrativeStrip, chips | Defined nowhere on screen. |
| "signal_type" → "Action Needed / Review / Info / Noise" | SignalSummaryPanel | OK, but the underlying token leaks into class names (`signal-action_required`) and breaks colour cues if the API later renames a value. |
| "Decision Reason" + "Signal Reason" + "Recommended Action" | drawer | Three near-identical "why" fields, all shown together. |
| "Impact Type" / "Change Type" / "Resource Family" | drawer | Internal classifier dimensions; meaningless to operators. |
| "Blast Radius" / "Production Hint" / "Resource Criticality" | drawer | Heuristic outputs without explanation. |
| "Actor Source" / "Actor Confidence" / "Actor Type" | drawer | Internal enrichment metadata. |
| "Subject" / "Subject Type" | drawer | Different from "Who" / "Actor"? Same person, two labels. |
| "Sampled summary: based on latest 5,000 of 12,438,217 matching events" | banner | Nuanced caveat with no inline explanation. |
| "Top Action" | SummaryCards | Top by what? (frequency, impact?) |

### Missing context

- **AuditEventTable Decision column** shows `Action Needed` / `Review` / `Info` as a badge, but the *why* (`decision_reason` or `signal_reason`) is rendered as a small grey subline. Users glance past it.
- **`/dashboard`** has no headline explaining "this is a 2h decision-mode view". A new user who sees "Total Events: 0" assumes the system is broken; they don't know to widen the time window.
- **No tooltips** anywhere — not on the 11 quick-filter chips, not on the dropdowns, not on drawer fields.
- **`event_title`** is shown in bold in the "What happened" cell, but `event_summary` rendered immediately below is the full sentence form ("u-75rw9o deleted Topic: jegan-testing"). The two often duplicate each other.

### Wrong defaults

| Default | Problem |
|---|---|
| `time_window=2h` on **both** `/dashboard` and `/events` | Forwarder is regularly hours behind real-time (per the May-07 handoff: "newest event ~5 h old → default 2 h window shows zero"). The first impression is an empty dashboard. **24h would be the right default.** |
| `hide_noise=false` in `defaultFilters` | The "decision mode" backend filter already removes most noise; the front-end keeps `hide_noise=false` so UI never inherits the optimisation unless the user clicks a preset. |
| Layout Lab in main nav | Static mockups visible to every end user. Confuses production users who click in expecting real data. |
| HeaderStatus initial state `degraded` | Renders before any fetch completes → users see "Degraded" briefly on every page load. Should be `loading` (or hidden until `/ready` resolves). |

### Redundant — multiple ways to do the same thing

| Same outcome | Available via |
|---|---|
| Apply "decision mode" | (a) DecisionBanner CTA when overall_status is action_required, (b) mode-bar "Back to decision mode" button, (c) "Decision mode" quick chip, (d) "Reset" button |
| Show only failures/denials | (a) "Failed/Denied" quick chip, (b) `result` dropdown, (c) `/dashboard` Failures card, (d) DecisionBanner CTA when overall_status is action_required, (e) NarrativeStrip "Failures / denied access" item |
| Show destructive changes | (a) "Destructive" quick chip, (b) mode-bar "Show only destructive changes" button, (c) impact_type filter (no dropdown — only via preset), (d) `/dashboard` Deletions card |
| Drill into a single event | (a) click table row, (b) (no other path — but the SignalSummaryPanel "flow group" card *suggests* drilling but only filters; doesn't open the event) |

The mode-bar duplicates the FilterBar's quick chips. The Failures/Deletions cards on `/dashboard` duplicate functionality that's better served by a single "Items needing your attention" surface.

### Verdict

Not bad — the structural metaphor (banner → narrative → signals → filters → table → drawer) is sound. But the page is **dense by default**, leans on internal classifier terminology that leaks into user-facing strings, and offers three overlapping ways to filter with no global visualisation of what's currently applied. A power user will adapt; a casual operator will be lost.

---

## 3. Bug hunting

### Hardcoded values that should come from the API or config

| Where | What | Why it matters |
|---|---|---|
| `app/dashboard/page.tsx:23` | `emptyEvents` literal duplicates the `EventListResponse` shape inline | Drifts whenever `types.ts` changes; should be a shared helper. |
| `app/dashboard/page.tsx:26-27` | Hardcoded `limit=10`, `time_window=2h`, `mode=decision` for the recent-events panel | Should be configurable / persisted. |
| `components/EventDetailDrawer.tsx:58-64` | `triageActions` array (5 statuses) hardcoded | Backend may add states; frontend won't reflect them. |
| `components/FilterBar.tsx:49-55` | Time window options hardcoded (10m / 1h / 2h / 24h / 72h) | Backend `parse_time_window` accepts arbitrary `Nm` / `Nh` — but UI only exposes 5 choices, no 6h or 12h. |
| `components/SignalSummaryPanel.tsx:9-19` | `resourceTypeForFamily` dict — 8 entries | After the `RESOURCE_TYPE_ALIASES` extension (commit `d1557ee`) this mapping is out of sync. New families (mfa, sso_connection, byok_key, custom_connector_plugin, ai, billing) won't map. |
| `lib/api.ts:3` | `API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8080"` | OK as a default; just note this is baked at *build* time, not container-start time. |

### Missing loading / error states

- **`/dashboard`**: only `recent` triggers the global LoadingState. Failures/Deletions/SystemStatus fetches fail silently — `getFailures().catch(() => setFailures(emptyEvents))` (line 31) means a 500 and an empty result are visually identical to the user. Same for getDeletions and getSystemStatus.
- **HeaderStatus**: initial state is `"degraded"` — renders the wrong colour for ~200-500 ms before the `/ready` fetch lands. Should default to `"loading"` or render nothing until the fetch resolves.
- **FilterBar**: dropdowns render with the `"All resource types"` placeholder before `getFilters()` resolves; user can't tell whether the dropdown is empty by design or still loading.
- **`/events`**: When `getEvents` errors, the page-level `error` is shown via ErrorState — but the same `useEffect` re-fires `getSystemStatus()` to attach `system?.db_writer_state`; if THAT also errors, system is silently set to `null` and the ErrorState doesn't surface the underlying cause.
- **`/system`**: no LoadingState wrapper around the JSON `<pre>` blocks; first paint flickers between "Loading" and full data.

### Race conditions (no AbortController on any fetcher)

- **`/events`** has 3 `useEffect`s tied to `[filters, offset]` (events) and `[filters]` (summary). Rapidly clicking quick-filter chips fires overlapping `getEvents` and `getSummary` calls; the *earliest-resolved* response wins on the screen because there's no cancellation, and `setData(setSummary)` calls aren't ordered. A user who clicks "Action Needed" then immediately "Review" can see Action-Needed results displayed under the Review chip's active state.
- **`/dashboard`** fires 5 parallel fetches; if the user navigates away mid-flight, no cleanup. `setRecent` etc. on an unmounted component is a React warning waiting to happen.
- **HeaderStatus** fetches once on mount only; status becomes stale forever after the first paint. (No polling, no auto-refresh.)

### Filter state not persisted (URL params)

- Filters live entirely in component state (`useState<EventFilters>`).
- Browser **back/forward = no-op for filters**.
- Browser **reload = filters reset to default**.
- **No shareable links** — "look at the failed RBAC events from the last 24h" can't be sent over Slack.
- `offset` (pagination) is also in component state, not in the URL; reload resets to page 1.

### Table virtualisation

- AuditEventTable renders all rows. Page size is capped at 50 (`paramsFromFilters` sets `limit: "50"`), so practical screen-perf is fine today.
- Dashboard panels render at most 10/5/5 rows. No issue.
- No virtualization library in use; would only matter if the limit grew.

### TODO / FIXME / XXX / HACK / `any` types

`grep -rE "TODO|FIXME|XXX|HACK|: any\b|as any" frontend/{app,components,lib}` → **zero hits**. The codebase is clean on that axis.

The only loose typings are deliberate `Record<string, unknown>` for JSON-ish blobs (`SystemStatus.storage_usage`, `db_health`, `EventListResponse.debug`). Those are displayed as raw `<pre>{JSON.stringify(...)}</pre>` on `/system` — not pretty, but type-correct.

### Components that fetch but don't handle empty state

- `/dashboard` Failures and Deletions panels DO have empty states ("No failed events in the current data set" / "No delete-category events"). But because `.catch(() => setFailures(emptyEvents))` swallows API errors, **the empty-state copy lies when the API is broken** — user sees "No failed events" when the request actually 500-ed.
- `SystemStatusPanel` renders `eventCount = "unknown"` when `db_health.event_count` isn't a number, but doesn't distinguish "no data yet" from "DB unreachable".

### Filters that exist in UI but don't map to API params

- `paramsFromFilters` is clean: `signal` → `signal_type`, `mode` → `mode`, `hide_noise` → only sent when `=true`, all others passed through verbatim.
- BUT: there's **no `signal_type` dropdown** in the FilterBar — users can only select via quick-chip combos. The query param exists, the UI doesn't expose it directly.
- The `result` dropdown shows raw values from `/filters/options`. Backend stores `"Success"` / `"Failure"` (capitalised); some events may have `"SUCCESS"` if Confluent emits caps. Filter is case-sensitive (string equality on the backend). Risk of silently empty results for mixed-case data.
- **No `cluster_id` / `environment_id` / `cluster_name` filter** — these fields exist on every event and are core to a Kafka admin's mental model, but the UI offers no way to scope by them.

### Other small things

- `/layout-lab` is a design playground using **hardcoded mocks**. It's reachable from the main nav. End users will see "Topic deleted by u-75rw9o" with no actual data. Should be hidden in production builds or behind `?lab` query.
- `app/system/page.tsx:26-30` dumps `db_health` and `storage_usage` as raw indented JSON. Functional, but unfit for non-devs.
- `SummaryCards` "Last Updated" shows `new Date().toLocaleTimeString()` of the *browser mount* — not data freshness. Misleading: tells you when you opened the page, not how recent the data is.
- `AuditEventTable.tsx:5-32` has identical helper logic (`displayActor`, `actorSecondary`, `displayResource`, `displaySummary`, `UNKNOWN_PRINCIPAL_LABELS`) duplicated almost verbatim in `EventDetailDrawer.tsx`. Drift risk.
- Whole-event search (free-text across actor/resource/summary) doesn't exist — only structured filters.

---

## 4. What's missing vs what a Kafka admin needs

Given the cleaner data the recent classification fixes deliver (signal_type, action_category, decision_reason all populated):

| Question | UI answers? | Notes |
|---|---|---|
| Does the UI surface `signal_type`? | ⚠️ Partial | SignalSummaryPanel shows the 4-bucket counts. Quick-filter chips reference Action Needed / Review. But there is **no `signal_type` dropdown** in FilterBar — explicit filtering is impossible without combining presets. |
| Is there a "show only what matters" default view? | ❌ Not really | The default is `mode=decision` + `time_window=2h`. That hides routine reads (good), but does **not** combine `signal=action_required,attention` + `hide_noise=true`. The "what matters" preset exists ("Action Needed") but isn't the default. |
| Can you see WHO did something? | ✅ Yes | `actor_display_name` is the primary cell, with email + raw id as the secondary line. Falls back gracefully through `subject → actor → raw_id`. |
| Can you see WHAT resource was affected? | ✅ Yes | `resource_display_name` is the primary; falls back to `resource_name → resource_display_short → resource_display → resource_type`. |
| Can you see WHY it was flagged? | ⚠️ Buried | `decision_reason` shows up as a small grey subline under the badge. The drawer has `Decision Reason`, `Signal Reason`, and `Recommended Action` as **three separate fields** — same idea, three labels. Casual users won't read it. |
| Is there a way to drill into a single event? | ✅ Yes | Right-side drawer with 26 fields + raw JSON + 5-state triage workflow. |

### Specific things missing

1. **No "What changed today?" landing view.** A Kafka admin's first instinct is "show me everything that happened in the last 24h that needs my attention." Today they have to: change `time_window` from 2h to 24h, click "Action Needed", and accept that "Review" items aren't included. There's no single-click preset that combines them.
2. **No `signal_type` dropdown.** All other dimensions have one; this — arguably the most useful column — does not.
3. **No `cluster_id` / `environment_id` filter.** Multi-cluster orgs can't scope by cluster.
4. **No URL-persisted filters.** Cannot share a view, cannot bookmark, cannot reload without losing state.
5. **Data freshness not surfaced anywhere.** "Last Updated" is the browser mount time, not the newest event timestamp. The forwarder lag is exposed in `/system` (consumer_lag) and `/ready` (newest_event), but the dashboard never tells the user "the most recent event in this view is from 5 hours ago".
6. **No search across event text.** Free-text search across summary/title/resource/actor fields would solve many "did I see this thing earlier?" questions that currently require crafting a specific filter.
7. **No CSV / JSON export.** Even on the drawer (single-event JSON copy is a workaround).
8. **No auto-refresh.** Newly arrived events require F5.
9. **No bulk triage.** Each event must be opened in the drawer and triaged individually.
10. **No charts at all.** (Streamlit shipped 45+ per the gap analysis.) For the question "how do incident counts compare to last week?" there's no answer in the UI.
11. **Fields the UI exposes but the operator doesn't need:** `actor_source`, `actor_confidence`, `actor_enriched_at`, `change_type`, `impact_type`, `resource_family`, `blast_radius_hint`, `production_hint`, `resource_criticality` — most of these are classifier internals. They take up half the drawer.

---

## 5. Recommended changes

Focus: **"Kafka admin opens dashboard, sees what changed in last 24h, clicks event to understand it."**

### Simple — 1-2 hours each

1. **Default `time_window` to `24h`** (one line in `lib/eventFilters.ts`) — biggest single UX improvement given the forwarder is regularly hours behind real-time.
2. **Hide `/layout-lab` from main nav** in production. Either feature-flag or remove the `<Link>` from `app/layout.tsx`.
3. **Replace `<pre>{JSON.stringify(...)}</pre>` blocks on `/system`** with formatted rows (or hide behind a "Raw diagnostics" disclosure).
4. **Fix HeaderStatus initial state** — render nothing (or a "Loading…" pill) until the first `/ready` resolves. Stop showing "Degraded" on every page load.
5. **Replace `SummaryCards` "Last Updated"** with the freshest event timestamp from the API response (use `summary.scanned_events` window or pull `newest_event` from `/ready`).
6. **Promote `decision_reason` into the badge** in AuditEventTable. Drop the tiny grey subline.
7. **Remove the mode-bar** ("Back to decision mode" / "Show all activity" / "Show only destructive changes"). Three dedicated buttons that duplicate the FilterBar chips.
8. **Collapse drawer triplicate**: merge `Decision Reason`, `Signal Reason`, `Recommended Action` into a single "Why this matters" block.
9. **Move classifier internals behind an "Advanced details" expander** in the drawer: `actor_source`, `actor_confidence`, `actor_enriched_at`, `change_type`, `impact_type`, `resource_family`, `blast_radius_hint`, `production_hint`, `resource_criticality`. Default-collapsed.
10. **Stop swallowing errors silently on `/dashboard`**. Replace the `.catch(() => setFailures(emptyEvents))` pattern with an inline "could not load Failures panel" notice; don't lie that there were zero events.
11. **Add tooltips to quick-filter chips** explaining what each preset does.
12. **Add a `signal_type` dropdown to FilterBar** — explicit filter for the most useful column.
13. **Normalise the `result` filter case** server-side or at request time (lower-case before comparing) — eliminates the silent-empty-result risk on `Success`/`SUCCESS` mismatches.
14. **Sync `SignalSummaryPanel.resourceTypeForFamily`** with the canonical aliases from `RESOURCE_TYPE_ALIASES`. New families (mfa, sso_connection, byok_key, custom_connector_plugin) currently map to `""`.
15. **Show `consumer_lag` / `newest_event` warning banner on `/dashboard`** when the forwarder is more than (say) 1 h behind real time. The data is already in `/ready`.

### Medium — half-day each

1. **URL-sync filters and pagination** on `/events`. Use `useSearchParams` + `router.replace`. Persist all 10 filter keys + offset. Enables shareable links, browser back/forward, and reload-safe state.
2. **Default `/events` landing state** to "What changed today?": `time_window=24h, signal=action_required,attention, hide_noise=true`. Make this a named preset visible in the chip row and the URL (`?view=needs_attention`).
3. **Add `AbortController` to every fetcher** in `lib/api.ts` and the page `useEffect`s. Stops the rapid-toggle race condition; prevents "fetch on unmounted" warnings.
4. **Replace the dual `/dashboard` Failures + Deletions cards** with a single "Items needing your attention" panel showing combined `signal_type=action_required,attention`. Half the visual real estate, double the relevance.
5. **Add inline triage buttons on table rows** (Acknowledge / Resolve) so most events can be cleared without opening the drawer.
6. **Group rapid runs of identical events** (same actor, action, resource, within 60 s) into a single expandable row. SignalSummaryPanel already exposes the concept via flow_groups — bring it down into the table.
7. **Manual refresh button** at the top of `/events` showing "Last loaded HH:MM" + a circular-arrow icon. Cheap; avoids the "did anything new happen?" F5 dance.
8. **Cluster / environment filter** on FilterBar. Pull dropdown values from `/filters/options` (extend the backend endpoint to include them).
9. **Persist last-used filter set in localStorage** as a "Resume where I was" link on `/dashboard` ("Last view: 24h, Action Needed, cluster lkc-xyz").
10. **Free-text search box** that hits a single backend `q=` parameter scanning summary/title/actor/resource — covers the "did I see this thing earlier?" use case without crafting a filter.

### Complex — explicitly out of scope here

- New chart pages (criticality breakdown, top-N actors, time-series). Streamlit covers these today.
- Virtualised table for huge result sets. Not a near-term need at limit=50.
- Real-time push (SSE / WebSocket) updates.
- Bulk triage / multi-select on the table.
- Role-based dashboards / per-user permissions inside the UI.
- Internationalisation / timezone selector.
