# Deployment Prerequisites

## 1. Supported Deployment Modes

Supported now:

- Local Docker Compose on a single machine.
- Foundation single-instance deployment using the current forwarder, SQLite persistence, and API/metrics surface.
- Kubernetes manifest generation exists in `src/product/bootstrap.py`, but runtime validation in this repo has been Docker-first.

Not supported as a production claim:

- High availability or multi-instance coordination.
- Shared multi-tenant customer deployment.
- Long-retention production search platform.
- Customer-facing production UI with enforced auth on every surface.

## 2. Minimum Local Machine Requirements

These are conservative estimates based on the current Compose footprint, local SQLite persistence, Streamlit, Prometheus, Grafana, and replay behavior. They are not measured throughput guarantees.

| Resource | Minimum | Recommended | Why |
|---|---:|---:|---|
| CPU | 4 cores | 8 cores | Forwarder, dashboard, Prometheus, Grafana, Loki, and replay compete for CPU. |
| RAM | 8 GB | 16 GB | Docker services plus Streamlit and SQLite cache can exceed small laptop footprints. |
| Disk | 20 GB | 50-100 GB | SQLite/WAL growth and Prometheus TSDB retention already caused local failures. |
| Docker | Required | Required | `docker info` and `docker compose` are assumed by setup. |
| Docker Compose | v2 | v2 | The installer and docs use `docker compose`, not legacy `docker-compose`. |
| Python | 3.11+ recommended | 3.11+ | Installer, local validation, and replay CLI usage assume modern Python. |
| Network | Outbound DNS + TCP 9092/443 | Same | Source/destination Kafka and optional Schema Registry validation require reachable endpoints. |

Operational note:

- Disk must be monitored continuously. SQLite plus WAL growth is an actual observed failure mode in this repo, not a theoretical warning.
- Default storage-pressure alerts now expect at least 1 GB free disk for warning headroom and treat 200 MB free as critical.

## 3. Port Requirements

Default local ports from `docker-compose.yml`:

| Service | Default port | Current bind behavior | Notes |
|---|---:|---|---|
| Landing page | 8088 | `127.0.0.1` only | Intended single local entrypoint. |
| Forwarder health/API/metrics | 8003 | `127.0.0.1` only | Local default now binds to localhost while preserving inter-container communication. |
| Dashboard | 8503 | `127.0.0.1` only | Streamlit UI. No product auth boundary today. |
| Grafana | 3000 | `127.0.0.1` only | Startup now requires a non-default Grafana admin password. |
| Prometheus | 9090 | `127.0.0.1` only | Admin API is disabled by default in local Compose mode. |
| Loki | 3100 | `127.0.0.1` only | Still not required for the basic user workflow, but no longer exposed beyond localhost by default. |
| Promtail | none | not published | Internal only. |
| MCP server | 8080 | future profile only | Not part of the default runtime path. |

Local binding expectation:

- The landing page is correctly localhost-only.
- Forwarder/API, dashboard, Grafana, Prometheus, and Loki now bind to `127.0.0.1` by default in local Compose mode.
- Any non-local exposure should be treated as an explicit deployment change with compensating ingress and auth controls.

## 4. Kafka / Confluent Requirements

Source audit cluster:

- Read access to the source audit topic, default `confluent-audit-log-events`.
- Valid Kafka API key and secret for the audit-log cluster.
- Consumer group permission for the configured group ID.
- The installer validates topic metadata and attempts to consume a bounded sample.

Destination Kafka cluster:

- Reachable bootstrap endpoint.
- Kafka API key and secret with topic create permission or pre-created topics.
- Write permission to all AuditLens destination topics.

Required destination topics:

- `audit.raw.v1`
- `audit.normalized.v1`
- `audit.enriched.v1`
- `audit.signals.denials.v1`
- `audit.signals.highrisk.v1`
- `audit.alerts.v1`
- `audit.dlq.v1`

Schema Registry:

- Optional for local/foundation setup in the current implementation.
- Runtime can continue without it.
- Product-mode documentation already treats Schema Registry enforcement as a target state, not a current hard requirement.

## 5. Storage Requirements

Current persistence model:

- SQLite database at `/var/lib/auditlens/auditlens.db` inside the forwarder container.
- Docker named volume `auditlens_data` backs `/var/lib/auditlens` in Compose.
- SQLite uses WAL mode in `src/product/persistence.py`.

Operational implications:

- WAL growth can consume disk independently of the main DB file.
- Retention cleanup exists in code via `cleanup_expired()`, but operators should not assume storage is self-managing without verification.
- Health and metrics now expose DB size, WAL size, free disk bytes, configured DB max, cleanup status, and checkpoint status.
- Prometheus now loads default SQLite storage alerts for low free disk, oversized DB/WAL, checkpoint failure, and cleanup failure.
- Disk-full conditions break persistence health and can block API search/export correctness.
- If the SQLite volume is lost, control-plane state must be rebuilt from Kafka replay.

## 6. Security Prerequisites

Required before using beyond a single developer laptop:

- Kafka access must use TLS/SASL credentials.
- Generated `.env`, `.secrets`, and token files must remain uncommitted and restricted locally.
- API auth should be enabled when API access is exposed beyond localhost.
- Grafana password is generated by the installer and Grafana startup now fails if the password is missing or set to `admin`.
- Forwarder/API, dashboard, Grafana, Prometheus, and Loki should be constrained to localhost or protected ingress.

Current limitations you must accept explicitly:

- Dashboard is not protected by AuditLens API auth.
- Prometheus admin API is disabled by default in Compose.
- Audit-of-audit access is only captured through the forwarder API path, not dashboard direct Kafka reads.

## 7. Preflight Checklist

Run these before treating a deployment as test-ready:

```bash
docker compose ps
docker system df
curl http://localhost:8088/status
curl http://localhost:8003/health
curl http://localhost:8003/metrics
bash setup.sh --config-file install.local.yaml
```

Additional useful checks:

```bash
docker compose logs --tail=100 auditlens-forwarder
docker compose logs --tail=100 dashboard
docker compose logs --tail=100 auditlens-landing
```

Preflight pass criteria:

- Compose services are running and not crash-looping.
- `/health` returns JSON with `coverage`, `freshness`, `recovery`, and `components`.
- `/metrics` returns Prometheus text.
- Landing `/status` returns HTTP 200.
- Installer completes without Kafka auth, persistence preflight, or health-wait failures.

## 8. Foundation Deployment Stop Conditions

Do not treat the system as safely runnable if any of these are true:

- Source Kafka auth fails or source topic metadata cannot be read.
- Destination Kafka topic create/write validation fails.
- SQLite preflight fails or disk is already near full.
- `/health` is reachable but persistence is degraded.
- Dashboard is the only path being used for investigation in a security-sensitive environment.
- Prometheus/Grafana are exposed on non-localhost interfaces in a shared environment without compensating controls.
