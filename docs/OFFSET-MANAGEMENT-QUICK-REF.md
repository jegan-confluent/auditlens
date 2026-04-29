# Offset Management Quick Reference

## Default Behavior (Zero-Config)

**No configuration needed.** Just start the container:

```bash
docker-compose up -d audit-forwarder
```

The system automatically chooses the optimal strategy based on context.

---

## Decision Matrix

| Scenario | Consumer Group | Lag | Decision | Reasoning |
|----------|---------------|-----|----------|-----------|
| **First-time setup** | Doesn't exist | N/A | `latest` | Skip historical backlog |
| **Normal restart** | Exists | < 1 hour (3,600) | `committed` | Small backlog, quick catch-up |
| **Extended downtime (small)** | Exists | < 10,000 | `committed` | Manageable backlog, process all |
| **Extended downtime (medium)** | Exists | 10K - 50K | `timestamp` (24h) | Balance completeness vs speed |
| **Extended downtime (large)** | Exists | > 50,000 | `latest` | Skip old events, focus on current |
| **Consumer group deleted** | Doesn't exist | N/A | `latest` | Intentional reset signal |

---

## Manual Override

Set `OFFSET_STRATEGY` environment variable to override auto-detection:

```bash
# Force latest (skip backlog)
OFFSET_STRATEGY=latest docker-compose up -d

# Force committed (process all pending)
OFFSET_STRATEGY=committed docker-compose up -d

# Force timestamp (last 7 days)
OFFSET_STRATEGY=timestamp OFFSET_HOURS_AGO=168 docker-compose up -d

# Force earliest (reprocess everything - rare use)
OFFSET_STRATEGY=earliest docker-compose up -d
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OFFSET_STRATEGY` | `auto` | Strategy mode: `auto`, `latest`, `committed`, `timestamp`, `earliest` |
| `OFFSET_HOURS_AGO` | `24` | Hours ago for timestamp strategy (e.g., `168` for 7 days) |
| `OFFSET_TIMESTAMP` | - | ISO 8601 timestamp (alternative to OFFSET_HOURS_AGO) |
| `OFFSET_DRY_RUN` | `false` | Set to `true` to preview without applying changes |

---

## Troubleshooting

### View Detection Decision

```bash
# Check logs for detection reasoning
docker logs audit-forwarder 2>&1 | grep "DECISION"

# Example output:
# [smart-offset-detector] [DECISION] Strategy: latest | Reason: First-time setup (no .setup-complete marker)
```

### View Audit Trail

```bash
# See all historical decisions
docker exec audit-forwarder cat /tmp/offset-detection-audit.log

# Example output:
# 2025-02-19T10:30:00Z | GROUP: audit-fwd-v3-feb | STRATEGY: latest | REASON: First-time setup
# 2025-02-19T14:45:00Z | GROUP: audit-fwd-v3-feb | STRATEGY: committed | REASON: Normal restart (lag: 247)
```

### Check Consumer Lag

```bash
# View current lag from forwarder metrics
curl -s http://localhost:8003/metrics | grep consumer_lag

# Example output:
# audit_forwarder_consumer_lag_total 247
# audit_forwarder_consumer_lag{partition="0"} 123
# audit_forwarder_consumer_lag{partition="1"} 124
```

### Reset to First-Time Behavior

```bash
# Delete setup marker
rm -f .setup-complete

# Restart container
docker-compose restart audit-forwarder

# Check logs
docker logs audit-forwarder 2>&1 | grep "First-time setup"
```

---

## Testing

### Test Auto-Detection

```bash
# Run test suite
./scripts/test-smart-offset-detection.sh

# Expected output:
# ✅ PASS: First-time setup strategy
# ✅ PASS: Manual override: latest
# ✅ PASS: Manual override: committed
# ...
```

### Simulate Scenarios

```bash
# Scenario 1: First-time setup
rm -f .setup-complete
docker-compose restart audit-forwarder
# Expected: latest

# Scenario 2: Normal restart (after 10 min)
sleep 600
docker-compose restart audit-forwarder
# Expected: committed

# Scenario 3: Consumer group deleted
docker exec audit-forwarder python3 -c "
from confluent_kafka.admin import AdminClient
import os
admin = AdminClient({
    'bootstrap.servers': os.environ['AUDIT_BOOTSTRAP'],
    'security.protocol': 'SASL_SSL',
    'sasl.mechanism': 'PLAIN',
    'sasl.username': os.environ['AUDIT_API_KEY'],
    'sasl.password': os.environ['AUDIT_API_SECRET'],
})
result = admin.delete_consumer_groups([os.environ['GROUP_ID']], request_timeout=30)
for g, f in result.items():
    print(f'Deleted: {g}')
"
docker-compose restart audit-forwarder
# Expected: latest
```

---

## One-Liners

```bash
# Force skip backlog (fresh start)
OFFSET_STRATEGY=latest docker-compose restart audit-forwarder

# Force process all pending events
OFFSET_STRATEGY=committed docker-compose restart audit-forwarder

# Start from last 48 hours
OFFSET_STRATEGY=timestamp OFFSET_HOURS_AGO=48 docker-compose restart audit-forwarder

# Check what strategy would be chosen (dry run simulation)
docker exec audit-forwarder /app/scripts/smart-offset-detector.sh

# View last 5 detection decisions
docker exec audit-forwarder tail -5 /tmp/offset-detection-audit.log
```

---

## Configuration Comparison

### Before v3.0.1 (Manual)

```yaml
# docker-compose.yml
services:
  audit-forwarder:
    environment:
      # User had to decide and set this
      - OFFSET_STRATEGY=latest
```

**User burden:**
- Read documentation
- Understand offset strategies
- Decide which one fits scenario
- Remember to update on different scenarios

### After v3.0.1 (Auto)

```yaml
# docker-compose.yml
services:
  audit-forwarder:
    environment:
      # Nothing needed - auto-detection!
      # (or explicitly set to "auto")
      - OFFSET_STRATEGY=${OFFSET_STRATEGY:-auto}
```

**User experience:**
- Start container
- System auto-detects right strategy
- Logs explain decision
- Override only if needed

---

## Related Documentation

- [Full Smart Offset Detection Guide](./SMART-OFFSET-DETECTION.md) - Complete technical documentation
- [Offset Manager](../scripts/offset-manager.sh) - Advanced manual management (legacy)
- [Entrypoint](../scripts/entrypoint.sh) - Container startup orchestration

---

**Version:** v3.0.1
**Last Updated:** 2025-02-19
