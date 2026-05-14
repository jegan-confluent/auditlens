# AuditLens User Guide

## What is AuditLens?

AuditLens consumes the Confluent Cloud audit log topic (`confluent-audit-log-events`), classifies every event by risk signal and impact type, enriches actor identities with display names, and stores the results in PostgreSQL. The dashboard lets security and platform teams see what is happening across their Confluent Cloud organisation in real time — who created or deleted resources, what access changes were made, which operations are failing, and which patterns repeat often enough to be expected noise versus genuine activity worth reviewing.

---

## The Four Pages

### Dashboard (`/dashboard`)

The dashboard is an at-a-glance summary for the current time window (1h / 6h / 24h / 7d, selectable at the top).

| Section | What it shows |
|---------|---------------|
| **NarrativeStrip** | A one-sentence summary of the current security posture: how many action-required events, time window, and whether the pipeline is healthy |
| **SignalSummaryPanel** | Event counts broken down by signal type (Critical / Review / Info / Noise) for the selected time window |
| **EventVolumeChart** | A stacked bar chart showing the signal mix at a glance — useful for spotting spikes in destructive or access-change activity |
| **ActionFeed** | The most recent `action_required` events — the things that need immediate attention |
| **TopActors** | The principals with the most activity in the window — helps identify unexpected accounts or runaway automation |
| **SystemStatusPanel** | Pipeline health: whether the forwarder is consuming, DB write lag, consumer lag |

**When to act:** If ActionFeed shows DeleteKafkaCluster, CreateApiKey for an unfamiliar account, or any `result: Failure` from a privileged principal, open `/events` to investigate.

The dashboard auto-refreshes every 60 seconds. Clicking a bar in EventVolumeChart navigates to `/events` filtered to that time window.

---

### Events (`/events`)

The primary triage page. This is where you work through alerts, investigate actors, and mark events as handled.

#### Default view

On first load, Events shows `action_required` signal events from the last 12 hours in decision mode. This is the "inbox" — the events most likely to need a human decision.

#### Signal badges

Each row has a coloured signal badge in the second column:

| Badge | Signal | Meaning |
|-------|--------|---------|
| 🔴 **CRITICAL** | `action_required` | Requires immediate review — destructive operations, unexpected access grants, or explicit deny patterns |
| 🟡 **REVIEW** | `attention` | Worth reviewing when time allows — configuration changes, new API keys, access modifications |
| 🔵 **INFO** | `informational` | Normal activity, logged for audit completeness — read operations, list calls, cluster lookups |
| ⬜ **NOISE** | `noise` | Routine system traffic that does not require review — internal RBAC checks, Kafka heartbeats |

#### Filtering

The filter panel is above the event table. Filters persist in the URL — copy and share a filtered view directly.

| Filter | Where it is | How to use |
|--------|------------|------------|
| Free-text search | Always visible, top of panel | Searches event title, actor, resource name, and request ID |
| Signal | Signal pills row | Click a pill to filter by signal type |
| Time window | Dropdown | Last 30 min → 30 days |
| Action category | Dropdown | create / delete / modify / api key / … |
| Actor | More filters → Actor field | Partial match on actor name or principal ID |
| Resource | More filters → Resource field | Partial text match on resource name |
| Resource type | More filters → Resource type | Topic / Cluster / Environment / … |
| Cluster | More filters → Cluster field | Exact cluster name |
| Environment | More filters → Environment dropdown | Filter by Confluent environment |
| Result | More filters → Result dropdown | Success / Failure / Denied |

**Quick filters** at the top of the panel pre-configure common views:
- **Needs Attention** — action_required + attention, last 24h
- **Destructive** — destructive impact type, decision mode
- **Access Changes** — access change events
- **Config Changes** — configuration change events
- **All Activity** — full audit trail, last 7 days, all signals

**Saved presets:** Click "Save preset" while any non-default filters are active to save the current filter combination. Presets are stored in browser local storage (up to 5).

#### Triaging an event

1. Click any row in the events table — a detail drawer opens on the right side of the screen.
2. The drawer shows: actor display name and ID, action, resource, timestamp, source IP (when available), result (Success / Failure / Denied), signal badge, and current triage status.
3. Scroll down in the drawer to the triage actions section. Three options:

