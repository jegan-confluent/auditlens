# AuditLens — Features

AuditLens is a self-hosted audit intelligence platform for Confluent Cloud. It ingests your org's audit log topic, classifies every event by signal priority, enriches actors with real names, and surfaces what matters through a dashboard built for security and operations teams.

---

## Signal Intelligence

Every event is automatically classified into one of four signal tiers:

- **Action Required** — destructive actions, access failures, denied attempts, unexpected actors. Requires immediate review.
- **Attention** — configuration changes, API key operations, creates with broad blast radius. Review when possible.
- **Informational** — read-only lookups, successful authentications, routine access. Logged for audit trail.
- **Noise** — high-volume background traffic (mds.Authorize, kafka.Fetch, schema-registry.Authentication). Hidden by default, available on demand.

Each signal carries a reason code, risk level, recommended action, and plain-English event title. No raw event reading required.

---

## Actor Enrichment

Raw principal IDs (`User:sa-8nwyn7`, `u-rrk8nmp`) are resolved to human-readable display names via Confluent Cloud IAM lookup:

- Service accounts resolved to their configured names
- Human users resolved to full name and email
- Confluent platform automation identified and labeled separately
- Display names backfilled across historical events
- Actor type badge (human vs service account) on every event
- Configurable actor mapping overrides via YAML for renamed or deprecated principals

Enrichment runs at ingest time. All downstream views — dashboard, events table, export — use resolved names.

---

## Dashboard

The main landing page gives a security narrative for the last 6–24 hours:

- **Decision banner** — one-line summary of critical activity with the most active actor and blast radius assessment
- **Signal breakdown** — count of action_required, attention, and informational events with trend
- **Needs attention** — grouped by category (Deletes, Creates, API Keys, Denials, Access Changes) with actor and timestamp
- **Who was active** — top actors ranked by signal weight, with human/SA badge and event count
- **Event volume chart** — activity over time
- Time window selector: 6h, 12h, 24h, 7d

Every card and actor in the dashboard is clickable and navigates to a pre-filtered Events view.

---

## Events Page

Full audit event stream with filtering, grouping, and detail drill-down.

**Filters:**
- Time window (15m, 1h, 6h, 12h, 24h, 7d, custom)
- Signal type (Action Required, Attention, Informational, All)
- Actor / principal (search by ID, email, or display name)
- Action / method
- Resource
- Action category (Create, Delete, Modify, Data, Security, API Key)
- Result (Success, Failure)
- Is denied
- Impact type
- Free-text search across actor, action, resource, event title
- Hide noise toggle
- Decision mode vs Audit Trail mode

**Event table columns:** Actor, Action, Resource, Signal badge, Risk level, Client tool, Source IP, Timestamp

**Event detail drawer:** Full event metadata including authentication info, authorization info, resource context, request metadata, triage status, recommended action, and raw event fields.

**Recurring patterns:** High-frequency actor/action/resource combinations detected automatically (>10 occurrences in 10 minutes). Suppression and mark-as-expected controls.

---

## Triage Workflow

Every event can be triaged directly from the detail drawer:

- Mark as **Reviewed** — acknowledged, no action needed
- Mark as **Resolved** — investigated and closed
- Mark as **Escalated** — flagged for follow-up
- Add a triage note with free text
- Triage status, actor, and timestamp recorded
- Triage history preserved on the event

---

## Actor Activity Panel

Clicking any actor opens a side panel with:

- Full activity timeline for that actor
- Chapters by action category with event counts and peak signal
- Anomaly detection: off-hours activity, deletion spikes, multi-tool usage
- Plain-English narrative headline ("ResMed Data Pipeline made 142 configuration changes in the last 6h")
- IP baseline history — known IPs vs new/unexpected IPs
- Actor metadata: type, source, enrichment confidence, last seen

---

## IP Baseline Tracking

Per-actor IP baseline built continuously from ingested events:

- Every source IP seen per actor is recorded with occurrence count
- Cloud provider and region detected from IP
- Trusted IP ranges configurable per actor in actor_mappings.yml
- New/unexpected IPs surfaced in the actor activity panel
- Foundation for alert-on-new-IP use cases

