# AuditLens Foundation Architecture

## Canonical Foundation Release

AuditLens foundation is a Kafka-native audit intelligence product with one
deterministic ingestion path and a small set of stable product-contract topics.

### In Scope

- Ingest raw Confluent Cloud audit logs from a source audit cluster
- Normalize events into a stable search-friendly schema
- Enrich events with centralized criticality classification
- Emit narrow signal streams for high-risk activity and denial aggregation
- Emit a simple alerts stream for operator-facing alert integrations
- Expose operator trust indicators: health, freshness, and lag
- Run portably on Docker Compose and Kubernetes

### Explicitly Postponed

- Decision engine / case lifecycle
- Flink as the default processing path
- Tableflow / Iceberg as the default storage or analytics path
- MCP as a core dependency for the base product workflow
- Lakehouse-first historical architecture

## Canonical Topic Contract

These topics are the foundation contract for AuditLens:

- `audit.raw.v1`
- `audit.normalized.v1`
- `audit.enriched.v1`
- `audit.signals.denials.v1`
- `audit.signals.highrisk.v1`
- `audit.alerts.v1`
- `audit.dlq.v1`

### Topic Intent

- `audit.raw.v1`: loss-minimized copy of consumed source events for replay and
  forensic inspection.
- `audit.normalized.v1`: flattened, searchable event shape with core audit
  fields.
- `audit.enriched.v1`: normalized event plus criticality and product metadata.
- `audit.signals.denials.v1`: grouped denial summaries for noisy authz denials.
- `audit.signals.highrisk.v1`: high-risk or critical enriched events.
- `audit.alerts.v1`: simple operator alert records derived from high-risk
  events or denial bursts.
- `audit.dlq.v1`: parse, validation, or production failure records.

## Foundation Processing Model

1. Consume from one source topic with one consumer group.
2. Produce raw envelope to `audit.raw.v1`.
3. Normalize source event into `audit.normalized.v1`.
4. Enrich using centralized classification into `audit.enriched.v1`.
5. Emit additive signal streams:
   - denial summaries
   - high-risk event stream
6. Emit alert records only for explainable high-signal conditions.
7. Commit offsets only after producer flush succeeds.

## Why Flink Is Not Default

The foundation release does not require cross-stream joins, event-time windows
across multiple independent streams, or advanced correlation. Adding Flink now
would increase deployment friction, support burden, and cloud portability cost
before the base product contract is stable.

Use Flink later when:

- multi-stream correlation is a hard requirement
- stateful incident detection materially improves operator outcomes
- customers already run managed Flink and can justify the operational cost

## Why Tableflow Is Not Default

The foundation release needs operational visibility first, not analytics
infrastructure first. Tableflow becomes justified once long-range history,
large-scale ad hoc analytics, or compliance export workflows require a managed
analytics layer beyond Kafka retention.

Use Tableflow later when:

- 30 to 365 day historical analysis is required
- customers need warehouse/lake integration
- cost of retaining and querying history in Kafka becomes inefficient

## Trust Principles

- The dashboard must show freshness and health, not just event counts.
- Alerting must be explainable and bounded.
- Classification must be centralized.
- The UI must not imply complete coverage when ingestion is delayed.
