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

- Slack, Teams, PagerDuty, and custom webhook destinations (opt-in) — configured via `notifications.yml` or the Settings UI
- Per-destination digest mode (daily summary) and per-destination rate limiting with burst suppression
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

- Interactive `./setup` wizard with checkpoint / resume — collects credentials, validates Kafka connectivity, generates `.env` and `.secrets`, starts services
- Optional Confluent Cloud API key step lists the Standard / Dedicated clusters in your org for reference (Basic clusters are filtered out) — informational only; the audit-log cluster bootstrap is sourced from the Confluent Cloud audit-logs page
- `make start / stop / restart / status / deploy / migrate / test / help`
- SQLite demo mode with seeded sample events — no Kafka credentials required (opt-in)
- Profile-based Docker Compose — `postgres`, `observability`, `dev` profiles for optional services
- EC2 / VM deployment via `make deploy` (rsync + rebuild)
- All service ports overridable via environment variables

### J. Integrations

- Schema Registry — endpoint and credentials configurable in Settings with live status check (opt-in)
- Tableflow — Iceberg / Delta Lake export with in-UI prerequisite checking; AWS + Azure clusters (Dedicated, Enterprise, or Freight) with Schema Registry enabled
- Confluent Cloud Admin API for IAM lookups and cluster discovery (opt-in, requires `CONFLUENT_CLOUD_API_KEY`)

---

## Architecture

The forwarder (`auditlens-forwarder`, port 8003) consumes the Confluent Cloud audit log topic, runs each event through signal classification and actor enrichment, then writes to PostgreSQL. The FastAPI backend (`auditlens-api`, port 8080) serves `/events`, `/summary`, `/filters`, `/system`, `/settings`, and admin endpoints from that database. The Next.js frontend (`auditlens-frontend`, port 3000) renders the dashboard, events, and settings pages.

Signal classification assigns every event a `signal_type` (`noise` → `informational` → `attention` → `action_required`) and a `signal_reason` code. The dashboard and events page filter and surface events by these signals; `noise` events are stored separately and hidden by default.

---

## Quick Start

**Host prerequisites:**

- Python 3.11 or higher
- Docker Desktop (or Docker Engine + Compose v2) with ≥ 6 GB RAM
- Free local ports: **8003** (forwarder), **8080** (API), **3000** (frontend); plus **9090** Prometheus, **3001** Grafana, **5432** Postgres in the default profile

**What you need before running `./setup`:**

```
┌─────────────────────────────────────────────────────────────────┐
│  What you need before running ./setup                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Audit Log Cluster credentials (SOURCE)                      │
│     These are NOT your regular Kafka cluster credentials.       │
│     Confluent Cloud routes all org audit events to a special    │
│     system cluster that is separate from any cluster you        │
│     created yourself.                                           │
│                                                                 │
│     Find your audit log cluster:                                │
│       → https://confluent.cloud/settings/audit_logs/cli         │
│     You will see:                                               │
│       Cluster   : lkc-xxxxx  (special system cluster)           │
│       Bootstrap : pkc-xxxxx.region.aws.confluent.cloud:9092     │
│       Topic     : confluent-audit-log-events                    │
│                                                                 │
│     Create a Kafka API key scoped to this cluster:              │
│       → Confluent Cloud → Cluster → API Keys → + Add key        │
│       Or: confluent api-key create --resource <lkc-xxxxx>       │
│                                                                 │
│  2. Destination Cluster credentials (where AuditLens writes)    │
│     This is a Standard or Dedicated Confluent Cloud cluster     │
│     you own or create — AuditLens writes processed events here. │
│     Bootstrap : pkc-yyyyy.region.aws.confluent.cloud:9092       │
│     Kafka API key + secret scoped to this cluster               │
│                                                                 │
│  3. Confluent Cloud API key (optional — for reference only)     │
│     A Cloud-scoped key (not a Kafka key) used only to display   │
│     eligible clusters in your org during setup.                 │
│     Create at: https://confluent.cloud/settings/api-keys        │
│     → Select "Cloud" scope (not a specific cluster)             │
│     You can skip this — it is purely informational.             │
└─────────────────────────────────────────────────────────────────┘
```

