# Smart Offset Detection - Zero-Config Offset Management

## Overview

AuditLens v3.0.1 introduces **intelligent auto-detection** for Kafka offset management. The system automatically chooses the optimal offset strategy based on:

- First-time setup vs restart
- Consumer group existence
- Current consumer lag
- Backlog size and age

**No user input required.** The system makes smart decisions to balance data completeness with catch-up time.

---

## How It Works

### Decision Tree

```
┌─────────────────────────────────────┐
│   Container Starts                  │
│   Check: OFFSET_STRATEGY env var    │
└─────────────────┬───────────────────┘
                  │
          ┌───────┴────────┐
          │ Is it "auto"?  │
          │ (or empty)     │
          └───────┬────────┘
                  │
          ┌───────┴────────┐
          │   YES: Smart   │────▶ Run smart-offset-detector.sh
          │   Detection    │
          └────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────┐
    │ NO: Manual Override             │
    │ Use explicit strategy           │
    └─────────────────────────────────┘
```

### Smart Detection Logic

```
START
  │
  ├─▶ .setup-complete exists?
  │   ├─ NO  ──▶ DECISION: latest (first-time setup)
  │   └─ YES ──▶ Continue
  │
  ├─▶ Consumer group exists?
  │   ├─ NO  ──▶ DECISION: latest (intentional reset)
  │   └─ YES ──▶ Continue
  │
  ├─▶ Calculate total lag
  │
  ├─▶ Lag < 3600 (1 hour)?
  │   ├─ YES ──▶ DECISION: committed (normal restart)
  │   └─ NO  ──▶ Continue
  │
  ├─▶ Lag < 10,000 (small backlog)?
  │   ├─ YES ──▶ DECISION: committed (process all)
  │   └─ NO  ──▶ Continue
  │
  ├─▶ Lag < 50,000 (medium backlog)?
  │   ├─ YES ──▶ DECISION: timestamp (last 24h)
  │   └─ NO  ──▶ Continue
  │
  └─▶ Lag > 50,000 (large backlog)?
      └─ YES ──▶ DECISION: latest (skip old events)
```

---

## Scenarios Explained

### Scenario 1: First-Time Setup

**Detection:**
- `.setup-complete` marker file does NOT exist

**Decision:** `latest`

**Reasoning:**
- New deployments shouldn't process months of historical audit logs
- Reduces initial catch-up time to zero
- Focuses on real-time monitoring from deployment forward

**Actions:**
1. Creates `.setup-complete` marker with metadata:
   ```
   First setup: 2025-02-19T10:30:00Z
   Consumer Group: audit-fwd-v3-feb
   Initial Strategy: latest (skip historical backlog)
   ```
2. Consumer starts from newest events

**Logs:**
```
[smart-offset-detector] [DECISION] Strategy: latest | Reason: First-time setup (no .setup-complete marker)
[entrypoint] Auto-detected strategy: latest
[entrypoint] → Forwarder will skip backlog and start from newest events
```

---

### Scenario 2: Normal Restart

**Detection:**
- `.setup-complete` exists
- Consumer group exists
- Total lag < 3,600 messages (~1 hour worth)

**Decision:** `committed`

**Reasoning:**
- Service was recently stopped/restarted
- Small backlog means quick catch-up
- Process all pending events for data completeness

**Actions:**
1. No offset reset needed
2. Consumer resumes from last committed offset

**Logs:**
```
[smart-offset-detector] Total consumer lag: 247 messages
[smart-offset-detector] [DECISION] Strategy: committed | Reason: Normal restart (lag: 247 < 3600 threshold)
[entrypoint] Auto-detected strategy: committed
[entrypoint] → Forwarder will resume from last committed offset
```

---

### Scenario 3: Extended Downtime - Small Backlog

**Detection:**
- `.setup-complete` exists
- Consumer group exists
- Total lag 3,600 - 10,000 messages

**Decision:** `committed`

**Reasoning:**
- Downtime was ~1-3 hours
- Backlog is manageable (10K events ≈ 3 hours at typical audit event rate)
- Process all events for complete audit trail

