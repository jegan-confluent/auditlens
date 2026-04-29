# AuditLens Product Runtime Architecture

AuditLens keeps the existing Kafka-native Streamlit path and adds a product path beside it:

1. `audit_forwarder.py` consumes Confluent audit events from the configured source topic.
2. The forwarder normalizes/classifies events once, emits canonical Kafka topics, and optionally writes normalized rows to the product database when `ENABLE_DB_WRITER=true`.
3. FastAPI reads the product database and exposes event, summary, filter, readiness, and system status endpoints.
4. The Next.js frontend reads FastAPI and becomes the gradual replacement UI.

The legacy Streamlit dashboard remains available and is not removed by this migration.

## Runtime Modes

- SQLite demo mode: `DATABASE_URL=sqlite:///./data/auditlens.db`. This is the default local/demo mode with `EVENT_RETENTION_DAYS=7`.
- Bundled Postgres PoC mode: start Compose with `--profile postgres` and set `DATABASE_URL=postgresql://auditlens:auditlens@postgres:5432/auditlens`.
- External managed Postgres production mode: set `DATABASE_URL` to the managed Postgres connection string. The Compose `postgres` service is not required.
- Observability mode: start Compose with `--profile observability` when Prometheus, Grafana, Loki, and Promtail are needed. They do not start by default.

## Core Contracts

- Canonical topics remain the system-of-record streaming contract.
- Normalization and classification stay centralized in `src/product/event_normalization.py`.
- The product database is a read/query surface for the API and UI.
- Raw audit payloads are retained in the database but are returned only from event detail endpoints, not list endpoints.
- Event deduplication uses `event_fingerprint`, with database uniqueness enforcing replay safety.

