# AuditLens

AuditLens is a Kafka-native audit intelligence foundation for Confluent Cloud audit logs.

It helps teams turn raw audit traffic into something usable:
- searchable audit events
- high-risk activity views
- denial burst summaries
- exportable investigation data
- replay-based rebuild from Kafka evidence

AuditLens is designed as a **single-instance, single-customer deployment model** for the first release.

## What AuditLens Does

AuditLens ingests Confluent Cloud audit logs, preserves replay-safe evidence, normalizes and enriches events, generates explainable signals, and exposes both a dashboard and a small API.

The canonical runtime flow is:

1. Consume audit events from the source audit topic
2. Write replay-safe raw records
3. Normalize and enrich events
4. Classify criticality and generate signals
5. Persist recent product data
6. Expose health, search, alerts, and exports

## Canonical Topic Contracts

- `audit.raw.v1`
- `audit.normalized.v1`
- `audit.enriched.v1`
- `audit.signals.denials.v1`
- `audit.signals.highrisk.v1`
- `audit.alerts.v1`
- `audit.dlq.v1`

## Foundation Scope

Included in this release:
- Kafka-native ingest
- canonical event contracts
- centralized classification
- denial aggregation
- high-risk signals
- API v1
- API authentication
- role-based access control
- export controls
- SQLite product persistence
- replay/rebuild from Kafka
- Docker and Kubernetes deployment
- health, lag, freshness, coverage, and replay visibility

Not included in this release:
- HA / multi-instance coordination
- Flink as default processing path
- Tableflow as default analytics path
- MCP as core product surface
- decision engine / automated response layer

## Main Surfaces

- Open AuditLens: `http://localhost:8088`
- Dashboard: `http://localhost:8503`
- Metrics: `http://localhost:8003/metrics`
- Health/API: `http://localhost:8003/api/v1/health`
- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`

## Guided Install

Recommended first-time flow:

```bash
cp install.template.yaml install.local.yaml
# edit install.local.yaml with your real cluster details and secrets
bash setup.sh --config-file install.local.yaml
```

`install.local.yaml` is intentionally gitignored because it is sensitive. Do not
put real credentials into tracked files.

```bash
bash setup.sh
```

If you prefer prompts instead of a file, interactive mode remains available:

```bash
bash setup.sh
```

The guided installer will:

- validate Docker, Docker Compose, Python, outbound DNS, and local port conflicts first
- read `install.local.yaml` when provided and validate each field before proceeding
- optionally prompt only for missing required values if the config file is incomplete
- validate source audit-log cluster details
- validate destination Kafka details
- optionally validate Schema Registry
- prompt for API auth preference
- validate persistence before startup, including Docker volume writeability for SQLite
- deploy with Docker or Kubernetes
- validate health, auth, persistence, metrics, dashboard reachability, and enriched output

Then open:

- AuditLens landing page: `http://localhost:8088`
- Dashboard: `http://localhost:8503`
- Health/API: `http://localhost:8003/api/v1/health`

Manual `.env` and `.secrets` editing is still available for advanced use, but it is not the primary first-time setup path.

The installer is designed to stop early and clearly for common failure classes:

- Kafka SASL authentication failure
- wrong cluster and API-key pairing
- bad bootstrap endpoint or blocked private networking
- blocked TCP `9092` to Kafka or HTTPS `443` to Schema Registry
- Schema Registry authentication failure
- persistence database open/write failure
- local port conflicts

Use Schema Registry only when your deployment actually depends on it. The core
Kafka-native AuditLens foundation does not require Schema Registry by default.

## Finding Source Audit-Log Details

Start with the Confluent CLI:

```bash
confluent login --save
confluent audit-log describe
```

Use the output to identify the audit-log environment ID, cluster ID, service
account ID, and topic name. Then select the source context if needed:

```bash
confluent environment use <ENVIRONMENT_ID>
confluent kafka cluster use <CLUSTER_ID>
confluent api-key list --resource <CLUSTER_ID>
confluent api-key create --service-account <SERVICE_ACCOUNT_ID> --resource <CLUSTER_ID>
```

Field mapping:

- `source.audit_topic`: topic name from `confluent audit-log describe`
- `source.bootstrap`: Kafka bootstrap endpoint from the audit-log cluster settings, not audit-log describe
- `source.api_key` / `source.api_secret`: Kafka API key and secret for the audit-log cluster
- `source.display_name`: display-only label chosen by you

Manual read check:

```bash
confluent kafka topic consume --from-beginning <AUDIT_LOG_TOPIC>
```

## Required Configuration

Required secrets:

- `AUDIT_BOOTSTRAP`
- `AUDIT_API_KEY`
- `AUDIT_API_SECRET`
- `DEST_BOOTSTRAP`
- `DEST_API_KEY`
- `DEST_API_SECRET`

Required non-secret contract:

- `AUDIT_TOPIC`
- `GROUP_ID`
- `AUDIT_RAW_TOPIC`
- `AUDIT_NORMALIZED_TOPIC`
- `AUDIT_ENRICHED_TOPIC`
- `AUDIT_SIGNALS_DENIALS_TOPIC`
- `AUDIT_SIGNALS_HIGHRISK_TOPIC`
- `AUDIT_ALERTS_TOPIC`
- `DLQ_TOPIC`

See [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md) for the complete grouped contract.

## API v1

AuditLens exposes a minimal API directly from the forwarder:

- `GET /api/v1/health`
- `GET /api/v1/events/search`
- `GET /api/v1/events/high-risk`
- `GET /api/v1/signals/denials`
- `GET /api/v1/export`
- `POST /api/v1/replay`

See [docs/API_V1.md](docs/API_V1.md) for endpoint details.
See [docs/OPERATIONS_MODEL.md](docs/OPERATIONS_MODEL.md) for offset, recovery, persistence, and export behavior.

## Deployment

- Docker Compose: [docker-compose.yml](docker-compose.yml)
- Bootstrap-generated Kubernetes manifests: [deploy/kubernetes](deploy/kubernetes)

The runtime is environment-driven and stateless. Offsets are stored in Kafka
consumer groups, not local files. Recent product search/export is backed by a
lightweight SQLite store on a mounted volume.

Foundation deployment note:

- Docker Compose: persistent named volume
- Kubernetes: single forwarder replica plus PVC
- This keeps the foundation portable and simple, but it is not yet a multi-replica HA query tier
