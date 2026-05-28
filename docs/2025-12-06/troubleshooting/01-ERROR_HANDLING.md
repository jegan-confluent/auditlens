# Error Handling & Recovery Guide

**Document Version:** 1.0
**Last Updated:** December 6, 2025
**Audience:** Operations, SRE, DevOps

---

## Table of Contents
1. [Error Handling Strategy](#error-handling-strategy)
2. [Offset Management](#offset-management)
3. [Forwarder Failure Scenarios](#forwarder-failure-scenarios)
4. [Recovery Procedures](#recovery-procedures)
5. [DLQ (Dead Letter Queue) Management](#dlq-management)
6. [Monitoring & Alerts](#monitoring--alerts)

---

## Error Handling Strategy

### **Layered Error Handling**

The system implements a **defense-in-depth** error handling strategy:

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Consumer Resilience                                │
│  • Automatic reconnection to Kafka brokers                  │
│  • Configurable retry on network failures                   │
│  • Watermark validation before seek                         │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Processing Pipeline Error Handling                 │
│  • Try-catch on event parsing                               │
│  • Graceful degradation (skip malformed events)             │
│  • Logging of all errors with event ID                      │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Producer Resilience                                │
│  • Idempotent producer (exactly-once semantics)             │
│  • Automatic retries (5 attempts)                           │
│  • Delivery timeout: 300 seconds                            │
│  • Queue buffering: 1M messages, 1GB memory                 │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 4: Dead Letter Queue (DLQ)                            │
│  • Failed events → DLQ sink                                 │
│  • Includes error reason & original event                   │
│  • Manual review and replay capability                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Offset Management

### **How Offsets Work**

The forwarder uses **manual offset management** for maximum reliability:

```python
# Configuration
consumer_conf = {
    "enable.auto.commit": False,      # Manual commit only
    "auto.offset.reset": "earliest",  # Default start position
}
```

### **Offset Storage**

**File:** `offsets.json` (persistent)

**Format:**
```json
{
  "confluent-audit-log-events_0": 1234567,
  "confluent-audit-log-events_1": 1234890,
  "confluent-audit-log-events_2": 1235012
}
```

**Key:** `{topic}_{partition}`
**Value:** Last successfully processed offset

### **Offset Commit Flow**

```
1. Consumer receives message batch (offset N)
     ↓
2. Process & enrich events
     ↓
3. Produce to destination topic(s)
     ↓
4. Wait for producer callback (success/failure)
     ↓
5. If ALL successful → save_offset(N) to offsets.json
     ↓
6. If ANY failed → DO NOT commit offset (will retry from N)
```

### **Starting Position Options**

#### **Option 1: Resume from Last Saved Offset (DEFAULT)**

```bash
# Forwarder checks offsets.json on startup
# If file exists with partition offset → resume from saved offset + 1
# If file missing for partition → seek to earliest available
```

**Use Case:** Normal operation, restarts after maintenance

**Behavior:**
- No data loss
- No duplicate processing (when combined with idempotent producer)
- Resumes exactly where left off

#### **Option 2: Start from Earliest**

```bash
# Delete or rename offsets.json
rm offsets.json

# Start forwarder
python audit_forwarder.py

# Will process ALL available events from beginning of retention
```

**Use Case:**
- First-time setup
- Backfill after extended downtime
- Reprocess historical events

**Caution:**
- May process 7 days of events (~8.4M events at 50K/hour)
- High initial load on destination
- Takes hours to catch up

#### **Option 3: Start from Latest**

```bash
# Manually create offsets.json with high watermark offsets
python << 'EOF'
import json
from confluent_kafka import Consumer
from pathlib import Path

conf = {
    "bootstrap.servers": os.getenv("AUDIT_BOOTSTRAP"),
    "security.protocol": "SASL_SSL",
    "sasl.mechanism": "PLAIN",
    "sasl.username": os.getenv("AUDIT_API_KEY"),
    "sasl.password": os.getenv("AUDIT_API_SECRET"),
    "group.id": "offset-setup-temp"
}

consumer = Consumer(conf)
metadata = consumer.list_topics("confluent-audit-log-events", timeout=10)
topic_meta = metadata.topics["confluent-audit-log-events"]

offsets = {}
for partition_id in topic_meta.partitions.keys():
    low, high = consumer.get_watermark_offsets(
        TopicPartition("confluent-audit-log-events", partition_id),
        timeout=5
    )
    offsets[f"confluent-audit-log-events_{partition_id}"] = high - 1

with open("offsets.json", "w") as f:
    json.dump(offsets, f, indent=2)

print(f"Created offsets.json with latest offsets: {offsets}")
consumer.close()
EOF

# Start forwarder
python audit_forwarder.py
```

**Use Case:**
- Ignore historical events
- Start monitoring from "now"
- Reduce initial processing load

**Trade-off:**
- Loses historical context
- No backfill capability

#### **Option 4: Start from Specific Timestamp**

```bash
# Use Kafka timestamp-based seeking
# Modify audit_forwarder.py temporarily or create wrapper script

python << 'EOF'
import json
import os
from confluent_kafka import Consumer, TopicPartition
from datetime import datetime, timezone

# Target timestamp (e.g., 7 days ago)
target_dt = datetime.now(timezone.utc) - timedelta(days=7)
target_ts = int(target_dt.timestamp() * 1000)  # milliseconds

conf = {
    "bootstrap.servers": os.getenv("AUDIT_BOOTSTRAP"),
    "security.protocol": "SASL_SSL",
    "sasl.mechanism": "PLAIN",
    "sasl.username": os.getenv("AUDIT_API_KEY"),
    "sasl.password": os.getenv("AUDIT_API_SECRET"),
    "group.id": "offset-setup-temp"
}

consumer = Consumer(conf)
metadata = consumer.list_topics("confluent-audit-log-events", timeout=10)
topic_meta = metadata.topics["confluent-audit-log-events"]

offsets = {}
for partition_id in topic_meta.partitions.keys():
    tp = TopicPartition("confluent-audit-log-events", partition_id, target_ts)
    offsets_for_times = consumer.offsets_for_times([tp])

    if offsets_for_times[0].offset >= 0:
        offsets[f"confluent-audit-log-events_{partition_id}"] = offsets_for_times[0].offset
    else:
        # Timestamp too old, use earliest
        low, high = consumer.get_watermark_offsets(
            TopicPartition("confluent-audit-log-events", partition_id),
            timeout=5
        )
        offsets[f"confluent-audit-log-events_{partition_id}"] = low

with open("offsets.json", "w") as f:
    json.dump(offsets, f, indent=2)

print(f"Created offsets.json for timestamp {target_dt}: {offsets}")
consumer.close()
EOF

# Start forwarder
python audit_forwarder.py
```

**Use Case:**
- Replay events from specific date
- Incident investigation (reprocess last 24 hours)
- Compliance audit (process specific time range)

---

## Forwarder Failure Scenarios

### **Scenario 1: Forwarder Crashes**

**Symptoms:**
- Process exits unexpectedly
- Prometheus `/metrics` endpoint unavailable
- No new events in destination topic

**Automatic Recovery:**
1. Kubernetes/Docker restarts container
2. Forwarder loads `offsets.json`
3. Resumes from last committed offset
4. No data loss

**Manual Intervention:** None required

**Validation:**
```bash
# Check forwarder logs
docker logs audit-forwarder --tail 100

# Verify offset file exists
cat offsets.json

# Check consumer lag
confluent kafka consumer group describe audit-forwarder-group \
  --cluster lkc-xxxxx
```

---

### **Scenario 2: Destination Topic Unavailable**

**Symptoms:**
- Producer delivery failures
- Increasing consumer lag
- `producer_send_error_total` metric increasing

**Automatic Recovery:**
1. Producer retries (5 attempts, 300s timeout)
2. If all retries fail → event goes to DLQ
3. Offset NOT committed (will retry event on restart)

**Manual Intervention:**
1. Fix destination topic (check ACLs, quotas, brokers)
2. Restart forwarder
3. Events will replay from last committed offset

**Prevention:**
```bash
# Monitor producer metrics
curl localhost:8000/metrics | grep producer_send_error

# Set up alerts for repeated failures
```

---

### **Scenario 3: Slow Destination (Backpressure)**

**Symptoms:**
- Increasing consumer lag
- `processing_duration_seconds` metric increasing
- Producer queue filling up

**Automatic Recovery:**
1. Producer queue buffers messages (up to 1M or 1GB)
2. Backpressure slows consumer automatically
3. No data loss, just increased latency

**Manual Intervention:**
```bash
# Option A: Increase producer throughput
export LINGER_MS=100  # Batch more aggressively
export BATCH_SIZE=$((1024 * 1024))  # 1MB batches

# Option B: Scale destination topic partitions
confluent kafka topic update jegan_auditlog \
  --cluster lkc-xxxxx \
  --partitions 6

# Option C: Add more forwarder instances (if partitions > 1)
kubectl scale deployment audit-forwarder --replicas=3
```

---

### **Scenario 4: Corrupted Offset File**

**Symptoms:**
- Forwarder fails to start
- JSON parse error in logs
- "Invalid offset" errors

**Recovery:**
```bash
# Backup corrupted file
mv offsets.json offsets.json.corrupted

# Choose recovery strategy:

# A. Start from latest (lose historical processing)
# Create empty file → will seek to earliest on first run
echo '{}' > offsets.json

# B. Manually inspect and fix
cat offsets.json.corrupted
# Edit JSON manually to fix syntax

# C. Reset to specific known-good offset
echo '{"confluent-audit-log-events_0": 1234567}' > offsets.json
```

---

### **Scenario 5: Schema Registry Unavailable**

**Symptoms:**
- Cannot produce events (schema validation fails)
- `schema_registry_error_total` metric increasing
- Events accumulate in memory

**Automatic Recovery:**
1. Producer retries schema registration (5 times)
2. If fails → event goes to DLQ
3. Forwarder continues processing other events

**Manual Intervention:**
```bash
# Check Schema Registry connectivity
curl -u "$SCHEMA_REGISTRY_KEY:$SCHEMA_REGISTRY_SECRET" \
  "$SCHEMA_REGISTRY_URL/subjects"

# Verify credentials
echo $SCHEMA_REGISTRY_KEY
echo $SCHEMA_REGISTRY_SECRET

# Restart forwarder once SR is back
kubectl rollout restart deployment audit-forwarder
```

---

## Recovery Procedures

### **Complete Recovery Checklist**

```bash
# 1. Verify source Kafka cluster accessible
confluent kafka cluster describe lkc-xxxxx

# 2. Verify destination Kafka cluster accessible
confluent kafka cluster describe lkc-yyyyy

# 3. Check offset file
cat offsets.json
# Ensure valid JSON and reasonable offset values

# 4. Check consumer lag (before restart)
confluent kafka consumer group describe audit-forwarder-group \
  --cluster lkc-xxxxx

# 5. Start forwarder
docker-compose up -d audit-forwarder
# OR
kubectl rollout restart deployment audit-forwarder

# 6. Monitor startup logs
docker logs -f audit-forwarder | grep "Assigned partitions\|offset"

# 7. Verify metrics endpoint
curl localhost:8000/metrics | grep audit_events_total

# 8. Check consumer lag (after restart)
confluent kafka consumer group describe audit-forwarder-group \
  --cluster lkc-xxxxx

# 9. Validate events in destination
confluent kafka topic consume jegan_auditlog \
  --cluster lkc-yyyyy \
  --from-beginning \
  --max-messages 10
```

---

## DLQ (Dead Letter Queue) Management

### **When Events Go to DLQ**

Events are sent to DLQ when:
1. Producer delivery fails after 5 retries
2. Schema validation fails
3. Unrecoverable processing errors

### **DLQ Event Format**

```json
{
  "original_event": { ... },
  "error_reason": "Producer timeout after 300s",
  "error_timestamp": "2025-12-06T12:00:00Z",
  "partition": 0,
  "offset": 1234567,
  "retry_count": 5
}
```

### **DLQ Review & Replay**

```bash
# 1. List DLQ events
confluent kafka topic consume jegan_auditlog_dlq \
  --cluster lkc-yyyyy \
  --from-beginning

# 2. Analyze error patterns
confluent kafka topic consume jegan_auditlog_dlq \
  --cluster lkc-yyyyy \
  --from-beginning \
  | jq -r '.error_reason' | sort | uniq -c

# 3. Fix root cause (e.g., increase quotas, fix ACLs)

# 4. Replay DLQ events
python scripts/replay_dlq.py --topic jegan_auditlog_dlq
```

---

## Monitoring & Alerts

### **Critical Metrics to Monitor**

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| `audit_events_processed_total` | No increase for 5 min | Restart forwarder |
| `producer_send_error_total` | >10 in 1 min | Check destination cluster |
| `anomaly_detected_total` | >50 in 5 min | Security investigation |
| Consumer lag | >100K messages | Scale forwarder or investigate slowness |
| `processing_duration_seconds` | >10s p99 | Optimize pipeline or scale |

### **Recommended Alerts**

```yaml
# Prometheus AlertManager rules
groups:
  - name: audit_forwarder
    interval: 30s
    rules:
      - alert: ForwarderDown
        expr: up{job="audit-forwarder"} == 0
        for: 2m
        annotations:
          summary: "Audit forwarder is down"

      - alert: HighProducerErrors
        expr: rate(producer_send_error_total[5m]) > 0.1
        for: 2m
        annotations:
          summary: "High producer error rate"

      - alert: HighConsumerLag
        expr: kafka_consumer_lag > 100000
        for: 5m
        annotations:
          summary: "Consumer lag exceeding threshold"
```

---

## Best Practices

1. **Always backup `offsets.json` before manual changes**
2. **Test offset changes in non-prod first**
3. **Monitor consumer lag continuously**
4. **Review DLQ events weekly**
5. **Keep forwarder version in sync with dashboard**
6. **Use idempotent producer + manual commits for exactly-once**
7. **Set up alerts before production deployment**
8. **Document all manual offset interventions**

---

## Emergency Contacts

- **Kafka Cluster Issues:** Confluent Cloud Support
- **TableFlow/Iceberg Issues:** Confluent Cloud Support
- **Forwarder Application:** [Your Team Slack Channel]
- **Dashboard Issues:** [Your Team Slack Channel]

---

## Appendix: Common Error Messages

| Error | Cause | Fix |
|-------|-------|-----|
| `Broker: Offset out of range` | Offset in file > high watermark | Delete offsets.json, restart |
| `Schema registry timeout` | SR unavailable or wrong credentials | Check SR_KEY/SECRET, verify SR URL |
| `Producer queue full` | Destination too slow | Increase partitions or scale forwarder |
| `JSON decode error` | Malformed event from Confluent | Log event, skip, continue (automatic) |
| `Authentication failure` | Wrong API keys | Verify AUDIT_API_KEY/SECRET |