The wizard explains each of these in turn and validates the source and destination credentials before writing `.env` / `.secrets`.

**Step 1 — Clone:**

```bash
git clone <repo-url>
cd AuditLens
```

**Step 2 — Run the wizard:**

```bash
./setup
```

That's it. **You do not need to edit `.env` by hand.** The wizard collects every credential interactively, validates Kafka connectivity, writes `.env` + `.secrets` for you, and starts the stack. Phase 7 ends with a service-status panel and clickable links for the dashboard, API, and metrics.

**Step 3 — Open the dashboard:**

```
http://localhost:3000
```

You'll see the Dashboard with signal counts, top actors, and the event volume chart. Tables stay empty until the forwarder has consumed events from your audit topic.

**No Kafka? SQLite demo mode:**

```bash
scripts/run_sqlite_demo.sh
# Open http://127.0.0.1:3000
```

---

## What the Setup Wizard Does

`./setup` runs through seven phases. On any failure it saves a checkpoint to `~/.auditlens_setup_checkpoint.json` so a re-run resumes from the last completed phase.

1. **Local prerequisites** — checks Python ≥ 3.11, Docker daemon reachable, Compose v2 available, disk space, required ports free. Offers to install missing tooling on Amazon Linux / Ubuntu / Debian / macOS.
2. **Source cluster** — points you at `https://confluent.cloud/settings/audit_logs/cli` (the only authoritative source for your org's audit-log cluster bootstrap, cluster id, env id, and topic name — the audit-log cluster is system-managed and not auto-discoverable via the public REST API). *(Optional)* If you provide a cloud-scoped Confluent Cloud API key (`https://confluent.cloud/settings/api-keys → Add key → Cloud scope`), the wizard validates it against `GET /org/v2/environments` and prints the Standard / Dedicated clusters in your org for reference — Basic clusters are filtered out because they cannot back audit logs. This listing is **informational only**, not a picker; the audit-log cluster bootstrap still comes from the audit-logs page above. Then collects the Kafka API key + secret for the audit-log cluster and validates connectivity by reading the audit topic.
3. **Destination cluster** — Kafka endpoint + credentials for the cluster that will hold the enriched / signal / DLQ topics. Topics are created if missing.
4. **Schema Registry** *(optional)* — URL + API key + secret; live `GET /subjects` validation.
5. **Product / API settings** — admin token (auto-generated or provided), API port, optional Slack webhook.
6. **Persistence** — SQLite path defaults match the deployment mode (`/app/data/auditlens.db` for Docker, the bind-mount path `./data/forwarder` is pre-created with current-user ownership).
7. **Startup** — `docker compose up -d --build`, then progress-ticked health checks against the forwarder, API, and frontend with a `Still waiting... (Ns elapsed)` heartbeat every 10 seconds. On success the wizard prints a status panel with both `localhost:*` links (for tunnel users) and EC2 public-IP links (IMDSv2-aware, falls back to localhost off-EC2). Successful runs clear the checkpoint.

Secrets generated for you: API admin token, `POSTGRES_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` — all written to `.env` / `.secrets` and on subsequent resumes restored from the checkpoint so the postgres data volume keeps working.

---

## Services & Ports

`docker compose -f docker-compose.prod.yml up -d` brings up:

| Service | Container | Host port | Role |
|---|---|---|---|
| Forwarder | `auditlens-forwarder` | **8003** | Kafka consumer → classification → enrichment → DB writer; serves `/health`, `/metrics` |
| API | `auditlens-api` | **8080** | FastAPI backend; serves `/events`, `/summary`, `/system`, `/settings`, `/health` |
| Frontend | `auditlens-frontend` | **3000** | Next.js dashboard, events, settings |
| Postgres | `auditlens-postgres` | 5432 | Event store + per-tenant settings |
| Caddy | `auditlens-caddy` | 80, 443 | Reverse proxy + automatic TLS (production) |
| Prometheus | `audit-prometheus` | 9090 | Metric scraping |
| Grafana | `audit-grafana` | 3001 | Pre-provisioned dashboards (login: admin / generated `GRAFANA_ADMIN_PASSWORD`) |
| AlertManager | `audit-alertmanager` | 9093 | Metric-based alert routing |
| Postgres exporter | `auditlens-postgres-exporter` | 9187 | Postgres metrics for Prometheus |

All host ports bind to `127.0.0.1` by default. The legacy Streamlit dashboard (formerly 8503) and the standalone landing page (formerly 8088) were removed — the Next.js frontend on 3000 is the only UI.

---

## Updating or Repairing an Existing Install

If your install is broken after a code update (503 errors, missing config, containers not starting) — or you just want to pick up the latest code without re-entering credentials:

```bash
make repair
```

This pulls the latest code, patches any missing `.env` keys against the current `.env.example`, rebuilds containers, and runs migrations — never asks for credentials, never overwrites operator-set values, and is fully idempotent.

If `make repair` fails, run the full wizard:

```bash
./setup
```

You don't need to re-run the wizard to pick up code changes either. Existing `.env` / `.secrets` are preserved across `git pull`. Other lifecycle targets:

```bash
# Pull + rebuild + migrate (same flow as make repair but no .env patch)
make update

# Just check if an update exists, without applying it
make update-check

# Manual equivalent
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build

# EC2 (or any remote deploy target) — one-liner
git pull origin main && docker compose -f docker-compose.prod.yml up -d --build
```

`./setup` itself also self-updates on launch: if the local clone is behind `origin/main`, it pulls and re-execs before the wizard starts. Disable with `--no-update` (or `AUDITLENS_NO_UPDATE=1`) for offline / CI runs. The wizard also runs the same `.env` migration as `make repair` on every invocation, so a re-run is a strict superset of a repair.

`make deploy` does the same flow remotely (rsync + rebuild) — see [docs/Deployment_Guide.md](docs/Deployment_Guide.md). Image updates are controlled rather than automatic: `make update` / `make deploy` pulls and recreates containers on demand. There is no background updater (no watchtower) because uncontrolled image pulls have surprised us on schema-incompatible upstream releases in the past.

### Windows / WSL2

The bash `./setup` wizard cannot run from CMD or PowerShell directly. Install WSL2 once and use the Ubuntu shell for everything:

```powershell
# In PowerShell (run as Administrator), one-time install:
wsl --install
```

Then open Ubuntu from the Start Menu and run:

```bash
git clone https://github.com/jegan-confluent/auditlens
cd auditlens
./setup
```

Docker Desktop for Windows with the WSL2 backend is also required (containers run inside the WSL2 VM). The repo includes a `setup.bat` stub that prints these instructions for anyone who accidentally double-clicks it from Explorer.

---

## Configuration

The most important variables in `.env`. The wizard writes all of these for you; this table is for operators who want to tune after the fact. Full reference in [INSTALL.md](INSTALL.md) and `.env.example`.

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `AUDIT_BOOTSTRAP` | — | Confluent Cloud audit-log Kafka bootstrap (required) |
| `AUDIT_API_KEY` / `AUDIT_API_SECRET` | — | Kafka API credentials for the audit topic (secret lives in `.secrets`) |
| `AUDIT_TOPIC` | `confluent-audit-log-events` | Audit log topic name |
| `GROUP_ID` | `auditlens-forwarder-v1` | Kafka consumer group ID |
| `AUTO_OFFSET_RESET` | `earliest` | `earliest` to replay retained history; `latest` to start from now |
| `DEST_BOOTSTRAP` / `DEST_API_KEY` / `DEST_API_SECRET` | — | Destination Kafka cluster + credentials for enriched / signal / DLQ topics |
| `DATABASE_URL` | `postgresql+psycopg://auditlens:…@postgres:5432/auditlens` | Postgres connection string; SQLite for demo mode only |
| `POSTGRES_PASSWORD` | auto-generated | Postgres admin password (kept stable across resumes) |
| `GRAFANA_ADMIN_PASSWORD` | auto-generated | Grafana login password |
| `API_AUTH_ENABLED` | `true` | Bearer token auth on every API endpoint |
| `EVENT_RETENTION_DAYS` | `7` | Days of signal events to keep |
| `NOISE_RETENTION_DAYS` | `3` | Days of noise events to keep |
| `IAM_ENRICHMENT_ENABLED` | `false` | Resolve actor display names via the Confluent Cloud IAM API |
| `CONFLUENT_CLOUD_API_KEY` / `_SECRET` | — | Cloud-scoped key for IAM lookups + Tableflow + the wizard's cluster picker |
| `SCHEMA_REGISTRY_URL` / `_API_KEY` / `_API_SECRET` | — | Schema Registry endpoint + credentials (required for Tableflow) |

---

## Tableflow

Settings → Tableflow shows a live prerequisite checklist before exposing the enable form. Tableflow has hard requirements on the Confluent side:

- **Cluster type** must be Dedicated, Enterprise, or Freight. Basic and Standard are not supported.
- **Cloud provider** must be AWS or Azure. GCP is not supported.
- **Schema Registry** must be configured — Tableflow does not support schemaless topics.
- **Region** eligibility follows the cloud provider (AWS = all Flink-supported regions, Azure GA).

The UI calls `GET /cmk/v2/clusters/{cluster_id}` with your `CONFLUENT_CLOUD_API_KEY`, evaluates each prerequisite, and only shows the enable form when all four pass. If the cloud API key isn't set, the UI shows a one-line hint and degrades to the form with a banner (the operator can still try, just without verification).

---

## Kubernetes

The interactive setup wizard supports Docker only. If `deployment_mode: kubernetes` is set via `--config-file` the wizard prints a clear "not yet supported" notice and exits cleanly — no half-installed state.

Manual Kubernetes deployment uses the templates in [`deploy/kubernetes/`](deploy/kubernetes/README.md). The README there covers apply order, secret management policy (sealed-secrets / external-secrets / cloud-managed identity), NetworkPolicy notes, and a production checklist. Wizard-driven Kubernetes is on the roadmap; the current templates need registry-push handling, full-stack (api / postgres / frontend / caddy) coverage, and prereq gating in Phase 0 before they're production-ready.

---

## Deployment

For production deployment use `docker-compose.prod.yml`, which adds Caddy as an HTTPS reverse proxy with automatic certificate management and explicitly binds api / frontend to `127.0.0.1:8080` / `127.0.0.1:3000` so health checks work without going through caddy. See [docs/Deployment_Guide.md](docs/Deployment_Guide.md) for the complete EC2 setup and `make deploy` workflow.

Terraform configurations for AWS and GCP are in `deploy/`. They're provided as starting points and have not been tested in production by the maintainers.

---

## Security

- All container ports are bound to `127.0.0.1` by default — no traffic is reachable from other machines without explicit configuration.
- API authentication (`API_AUTH_ENABLED=true`) is required before any external exposure. The wizard enables it by default and generates an admin token.
- `.env` and `.secrets` are gitignored and never committed. Credentials stay on the host where AuditLens is deployed. The wizard refuses to overwrite `.env` if required credentials are empty, so a partial run can't clobber a working config.
- AuditLens has no telemetry and no phone-home. The only outbound connections are to your Confluent Kafka endpoint and (when explicitly enabled) `api.confluent.cloud`.

See [SECURITY.md](SECURITY.md) for the full hardening guide, including reverse-proxy configuration, network firewall rules, secrets management, and container hardening notes.

---

## Contributing

Bug reports, feature requests, and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development environment setup, test commands, and commit conventions.

---

## License

No license file is present in this repository. All rights reserved until a license is added.