**Actions:**
1. No offset reset needed
2. Consumer resumes from last committed offset

**Logs:**
```
[smart-offset-detector] Total consumer lag: 8,450 messages
[smart-offset-detector] [DECISION] Strategy: committed | Reason: Small backlog (lag: 8450 < 10000) - process all
[entrypoint] Auto-detected strategy: committed
[entrypoint] → Forwarder will resume from last committed offset
```

---

### Scenario 4: Extended Downtime - Medium Backlog

**Detection:**
- `.setup-complete` exists
- Consumer group exists
- Total lag 10,000 - 50,000 messages

**Decision:** `timestamp` (last 24 hours)

**Reasoning:**
- Downtime was 3-14 hours
- Processing 50K events would take significant time
- Focus on recent events (last 24h) for relevant security insights
- Older events are less actionable

**Actions:**
1. Deletes consumer group
2. Creates timestamp marker: `/tmp/offset_reset_timestamp` with timestamp from 24h ago
3. Consumer seeks to timestamp on startup

**Logs:**
```
[smart-offset-detector] Total consumer lag: 32,000 messages
[smart-offset-detector] [DECISION] Strategy: timestamp | Reason: Medium backlog (lag: 32000 < 50000) - last 24h
[entrypoint] Auto-detected strategy: timestamp
[entrypoint] → Forwarder will start from 24h ago
[entrypoint] Timestamp marker created: 1708412400000ms
```

---

### Scenario 5: Extended Downtime - Large Backlog

**Detection:**
- `.setup-complete` exists
- Consumer group exists
- Total lag > 50,000 messages

**Decision:** `latest`

**Reasoning:**
- Downtime was >14 hours or significant event burst occurred
- Processing 50K+ events would delay real-time monitoring
- Old audit events lose relevance over time
- Better to skip backlog and focus on current activity

**Actions:**
1. Deletes consumer group
2. Consumer starts from newest events

**Logs:**
```
[smart-offset-detector] Total consumer lag: 125,000 messages
[smart-offset-detector] [DECISION] Strategy: latest | Reason: Large backlog (lag: 125000 > 50000) - skip old events
[entrypoint] Auto-detected strategy: latest
[entrypoint] → Forwarder will skip backlog and start from newest events
```

---

### Scenario 6: Consumer Group Deleted

**Detection:**
- `.setup-complete` exists (not first-time setup)
- Consumer group does NOT exist

**Decision:** `latest`

**Reasoning:**
- User explicitly deleted the consumer group
- Deletion signals intentional reset
- Start fresh from current events

**Actions:**
1. No group to delete (already gone)
2. Consumer starts from newest events

**Logs:**
```
[smart-offset-detector] [DECISION] Strategy: latest | Reason: Consumer group deleted (intentional reset signal)
[entrypoint] Auto-detected strategy: latest
[entrypoint] → Forwarder will skip backlog and start from newest events
```

---

## Configuration

### Default Behavior (Zero-Config)

**No environment variables needed.**

The system automatically detects the right strategy.

```bash
# Just start the container - that's it!
docker-compose up -d audit-forwarder
```

---

### Manual Override (Advanced)

If you need to override the auto-detection, set `OFFSET_STRATEGY` explicitly:

```bash
# Force latest (skip backlog)
OFFSET_STRATEGY=latest docker-compose up -d

# Force committed (process all pending events)
OFFSET_STRATEGY=committed docker-compose up -d

# Force timestamp (last 7 days)
OFFSET_STRATEGY=timestamp OFFSET_HOURS_AGO=168 docker-compose up -d

# Force earliest (reprocess everything - use with caution!)
OFFSET_STRATEGY=earliest docker-compose up -d
```

**Available Strategies:**
- `auto` - Smart detection (default if not set)
- `latest` - Skip backlog, start from newest
- `committed` - Resume from last committed offset
- `timestamp` - Start from specific time (requires `OFFSET_TIMESTAMP` or `OFFSET_HOURS_AGO`)
- `earliest` - Reprocess all events from beginning

---

## Thresholds and Tuning

### Detection Thresholds

Default values in `smart-offset-detector.sh`:

