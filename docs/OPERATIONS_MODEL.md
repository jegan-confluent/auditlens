# AuditLens Operations Model

## Offset and Recovery Model

AuditLens foundation uses Kafka consumer-group offsets only.

- No local offset files are part of the supported path.
- Offsets are committed only after:
  - required persistence writes succeed
  - Kafka producer flush completes
  - no new delivery errors are observed for the batch

Delivery semantics are at-least-once.

Implications:

- Docker restart before commit: uncommitted events are replayed
- Kubernetes pod restart before commit: uncommitted events are replayed
- Rebalance during processing: replay can occur if ownership changes before a successful commit
- Partial produce failure: offsets are not committed
- Persistence failure: offsets are not committed
- Duplicate replay: possible after crash or rebalance between downstream success and commit

Duplicate tolerance in the product layer comes from idempotent persistence
upserts keyed by event IDs and alert IDs where available.

## Persistence Model

AuditLens persists recent product data in a lightweight SQLite store:

- enriched events
- high-risk events
- denial summaries
- alerts
- API/export audit logs

This store is for product search, export, and operator continuity. Kafka remains
the system event backbone and replay source of truth.

Foundation tradeoff:

- Docker: suitable with a named volume
- Kubernetes: suitable as a single-writer deployment with a PVC
- Not a multi-replica HA query tier

## API Auth and RBAC

API auth is bearer token or `X-API-Key` based.

Roles:

- `viewer`
- `responder`
- `exporter`
- `admin`

Scope dimensions:

- organization
- environment
- cluster

Exports require `exporter` or `admin`.

## Export Controls

Exports are:

- authenticated
- role-gated
- scope-filtered
- audited with actor, endpoint, filters, and time
- limited by configurable row and time-window caps

## Health and Trust

Health now reflects:

- freshness
- lag
- persistence status
- auth status
- offset commit behavior
- coverage limitations

Probes should use `/health`.
Authenticated clients should use `/api/v1/health`.