---

## Pattern Detection

Automated detection of high-frequency repetitive activity:

- Fires when any (actor, action, resource) tuple exceeds 10 occurrences in 10 minutes
- Persisted in `audit_event_patterns` table
- Surfaced in the Events page (hidden when noise filters active)
- Per-pattern controls: suppress, mark as expected, reactivate
- Catches runaway automation, misconfigured clients, and credential abuse patterns

---

## Notifications

Webhook-based alerting for high-signal events:

- Configurable in `notifications.yml`
- Slack and Teams supported via incoming webhook
- Configurable per signal type and action category
- Test endpoint available from the Settings page
- Alert payload includes actor display name, action, resource, signal type, recommended action, source IP, and timestamp

---

## Settings

In-product configuration for:

- **Retention** — configurable per signal tier (signals, noise, raw payloads)
- **Cold storage** — S3 or GCS archival with provider, bucket, prefix, and credential configuration. Test connection from UI.
- **Schema Registry** — SR endpoint and credentials with live status check
- **Notifications** — webhook test and configuration
- **Tableflow** — enable/disable integration
- **Actor Mappings** — documentation and override guidance

All secrets stored AES-256-GCM encrypted in the database. Never returned in plaintext from any API endpoint.

---

## Cold Storage Archival

Long-term event archival before retention cleanup:

- Supports AWS S3 and Google Cloud Storage
- Configurable bucket, prefix, and credentials
- Events archived before deletion when cold storage is configured
- Archive-before-delete enforced automatically — no silent data loss

---

## Schema Registry Integration

- SR endpoint and credentials configurable in Settings
- Live connection status surfaced in the UI
- Schema-registry audit events enriched with SR context

---

## System Page

Operational visibility into the full pipeline:

- **Consumer status** — connected/disconnected, consumer lag (total and per-partition), processing rate
- **DB writer status** — connected, write errors, last write timestamp, total events
- **DB mode** — postgres
- **Event counts** — total signal events and noise events
- **VACUUM** — manual trigger for database maintenance
- **Forwarder health** — processing rate, queue depths per lane (critical/normal/bulk/catalog), enrichment cache stats, identity counts loaded

---

## Observability Stack

Built-in monitoring for the AuditLens platform itself:

- **Prometheus** — scrapes forwarder `/metrics` endpoint
- **Grafana** — pre-provisioned dashboards for processing rate, consumer lag, queue depths, DB write latency, error rates
- **postgres-exporter** — Postgres metrics exposed to Prometheus
- All services run with resource limits and restart policies

---

## Deployment

- Single `docker compose up` for local development
- `make deploy` for EC2/VM deployment via rsync + Docker
- Auto-migration on container start via `docker_entrypoint.py`
- Nightly database backup with 7-day retention
- Daily automated retention cleanup
- Caddy reverse proxy with automatic HTTPS support
- All ports bound to 127.0.0.1 by default — not externally exposed without explicit configuration

Supported deployment targets: Local (Mac/Linux), EC2/VM, AWS EKS (script, untested), GCP GKE (script, untested), Azure AKS (script, untested).

---

## MCP Server

An MCP (Model Context Protocol) server exposing AuditLens data to AI assistants:

- Query audit events in natural language
- Search by actor, action, time window, signal type
- Analyze authentication failures
- Export findings to S3
- Compatible with Claude Desktop, Claude Code, Cursor, and any MCP-compatible client

---

## Security

- API authentication via bearer token (configurable)
- All secrets encrypted at rest (AES-256-GCM)
- No audit data leaves your infrastructure
- TLS via Caddy (automatic certificate management)
- 0 known CVEs at release (21 resolved before GA)
- Dependency audit on every build

---

## Data Retention

Configurable per tier with defaults:

| Tier | Default Retention |
|------|------------------|
| Signal events (audit_events) | 90 days |
| Noise events (audit_events_noise) | 3 days |
| Raw payloads | 7 days |

Automated cleanup runs daily. Cold storage archival available before deletion.
