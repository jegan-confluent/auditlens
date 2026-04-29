# AuditLens Clean Onboarding Walkthrough

Use this guide as a live demo script for first-time users testing AuditLens Clean against a real Confluent Cloud environment.

## 1. What AuditLens Clean Does

AuditLens Clean is a focused dashboard for Confluent Cloud audit logs. It helps you quickly answer:

- What changed?
- Who did it?
- What failed?
- Was access denied?
- Which actor, service account, topic, cluster, or resource is involved?

The clean dashboard is intentionally narrow. It hides routine successful authentication, authorization, and metadata-read noise by default so the first screen is useful for debugging failures, denied access, creations, deletions, and other audit signals.

## 2. Prerequisites

Before starting, make sure you have:

1. Access to a Confluent Cloud organization with audit logging enabled.
2. A Confluent Cloud audit-log source cluster.
3. A destination Kafka cluster where AuditLens reads enriched events.
4. API keys for Kafka access:
   - `DEST_BOOTSTRAP`
   - `DEST_API_KEY`
   - `DEST_API_SECRET`
5. Local Python environment with Streamlit dependencies installed.
6. Optional but useful: Confluent CLI access so you can create topics, inspect permissions, or trigger test actions.

You should also know which service account or user you will use for the demo.

## 3. Setup

1. Clone the repo:

```bash
git clone <repo-url>
cd AuditLens
```

2. Install dependencies. Use the repo’s preferred setup path if available:

```bash
bash setup.sh
```

Or install dashboard dependencies directly:

```bash
pip install -r dashboard/requirements.txt
```

3. Configure environment variables in `.env` or `.secrets`:

```bash
DEST_BOOTSTRAP=pkc-xxxxx.region.provider.confluent.cloud:9092
DEST_API_KEY=your-destination-api-key
DEST_API_SECRET=your-destination-api-secret
DASHBOARD_SOURCE_TOPIC=audit.enriched.v1
```

4. Start the clean dashboard:

```bash
streamlit run dashboard/app_clean.py --server.port 8504
```

5. Open:

```text
http://localhost:8504
```

## 4. First Launch Experience

When the dashboard opens, you should see:

1. Header
   - Product name: `AuditLens Clean`
   - Health pill: shows whether the forwarder looks healthy, degraded, or unavailable.
   - Freshness pill: shows how recently the latest event was seen.
   - Hot-cache pill: shows storage state.

2. Focus Strip
   - Failures count.
   - Deletions count.
   - Storage usage percent.
   - Last update freshness.

3. Overview Cards
   - Loaded Events: how many audit events are currently in the selected window.
   - Failures: failed or denied activity to investigate.
   - Deletions: irreversible operations.
   - Storage Used: SQLite bounded hot-cache pressure.

4. Tabs
   - `Overview`: start here.
   - `Audit Trail`: general event investigation.
   - `Failures`: failure-only view.
   - `Deletions`: deletion-only view.
   - `Advanced`: points users to the legacy dashboard for deeper tools.

5. Sidebar Filters
   - Time Window.
   - Max Events.
   - Actor or service account.
   - Resource name.
   - Action or method.
   - Show routine auth/authz events.

What to look for:

- Health should not be `Unavailable`.
- Freshness should be recent after test actions.
- Focus Strip should make failures obvious.
- Audit Trail should show human-readable summaries, not raw CRNs.

## 5. Guided Demo Flow

### Step 1: Open Dashboard and Check Overview

Open:

```text
http://localhost:8504
```

Start on the `Overview` tab.

What to say:

> AuditLens Clean starts with the signals we usually care about first: failures, deletions, freshness, and storage state. It hides routine audit noise so the dashboard is useful within a few seconds.

What to look for:

- `Failures` in the Focus Strip.
- `Storage` status.
- `Latest event` freshness.
- If failures exist, the CTA: `Investigate failures in the Failures tab.`

### Step 2: Trigger a Real Successful Action

In Confluent Cloud, perform a simple action that should create an audit event. Good examples:

- Create a test topic.
- List compute pools.
- Run or inspect a Flink/ksqlDB job.
- Create and then delete a temporary API key if safe in your environment.

Example with Confluent CLI:

```bash
confluent kafka topic create auditlens-demo-topic --partitions 1
```

What to look for:

- The Focus Strip freshness should update.
- Loaded Events may increase.
- The event should appear in `Audit Trail`.

### Step 3: Go to Audit Trail and Observe the Event

Open the `Audit Trail` tab.

Find the new event. Use the sidebar filters if needed:

- Resource name: `auditlens-demo-topic`
- Actor or service account: `sa-xxxxx`
- Action or method: `CreateTopic`

What to look for:

- Summary like: `sa-xyz created topic 'auditlens-demo-topic'`.
- Action like: `Create topic`.
- Resource like: `Topic: auditlens-demo-topic`.
- No huge CRNs in the default table.
- Raw method and raw resource remain available in Row Details.

### Step 4: Trigger a Failure or Denied Access

Use an actor that lacks permission, or attempt an operation outside its allowed scope.

Examples:

- Try to create a topic with a read-only service account.
- Try to access a cluster/resource where the actor lacks ACL/RBAC.
- Try to run an operation against a topic the actor cannot access.

Example pattern:

```bash
CONFLUENT_API_KEY=<restricted-key> \
CONFLUENT_API_SECRET=<restricted-secret> \
confluent kafka topic create auditlens-denied-topic
```

