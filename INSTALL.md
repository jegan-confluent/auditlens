# Installing AuditLens

## What you need before starting

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

The wizard explains each of these in turn during Phase 1 (source cluster) and Phase 2 (destination cluster). The optional Cloud API key, if provided, is used solely to print the list of Standard / Dedicated clusters in your org for reference — it is not a picker, and your audit-log cluster bootstrap still comes from the audit-logs page in the Confluent Cloud UI.

---

## Prerequisites

**On your machine:**
- Python 3.11 or higher
- Docker Desktop with at least 6 GB RAM allocated
- 20 GB free disk space (PostgreSQL data + Docker images)
- macOS or Linux (Windows: Docker Desktop with WSL2)

**From Confluent Cloud:**
- Access to a Confluent Cloud organisation
- The audit log topic name (usually `confluent-audit-log-events` — visible on `https://confluent.cloud/settings/audit_logs/cli`)
- A Kafka API Key + Secret with read access to the audit log topic on the audit-log cluster
- A Destination Kafka cluster bootstrap + API Key + Secret (for routing enriched events)
- A Cloud API Key + Secret (`CONFLUENT_CLOUD_API_KEY` / `CONFLUENT_CLOUD_API_SECRET`) — optional. Used in Phase 1 to list eligible clusters for reference, and optionally at runtime by IAM display-name enrichment.

---

## Quick Install

```bash
git clone <repo-url>
cd AuditLens
./setup
```

The setup wizard will prompt for your Confluent Cloud credentials, validate access to the audit log topic, generate your `.env` and `.secrets` files, and start all services.

When complete you will see:

```text
✅  AuditLens is ready.
    Open http://localhost:3000
```

*(local dev only)*

---

## What the Setup Wizard Asks

The `./setup` script runs an interactive wizard that collects:

| Prompt | Notes |
|--------|-------|
| Source cluster display name | Label only; default: `Confluent Cloud Audit Logs` |
| Source bootstrap endpoint | e.g. `pkc-xxxxx.us-west-2.aws.confluent.cloud:9092` |
| Source Kafka API key | Read access to the audit log topic |
| Source Kafka API secret | Entered hidden |
| Source audit topic | Default: `confluent-audit-log-events` — confirm with `confluent audit-log describe` |
| Consumer group | Default: `auditlens-forwarder-v1` — controls Kafka-managed offset tracking |
| Offset reset policy | `earliest` replays retained history; `latest` starts from now. Default: `earliest` for first install |
| Destination cluster display name | Label only; default: `AuditLens Internal Kafka` |
| Destination bootstrap endpoint | Where enriched events are written |
| Destination Kafka API key | Write access |
| Destination Kafka API secret | Entered hidden |
| Destination topics exist? | If no, wizard creates the canonical AuditLens topics automatically |
| Enable API authentication | Default: yes. The wizard generates a secure admin token |
| Port selection | Dashboard (8503), metrics (8003), MCP (8080), landing (8088). Accept defaults unless ports conflict |
| Slack/alerting webhook | Optional. Leave blank to skip |

After collecting inputs, the wizard validates connectivity to both clusters, generates `.env`, `.secrets`, and (when API auth is enabled) `secrets/auditlens-bootstrap-admin.token`, then starts all services with `docker compose up -d --build`.

**Your admin token** (for Settings and admin API calls) is written to `secrets/auditlens-bootstrap-admin.token` — keep it safe and do not commit it.

---

## What Gets Installed

### Default services (always started)

| Service (compose name) | What it does | Local port |
|------------------------|-------------|------------|
| `auditlens-forwarder` | Consumes the Confluent audit log topic, classifies and enriches events, writes to PostgreSQL | 8003 (health) |
| `api` | FastAPI backend — serves `/events`, `/summary`, `/filters`, `/system`, `/settings` | 8080 |
| `frontend` | Next.js dashboard (Dashboard, Events, System, Settings pages) | 3000 |
| `prometheus` | Prometheus metrics collection | 9090 |
| `grafana` | Grafana dashboards for forwarder metrics | 3001 |

*(All local ports are bound to `127.0.0.1` — they are not accessible from other machines.)*

Use the service name for `docker compose` commands: `docker compose logs api`, `docker compose restart frontend`.

### Profile-based services

| Service (compose name) | Profile | What it does | Local port |
|------------------------|---------|-------------|------------|
| `postgres` | `postgres`, `dev` | PostgreSQL 16 (product mode) | 5432 |
| `postgres-exporter` | `postgres`, `dev` | Exports Postgres metrics to Prometheus | 9187 |
| `loki` | `observability` | Log aggregation | 3100 |
| `promtail` | `observability` | Log shipper from `./logs/` to Loki | — |

The `./setup` wizard starts the correct profile automatically. To start Postgres manually:

