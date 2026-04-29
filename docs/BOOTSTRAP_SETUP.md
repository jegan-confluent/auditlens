# AuditLens Bootstrap Setup

AuditLens now has a first-time bootstrap path designed for the real Confluent
Cloud audit-log model:

- audit logs are in a separate audit-log cluster
- the source topic is `confluent-audit-log-events`
- source consumption requires an API key for the audit-log cluster
- audit logs are retained for seven days by default
- users cannot produce to the source audit topic

## Recommended First-Time Flow

```bash
cp install.template.yaml install.local.yaml
# edit install.local.yaml with real source and destination credentials
bash setup.sh --config-file install.local.yaml
```

`install.local.yaml` is sensitive and gitignored by default. Keep real secrets in
that local file, not in tracked repo files.

Interactive mode is still available:

```bash
bash setup.sh
```

Use the template-file path for repeatable installs and easier reruns.

## What The Template File Contains

- `deployment_mode`
- `source`
  - audit-log cluster display name
  - bootstrap endpoint
  - audit-log Kafka API key and secret
  - `confluent-audit-log-events`
  - consumer group
  - offset reset policy
- `destination`
  - destination cluster display name
  - bootstrap endpoint
  - destination Kafka API key and secret
  - whether the canonical AuditLens topics already exist
- `schema_registry`
  - enable only if your deployment actually uses it
  - URL, API key, and API secret
- `product`
  - API auth mode
  - token file mode
  - dashboard, metrics, and MCP ports
  - optional alerting and Slack webhooks
- `persistence`
  - enabled or disabled
  - backend
  - SQLite DB path

If a config file is passed, the installer uses those values as the primary
input source and only prompts for required values that are missing or still use
placeholders such as `REPLACE_ME`.

## Source vs Destination Cluster Details

- Source cluster:
  - this must be the independent Confluent Cloud audit-log cluster
  - it is read-only from AuditLens
  - the source topic is `confluent-audit-log-events`
  - it requires the Kafka API key and secret for that audit-log cluster
- Destination cluster:
  - this is where AuditLens writes `audit.raw.v1`, `audit.enriched.v1`, signals, alerts, and DLQ topics
  - it requires separate destination Kafka credentials

Common operator mistake:
- using a workload-cluster API key against the audit-log cluster, or vice versa

## How To Find Source Audit-Log Details

Use the Confluent CLI to find the audit-log configuration:

```bash
confluent login --save
confluent audit-log describe
```

Use that output to identify:

- environment ID
- cluster ID
- service account ID
- audit-log topic name

Then select the audit-log context and manage the Kafka API key if needed:

```bash
confluent environment use <ENVIRONMENT_ID>
confluent kafka cluster use <CLUSTER_ID>
confluent api-key list --resource <CLUSTER_ID>
confluent api-key create --service-account <SERVICE_ACCOUNT_ID> --resource <CLUSTER_ID>
```

Installer field mapping:

- `source.audit_topic` -> topic name from `confluent audit-log describe`
- `source.bootstrap` -> Kafka bootstrap endpoint from audit-log cluster settings, not audit-log describe
- `source.api_key` / `source.api_secret` -> Kafka API key and secret scoped to that audit-log cluster
- `source.display_name` -> display-only label for summaries

Manual source read check:

```bash
confluent kafka topic consume --from-beginning <AUDIT_LOG_TOPIC>
```

## Optional Inputs

- Schema Registry URL / key / secret
- metrics port
- dashboard port
- landing page port
- MCP port
- Kubernetes namespace
- persistence DB path
- optional alerting webhook
- optional Slack webhook

## Installer Phases

1. Local prerequisites
   - Docker installed
   - Docker daemon reachable
   - Docker Compose available
   - Python available
   - local directories creatable
   - outbound DNS validated
   - obvious port conflicts detected

2. Source cluster validation
   - bootstrap format
   - DNS resolution
   - TCP reachability to Kafka on `9092`
   - Kafka SASL authentication
   - source topic metadata lookup

3. Destination cluster validation
   - bootstrap format
   - DNS resolution
   - TCP reachability to Kafka on `9092`
   - Kafka SASL authentication
   - canonical topic verification or creation

4. Optional Schema Registry validation
   - URL format
   - DNS resolution
   - HTTPS reachability on `443`
   - authenticated `/subjects` check

5. Product/API validation
   - token generation or token file validation
   - metrics/dashboard/MCP port validation
   - webhook format validation

6. Persistence validation
   - backend support check
   - SQLite path contract check
   - Docker named volume writeability preflight as runtime UID 1000

7. Review before write
   - masked config summary
   - config written only after confirmation

8. Startup and post-start verification
   - startup
   - local landing page
   - `/health`
   - `/api/v1/health`
   - `/metrics`
   - dashboard root
   - enriched output visibility

## Docker Mode

- writes local config files
- runs `docker compose up -d --build`
- waits for health and API readiness on `localhost`
- validates metrics and dashboard reachability

## Kubernetes Mode

- builds local forwarder and dashboard images
- loads them into `kind` or `minikube` automatically when detected
- renders manifests into `deploy/kubernetes/generated/`
- applies namespace, configmap, secret, PVC, forwarder, dashboard, and services
- temporarily port-forwards forwarder and dashboard for readiness validation

Kubernetes note:

- on remote clusters, locally built images must still be pullable by the cluster
- if the cluster cannot pull local image tags, bootstrap fails clearly during rollout

## Secrets Handling

- secrets are written to `.secrets`
- generated API tokens are written to `secrets/`
- bootstrap output masks secrets in console messages
- masked review runs before runtime files are written
- `/health` remains unauthenticated for probe behavior
- `/api/v1/*` is validated with auth when enabled

## End-User Validation

Bootstrap does not stop at config generation. It validates:

- source audit topic readable
- destination topics available
- forwarder health
- authenticated API health
- persistence status
- replay not accidentally running
- enriched output visible on `audit.enriched.v1`

## Troubleshooting

### Persistence initialization failed: unable to open database file

Likely causes:

- SQLite path is outside the mounted Docker volume or PVC
- runtime container UID cannot write the target path
- Docker volume state is unhealthy

What the installer now does:

- fails before startup if the Docker named volume preflight cannot create and remove a test SQLite file as UID 1000

### Kafka SASL authentication failure

Likely causes:

- wrong API key or secret
- wrong bootstrap endpoint
- using the wrong cluster credentials for the audit-log cluster
- using source credentials against the destination cluster or the reverse

What the installer now does:

- validates Kafka auth with metadata lookups before writing config or starting services

### Port blocked or conflict

Likely causes:

- another local process is using the chosen dashboard, metrics, or MCP port
- customer networking blocks access to Confluent endpoints on `9092` or `443`

What the installer now does:

- checks local port conflicts before startup
- checks DNS and TCP reachability before Kafka or Schema Registry auth attempts

### Schema Registry authentication failure

Likely causes:

- wrong URL
- wrong API key or secret
- networking path mismatch

What the installer now does:

- validates the `/subjects` endpoint with auth before continuing

### Private networking caveats

If your Confluent endpoints are reachable only through VPN, private link, or
customer-controlled routing, the installer will stop at the failing DNS or TCP
step instead of starting the stack blindly. Fix networking first, then rerun.