The exact command depends on your Confluent Cloud setup and permissions.

What to look for:

- Focus Strip `Failures` count should increase.
- The CTA should appear if failures exist.
- A denied or failed event should appear in `Failures`.

### Step 5: Open Failures and Identify the Issue

Go to the `Failures` tab.

What to look for:

- Result should show `Failure` or `Denied`.
- Summary should explain the issue in human language, for example:
  - `sa-xyz failed to create topic 'orders'`
  - `sa-xyz was denied access to cluster 'lkc-123'`
- Actor should show the user or service account.
- Resource should show a concise resource label.

What to say:

> The Failures tab removes the need to scan the full audit stream. It keeps the same filters, but automatically focuses on failed and denied events.

### Step 6: Use Row Details

Select the event in Row Details.

Use this when you need exact evidence:

- Raw method.
- Environment.
- Client ID.
- Request ID.
- Error reason.
- Full raw resource / JSON if available.

What to look for:

- Request ID if you need to correlate with Confluent Cloud support or internal logs.
- Raw method if the summary needs confirmation.
- Error reason if the audit event includes one.

### Step 7: Narrow by Actor or Resource

Use the sidebar filters:

1. Actor or service account:

```text
sa-xxxxx
```

2. Resource name:

```text
auditlens-demo-topic
```

3. Action or method:

```text
CreateTopic
```

What to look for:

- Table narrows to the relevant actor/resource/action.
- Summary remains readable.
- If no rows appear, clear filters or widen the time window.

## 6. Key Behaviors to Understand

### Noise Filtering

By default, AuditLens Clean hides routine successful/neutral events such as:

- successful authentication
- successful authorization
- metadata reads
- `GetKafkaClusters`
- `ListComputePools`
- `GetConnectors`
- `ListConnectors`

It does not hide:

- failures
- denied access
- creations
- deletions
- ACL/RBAC changes
- API key changes

To see everything, enable:

```text
Show routine auth/authz events
```

### Humanized Summaries

AuditLens Clean converts raw audit methods into sentences:

- `GetKafkaClusters` -> `sa-xyz fetched cluster metadata for env-abc`
- `ListComputePools` -> `sa-xyz listed compute pools in env-abc`
- `CreateTopics` -> `sa-xyz created topic 'orders'`
- `DeleteTopics` -> `sa-xyz deleted topic 'orders'`
- denied authorize -> `sa-xyz was denied access to cluster 'lkc-123'`

### Failure CTA

If failures are present, the dashboard shows:

```text
Investigate failures in the Failures tab.
```

Use it as the next step in a live demo.

### Storage Indicators

AuditLens Clean uses SQLite as a bounded hot cache, not a long-term archive.

Storage colors:

- under 60%: green
- 60-79%: yellow
- 80-89%: orange
- 90% and above: red

If storage is elevated, the dashboard can still be useful, but users should understand that older data may be rotated out.

## 7. What To Look For During Demo

1. Overview
   - Freshness updates after real actions.
   - Failures are visible immediately.
   - Storage usage is understandable.

2. Audit Trail
   - New successful action appears.
   - Summary is readable.
   - Resource is summarized.
   - No CRN clutter in the default table.

3. Failures
   - Denied or failed action appears.
   - Actor, action, and resource are clear.
   - Row Details contain raw evidence.

4. Filters
   - Actor filter narrows to one user/service account.
   - Resource filter narrows to topic/cluster/job.
   - Action filter narrows to method/action.

## 8. Common Mistakes and Fixes

### No Data Appears

Try:

1. Increase Time Window to `24 hours` or `72 hours`.
2. Increase Max Events.
3. Clear Actor, Resource, and Action filters.
4. Confirm `DASHBOARD_SOURCE_TOPIC` points to `audit.enriched.v1`.
5. Confirm the forwarder is producing enriched events.
6. Confirm Kafka credentials are correct.

### I Created a Topic, But I Do Not See It

Try:

1. Wait 30-60 seconds.
2. Click `Refresh Data`.
3. Search by the exact topic name.
4. Search by the service account that performed the action.
5. Increase Time Window.

### I See Too Few Authentication Events

This is expected. Routine auth/authz is hidden by default.

Enable:

```text
Show routine auth/authz events
```

Use this only when investigating authentication patterns.

### The Failure Is Not Obvious

Go to the `Failures` tab and inspect:

- Result.
- Summary.
- Actor.
- Resource.
- Row Details.

If the summary is still too generic, use Raw Method and Request ID in Row Details.

### Storage Looks Warning or Critical

AuditLens Clean is a hot-cache dashboard. It is expected to rotate older data when storage pressure rises.

Use the Storage Summary to check:

- Current DB size.
- Max DB size.
- Hot-cache retention.
- Archive enabled status.

## 9. 10-Minute Demo Script

1. Open `http://localhost:8504`.
2. Explain Focus Strip and Overview cards.
3. Create a test topic in Confluent Cloud.
4. Open `Audit Trail`.
5. Filter by the topic name.
6. Show the human-readable summary.
7. Trigger a denied action with a restricted actor.
8. Open `Failures`.
9. Use Row Details to show raw evidence.
10. Clear filters and explain noise filtering/storage indicators.

After this flow, a new user should be able to find and debug a real Confluent Cloud audit failure in under 10 minutes.

