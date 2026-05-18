# AuditLens

Self-hosted audit intelligence for Confluent Cloud. AuditLens consumes your organisation's audit log topic, classifies every event by signal priority (action required / attention / informational / noise), enriches actors with real display names, and surfaces what matters through a real-time dashboard built for security and operations teams.

No data leaves your deployment. No telemetry. No phone-home.

---

## Features

### A. Ingestion & Forwarding

- Kafka consumer reads the Confluent Cloud audit log topic using native consumer group offset tracking
- Bulk-noise short circuit bypasses full pipeline for high-volume routine methods (mds.Authorize, kafka.Fetch, schema-registry.Authentication, etc.) — saves ~83% of processor work
- Two-table storage split routes noise to a lean `audit_events_noise` table and signal events to `audit_events`
- Multi-topic Kafka routing writes classified events to `audit.raw.v1`, `audit.enriched.v1`, `audit.signals.*`, `audit.dlq.v1`
- Event fingerprinting prevents duplicate writes on consumer replay
- Priority queue lanes (critical / normal / bulk / catalog) with configurable sizes
- Resource snapshot extracted at ingest time — type, name, cluster, environment, blast radius hint

### B. Signal Classification

- Four-tier classification: every event is `action_required`, `attention`, `informational`, or `noise`
- Signal reason codes: `denied_access`, `destructive_change`, `failure_detected`, `security_sensitive_change`, `access_changed`, `config_changed`, `auth_noise`, and more
- Internal Confluent topic suppression — `error-lcc-*`, `_confluent*`, `__consumer_*`, `_schemas` classified as noise
- Confluent platform automation detected and classified separately from customer activity
- Schema registry compatibility failures reclassified as `attention` instead of `action_required`
- Plain-English event title and summary derived from method and resource
- Data / control / management plane tagging

### C. Actor & Identity Enrichment

- Manual actor mapping overrides via `actor_mappings.yml` (opt-in) — highest priority in resolution chain
- IAM display name resolution via Confluent Cloud API — resolves principal IDs to names and email (opt-in)
- Actor type detection: human user, service account, or Confluent platform automation
- IP baseline tracking — records source IPs per actor, detects new or unexpected IPs
- Actor activity narrative — per-actor timeline grouped by action category with anomaly detection (off-hours activity, deletion spikes, multi-tool usage)
- Display name backfill — admin endpoint repairs legacy rows retroactively
- Actor Mappings CRUD in Settings UI — view, add, edit, and delete name overrides in-product

### D. Dashboard & UI

- Dashboard with decision banner, signal breakdown, top actors, and hourly event volume chart
- Dashboard cards and actor entries are clickable — navigate to a pre-filtered event list
- Events page with 15+ filter dimensions: time window, signal type, actor, action, resource, result, plane, free-text search
- Event detail drawer — full metadata, auth and authz context, resource snapshot, source IP, raw payload
- Triage controls in every event drawer — mark reviewed, resolved, or escalated with a free-text note
- CSV and JSON event export (up to 10,000 rows per request)
- Hierarchical method filter — three-level Service → Category → Method picker
- Resource Catalog page — searchable inventory of all resources seen in audit events, grouped by type
- System page — consumer lag, DB writer state, pipeline lag, queue depths, storage usage, effective retention
- Settings page — tabs for retention, cold storage, notifications, schema registry, tableflow, actor mappings
- Action alert banner when `action_required` events are present in the current window
- Pipeline lag banner when forwarder → DB write lag is detected
- Recurring patterns panel — surfaces high-frequency (actor, action, resource) combinations automatically

### E. Alerting & Notifications

- Slack, Teams, and custom webhook notifications (opt-in) — configured via `notifications.yml`
- Per-signal-type and per-action-category filter rules
- Alert deduplication and retry on transient failures
- Test notification button in Settings UI
- AlertManager in production compose for metric-based alerting rules

