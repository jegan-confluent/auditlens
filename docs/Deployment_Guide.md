# AuditLens Deployment Guide

## Local SQLite Dev

```bash
DATABASE_URL=sqlite:///./data/auditlens.db ENABLE_DB_WRITER=true docker compose up --build auditlens-forwarder api frontend
```

SQLite is intended for local/demo mode. The default `EVENT_RETENTION_DAYS` is 7.

## Docker Postgres PoC

```bash
DATABASE_URL=postgresql://auditlens:auditlens@postgres:5432/auditlens docker compose --profile postgres up --build postgres auditlens-forwarder api frontend
```

Use this for PoC validation when you want Postgres behavior without managed infrastructure.

## External Postgres Production

```bash
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DB ENABLE_DB_WRITER=true docker compose up --build auditlens-forwarder api frontend
```

Do not start the bundled `postgres` service for managed Postgres. Keep observability optional unless explicitly needed.

## Observability

```bash
docker compose --profile observability up -d prometheus grafana loki promtail
```

Prometheus, Grafana, Loki, and Promtail are profile-gated and do not start by default.

## Troubleshooting

- API readiness: `curl http://localhost:8080/ready`
- API liveness: `curl http://localhost:8080/live`
- DB health and forwarder state: `curl http://localhost:8080/system/status`
- Forwarder health: `curl http://localhost:8003/health`
- Confirm raw payload contract: compare `/events` with `/events/{id}`.
- Confirm deduplication: replay the same source event and verify event count does not increase.

## Tests

```bash
pytest -q backend/tests/test_api.py
pytest -q tests/test_productization.py
npm --prefix frontend install
npm --prefix frontend run build
npm --prefix frontend test
```

