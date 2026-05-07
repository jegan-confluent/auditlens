# AuditLens Config Reference

This is the canonical foundation configuration contract.

## Source Audit Cluster

Required:

- `AUDIT_BOOTSTRAP`
- `AUDIT_API_KEY`
- `AUDIT_API_SECRET`

Optional:

- `AUDIT_TOPIC` default `confluent-audit-log-events`
- `GROUP_ID` default `auditlens-forwarder-v1`
- `AUTO_OFFSET_RESET` default `latest`

## Internal Kafka and Topics

Required:

- `DEST_BOOTSTRAP`
- `DEST_API_KEY`
- `DEST_API_SECRET`

Canonical topics:

- `AUDIT_RAW_TOPIC` default `audit.raw.v1`
- `AUDIT_NORMALIZED_TOPIC` default `audit.normalized.v1`
- `AUDIT_ENRICHED_TOPIC` default `audit.enriched.v1`
- `AUDIT_SIGNALS_DENIALS_TOPIC` default `audit.signals.denials.v1`
- `AUDIT_SIGNALS_HIGHRISK_TOPIC` default `audit.signals.highrisk.v1`
- `AUDIT_ALERTS_TOPIC` default `audit.alerts.v1`
- `DLQ_TOPIC` default `audit.dlq.v1`

Rules:

- Do not reuse the same topic name for multiple contracts.
- Dashboard and API should treat `audit.enriched.v1` and `audit.signals.*` as their primary data sources.

## Alerting

Optional:

- `SLACK_WEBHOOK`
- `ALERT_ON_HIGH_RISK` default `true`
- `ENABLE_DENIAL_AGGREGATION` default `true`
- `DENIAL_AGGREGATOR_WINDOW` default `60`
- `DENIAL_AGGREGATOR_THRESHOLD` default `10`

## Dashboard and API

Dashboard:

- `DASHBOARD_SOURCE_TOPIC` default `audit.enriched.v1`
- `DASHBOARD_DENIALS_TOPIC` default `audit.signals.denials.v1`
- `DASHBOARD_ALERTS_TOPIC` default `audit.alerts.v1`
- `DASHBOARD_FORWARDER_URL` default `http://auditlens-forwarder:8003`
- `DASHBOARD_GRAFANA_URL` default `http://grafana:3000`
- `DASHBOARD_PROMETHEUS_URL` default `http://prometheus:9090`

Forwarder API:

- `METRICS_PORT` default `8003`
- `API_MAX_SEARCH_RESULTS` default `500`
- `API_AUTH_ENABLED` default `false`
- `API_AUTH_TOKEN_FILE` default `/run/secrets/auditlens-api-tokens.json`
- `API_AUTH_TOKENS_JSON` optional inline token config for local/dev only
- `API_EXPORT_MAX_ROWS` default `5000`
- `API_EXPORT_MAX_HOURS` default `168`
- `API_BUFFER_ENRICHED` default `5000`
- `API_BUFFER_SIGNALS` default `1000`

## IAM and Metrics Enrichment

Principal enrichment order:

1. `IAM_MAPPING_FILE` or `ACTOR_IDENTITY_MAP_JSON`
2. `IAM_ENRICHMENT_ENABLED=true` with Confluent Cloud IAM/Admin credentials
3. audit-event-derived identity
4. `METRICS_ENRICHMENT_ENABLED=true` correlation
5. raw fallback principal ID

Configuration:

- `IAM_ENRICHMENT_ENABLED` default `false`
- `IAM_ENRICHMENT_SOURCE` default `manual,confluent_api,metrics`
- `IAM_ENRICHMENT_CACHE_TTL_SECONDS` default `3600`
- `IAM_MAPPING_FILE` default `data/iam_mapping.json`
- `ACTOR_IDENTITY_MAP_JSON` optional inline mapping for local/dev
- `CONFLUENT_CLOUD_API_KEY` optional Cloud IAM/Admin API key
- `CONFLUENT_CLOUD_API_SECRET` optional Cloud IAM/Admin API secret
- `CONFLUENT_API_BASE_URL` default `https://api.confluent.cloud`
- `METRICS_ENRICHMENT_ENABLED` default `false`
- `METRICS_ENRICHMENT_SOURCE` default `correlation`
- `METRICS_ENRICHMENT_CACHE_TTL_SECONDS` default `3600`

Trust model:

- Manual mapping is authoritative.
- Confluent IAM/Admin lookup is authoritative when enabled and successful.
- Audit-event-derived identity is medium confidence.
- Metrics correlation is advisory and must stay low/medium confidence unless labels directly prove identity.
- Raw fallback should preserve the original principal ID and only use a generic unknown label when no usable ID exists.

## Persistence

Required for durable product search/export in the foundation release:

- `PERSISTENCE_ENABLED` default `true`
- `PERSISTENCE_BACKEND` default `sqlite`
- `PERSISTENCE_DB_PATH` default `/var/lib/auditlens/auditlens.db`
- `PERSISTENCE_ENRICHED_RETENTION_DAYS` default `30`
- `PERSISTENCE_SIGNALS_RETENTION_DAYS` default `30`
- `PERSISTENCE_ALERTS_RETENTION_DAYS` default `90`
- `PERSISTENCE_AUDIT_RETENTION_DAYS` default `90`

Foundation note:

- Docker Compose uses a named volume
- Kubernetes uses a PVC and a single forwarder replica
- This is a deliberate foundation tradeoff to keep the product portable and simple

## Replay and Recovery

Optional foundation controls:

- `REPLAY_ENABLED` default `true`
- `REPLAY_DEFAULT_HOURS` default `24`
- `REPLAY_MAX_HOURS` default `720`
- `REPLAY_PUBLISH_DERIVED_TOPICS` default `false`

Rules:

- Replay is a controlled rebuild path, not the steady-state ingestion path.
- Replay rebuilds persistence and signals from Kafka-backed evidence.
- Leave `REPLAY_PUBLISH_DERIVED_TOPICS=false` unless you explicitly want replay to re-emit derived contracts.

## Monitoring

Optional:

- `SCHEMA_REGISTRY_URL`
- `SCHEMA_REGISTRY_KEY`
- `SCHEMA_REGISTRY_SECRET`

Schema Registry is optional for the foundation runtime. The forwarder continues
to run without it.

## Feature Flags

Foundation flags:

- `ENABLE_DENIAL_AGGREGATION`
- `ALERT_ON_HIGH_RISK`

Legacy compatibility only:

- `ENABLE_LEGACY_MULTI_TOPIC_ROUTING`
- `AUDIT_ROUTER_DRY_RUN`

If you are operating the foundation release, leave legacy flags disabled.