### F. Storage & Retention

- Configurable retention per tier: signal events (default 7d), raw payloads (default 7d), noise events (default 3d)
- Retention values set in Settings UI take effect at runtime — no container restart required
- Automatic daily cleanup loop in the API process
- Cold storage archival to AWS S3 or Google Cloud Storage before deletion (opt-in)
- Archive-before-delete enforced — no silent data loss when cold storage is configured
- Postgres auto-tuning at container start — sets `shared_buffers`, `work_mem`, etc. based on available RAM

### G. Observability

- Forwarder `/health` endpoint reports consumer state, queue depths per lane, write stats, enrichment cache size
- Prometheus metrics on API `/metrics` endpoint
- Grafana pre-provisioned dashboards — processing rate, consumer lag, queue depths, write latency, error rates (started by default)
- Loki + Promtail log aggregation (opt-in, `observability` compose profile)
- Pipeline lag and consumer lag visible on the System page without external tooling

### H. Security

- Bearer token auth with three roles: `viewer`, `responder`, `admin` (opt-in, recommended for any non-local use)
- AES-256-GCM encryption for all secrets stored in the database; never returned in plaintext from any endpoint
- HMAC constant-time token comparison prevents timing attacks
- Content-Security-Policy, X-Frame-Options, Referrer-Policy headers on every response
- Per-IP rate limiting on all endpoints
- All container ports bound to `127.0.0.1` by default — not externally reachable without explicit configuration
- Forwarder container runs with `read_only: true` and `cap_drop: ALL`
- TLS via Caddy automatic certificate management in production compose
- No telemetry — only outbound connections are your Kafka endpoint and optionally `api.confluent.cloud`

### I. Setup & Configuration

- Interactive `./setup` wizard — collects credentials, validates Kafka connectivity, generates `.env` and `.secrets`, starts services
- `make start / stop / restart / status / deploy / migrate / test / help`
- SQLite demo mode with seeded sample events — no Kafka credentials required (opt-in)
- Profile-based Docker Compose — `postgres`, `observability`, `dev` profiles for optional services
- EC2 / VM deployment via `make deploy` (rsync + rebuild)
- All service ports overridable via environment variables

### J. Integrations

- Schema Registry — endpoint and credentials configurable in Settings with live status check (opt-in)
- Tableflow — enable/disable integration and enrich Tableflow audit events (opt-in)
- Confluent Cloud Admin API for IAM lookups (opt-in, requires `CONFLUENT_CLOUD_API_KEY`)

---

## Architecture

The forwarder (`auditlens-forwarder`) consumes the Confluent Cloud audit log topic, runs each event through signal classification and actor enrichment, then writes to PostgreSQL. The FastAPI backend (`auditlens-api`, port 8080) serves `/events`, `/summary`, `/filters`, `/system`, `/settings`, and admin endpoints from that database. The Next.js frontend (`auditlens-frontend`, port 3000) renders the dashboard, events, and settings pages.

Signal classification assigns every event a `signal_type` (`noise` → `informational` → `attention` → `action_required`) and a `signal_reason` code. The dashboard and events page filter and surface events by these signals; `noise` events are stored separately and hidden by default.

---

## Quick Start

**Prerequisites:**
- Python 3.11 or higher
- Docker Desktop with at least 6 GB RAM allocated
- A Confluent Cloud account with access to the audit log topic
- Kafka API Key + Secret with read access to the audit log topic

**Step 1 — Clone:**

```bash
git clone <repo-url>
cd AuditLens
```

**Step 2 — Run the setup wizard:**

```bash
./setup
```

The wizard prompts for your Kafka bootstrap endpoint, API key, and secret; validates connectivity; generates `.env` and `.secrets`; then starts all services.

**Step 3 — Open the dashboard:**

```
http://localhost:3000  (local dev only)
```

You will see the Dashboard page with signal counts, top actors, and the event volume chart. Tables are empty until the forwarder has consumed events from your audit topic.

