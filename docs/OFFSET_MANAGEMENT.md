# AuditLens Offset Management Guide

## Overview

AuditLens provides **customer-configurable offset management** to control how the forwarder handles Kafka consumer group offsets after restart or redeployment. This feature enables disaster recovery, backlog processing, and flexible data retention strategies **without any code changes**.

## Quick Start

Set the `OFFSET_STRATEGY` environment variable in your `.env` file:

```bash
# Skip backlog and catch up quickly
OFFSET_STRATEGY=latest

# Reprocess all audit events
OFFSET_STRATEGY=earliest

# Start from 7 days ago
OFFSET_STRATEGY=timestamp
OFFSET_HOURS_AGO=168

# Resume normally (default)
OFFSET_STRATEGY=committed
```

Then restart the forwarder:

```bash
docker compose restart audit-forwarder
```

---

## Offset Strategies

### 1. `committed` (Default)

**Use Case**: Normal operation, resume from last processed message

**Behavior**:
- Resumes from the last committed offset in the Kafka consumer group
- Standard Kafka behavior for reliable message processing
- No messages are skipped or reprocessed

**Configuration**:
```bash
OFFSET_STRATEGY=committed
```

**When to Use**:
- ✅ Normal restarts and deployments
- ✅ Short downtime (< 24 hours)
- ✅ Production environments with SLAs
- ✅ When message loss is unacceptable

**Example**:
```bash
# In .env file
OFFSET_STRATEGY=committed

# Or use default (no configuration needed)
# docker compose up -d
```

---

### 2. `latest` (Fast Recovery)

**Use Case**: Skip backlog after long downtime, catch up quickly

**Behavior**:
- Starts consuming from the **newest available messages**
- Skips all messages accumulated during downtime
- Fast recovery but loses historical data from downtime period

**Configuration**:
```bash
OFFSET_STRATEGY=latest
```

**When to Use**:
- ✅ After extended outage (> 7 days)
- ✅ When backlog is too large to process
- ✅ When historical data is not critical
- ✅ Quick disaster recovery

**Example**:
```bash
# Scenario: Forwarder was down for 30 days
# You have 500GB of backlog you don't need to process

# In .env file
OFFSET_STRATEGY=latest

# Restart forwarder
docker compose restart audit-forwarder

# Forwarder will skip the 500GB backlog and start fresh
```

⚠️ **Warning**: This will permanently skip all messages from the downtime period. Use with caution.

---

### 3. `earliest` (Full Reprocessing)

**Use Case**: Rebuild all data from scratch, compliance requirements

**Behavior**:
- Starts consuming from the **oldest available message** in the topic
- Reprocesses the entire topic history
- Useful for data migration, compliance audits, or fixing data quality issues

**Configuration**:
```bash
OFFSET_STRATEGY=earliest
```

**When to Use**:
- ✅ Data warehouse rebuild
- ✅ Compliance audit requirements
- ✅ Fixing classification logic (reprocess with new rules)
- ✅ Data quality issues in downstream systems

**Example**:
```bash
# Scenario: You fixed a bug in the criticality classification
# You need to reprocess all events with the corrected logic

# In .env file
OFFSET_STRATEGY=earliest

# Restart forwarder
docker compose restart audit-forwarder

# Forwarder will reprocess ALL audit events from day 1
```

⚠️ **Warning**: This can take hours or days depending on topic size. Plan for:
- Increased Kafka egress costs
- Duplicate events in destination topics (use idempotency keys)
- High CPU and memory usage during catchup

---

### 4. `timestamp` (Point-in-Time Recovery)

**Use Case**: Start from specific date/time for disaster recovery

**Behavior**:
- Starts consuming from messages **after** the specified timestamp
- Useful for replaying events from a known-good state
- Supports both absolute and relative timestamps

**Configuration**:

**Option A: Absolute Timestamp (ISO 8601)**
```bash
OFFSET_STRATEGY=timestamp
OFFSET_TIMESTAMP=2025-02-01T00:00:00Z
```

**Option B: Relative Time (hours ago)**
```bash
OFFSET_STRATEGY=timestamp
OFFSET_HOURS_AGO=168  # 7 days ago
```

**When to Use**:
- ✅ Disaster recovery from known-good point
- ✅ Replay events after a specific incident
- ✅ Testing with recent production data
- ✅ Gradual catchup after extended downtime

**Example 1: Disaster Recovery**
```bash
# Scenario: Data corruption detected on Feb 15, 2025
# Last known-good state was Feb 1, 2025

# In .env file
OFFSET_STRATEGY=timestamp
OFFSET_TIMESTAMP=2025-02-01T00:00:00Z

# Restart forwarder
docker compose restart audit-forwarder

# Forwarder will replay all events from Feb 1 onwards
```