```bash
docker compose --profile postgres up -d postgres
```

To start the observability stack manually:

```bash
docker compose --profile observability up -d prometheus grafana loki promtail
```

---

## Configuration

All configuration lives in `.env` (generated by `./setup`). Reference: `.env.example`.

### Required — Audit Log Source

| Variable | Required | Description |
|----------|----------|-------------|
| `AUDIT_BOOTSTRAP` | Yes | Confluent Cloud audit-log Kafka bootstrap server. Example: `pkc-abc123.us-east-1.aws.confluent.cloud:9092` |
| `AUDIT_API_KEY` | Yes | Kafka API key with read access to the audit log topic |
| `AUDIT_API_SECRET` | Yes | Kafka API secret (stored in `.secrets`) |
| `AUDIT_TOPIC` | Yes (default) | Audit log topic name. Default: `confluent-audit-log-events` |
| `GROUP_ID` | Yes (default) | Kafka consumer group ID. Default: `auditlens-forwarder-v1` |
| `AUTO_OFFSET_RESET` | Yes (default) | `earliest` for first install; `latest` after. Default: `earliest` |

### Required — Destination Cluster

| Variable | Required | Description |
|----------|----------|-------------|
| `DEST_BOOTSTRAP` | Yes | Destination Kafka cluster bootstrap server for enriched event topics |
| `DEST_API_KEY` | Yes | Kafka API key with write access to destination topics |
| `DEST_API_SECRET` | Yes | Kafka API secret (stored in `.secrets`) |

### Required — Database

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_PASSWORD` | Yes (postgres profile) | PostgreSQL password. Must be set before starting `postgres` service |
| `DATABASE_URL` | Yes (default) | Database connection string. PostgreSQL (required) |

### Required — Frontend

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | Yes | URL the browser uses to reach the API. Default: `http://127.0.0.1:8080` |

### Optional — IAM Enrichment

| Variable | Default | Description |
|----------|---------|-------------|
| `IAM_ENRICHMENT_ENABLED` | `false` | Set `true` to resolve actor display names via Confluent Cloud IAM API |
| `CONFLUENT_CLOUD_API_KEY` | — | Cloud API key for IAM + admin lookups |
| `CONFLUENT_CLOUD_API_SECRET` | — | Cloud API secret |
| `IAM_ENRICHMENT_CACHE_TTL_SECONDS` | `3600` | How long IAM results are cached |

### Optional — Notifications

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTIFICATIONS_CONFIG` | `notifications.yml` | Path to the notifications destinations file. Copy `notifications.example.yml` to configure Slack/Teams/webhook |
| `ENABLE_LEGACY_SLACK_WEBHOOK` | `auto` | `auto` disables legacy webhook when `notifications.yml` provides destinations |

### Optional — Actor Mappings

| Variable | Default | Description |
|----------|---------|-------------|
| `ACTOR_MAPPINGS_FILE` | — | Path to `actor_mappings.yml`. Copy `actor_mappings.example.yml` and set this to override cryptic principal IDs with human-readable names |

### Optional — Retention

| Variable | Default | Description |
|----------|---------|-------------|
| `EVENT_RETENTION_DAYS` | `7` | How many days of events to keep in the database |
| `RAW_PAYLOAD_RETENTION_DAYS` | `7` | How many days to keep the original Confluent event JSON |
| `NOISE_RETENTION_DAYS` | `3` | How many days to keep routine noise events |

### Optional — Ports (if defaults conflict)

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_PORT` | `8080` | API service host port |
| `FRONTEND_PORT` | `3000` | Frontend service host port |
| `METRICS_PORT` | `8003` | Forwarder health/metrics host port |
| `POSTGRES_PORT` | `5432` | PostgreSQL host port |

### Optional — Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAFANA_ADMIN_PASSWORD` | `changeme` | Grafana admin password — change before any network exposure |
| `PROMETHEUS_RETENTION_TIME` | `7d` | How long Prometheus retains metrics |
| `PROMETHEUS_RETENTION_SIZE` | `1GB` | Maximum Prometheus storage size |

---

## Deploy to EC2 (Production)

Production uses `docker-compose.prod.yml`, which adds Caddy as an HTTPS reverse proxy and removes the local port bindings so all traffic goes through 80/443.

### First-time EC2 setup

1. Launch an EC2 instance (Amazon Linux 2023 or Ubuntu 22.04), install Docker + Docker Compose v2.
2. Clone the repo on EC2: `git clone <repo-url> ~/AuditLens`
3. Copy your secrets from your local machine **once**:
   ```bash
   scp -i ~/.ssh/auditlens-ec2.pem .env .secrets \
     ec2-user@<EC2-IP>:~/AuditLens/
   ```
   `.env` and `.secrets` are never synced by `make deploy` — copy them manually when credentials change.
