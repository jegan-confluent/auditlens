# AuditLens v1.0.0

First stable release of AuditLens — Kafka-native audit intelligence for Confluent Cloud.

Your Confluent Cloud organisation generates millions of audit events every day. Most are noise. AuditLens finds what matters — entirely self-hosted, with no data leaving your deployment.

## What's included

### Core platform

- **Forwarder** — stateless Kafka consumer that ingests your audit-log topic, classifies every event in real time, and writes to Postgres + downstream Kafka topics (`audit.enriched.v1`, `audit.signals.v1`, `audit.alerts.v1`, `audit.dlq.v1`).
- **Deterministic signal classification** — every event lands in exactly one of four tiers (Critical / High / Medium / Info). Same event in, same tier out; rules in `src/product/event_signals.py`.
- **Two-table architecture** — signal events go to `audit_events` (full column set), bulk-noise methods (`mds.Authorize`, `kafka.Fetch`, `kafka.Authentication`, …) short-circuit to `audit_events_noise` with the lean column set. ~83% storage saving on the main table.
- **IAM actor enrichment** — `manual_mapping` → IAM cache → audit-event cross-extract → raw ID fallback. Hot-reload `actor_mappings.yml` overrides any time without restart.
- **Schema Registry** — Avro serialization with FORWARD compatibility on enriched topics; subjects filtered to `audit.*` in the UI.

### Security features

- **Auth analytics** — top API keys and source IPs by `kafka.Authentication` volume, 1d / 7d window, cloud-provider classification (AWS / GCP / Azure / Confluent Internal) by IP `/8` prefix.
- **IP-filter denial detection** — `ipfilterAuthorization.{client_ip, resource_group}` extracted at ingest and persisted; classifier fires `ip_filter_deny` before the generic deny cascade so the alert carries the actual blocked IP.
- **Role-binding alerts** — `rbacAuthorization.role` extracted at ingest; privilege-escalation grants of Org/Env/CloudClusterAdmin fire `privilege_escalation` with the role + target in the decision reason.
- **Auth-failure burst detection** — per-actor sliding-window counter (5 failures / 300 s defaults) fires Slack/Teams alerts on burst, separate from the Kafka-stream anomaly detector.
- **Access Transparency** — dedicated view of Confluent personnel access events on Dedicated clusters; operator + business justification per row. Built for DORA / SOX / GDPR / FCA obligations.

### Operations

- **`make doctor`** — single-command end-to-end health check. Seven independent checks (Docker services, forwarder, API, Postgres, dead-tuple bloat, config sanity, domain reachability) with severity-ranked exit codes for cron / CI use.
- **CLI (`auditlens`)** — single-file Python CLI talking to a running deployment over the REST API. Commands: `config`, `events list/get/export`, `stats compare`, `pipeline status/indexes`, `alerts test`, `doctor`.
- **Prometheus + Grafana** — forwarder and API expose `/metrics`; pre-provisioned Grafana dashboards for processing rate, consumer lag, queue depths, write latency, error rates. AlertManager for metric-based alerts.
- **Notifications** — Slack (realtime + digest), Microsoft Teams (Adaptive Card), PagerDuty Events API v2, generic webhook (SSRF-validated, HTTPS-only). Per-destination filters, rate limiting with burst summarisation, cross-destination dedup. Hot-reloaded from `notifications.yml`.
- **MCP server** — token-protected HTTP endpoint exposing AuditLens to LLM agents via the Model Context Protocol.

### Deployment

- **Docker Compose** — every service in `docker-compose.prod.yml`; host ports bind to `127.0.0.1`, Caddy `:80`/`:443` are the only externally-reachable bindings.
- **AWS ALB + Cognito** — internal deployment supports Cognito-fronted access (Google IdP, restricted to a single email domain).
- **AWS Secrets Manager** — opt-in via `AWS_SECRETS_MANAGER_ENABLED=true`; `src/core/secrets.py` overlays HIGH-sensitivity env values with ASM-sourced versions (15 min in-memory TTL). Env-var fallback when ASM is off or boto3 fails.
- **Self-hosted wizard** — `./setup` shell wrapper at repo root; seven-phase, idempotent, resumable from `~/.auditlens_setup_checkpoint.json`.

## Quick start

```bash
git clone https://github.com/jegan-confluent/auditlens AuditLens
cd AuditLens
cp .env.example .env       # edit AUDIT_*/DEST_*/DATABASE_URL/etc
docker compose -f docker-compose.prod.yml up -d
```

Or use the guided wizard:

```bash
./setup
```

Verify with `python3 cli/auditlens.py doctor` and open `http://localhost`.

## Requirements

- Confluent Cloud organisation with audit logs enabled
- Docker Engine + Compose v2 (≥ 6 GB RAM)
- Python 3.10+ (for the CLI and the wizard)

## Known limitations

- **Access Transparency requires a Dedicated cluster** with Access Transparency enabled in your Confluent Cloud organisation, plus Confluent Support to activate operator-access event delivery to your audit log topic.
- **Signal classification thresholds are preset defaults.** Customer-configurable rules are on the roadmap.
- **Frontend test framework (Vitest) not yet included.** Backend has 791+ passing pytest cases; the Next.js frontend ships only a render-smoke today.

## What's next

- **Customer-configurable classification rules** — per-tenant override of the deterministic tier mapping.
- **One-click AMI** — AWS Marketplace AMI for a 5-minute install with no Docker fiddling.
- **Flink windowed analytics** — sliding-window denial rates and cross-environment actor correlation as Flink SQL views over `audit.enriched.v1`.
- **AI-powered audit narrative** — Claude-driven plain-English summaries of the signal stream (opt-in scaffolding already in the codebase).