**Example 2: Gradual Catchup**
```bash
# Scenario: Forwarder was down for 30 days
# You want to process the last 7 days of backlog

# In .env file
OFFSET_STRATEGY=timestamp
OFFSET_HOURS_AGO=168  # 7 days = 168 hours

# Restart forwarder
docker compose restart audit-forwarder

# Forwarder will process events from 7 days ago to now
```

---

## Common Scenarios

### Scenario 1: Extended Outage (Fast Recovery)

**Situation**: Forwarder was down for 2 weeks, 100GB backlog accumulated

**Solution**: Use `latest` to skip backlog
```bash
OFFSET_STRATEGY=latest
docker compose restart audit-forwarder
```

**Result**: Forwarder catches up in minutes instead of hours

---

### Scenario 2: Compliance Audit (Full History)

**Situation**: Regulatory audit requires all events from last 90 days

**Solution**: Use `earliest` to reprocess everything
```bash
OFFSET_STRATEGY=earliest
docker compose restart audit-forwarder
```

**Result**: All events reprocessed, complete audit trail available

---

### Scenario 3: Bug Fix (Reprocess Recent Data)

**Situation**: Classification bug fixed, need to reprocess last 48 hours

**Solution**: Use `timestamp` with relative time
```bash
OFFSET_STRATEGY=timestamp
OFFSET_HOURS_AGO=48
docker compose restart audit-forwarder
```

**Result**: Last 48 hours reprocessed with corrected logic

---

### Scenario 4: Disaster Recovery (Known-Good Point)

**Situation**: Data corruption detected, rollback to Jan 1, 2025

**Solution**: Use `timestamp` with absolute date
```bash
OFFSET_STRATEGY=timestamp
OFFSET_TIMESTAMP=2025-01-01T00:00:00Z
docker compose restart audit-forwarder
```

**Result**: All events from Jan 1 onwards replayed

---

## Testing Changes (Dry Run)

Before applying offset changes in production, use **dry run mode** to preview:

```bash
# In .env file
OFFSET_STRATEGY=earliest
OFFSET_DRY_RUN=true

# Restart and check logs
docker compose restart audit-forwarder
docker logs -f audit-forwarder | grep offset-manager
```

**Sample Dry Run Output**:
```
[offset-manager] [INFO] Starting Offset Manager v1.0.0
[offset-manager] [INFO] Strategy: earliest | Dry Run: true
[offset-manager] [DRY RUN] Would reset consumer group to earliest offsets
[offset-manager] [INFO] DRY RUN completed - no changes applied
```

Once verified, disable dry run:
```bash
OFFSET_DRY_RUN=false
docker compose restart audit-forwarder
```

---

## Verification & Monitoring

### Check Current Consumer Group Status

```bash
# View current offsets
docker exec -it audit-forwarder \
  curl -s http://localhost:8003/metrics | grep consumer_lag
```

**Expected Output**:
```
audit_forwarder_consumer_lag_total 0
audit_forwarder_consumer_lag{partition="0"} 0
audit_forwarder_consumer_lag{partition="1"} 0
```

### Monitor Offset Reset Audit Trail

```bash
# View audit log
docker exec -it audit-forwarder cat /tmp/offset-manager-audit.log
```

**Sample Audit Log**:
```
================================================================================
Offset Manager Execution
================================================================================
Timestamp:        2025-02-19T10:30:00Z
Strategy:         latest
Consumer Group:   audit-fwd-v3-feb
Topic:            confluent-audit-log-events
Bootstrap:        pkc-xxxxx.us-west-2.aws.confluent.cloud:9092
Dry Run:          false
User:             forwarder
Host:             audit-forwarder
================================================================================
```

### Check Forwarder Logs

```bash
# Watch for offset-related messages
docker logs -f audit-forwarder --since 1m | grep -i offset
```

---

## Advanced Configuration

### Multiple Consumer Groups

To test offset strategies without affecting production:

```bash
# Production consumer group
GROUP_ID=audit-fwd-v3-feb
OFFSET_STRATEGY=committed

# Test consumer group (reprocess 24h)
GROUP_ID=audit-fwd-v3-feb-test
OFFSET_STRATEGY=timestamp
OFFSET_HOURS_AGO=24
```

### Idempotency Keys

When using `earliest` or `timestamp` strategies, ensure downstream systems handle duplicates:

```python
# Example: Use event ID as idempotency key
event_id = event['id']  # Confluent audit log ID
upsert_to_database(event_id, event)  # Idempotent write
```

---

## Troubleshooting

### Issue: Offset reset not working

**Symptoms**: Forwarder still shows old lag, offset not reset

**Causes**:
1. Consumer group has active consumers
2. Invalid timestamp format
3. Missing environment variables