| Threshold | Value | Meaning |
|-----------|-------|---------|
| `LAG_THRESHOLD_1H` | 3,600 | Normal restart - lag < 1 hour worth |
| `LAG_THRESHOLD_SMALL` | 10,000 | Small backlog - process all |
| `LAG_THRESHOLD_MEDIUM` | 50,000 | Medium backlog - use timestamp |
| `TIMESTAMP_LOOKBACK_HOURS` | 24 | For medium/large backlogs, start from 24h ago |

### Customizing Thresholds

Edit `scripts/smart-offset-detector.sh` if your environment has different characteristics:

```bash
# Example: High-volume environment (10 events/sec average)
LAG_THRESHOLD_1H=36000        # 1 hour at 10/sec
LAG_THRESHOLD_SMALL=100000    # ~3 hours backlog
LAG_THRESHOLD_MEDIUM=500000   # ~14 hours backlog
```

---

## Audit Trail

All detection decisions are logged to `/tmp/offset-detection-audit.log`:

```
2025-02-19T10:30:00Z | GROUP: audit-fwd-v3-feb | STRATEGY: latest | REASON: First-time setup (no .setup-complete marker)
2025-02-19T14:45:00Z | GROUP: audit-fwd-v3-feb | STRATEGY: committed | REASON: Normal restart (lag: 247 < 3600 threshold)
2025-02-20T08:00:00Z | GROUP: audit-fwd-v3-feb | STRATEGY: timestamp | REASON: Medium backlog (lag: 32000 < 50000) - last 24h
```

View audit trail:
```bash
docker exec audit-forwarder cat /tmp/offset-detection-audit.log
```

---

## Troubleshooting

### Detection Fails

If smart detection fails (network issues, API errors), the system falls back to **safe default: `latest`**.

**Logs:**
```
[smart-offset-detector] [ERROR] Failed to connect to Kafka cluster
[smart-offset-detector] [WARN] Falling back to safe default: latest
[entrypoint] WARNING: Detection failed, using safe default: latest
```

### Consumer Group Lag Check Fails

If lag calculation fails (timeout, permission issues), lag is assumed to be `0` and strategy becomes `committed`.

**Logs:**
```
[smart-offset-detector] ERROR: Could not calculate lag: timeout
[smart-offset-detector] [WARN] Assuming lag = 0 (safe default)
[smart-offset-detector] [DECISION] Strategy: committed | Reason: Normal restart (lag: 0 < 3600 threshold)
```

### .setup-complete Marker Missing

If the marker file is accidentally deleted, the system treats it as first-time setup and uses `latest`.

**Recovery:**
```bash
# Recreate marker manually to prevent "first-time setup" behavior
docker exec -it audit-forwarder bash
cat > /app/.setup-complete <<EOF
First setup: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Consumer Group: ${GROUP_ID}
Initial Strategy: latest (skip historical backlog)
EOF
```

---

## Benefits

### Before (Manual Configuration)

**User burden:**
1. Read documentation to understand offset strategies
2. Decide which strategy fits their scenario
3. Set `OFFSET_STRATEGY` environment variable
4. Restart container
5. Monitor logs to verify correct behavior

**Risks:**
- Wrong strategy choice → data loss or slow catch-up
- Forgotten configuration → defaults to generic behavior
- No context-aware decision making

### After (Smart Detection)

**User experience:**
1. Start container
2. System automatically chooses right strategy
3. Logs clearly explain decision

**Benefits:**
- Zero cognitive load
- Context-aware decisions
- Auditable reasoning
- Safe fallbacks
- Gradual degradation on errors

---

## Testing

### Simulate Scenarios

```bash
# Test 1: First-time setup
rm -f .setup-complete
docker-compose restart audit-forwarder
# Expected: latest

# Test 2: Normal restart (small lag)
# Let system run for 10 minutes, then restart
docker-compose restart audit-forwarder
# Expected: committed

# Test 3: Consumer group deleted
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
# Expected: latest (reset signal)

# Test 4: Manual override
OFFSET_STRATEGY=earliest docker-compose restart audit-forwarder
# Expected: earliest (manual override)
```