| Button | Status set | When to use |
|--------|-----------|-------------|
| **Acknowledge** | `acknowledged` | You have seen it and it is being handled |
| **Resolve** | `resolved` | Investigation is complete — no further action needed |
| **Mark False Positive** | `false_positive` | This signal classification is wrong for this event |

4. The triage status updates immediately in the table row — no page reload required.
5. Triage is keyed on `event_fingerprint` — marking an event in one session marks the same fingerprint everywhere.

#### RecurringPatterns

The RecurringPatterns panel appears below the event table (collapsed by default). It shows `(actor, action, resource)` combinations that have fired more than 10 times within a 10-minute window — patterns that are clearly repeating automation rather than one-off human actions.

Each pattern has two actions:

| Button | What it does |
|--------|-------------|
| **Suppress 24h** | Hides matching events from decision mode for 24 hours — use for temporarily noisy automation during a deploy |
| **Mark Expected** | Permanently marks the pattern as expected automation — permanently hides from decision mode |

Use **Suppress 24h** for temporary noise (e.g. a runbook that fires every few minutes during an incident). Use **Mark Expected** only when you are certain the pattern is always routine and should never surface as a decision-mode event.

#### Actor activity panel

Clicking an actor's name in the event table opens the ActorActivityPanel on the right, showing that actor's recent event history, their most frequent actions, and the resources they have touched. Use this when you see an unfamiliar principal and want to understand their activity pattern before triaging.

---

### System (`/system`)

The System page shows the health of the ingestion pipeline — from Confluent Cloud to your PostgreSQL database.

#### Pipeline health statuses

| Status | What it means |
|--------|---------------|
| **healthy** | Consumer lag < 100,000 messages AND newest event written < 60 seconds ago |
| **degraded** | Consumer lag is elevated (10,000–100,000) OR newest event is 1–5 minutes old |
| **stalled** | Consumer lag > 1,000,000 OR no events written in > 5 minutes OR DB timestamp is unknown |
| **unknown** | Forwarder health endpoint is unreachable |

#### Key metrics

| Metric | Where shown | What to watch |
|--------|------------|---------------|
| Consumer lag | Pipeline section | Lag > 10,000 is warning; > 100,000 is critical. Sustained growth means the forwarder is not keeping up |
| Processing rate | Pipeline section | Messages per second the forwarder is processing |
| DB writer status | Pipeline section | Should be `running`. `blocked` or `error` means events are not reaching the database |
| Newest event age | Pipeline section | Time since the most recent event was written. > 5 minutes in production warrants investigation |
| Storage mode | Storage section | `normal` is healthy; `warning` / `critical` / `emergency` means Postgres or SQLite storage is filling up |

#### PipelineLagBanner

When consumer lag exceeds the warning threshold, a yellow banner appears at the top of the Events and System pages. If the status is `stalled`, the banner turns red. The banner disappears automatically once the forwarder catches up.

**What to do when the banner shows:**

1. Run `make health` (EC2) or check `http://localhost:8003/health` (local dev only) to see the raw forwarder state.
2. Check `make logs` (EC2) or `docker compose logs auditlens-forwarder` (local dev only) for error messages.
3. Most common cause: expired Kafka credentials. Update `AUDIT_API_KEY` / `AUDIT_API_SECRET` in `.env` and restart the forwarder.
4. If lag is growing from a cold start after downtime, wait — the forwarder will catch up. High lag from a fresh restart is normal for the first few minutes.

#### Checking health directly

```bash
# EC2 (via Makefile)
make health

# Local dev only
curl -s http://localhost:8003/health | python3 -m json.tool
curl -s http://localhost:8080/health | python3 -m json.tool
```

---

### Settings (`/settings`)

The Settings page requires an admin API token when `API_AUTH_ENABLED=true`. It has four tabs.

#### Retention tab

Configure how long events are kept in the database:

| Field | Default | Description |
|-------|---------|-------------|
| Event retention | 7 days | How long enriched events are kept |
| Raw payload retention | 7 days | How long the original Confluent JSON payload is retained. Enriched fields are always kept for the full event retention period |
| Noise retention | 3 days | How long routine noise events are kept |