**Solutions**:

```bash
# 1. Stop all forwarder instances
docker compose stop audit-forwarder

# 2. Verify environment variables
docker compose config | grep OFFSET

# 3. Restart with dry run to test
OFFSET_DRY_RUN=true docker compose up audit-forwarder

# 4. Check logs for errors
docker logs audit-forwarder | grep ERROR
```

---

### Issue: Timestamp parsing error

**Symptoms**: Error: "Invalid timestamp format"

**Solution**: Use ISO 8601 format with timezone

```bash
# ❌ Wrong
OFFSET_TIMESTAMP=2025-02-01 00:00:00

# ✅ Correct
OFFSET_TIMESTAMP=2025-02-01T00:00:00Z
OFFSET_TIMESTAMP=2025-02-01T08:00:00+08:00
```

---

### Issue: Consumer group doesn't exist

**Symptoms**: Warning: "Consumer group may not exist"

**Solution**: This is expected for new deployments

```bash
# First startup: consumer group created automatically
OFFSET_STRATEGY=latest
docker compose up -d audit-forwarder

# Verify group created
docker logs audit-forwarder | grep "Consumer group"
```

---

## Cost & Performance Implications

### Storage Costs

| Strategy | Kafka Egress | Destination Storage | Processing Time |
|----------|--------------|---------------------|-----------------|
| `committed` | Minimal (only new data) | Incremental | Fast (< 1 min) |
| `latest` | None (skip backlog) | None | Instant |
| `earliest` | Full topic size (e.g., 500GB) | Full reprocessing | Hours to days |
| `timestamp` | Partial (time range) | Partial | Minutes to hours |

### Performance Guidelines

**For topics < 100GB**:
- `earliest`: 1-2 hours to reprocess
- `timestamp` (7 days): 10-30 minutes

**For topics > 500GB**:
- `earliest`: 6-12 hours to reprocess
- `timestamp` (30 days): 2-4 hours

**Recommendation**: Use `timestamp` with incremental windows for large topics:

```bash
# Week 1: Process last 7 days
OFFSET_HOURS_AGO=168
docker compose restart audit-forwarder
# Wait for catchup...

# Week 2: Reset to committed for ongoing processing
OFFSET_STRATEGY=committed
docker compose restart audit-forwarder
```

---

## Best Practices

### 1. Always Test with Dry Run First

```bash
OFFSET_STRATEGY=earliest
OFFSET_DRY_RUN=true
docker compose restart audit-forwarder
```

### 2. Document Offset Resets

Create a change log entry:

```markdown
## 2025-02-19 - Offset Reset

- **Strategy**: timestamp
- **Timestamp**: 2025-02-01T00:00:00Z
- **Reason**: Reprocess events after classification bug fix
- **Impact**: 7 days of events (50GB)
- **Duration**: 2 hours
- **Performed by**: ops-team
```

### 3. Monitor During Catchup

```bash
# Watch lag decrease
watch -n 5 'docker exec audit-forwarder \
  curl -s http://localhost:8003/metrics | grep consumer_lag_total'
```

### 4. Use Separate Consumer Groups for Testing

```bash
# Test group
GROUP_ID=audit-fwd-test
OFFSET_STRATEGY=earliest

# Production group (unaffected)
GROUP_ID=audit-fwd-v3-feb
OFFSET_STRATEGY=committed
```

### 5. Plan for Idempotency

Ensure downstream systems can handle duplicate events during reprocessing.

---

## FAQ

**Q: Can I change offset strategy while forwarder is running?**

A: No, you must restart the forwarder for changes to take effect.

**Q: Will offset reset affect other consumers of the same topic?**

A: No, each consumer group has independent offsets. Only the forwarder's consumer group is affected.

**Q: What happens if I set `earliest` by mistake?**

A: The forwarder will start reprocessing all events. To stop:
```bash
docker compose stop audit-forwarder
OFFSET_STRATEGY=committed  # Reset to default
docker compose up -d audit-forwarder
```

**Q: Can I reset offsets for specific partitions only?**

A: Not currently supported. Use Kafka's `kafka-consumer-groups` CLI for partition-specific resets.

**Q: Does offset reset delete data from destination topics?**

A: No, offset reset only controls what the forwarder reads. Destination data is not affected.

---

## Support & References

- **Kafka Consumer Groups**: https://kafka.apache.org/documentation/#consumerconfigs
- **Confluent Cloud Console**: View consumer lag in UI
- **AuditLens Metrics**: `http://localhost:8003/metrics`
- **Support Contact**: Your internal Kafka ops team

---

**Last Updated**: 2025-02-19
**Version**: 1.0.0
**Maintainer**: AuditLens Team
