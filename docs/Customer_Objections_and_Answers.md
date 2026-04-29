# Customer Objections and Answers

## 1. Why SQLite if Kafka already stores the events?

- Kafka is the evidence and replay backbone.
- SQLite is the local hot cache for product queries: recent search, export, alert history, denial summaries, and API audit metadata.
- The current product surfaces need indexed reads, pagination, filtering, and bounded latency. Kafka alone is not a practical control-plane query store.
- In the current foundation, Kafka keeps the audit evidence; SQLite keeps the recent operational working set.

## 2. What happens when SQLite disk fills?

- Product persistence fails before Kafka evidence disappears.
- The forwarder can become degraded or fail persistence startup if the volume is completely exhausted.
- `/health` and `/metrics` may become unavailable if the service cannot initialize persistence at all.
- Operators should expect search, export, alert history, and denial summaries to become incomplete or unavailable before Kafka source data is lost.

## 3. Do we lose audit events?

- Not automatically.
- The upstream source topic remains the primary evidence source until its Kafka retention expires.
- What is lost first is local product state in SQLite, not the source audit topic.
- If the required replay window has already expired from Kafka retention, then the missing local window cannot be rebuilt.

## 4. What is the long-term archive strategy?

- The current foundation keeps Kafka as the operational evidence plane and SQLite as the bounded hot cache.
- The intended long-term archive path is Tableflow or an equivalent Confluent-native analytical archive for `audit.raw.v1` and `audit.enriched.v1`.
- SQLite should not become the long-retention archive or the compliance system of record.

## 5. Why not use Kafka as the dashboard database?

- Kafka is optimized for append, replay, and fan-out, not scoped operator search.
- Direct Kafka reads from the UI create inconsistent access control, repeated partition scans, and unpredictable latency.
- The product query path should converge on API plus persistence, with Kafka reserved for evidence transport and replay.

## 6. Why not use Tableflow directly for the dashboard?

- Tableflow is a better fit for long-retention history and broad analytical queries than for the operational hot path.
- Making it the default dashboard backend now would complicate deployment before the control plane is fully stabilized.
- The current foundation should keep the dashboard focused on recent operational state and move long-range history to an archive tier later.

## 7. What is the role of Tableflow?

- Long-term archive for raw and enriched audit events.
- Historical investigations beyond the bounded SQLite window.
- Large-window reporting that should not depend on the local hot cache.
- It should complement Kafka and SQLite, not replace the hot control-plane query path.

## 8. What is the default retention model?

- Source Kafka retention is external and independent of AuditLens.
- Current local SQLite defaults in this repo are configuration-driven:
  - `PERSISTENCE_ENRICHED_RETENTION_DAYS=30`
  - `PERSISTENCE_SIGNALS_RETENTION_DAYS=30`
  - `PERSISTENCE_ALERTS_RETENTION_DAYS=90`
  - `PERSISTENCE_AUDIT_RETENTION_DAYS=90`
- These are local product retention targets, not guaranteed query windows.

## 9. Can customers query last 3 days or last 5 days?

- Yes, if that data still exists in SQLite or can be replayed from Kafka.
- In the current design, 3 to 5 days is a realistic hot-cache use case when disk sizing matches ingest rate.
- Longer windows should move to Tableflow or another archive/query tier rather than overgrowing SQLite.

## 10. How does dynamic retention work?

- It does not today.
- Retention is static and configuration-driven.
- Cleanup removes records older than the configured windows, but it does not automatically shrink the hot cache when disk pressure rises.
- This is a known reliability gap.

## 11. What happens when configured retention cannot fit disk?

- The database can keep growing even though cleanup still runs successfully.
- That happens when all retained data is still inside the configured time window.
- The current runtime now shows exactly that failure mode at warning level: the DB is healthy but larger than the configured maximum.
- Operators need disk budgeting, alerting, and eventually adaptive retention or a larger archive tier.

## 12. How do we prove audit completeness?

- We do not claim absolute completeness today.
- We can show consumer lag, freshness, offset recovery state, persistence health, replay capability, and whether the service is keeping up.
- We cannot prove completeness after source retention expiry or after an ingestion gap that outlasted Kafka retention.
- AuditLens currently provides evidence of pipeline condition, not a formal mathematical proof of completeness.

## 13. What happens during replay?

- Replay rebuilds normalized, enriched, signal, and alert state from Kafka evidence.
- Replay is bounded by what still exists in Kafka retention.
- Replay is the recovery path for lost SQLite state.
- Replay safety still depends on deterministic classification and deterministic derived identifiers; that is not fully complete across every path yet.

## 14. Is dashboard access secured?

- Not fully.
- API authentication and RBAC exist on the forwarder API.
- The Streamlit dashboard is still a weaker surface and is not yet a fully API-backed, product-grade authenticated UI.
- That remains a customer-facing readiness blocker.

## 15. What is not production-ready yet?

- Dashboard auth or a fully API-backed UI path.
- Adaptive retention and bounded hot-cache enforcement.
- Replay dry-run and stronger deterministic replay guarantees.
- Full audit-of-audit coverage for all UI reads.
- Multi-instance coordination and HA.
- Long-term archive integration as the default answer for historical queries.