### Verify Detection

```bash
# View detection logs
docker logs audit-forwarder 2>&1 | grep "smart-offset-detector"

# View audit trail
docker exec audit-forwarder cat /tmp/offset-detection-audit.log

# Check setup marker
docker exec audit-forwarder cat /app/.setup-complete
```

---

## Architecture

### Components

```
┌────────────────────────────────────────────────────────────┐
│                    Container Startup                       │
└─────────────────────────┬──────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│              scripts/entrypoint.sh                         │
│  - Checks OFFSET_STRATEGY env var                         │
│  - If "auto" or empty → calls smart-offset-detector.sh    │
│  - If explicit → uses that strategy                        │
└─────────────────────────┬──────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│         scripts/smart-offset-detector.sh                   │
│  1. Check .setup-complete marker                          │
│  2. Query consumer group existence (Python + AdminClient)  │
│  3. Calculate consumer lag (Python + Consumer API)         │
│  4. Apply decision tree logic                              │
│  5. Return strategy + log reasoning                        │
└─────────────────────────┬──────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│              scripts/entrypoint.sh                         │
│  - Receives strategy (latest|committed|timestamp)          │
│  - Applies strategy:                                       │
│    - latest: delete consumer group                         │
│    - committed: do nothing                                 │
│    - timestamp: delete group + create marker               │
│  - Starts audit_forwarder.py                               │
└────────────────────────────────────────────────────────────┘
```

### Files

| File | Purpose |
|------|---------|
| `scripts/entrypoint.sh` | Container entrypoint - orchestrates detection and strategy application |
| `scripts/smart-offset-detector.sh` | Smart detection logic - returns strategy |
| `.setup-complete` | Marker file - tracks first-time setup |
| `/tmp/offset-detection-audit.log` | Audit trail - all decisions logged |
| `/tmp/offset_reset_timestamp` | Timestamp marker - for timestamp strategy |

---

## Migration from Manual Configuration

### Before (v3.0.0)

```yaml
# docker-compose.yml
services:
  audit-forwarder:
    environment:
      - OFFSET_STRATEGY=latest  # User had to set this
```

### After (v3.0.1)

```yaml
# docker-compose.yml
services:
  audit-forwarder:
    environment:
      # No OFFSET_STRATEGY needed - auto-detection!
      # (or set to "auto" explicitly)
```

### Existing Deployments

**No action required.**

- If `OFFSET_STRATEGY` is not set → auto-detection activates
- If `OFFSET_STRATEGY=latest|committed|timestamp` → manual override (backwards compatible)
- If `.setup-complete` exists → system knows it's not first-time setup

---

## FAQ

**Q: What if I want to always use `latest`?**

A: Set `OFFSET_STRATEGY=latest` explicitly. The auto-detection respects manual overrides.

**Q: How do I reset to first-time behavior?**

A: Delete the `.setup-complete` marker:
```bash
docker exec audit-forwarder rm /app/.setup-complete
docker-compose restart audit-forwarder
```

**Q: Can I change the thresholds?**

A: Yes. Edit `scripts/smart-offset-detector.sh` and adjust the `LAG_THRESHOLD_*` variables.

**Q: What happens if Kafka is unreachable during detection?**

A: The system falls back to `latest` (safe default) and logs a warning.

**Q: How do I see why a particular strategy was chosen?**

A: Check the logs:
```bash
docker logs audit-forwarder 2>&1 | grep DECISION
```

**Q: Does this work with Confluent Cloud?**

A: Yes. The system uses Confluent Kafka AdminClient which works with all Kafka distributions.

**Q: What about Schema Registry dependencies?**

A: The detection logic is independent of Schema Registry. It only queries consumer group metadata and watermarks.

---

## Related Documentation

- [Offset Manager](../scripts/offset-manager.sh) - Advanced manual offset management
- [Entrypoint](../scripts/entrypoint.sh) - Container startup orchestration
- [END_TO_END_FLOW.md](./END_TO_END_FLOW.md) - Full system architecture

---

**Last Updated:** 2025-02-19
**Version:** v3.0.1
