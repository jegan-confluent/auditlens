# Confluent AuditLens v10.0

Real-time Kafka Audit Intelligence Dashboard for Confluent Cloud.

![Dashboard](docs/screenshot.png)

## What You Get

| Service | URL | Description |
|---------|-----|-------------|
| **AuditLens Dashboard** | http://localhost:8503 | Main audit intelligence UI |
| **Grafana** | http://localhost:3000 | Metrics dashboards (admin/admin) |
| **Prometheus** | http://localhost:9090 | Metrics storage |
| **Forwarder Metrics** | http://localhost:8003/metrics | Raw Prometheus metrics |

## Features

- **Real-time audit events** from Confluent Cloud
- **Who did What on Which Resource When** - Complete audit trail
- **Failure detection** - All auth failures, denials, errors
- **Smart filtering** - By criticality, time, user, method
- **Email enrichment** - Auto-resolves user IDs to emails
- **Export** - CSV/JSON export for compliance
- **Anomaly alerts** - Spikes in deletions, failures, API keys

## Quick Start (5 minutes)

```bash
# 1. Clone and setup
git clone <repo-url>
cd audit-forwarder

# 2. Configure credentials (see Prerequisites below)
cp .env.example .env
cp .secrets.example .secrets
# Edit .secrets with your Confluent credentials

# 3. One-click deploy
./scripts/setup.sh

# 4. Verify
./scripts/verify.sh

# 5. Open dashboard
open http://localhost:8503
```

## Prerequisites

### 1. Docker Desktop
```bash
# macOS
brew install --cask docker

# Or download from https://docker.com/products/docker-desktop
```

### 2. Confluent Cloud Credentials

You need credentials for **two clusters**:

| Credential | Description | How to Get |
|------------|-------------|------------|
| `SOURCE_BOOTSTRAP` | Audit log cluster bootstrap | Confluent Cloud → Audit Log Settings |
| `SOURCE_API_KEY` | Audit log cluster API key | Create in Confluent Cloud |
| `SOURCE_API_SECRET` | Audit log cluster API secret | Create in Confluent Cloud |
| `DEST_BOOTSTRAP` | Destination cluster bootstrap | Your Kafka cluster |
| `DEST_API_KEY` | Destination cluster API key | Create in Confluent Cloud |
| `DEST_API_SECRET` | Destination cluster API secret | Create in Confluent Cloud |

### 3. (Optional) Confluent Cloud API Key

For email resolution (user ID → email):

| Credential | Description |
|------------|-------------|
| `CONFLUENT_CLOUD_API_KEY` | Cloud API key (not Kafka!) |
| `CONFLUENT_CLOUD_API_SECRET` | Cloud API secret |

Create at: https://confluent.cloud/settings/api-keys

## Configuration Files

### `.env` - Non-sensitive settings
```bash
# Topics
AUDIT_TOPIC_CRITICAL=audit_events_critical
AUDIT_TOPIC_HIGH=audit_events_high
AUDIT_TOPIC_MEDIUM=audit_events_medium

# Forwarder settings
ENABLE_MULTI_TOPIC_ROUTING=true
AUDIT_ROUTER_DRY_RUN=false
METRICS_PORT=8003
```

### `.secrets` - Sensitive credentials
```bash
# Source (Audit Log Cluster)
SOURCE_BOOTSTRAP=pkc-xxxxx.region.provider.confluent.cloud:9092
SOURCE_API_KEY=XXXXXXXXXX
SOURCE_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Destination (Your Cluster)
DEST_BOOTSTRAP=pkc-yyyyy.region.provider.confluent.cloud:9092
DEST_API_KEY=YYYYYYYYYY
DEST_API_SECRET=yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy

# Optional: For email resolution
CONFLUENT_CLOUD_API_KEY=ZZZZZZZZZZ
CONFLUENT_CLOUD_API_SECRET=zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz
```

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Confluent Cloud    │     │   Audit Forwarder   │     │   AuditLens UI      │
│  Audit Log Cluster  │────▶│   (Python)          │────▶│   (Streamlit)       │
│  (Source)           │     │                     │     │                     │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
                                     │
                                     ▼
                            ┌─────────────────────┐
                            │  Destination Kafka  │
                            │  - audit_events_*   │
                            │  (3 topics by       │
                            │   criticality)      │
                            └─────────────────────┘
```

## Scripts

| Script | Description |
|--------|-------------|
| `./scripts/setup.sh` | Full setup (build + deploy all services) |
| `./scripts/verify.sh` | Health check all services |
| `./scripts/stop.sh` | Stop all services |
| `./scripts/logs.sh` | View forwarder logs |
| `./scripts/rebuild.sh` | Rebuild and redeploy |

## Troubleshooting

### Dashboard shows "No events found"
- Check forwarder logs: `docker logs audit-forwarder --tail 50`
- Verify credentials in `.secrets`
- Ensure destination topics exist and have data

### Forwarder not processing
- Check if source cluster is reachable
- Verify API keys have correct permissions
- Check consumer group lag: `docker logs audit-forwarder | grep Lag`

### Email not showing for users
1. Click "Refresh from API" in sidebar (requires Cloud API key)
2. Or wait - emails auto-cache when events include them

### Port already in use
```bash
# Find and kill process
lsof -i :8503
kill -9 <PID>
```

## Support

- Issues: Open a GitHub issue
- Logs: `docker logs audit-forwarder`
- Metrics: http://localhost:8003/metrics

---
Built with Confluent Kafka, Streamlit, and Python.
