# AuditLens Documentation

**Confluent Audit Log Intelligence System v2.1**

---

## Documentation Index

| Document | Description |
|----------|-------------|
| [END_TO_END_FLOW.md](./END_TO_END_FLOW.md) | Complete technical flow from source to dashboard |
| [QUICK_START.md](./QUICK_START.md) | 5-minute setup guide |
| [AUDIT_QUERIES.md](./AUDIT_QUERIES.md) | Common audit log queries and examples |
| [audit-logs-schema.json](./audit-logs-schema.json) | JSON schema for audit events |

## Quick Links

- **Getting Started**: [../GETTING_STARTED.md](../GETTING_STARTED.md)
- **Setup Scripts**: [../scripts/](../scripts/)
- **Classification Rules**: [../config/classification_rules.yaml](../config/classification_rules.yaml)

---

## Architecture Overview

```
Confluent Cloud                          Local Docker
┌─────────────────┐                     ┌─────────────────────────┐
│ Audit Log       │                     │                         │
│ Cluster         │                     │  ┌─────────────────┐    │
│                 │   Forwarder         │  │    Dashboard    │    │
│ confluent-      │──────────────────►  │  │    :8503        │    │
│ audit-log-      │   • Consume         │  └─────────────────┘    │
│ events          │   • Classify        │                         │
│                 │   • Route           │  ┌─────────────────┐    │
├─────────────────┤   • Alert           │  │    Grafana      │    │
│ Your Cluster    │                     │  │    :3000        │    │
│                 │◄──────────────────  │  └─────────────────┘    │
│ • critical      │                     │                         │
│ • high          │                     │  ┌─────────────────┐    │
│ • medium        │                     │  │   Prometheus    │    │
│ • alerts        │                     │  │    :9090        │    │
└─────────────────┘                     │  └─────────────────┘    │
                                        └─────────────────────────┘
```

---

## Key Concepts

### Criticality Levels

| Level | Description | Response Time | Retention |
|-------|-------------|---------------|-----------|
| **CRITICAL** | Destructive operations, security breaches | Immediate alert | 90 days |
| **HIGH** | Credential operations, permission changes | Hours | 30 days |
| **MEDIUM** | Configuration changes, resource creation | Daily review | 14 days |
| **LOW** | Read operations, routine activity | Archive | 7 days |

### Event Classification

Events are classified based on:
1. **Security failures** (UNAUTHENTICATED, PERMISSION_DENIED) → CRITICAL
2. **Denied access** on sensitive operations → CRITICAL
3. **Method name** (200+ pre-classified methods)
4. **Naming patterns** (Delete→HIGH, Create→MEDIUM)

### Multi-Topic Routing

```
Event → Classification → Routing
                           │
                           ├─► audit_events_critical (immediate alerts)
                           ├─► audit_events_high (daily review)
                           ├─► audit_events_medium (weekly audit)
                           └─► DROP or audit_events_low (archive)
```

### Denial Aggregation

High-volume authorization denials are aggregated into summary alerts:
- Window: 60 seconds
- HIGH threshold: 20+ denials
- MEDIUM threshold: 5+ denials

---

## Module Reference

### Core Modules (`src/`)

| Module | Purpose |
|--------|---------|
| `classification/` | Event criticality determination |
| `routing/` | Multi-topic event routing |
| `anomaly/` | Rate-based anomaly detection |
| `alerting/` | Webhook integration (Slack, Teams, PagerDuty) |
| `aggregation/` | Denial event aggregation |
| `metrics/` | Prometheus metrics collection |
| `secrets/` | Multi-backend secrets management |
| `config/` | Pydantic configuration validation |

### Dashboard Modules (`dashboard/`)

| Module | Purpose |
|--------|---------|
| `data/kafka_consumer.py` | Parallel partition reading |
| `data/transformations.py` | DataFrame processing |
| `data/email_cache.py` | LRU cache for email resolution |
| `components/` | Reusable UI components |
| `tabs/` | 10 specialized view tabs |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Non-sensitive configuration (safe to commit) |
| `.secrets` | Sensitive credentials (never commit) |
| `config/classification_rules.yaml` | Customizable classification rules |
| `docker-compose.yml` | Service definitions |
| `prometheus/prometheus.yml` | Prometheus scrape config |

---

## Performance Tuning

### Forwarder Optimization

| Setting | Default | Purpose |
|---------|---------|---------|
| `BATCH_SIZE` | 5000 | Events per consume batch |
| `DROP_LOW_EVENTS` | true | Drop ~89% of events |
| Compression | LZ4 | Fast compression for throughput |

### Dashboard Optimization

| Setting | Default | Purpose |
|---------|---------|---------|
| Cache TTL | 60s | Streamlit data cache |
| Max events | 1500 | Limit per load |
| Email cache | 10000 | LRU cache size |

---

## Troubleshooting

See [GETTING_STARTED.md](../GETTING_STARTED.md#troubleshooting) for common issues.

### Quick Diagnostics

```bash
# Check service health
./scripts/verify.sh

# View forwarder logs
docker logs -f audit-forwarder

# Check metrics
curl http://localhost:8003/metrics | grep audit

# Test Kafka connectivity
docker exec audit-forwarder python -c "
from confluent_kafka import Consumer
c = Consumer({'bootstrap.servers': '\$AUDIT_BOOTSTRAP', ...})
print(c.list_topics())
"
```

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes
4. Run tests: `./scripts/test.sh`
5. Submit PR

---

**Version:** 2.1.0
**Last Updated:** December 12, 2025
