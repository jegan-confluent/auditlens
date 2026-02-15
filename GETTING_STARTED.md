# Getting Started with Confluent AuditLens

**Version 2.1.0** | Real-time Audit Log Intelligence for Confluent Cloud

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start (5 minutes)](#quick-start-5-minutes)
4. [Step-by-Step Setup](#step-by-step-setup)
5. [Configuration Reference](#configuration-reference)
6. [Using the Dashboard](#using-the-dashboard)
7. [Common Operations](#common-operations)
8. [Troubleshooting](#troubleshooting)
9. [Security Best Practices](#security-best-practices)
10. [Architecture](#architecture)

---

## Overview

AuditLens is a real-time audit log intelligence system for Confluent Cloud that:

- **Consumes** audit events from your Confluent Cloud audit log cluster
- **Classifies** events by criticality (CRITICAL, HIGH, MEDIUM, LOW)
- **Routes** events to separate topics based on criticality
- **Visualizes** activity in a real-time dashboard with 12+ views
- **Alerts** on critical security events via Slack

### Key Features

| Feature | Description |
|---------|-------------|
| Multi-topic Routing | Route events to dedicated topics by criticality |
| Real-time Dashboard | 12 tabs including Security Alerts, Deletions, API Keys |
| Smart Classification | 200+ methods classified by risk level |
| Cost Optimization | DROP_LOW_EVENTS reduces throughput by ~89% |
| Enterprise Security | Non-root containers, network segmentation, secrets management |

---

## Prerequisites

### Required

- **Docker Desktop** 4.0+ with Docker Compose v2
  ```bash
  # macOS
  brew install --cask docker

  # Verify installation
  docker --version
  docker compose version
  ```

- **Confluent Cloud Account** with:
  - Access to audit log cluster
  - A destination Kafka cluster
  - Schema Registry enabled

### Optional

- **Confluent CLI** (for topic management)
  ```bash
  brew install confluentinc/tap/cli
  confluent login
  ```

- **Python 3.9+** (for local development only)

---

## Quick Start (5 minutes)

### 1. Clone and enter the project

```bash
cd audit-forwarder
```

### 2. Create your secrets file

```bash
cp .secrets.example .secrets
chmod 600 .secrets
```

### 3. Edit `.secrets` with your credentials

```bash
nano .secrets  # or use your preferred editor
```

Fill in these required values:

```bash
# Audit Log Cluster (source)
AUDIT_BOOTSTRAP=pkc-xxxxx.us-west-2.aws.confluent.cloud:9092
AUDIT_API_KEY=your-audit-api-key
AUDIT_API_SECRET=your-audit-api-secret

# Destination Cluster
DEST_BOOTSTRAP=pkc-yyyyy.region.aws.confluent.cloud:9092
DEST_API_KEY=your-dest-api-key
DEST_API_SECRET=your-dest-api-secret

# Schema Registry
SCHEMA_REGISTRY_URL=https://psrc-xxxxx.region.aws.confluent.cloud
SCHEMA_REGISTRY_KEY=your-sr-key
SCHEMA_REGISTRY_SECRET=your-sr-secret

# Grafana password (required)
GF_ADMIN_PASSWORD=your-secure-password
```

### 4. Run the setup script

```bash
./scripts/setup.sh
```

### 5. Open the dashboard

The setup script automatically opens http://localhost:8503 in your browser.

---

## Step-by-Step Setup

### Step 1: Get Audit Log Cluster Credentials

1. Go to Confluent Cloud → **Organization** → **Audit Log Settings**
2. Note the **Cluster ID** and **Bootstrap Server**
3. Create an API key for the audit log cluster:
   ```bash
   confluent api-key create --resource <audit-cluster-id>
   ```

### Step 2: Get Destination Cluster Credentials

1. Go to Confluent Cloud → Select your environment → Select your cluster
2. Go to **Cluster Settings** → **Endpoints**
3. Note the **Bootstrap Server**
4. Create an API key:
   ```bash
   confluent api-key create --resource <your-cluster-id>
   ```

### Step 3: Get Schema Registry Credentials

> **Important:** Schema Registry uses DIFFERENT API keys than Kafka clusters!

1. Go to Confluent Cloud → Select environment → **Stream Governance**
2. Click **API credentials** tab
3. Click **+ Add key** to create a new key

### Step 4: Create Destination Topics

Create the destination topics in your cluster:

```bash
# Set environment
confluent environment use <env-id>
confluent kafka cluster use <cluster-id>

# Create topics
confluent kafka topic create audit_events_critical --partitions 6
confluent kafka topic create audit_events_high --partitions 6
confluent kafka topic create audit_events_medium --partitions 6
confluent kafka topic create audit_events_flattened --partitions 6
```

### Step 5: Configure and Start

```bash
# Copy and edit secrets
cp .secrets.example .secrets
nano .secrets

# Run setup
./scripts/setup.sh
```

---

## Configuration Reference

### Environment Variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_MULTI_TOPIC_ROUTING` | `true` | Route to criticality-specific topics |
| `DROP_LOW_EVENTS` | `true` | Drop LOW criticality events (saves ~89%) |
| `AUDIT_TOPIC` | `confluent-audit-log-events` | Source audit topic |
| `GROUP_ID` | `audit-forwarder-v2` | Consumer group ID |
| `METRICS_PORT` | `8003` | Prometheus metrics port |

### Secrets (`.secrets`)

| Variable | Required | Description |
|----------|----------|-------------|
| `AUDIT_BOOTSTRAP` | Yes | Audit cluster bootstrap servers |
| `AUDIT_API_KEY` | Yes | Audit cluster API key |
| `AUDIT_API_SECRET` | Yes | Audit cluster API secret |
| `DEST_BOOTSTRAP` | Yes | Destination cluster bootstrap |
| `DEST_API_KEY` | Yes | Destination cluster API key |
| `DEST_API_SECRET` | Yes | Destination cluster API secret |
| `SCHEMA_REGISTRY_URL` | Yes | Schema Registry URL |
| `SCHEMA_REGISTRY_KEY` | Yes | Schema Registry API key |
| `SCHEMA_REGISTRY_SECRET` | Yes | Schema Registry API secret |
| `GF_ADMIN_PASSWORD` | Yes | Grafana admin password |
| `SLACK_WEBHOOK_URL` | No | Slack webhook for alerts |
| `METRICS_AUTH_TOKEN` | No | Token to protect /metrics endpoint |

### Criticality Topics

| Topic | Events |
|-------|--------|
| `audit_events_critical` | Deletions, security breaches, destructive ops |
| `audit_events_high` | API key ops, role bindings, network changes |
| `audit_events_medium` | Config changes, topic creation, connector ops |
| `audit_events_low` | Read operations, metadata, produce/consume |

---

## Using the Dashboard

### Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| AuditLens Dashboard | http://localhost:8503 | None required |
| Grafana | http://localhost:3000 | admin / (your GF_ADMIN_PASSWORD) |
| Prometheus | http://localhost:9090 | None |
| Metrics | http://localhost:8003/metrics | Optional auth |

### Dashboard Tabs

1. **Audit Trail** - All events with filtering and search
2. **Failures** - Authorization denials and errors
3. **Deletions** - All deletion operations
4. **API Keys** - API key create/delete/rotate events
5. **Security** - Security-related events
6. **Details** - Detailed event view with JSON
7. **Analytics** - Charts and statistics
8. **Time Insights** - Temporal patterns
9. **Export** - Export data to CSV
10. **Security Alerts** - Aggregated denial alerts
11. **Consumer Health** - Kafka consumer status
12. **Settings** - Dashboard configuration

### Quick Filters

Use the quick filter buttons to jump to common views:
- **All Events** - No filter
- **Deletions** - `Delete` in method name
- **Critical** - Critical criticality
- **Failures** - Failed authorization

---

## Common Operations

### View Logs

```bash
# Follow forwarder logs
docker logs -f audit-forwarder

# Follow dashboard logs
docker logs -f dashboard

# View last 100 lines
docker logs --tail 100 audit-forwarder
```

### Check Health

```bash
./scripts/verify.sh
```

### Restart Services

```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart audit-forwarder
```

### Stop Services

```bash
# Stop (keep data)
./scripts/stop.sh

# Stop and remove all data
./scripts/stop.sh --all
```

### Update Configuration

```bash
# Edit configuration
nano .env
nano .secrets

# Restart to apply
docker compose restart
```

### Rebuild After Code Changes

```bash
./scripts/setup.sh --full
```

---

## Troubleshooting

### Forwarder not consuming events

```bash
# Check logs
docker logs audit-forwarder --tail 50

# Verify credentials
cat .secrets | grep AUDIT

# Test connectivity
confluent kafka topic consume confluent-audit-log-events \
  --bootstrap <audit-bootstrap> \
  --api-key <key> --api-secret <secret> \
  --from-beginning
```

### Schema Registry errors

```bash
# Verify SR credentials are for Schema Registry, not Kafka
curl -u "$SR_KEY:$SR_SECRET" "$SR_URL/subjects"

# Should return: [] or list of subjects
```

### Dashboard not loading

```bash
# Check container status
docker ps | grep dashboard

# Check logs
docker logs dashboard

# Verify port not in use
lsof -i :8503
```

### Grafana "password required" error

Ensure `GF_ADMIN_PASSWORD` is set in `.secrets`:
```bash
GF_ADMIN_PASSWORD=your-secure-password
```

### High memory usage

Edit `docker-compose.yml` to adjust limits:
```yaml
deploy:
  resources:
    limits:
      memory: 1G  # Reduce from 2G
```

---

## Security Best Practices

### 1. Protect Secrets

```bash
# Ensure proper permissions
chmod 600 .secrets

# Verify not in git
grep ".secrets" .gitignore
```

### 2. Enable Metrics Authentication

Add to `.secrets`:
```bash
METRICS_AUTH_ENABLED=true
METRICS_AUTH_TOKEN=$(openssl rand -base64 32)
```

Update Prometheus config to include the token.

### 3. Use Strong Grafana Password

Never use `admin` or simple passwords:
```bash
GF_ADMIN_PASSWORD=$(openssl rand -base64 24)
```

### 4. Network Segmentation

The default `docker-compose.yml` includes network segmentation:
- `kafka-network` - Kafka communication (external)
- `monitoring` - Internal monitoring
- `frontend-network` - User-facing services

### 5. Regular Updates

```bash
# Pull latest images
docker compose pull

# Rebuild
./scripts/setup.sh --full
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Confluent Cloud                               │
│  ┌──────────────────┐                    ┌──────────────────────┐   │
│  │  Audit Log       │                    │  Your Kafka Cluster  │   │
│  │  Cluster         │                    │  ┌────────────────┐  │   │
│  │  ┌────────────┐  │                    │  │ audit_critical │  │   │
│  │  │ audit-log- │  │                    │  ├────────────────┤  │   │
│  │  │ events     │◄─┼────────────────────┼──│ audit_high     │  │   │
│  │  └────────────┘  │                    │  ├────────────────┤  │   │
│  └──────────────────┘                    │  │ audit_medium   │  │   │
│                                          │  └────────────────┘  │   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Local Docker                                  │
│                                                                      │
│  ┌─────────────────┐      ┌──────────────┐      ┌───────────────┐   │
│  │  Forwarder      │      │  Dashboard   │      │  Prometheus   │   │
│  │  (:8003)        │◄────►│  (:8503)     │◄────►│  (:9090)      │   │
│  │                 │      │              │      │               │   │
│  │  • Consume      │      │  • 12 Tabs   │      │  • Metrics    │   │
│  │  • Classify     │      │  • Filters   │      │  • Alerts     │   │
│  │  • Route        │      │  • Export    │      │               │   │
│  └─────────────────┘      └──────────────┘      └───────────────┘   │
│                                                         │           │
│                                                         ▼           │
│                                                  ┌───────────────┐   │
│                                                  │   Grafana     │   │
│                                                  │   (:3000)     │   │
│                                                  └───────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Port | Purpose |
|-----------|------|---------|
| audit-forwarder | 8003 | Consume, classify, route events |
| dashboard | 8503 | Streamlit UI for visualization |
| prometheus | 9090 | Metrics collection and storage |
| grafana | 3000 | Advanced dashboards and alerting |
| loki | 3100 | Log aggregation |
| promtail | - | Log shipping to Loki |

---

## Need Help?

- **Check logs**: `docker logs -f audit-forwarder`
- **Verify health**: `./scripts/verify.sh`
- **View metrics**: http://localhost:8003/metrics

---

**Happy Auditing!** 🔒