4. On EC2, edit `~/AuditLens/.env` to set `AUDITLENS_DOMAIN=` to your domain or elastic IP, and `NEXT_PUBLIC_API_BASE_URL=https://<your-domain>`.

### Deploy workflow

```bash
# 1. Set the EC2 IP (or override on command line)
# Edit Makefile: EC2_IP ?= <your-elastic-ip>
# Or: make deploy EC2_IP=<your-elastic-ip>

# 2. Preview what will be synced (dry run)
make deploy-check

# 3. Deploy
make deploy

# 4. Verify
make health
make ps
```

`make deploy` rsyncs all source files (excluding `.venv`, `node_modules`, `.git`, `.env`, `.secrets`, `logs`, `data`) to EC2 then runs `docker compose -f docker-compose.prod.yml up -d --build`.

### Updating credentials on EC2

```bash
scp -i ~/.ssh/auditlens-ec2.pem .env .secrets \
  ec2-user@<EC2-IP>:~/AuditLens/
ssh -i ~/.ssh/auditlens-ec2.pem ec2-user@<EC2-IP> \
  "cd ~/AuditLens && docker compose -f docker-compose.prod.yml up -d --force-recreate forwarder api"
```

---

## Common Commands

| Command | What it does |
|---------|-------------|
| `make setup` | Run the guided setup wizard |
| `make start` | Start all services (local) |
| `make stop` | Stop all services (local) |
| `make restart` | Stop then start (local) |
| `make status` | Show local container status + API/forwarder health |
| `make deploy` | Rsync to EC2 + rebuild and restart containers |
| `make deploy-check` | Dry-run rsync — shows what would change |
| `make health` | Check EC2 forwarder + API health endpoints |
| `make logs` | Tail EC2 prod container logs |
| `make ps` | Show EC2 container status |
| `make sync` | Rsync files to EC2 without restarting containers |
| `make test` | Run the Python test suite |
| `make migrate` | Apply Alembic database migrations |
| `make help` | List all available commands |

---

## Troubleshooting

### Frontend build fails with npm peer dependency error

The frontend uses recharts, which requires `--legacy-peer-deps` with React 19. If you are building the frontend manually outside Docker, run:

```bash
cd frontend && npm install --legacy-peer-deps
```

Docker builds handle this automatically via the frontend Dockerfile.

### Consumer lag keeps growing

If `make health` shows `Lag:` climbing continuously, the forwarder is not keeping up with the audit topic. Check:

```bash
# Local dev
curl -s http://localhost:8003/health | python3 -m json.tool  # (local dev only)
docker compose logs auditlens-forwarder

# EC2
make health
make logs
```

Most common causes: wrong `AUDIT_BOOTSTRAP`, expired `AUDIT_API_KEY`/`AUDIT_API_SECRET`, or the consumer group was reset to `latest` and there are existing messages.

### Frontend shows blank page or "API unreachable"

Confirm `.env` has:

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8080
```

For EC2/production, this must be your domain or public IP — `127.0.0.1` will not resolve from a browser connecting remotely.

After changing, rebuild the frontend:

```bash
docker compose build frontend && docker compose up -d frontend
```

### Postgres Auto-Tuning

AuditLens automatically tunes Postgres at container start via `infra/postgres/tune.sh`. It reads `/proc/meminfo` and sets `shared_buffers`, `effective_cache_size`, `work_mem`, `maintenance_work_mem`, and `wal_buffers` relative to available RAM. No manual configuration required.

| Instance | RAM | shared_buffers | work_mem | Notes |
|----------|-----|----------------|----------|-------|
| t3.small | 2GB | 512MB | 4MB | Minimum supported |
| t3.medium | 4GB | 1GB | 8MB | Dev/demo |
| t3.large | 8GB | 2GB | 16MB | Recommended |
| t3.xlarge | 16GB | 4GB | 32MB | High volume |
| t3.2xlarge | 32GB | 8GB | 64MB | Enterprise |

Tuning happens automatically at container start. No manual configuration required.

### Postgres disk filling up

The default retention is 7 days for events and 3 days for noise. To reduce storage:

1. Open the dashboard → Settings → Retention tab
2. Lower `Event retention` and `Noise retention` days
3. Click Save

Or set `EVENT_RETENTION_DAYS` and `NOISE_RETENTION_DAYS` in `.env` and restart the forwarder. Cleanup runs automatically every hour (`DB_RETENTION_CLEANUP_INTERVAL_SECONDS=3600`).

### Grafana shows no data

Grafana requires `GRAFANA_ADMIN_PASSWORD` to be set in `.env`. If it was left as `changeme`, update it and recreate the container:

```bash
docker compose up -d --force-recreate grafana
```

Prometheus and Grafana are started by default (`docker compose up -d`) — they do not require the `observability` profile.