Click **Save** to apply. Changes take effect on the next cleanup cycle (runs every hour by default).

#### Cold Storage tab

Configure export of older events to S3 or Google Cloud Storage. Supported providers: `s3`, `gcs`. Set `enabled`, `provider`, `bucket`, `prefix`, and credentials. Use the **Test** button to validate connectivity before saving.

#### Notifications tab

Notification destinations (Slack, Microsoft Teams, generic webhooks) are configured in `notifications.yml` at the repo root. Copy `notifications.example.yml` to `notifications.yml` and edit it. The forwarder hot-reloads `notifications.yml` within 60 seconds of a file change — no restart required.

Supported per-destination options: signal filter (action_required / attention only), minimum risk level, and deduplication window.

#### Actor Mappings tab

Actor display name overrides are configured in `actor_mappings.yml` at the repo root. Copy `actor_mappings.example.yml` to `actor_mappings.yml` and add entries mapping principal IDs to human-readable names. The forwarder hot-reloads `actor_mappings.yml` within 60 seconds of a file change.

Mapped names take priority over IAM API resolution and audit-event-derived names.

---

## Signal Types Explained

| Signal | Badge | What it means | Examples |
|--------|-------|---------------|---------|
| `action_required` | 🔴 CRITICAL | Requires immediate review | `DeleteKafkaCluster`, `DeleteEnvironment`, `CreateRoleBinding` for an unknown principal, any operation that returns Denied for a privileged account |
| `attention` | 🟡 REVIEW | Worth reviewing when time allows | `CreateApiKey`, configuration changes, new service account creation |
| `informational` | 🔵 INFO | Normal activity, logged for completeness | `GetCluster`, `ListTopics`, `DescribeEnvironment` |
| `noise` | ⬜ NOISE | Routine system traffic | Internal RBAC checks (`mds.Authorize`), Kafka heartbeats (`kafka.Fetch`, `kafka.Produce`), producer offset commits |

Decision mode (the default on the Events page) hides `noise` events and optionally `informational` events. Full audit trail mode shows everything. Switch with the "All Activity" quick filter.

---

## Triage Workflow

A typical daily workflow for reviewing `action_required` events:

1. Open `/events` — default shows `action_required` events from the last 12 hours.
2. Scan the ActionFeed section on Dashboard for anything urgent first.
3. Work through the events table top-to-bottom (sorted newest first).
4. For each event: click the row to open the detail drawer.
5. Read: actor display name, action, resource, result, source IP.
6. Decide:
   - **Acknowledge** — you have seen it, no further action yet (in-progress investigation).
   - **Resolve** — investigation complete, no action needed.
   - **Mark False Positive** — this event was mis-classified; signal was too high.
7. Move to the next event. Rows update their triage status immediately.

At the end of the session, events you have not triaged remain `open`. You can filter by result or actor to batch-triage related events.

---

## Recurring Patterns

Recurring patterns automatically surface repeating `(actor, action, resource)` combinations that cross a threshold of 10 or more occurrences within a 10-minute window. This catches runbook loops, misconfigured automation, and CI/CD pipelines that generate audit events at high volume.

**When to Suppress vs Mark Expected:**

- **Suppress 24h** is for temporary noise. The events still exist in the database and will surface again after 24 hours. Use this during an incident, a deploy, or any time you need to clear the view without making a permanent decision.
- **Mark Expected** permanently removes the pattern from decision mode. Use this only for automation you have verified is always routine — for example, a known service account that runs `CreateTopicPartitions` repeatedly as part of normal operations. You cannot un-mark expected from the UI (requires admin API or database access).

---

## Pipeline Health

The forwarder exposes a `/health` endpoint that reports real-time ingestion metrics.

```bash
# EC2
make health

# Local dev only
curl -s http://localhost:8003/health
```

Key fields in the health response:

| Field | What it means |
|-------|---------------|
| `status` | `ok` or `error` |
| `consumer_lag` | Number of messages behind the head of the audit topic |
| `processing_rate` | Messages processed per second |
| `processed_total` | Total messages processed since forwarder start |
| `db_writer_status` | `running`, `blocked`, or `error` |

