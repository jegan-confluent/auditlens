# Offset Management Quick Reference

## One-Liner Decision Tree

```
Need to...
├─ Resume normally? ────────────────────► OFFSET_STRATEGY=committed (default)
├─ Skip backlog after downtime? ───────► OFFSET_STRATEGY=latest
├─ Reprocess all history? ─────────────► OFFSET_STRATEGY=earliest
└─ Start from specific time? ──────────► OFFSET_STRATEGY=timestamp
```

---

## Configuration Cheat Sheet

| Scenario | Configuration | Downtime | Data Loss | Reprocessing |
|----------|---------------|----------|-----------|--------------|
| **Normal restart** | `OFFSET_STRATEGY=committed` | < 1 min | None | None |
| **Fast recovery** | `OFFSET_STRATEGY=latest` | < 1 min | Backlog skipped | None |
| **Full rebuild** | `OFFSET_STRATEGY=earliest` | Hours | None | All data |
| **Last 7 days** | `OFFSET_STRATEGY=timestamp`<br>`OFFSET_HOURS_AGO=168` | Minutes | Configurable | Partial |
| **From Feb 1** | `OFFSET_STRATEGY=timestamp`<br>`OFFSET_TIMESTAMP=2025-02-01T00:00:00Z` | Minutes | Configurable | Partial |

---

## Quick Commands

### Skip Backlog (Fast Recovery)
```bash
echo "OFFSET_STRATEGY=latest" >> .env
docker compose restart audit-forwarder
```

### Reprocess All Events
```bash
echo "OFFSET_STRATEGY=earliest" >> .env
docker compose restart audit-forwarder
```

### Reprocess Last 24 Hours
```bash
cat >> .env <<EOF
OFFSET_STRATEGY=timestamp
OFFSET_HOURS_AGO=24
EOF
docker compose restart audit-forwarder
```

### Reprocess from Specific Date
```bash
cat >> .env <<EOF
OFFSET_STRATEGY=timestamp
OFFSET_TIMESTAMP=2025-02-01T00:00:00Z
EOF
docker compose restart audit-forwarder
```

### Test Before Applying (Dry Run)
```bash
cat >> .env <<EOF
OFFSET_STRATEGY=earliest
OFFSET_DRY_RUN=true
EOF
docker compose restart audit-forwarder
docker logs -f audit-forwarder | grep offset-manager
```

---

## Verification One-Liners

```bash
# Check current consumer lag
docker exec -it audit-forwarder curl -s http://localhost:8003/metrics | grep consumer_lag_total

# View offset reset audit log
docker exec -it audit-forwarder cat /tmp/offset-manager-audit.log

# Monitor catchup progress
watch -n 5 'docker exec audit-forwarder curl -s http://localhost:8003/metrics | grep consumer_lag_total'

# Check forwarder processing rate
docker exec -it audit-forwarder curl -s http://localhost:8003/health | jq .processing_rate
```

---

## Cost Estimator

**Kafka Egress Costs** (at $0.05/GB):

| Topic Size | Strategy | Data Transfer | Estimated Cost |
|------------|----------|---------------|----------------|
| 100 GB | `earliest` | 100 GB | $5.00 |
| 500 GB | `earliest` | 500 GB | $25.00 |
| 100 GB | `timestamp` (7d, 10%) | 10 GB | $0.50 |
| 500 GB | `latest` | 0 GB | $0.00 |

---

## Troubleshooting One-Liners

```bash
# Issue: Offset not resetting
docker compose stop audit-forwarder
docker compose config | grep OFFSET  # Verify config
OFFSET_DRY_RUN=true docker compose up audit-forwarder  # Test

# Issue: Invalid timestamp
# Fix: Use ISO 8601 format
OFFSET_TIMESTAMP=2025-02-01T00:00:00Z  # Correct
# NOT: OFFSET_TIMESTAMP="2025-02-01 00:00:00"  # Wrong

# Issue: Consumer group not found (expected for new deployments)
docker logs audit-forwarder | grep "Consumer group"

# Rollback to normal operation
sed -i '/OFFSET_STRATEGY/d' .env
sed -i '/OFFSET_TIMESTAMP/d' .env
sed -i '/OFFSET_HOURS_AGO/d' .env
docker compose restart audit-forwarder
```

---

## Emergency Procedures

### EMERGENCY: Stop Runaway Reprocessing
```bash
docker compose stop audit-forwarder
echo "OFFSET_STRATEGY=committed" > .env.offset.backup
docker compose up -d audit-forwarder
```

### EMERGENCY: Restore to Last Known Good State
```bash
# Find last committed offset
docker exec -it audit-forwarder curl -s http://localhost:8003/metrics | grep consumer_lag

# Reset to committed
docker compose stop audit-forwarder
sed -i '/OFFSET_/d' .env  # Remove all offset configs
docker compose up -d audit-forwarder
```

---

## When in Doubt

**Default is SAFE**: If you don't set `OFFSET_STRATEGY`, the forwarder uses `committed` (resume normally).

**Test First**: Always use `OFFSET_DRY_RUN=true` before production changes.

**Document Changes**: Create a changelog entry for every offset reset.

---

**Full Documentation**: See [OFFSET_MANAGEMENT.md](./OFFSET_MANAGEMENT.md)