**No Kafka? SQLite demo mode:**

```bash
scripts/run_sqlite_demo.sh
# Open http://127.0.0.1:3000  (local dev only)
```

See [INSTALL.md](INSTALL.md) for every configuration variable, manual setup steps, and EC2 deployment instructions.

---

## Configuration

The most important variables in `.env` (generated by `./setup`). Full reference in [INSTALL.md](INSTALL.md) and `.env.example`.

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `AUDIT_BOOTSTRAP` | — | Confluent Cloud audit-log Kafka bootstrap server (required) |
| `AUDIT_API_KEY` | — | Kafka API key with read access to the audit log topic (required) |
| `AUDIT_API_SECRET` | — | Kafka API secret (required, stored in `.secrets`) |
| `AUDIT_TOPIC` | `confluent-audit-log-events` | Audit log topic name |
| `GROUP_ID` | `auditlens-forwarder-v1` | Kafka consumer group ID |
| `AUTO_OFFSET_RESET` | `earliest` | `earliest` to replay retained history; `latest` to start from now |
| `DEST_BOOTSTRAP` | — | Destination Kafka cluster for enriched event topics |
| `DEST_API_KEY` | — | API key with write access to destination topics |
| `DATABASE_URL` | SQLite (demo) | Connection string; set to `postgresql+psycopg://...` for product mode |
| `POSTGRES_PASSWORD` | — | PostgreSQL password (required when using `postgres` profile) |
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8080` | URL the browser uses to reach the API |
| `API_AUTH_ENABLED` | `true` | Enable bearer token authentication on all API endpoints |
| `EVENT_RETENTION_DAYS` | `7` | Days of signal events to keep in the database |
| `NOISE_RETENTION_DAYS` | `3` | Days of noise events to keep |
| `IAM_ENRICHMENT_ENABLED` | `false` | Enable actor name resolution via Confluent Cloud IAM API |
| `CONFLUENT_CLOUD_API_KEY` | — | Cloud API key for IAM lookups (required when `IAM_ENRICHMENT_ENABLED=true`) |
| `NOTIFICATIONS_CONFIG` | `notifications.yml` | Path to webhook notification destinations file |
| `ENABLE_NOISE_SHORT_CIRCUIT` | `true` | Bypass full pipeline for bulk-noise events (recommended: keep true) |
| `GRAFANA_ADMIN_PASSWORD` | `changeme` | Grafana admin password — change before any network exposure |

---

## Deployment

For production deployment, use `docker-compose.prod.yml` which adds Caddy as an HTTPS reverse proxy with automatic certificate management and removes the localhost port bindings. See [docs/Deployment_Guide.md](docs/Deployment_Guide.md) for a complete step-by-step guide including EC2 setup and the `make deploy` workflow.

Terraform configurations for AWS, GCP, and Kubernetes are in `deploy/`. These are provided as starting points and have not been tested in production by the maintainers.

---

## Security

- All container ports are bound to `127.0.0.1` by default — no traffic is reachable from other machines without explicit configuration.
- API authentication (`API_AUTH_ENABLED=true`) is required before any external exposure. The setup wizard enables it by default and generates an admin token. See [SECURITY.md](SECURITY.md) for role definitions and token setup.
- `.env` and `.secrets` are gitignored and never committed. Credentials stay on the host where AuditLens is deployed.
- AuditLens has no telemetry and no phone-home. The only outbound connections are to your Confluent Kafka endpoint and to `api.confluent.cloud` when `IAM_ENRICHMENT_ENABLED=true`.

See [SECURITY.md](SECURITY.md) for the full hardening guide, including reverse-proxy configuration, network firewall rules, secrets management, and container hardening notes.

---

## Contributing

Bug reports, feature requests, and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development environment setup, test commands, and commit conventions.

---

## License

No license file is present in this repository. All rights reserved until a license is added.