**What consumer lag means:** Each Confluent Cloud organisation continuously writes events to the audit log topic. Consumer lag is how far behind the forwarder is. Under normal conditions, lag should be near zero. Lag builds up when the forwarder restarts (it catches up automatically), when Kafka credentials expire, or when the database is too slow to accept writes.

**Lag thresholds:**
- < 10,000 — normal
- 10,000–100,000 — warning (Events page banner shows)
- > 100,000 — critical (banner turns red)
- > 1,000,000 or no recent writes — stalled

---

## Retention and Storage

AuditLens stores two categories of events in PostgreSQL:

- `audit_events` — enriched events with signal classification, actor display name, resource type, impact type, and triage state
- `audit_events_noise` — routine noise events stored separately at higher volume

The retention cleanup job runs every hour (`DB_RETENTION_CLEANUP_INTERVAL_SECONDS`). It deletes rows in batches by `timestamp < now() - retention_days` using `FOR UPDATE SKIP LOCKED` so it never blocks the live write path.

**Retention defaults:**

| Table | Default | Setting |
|-------|---------|---------|
| `audit_events` | 7 days | `EVENT_RETENTION_DAYS` / Settings → Retention → Event retention |
| Raw Confluent payload JSON | 7 days | `RAW_PAYLOAD_RETENTION_DAYS` / Settings → Retention → Raw payload retention |
| `audit_events_noise` | 3 days | `NOISE_RETENTION_DAYS` / Settings → Retention → Noise retention |

Raw payload retention only removes the original JSON blob. All enriched fields (actor, resource, signal, triage) are kept for the full event retention period.

To reduce storage immediately, lower the retention values in Settings → Retention and wait up to one hour for the next cleanup cycle.

---

## FAQ

**Q: The dashboard shows "Last event: X hours ago" — is something wrong?**

A: Check the pipeline health. Open `/system` or run `make health`. If consumer lag is growing and `db_writer_status` is not `running`, the forwarder is not writing to the database. The most common cause is expired Kafka credentials — check `AUDIT_API_KEY` and `AUDIT_API_SECRET` in `.env`.

**Q: How do I suppress a noisy service account?**

A: Two options. For a temporary suppression (e.g. during a deploy), open Events → Recurring Patterns, find the pattern for that service account, and click "Suppress 24h". For permanent suppression of expected automation, click "Mark Expected". For a manual display name override so the account shows up with a readable name, add it to `actor_mappings.yml`.

**Q: What is the difference between Acknowledge and Resolve?**

A: **Acknowledge** (`acknowledged`) means you have seen the event and are actively investigating or have noted it. **Resolve** (`resolved`) means investigation is complete and no further action is required. Both remove the event from the default `open` triage view. Use Acknowledge for in-progress work; use Resolve when done.

**Q: Why do some actors still show their raw principal ID (e.g. `sa-abc123`) instead of a display name?**

A: Actor enrichment resolves display names from four sources in priority order: manual mapping (`actor_mappings.yml`), Confluent IAM API (if `IAM_ENRICHMENT_ENABLED=true`), audit-event-derived identity, and raw ID fallback. If IAM enrichment is disabled or the credential is not in the IAM API, the raw ID is shown. To add a human-readable name, add the principal to `actor_mappings.yml`.

**Q: An event shows Result: Denied — is that always a security issue?**

A: Not always. Internal Confluent RBAC checks (`mds.Authorize`) routinely return Denied as part of normal access control evaluation and are classified as `noise`. Denied results on data-plane operations (create, delete, modify) from external principals are more likely to be genuinely interesting and are classified `attention` or `action_required`. Filter by `Result: Denied` and check the action and actor before deciding.

**Q: How do I share a filtered view with a colleague?**

A: The Events page persists all active filters in the URL. Copy the browser URL while your filters are active and share it. The recipient will land on the same filtered view. Saved presets are browser-local and do not transfer via URL.

**Q: How do I run AuditLens without Kafka credentials (demo mode)?**

A: Run `scripts/run_sqlite_demo.sh`. This starts the API and frontend with a local SQLite database and seeds sample audit events. No Kafka credentials are required. Open `http://127.0.0.1:3000/events` (local dev only) to explore the UI with sample data.
