# Dead Letter Queue (DLQ) API Documentation

## Overview

The Dead Letter Queue captures events that fail during processing, allowing for later analysis and reprocessing. Introduced in v2.2.0.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_DLQ` | `true` | Enable/disable DLQ functionality |
| `DLQ_TOPIC` | `audit.dlq.v1` | Kafka topic for failed events |

### Example

```bash
# Enable DLQ (default)
ENABLE_DLQ=true
DLQ_TOPIC=audit.dlq.v1

# Disable DLQ
ENABLE_DLQ=false
```

---

## DLQ Event Schema

### Structure

```json
{
  "original_value": "<string>",
  "error": "<string>",
  "source_topic": "<string>",
  "source_partition": <integer>,
  "source_offset": <integer>,
  "failed_at": "<ISO8601 timestamp>",
  "forwarder_version": "<string>"
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `original_value` | string | Raw event JSON (decoded with error replacement) |
| `error` | string | Exception message that caused the failure |
| `source_topic` | string | Original Kafka topic name |
| `source_partition` | integer | Partition number where event originated |
| `source_offset` | integer | Offset within the partition |
| `failed_at` | string | ISO8601 UTC timestamp of failure |
| `forwarder_version` | string | Forwarder version that processed the event |

### Example DLQ Event

```json
{
  "original_value": "{\"specversion\":\"1.0\",\"type\":\"io.confluent.kafka.server/authorization\",\"time\":\"2025-12-14T10:30:00Z\",\"data\":{\"methodName\":\"DeleteTopic\"}}",
  "error": "KeyError: 'resourceName'",
  "source_topic": "confluent-audit-log-events",
  "source_partition": 5,
  "source_offset": 1234567,
  "failed_at": "2025-12-14T10:30:05Z",
  "forwarder_version": "2.2.0"
}
```

---

## API Functions

### send_to_dlq()

Sends a failed event to the Dead Letter Queue.

```python
def send_to_dlq(
    producer: Producer,
    raw_value: bytes,
    error_msg: str,
    source_topic: str,
    partition: int,
    offset: int
) -> None:
    """
    Send failed event to Dead Letter Queue with error metadata.

    @param producer: Kafka producer instance
    @param raw_value: Original message value as bytes
    @param error_msg: Error message describing the failure
    @param source_topic: Source Kafka topic name
    @param partition: Source partition number
    @param offset: Source message offset

    @returns: None

    @example:
        try:
            process_event(msg)
        except Exception as ex:
            send_to_dlq(
                producer,
                msg.value(),
                str(ex),
                msg.topic(),
                msg.partition(),
                msg.offset()
            )

    @note: Function is no-op if ENABLE_DLQ is False
    @note: Failures to send to DLQ are logged but don't raise exceptions
    """
```

### DLQ Statistics

The forwarder tracks DLQ statistics in the `dlq_stats` dictionary:

```python
dlq_stats = {
    "sent": 0,      # Successfully sent to DLQ
    "failed": 0     # Failed to send to DLQ
}
```

Statistics are logged every 30 seconds in the heartbeat:

```
Forwarder is alive at Sun Dec 14 11:25:43 2025. Processed: 60000, Errors: 0, Delivery failures: 0, DLQ: 0 sent/0 failed
```

---

## Message Key Format

DLQ messages use a composite key for deduplication and ordering:

```
{source_topic}-{partition}-{offset}
```

Example: `confluent-audit-log-events-5-1234567`

This allows:
- Deduplication if the same event is sent multiple times
- Compaction-friendly topic configuration
- Easy identification of original event location

---

## Topic Configuration Recommendations

```bash
# Create DLQ topic with appropriate settings
confluent kafka topic create audit.dlq.v1 \
  --partitions 6 \
  --config retention.ms=2592000000 \  # 30 days
  --config cleanup.policy=delete
```

| Setting | Recommended | Reason |
|---------|-------------|--------|
| Partitions | 6 | Matches source topic partitioning |
| Retention | 30 days | Long enough to investigate failures |
| Cleanup Policy | delete | Time-based retention |
| Replication Factor | 3 | Production durability |

---

## Monitoring DLQ

### Check DLQ Size

```bash
# Count messages in DLQ
confluent kafka topic consume audit.dlq.v1 \
  --from-beginning \
  --print-key \
  | wc -l
```

### Analyze Failure Patterns

```bash
# Group by error type
confluent kafka topic consume audit.dlq.v1 \
  --from-beginning \
  | jq -r '.error' \
  | sort | uniq -c | sort -rn
```

### Sample DLQ Events

```bash
# View recent DLQ events
confluent kafka topic consume audit.dlq.v1 \
  --from-beginning \
  | tail -10 \
  | jq .
```

---

## Reprocessing DLQ Events

### Manual Reprocessing Script

```python
#!/usr/bin/env python3
"""
Reprocess events from DLQ.

@example:
    python reprocess_dlq.py --limit 100 --dry-run
"""

from confluent_kafka import Consumer, Producer
import orjson

def reprocess_dlq(limit=None, dry_run=True):
    """
    Read events from DLQ and attempt to reprocess.

    @param limit: Maximum events to reprocess (None for all)
    @param dry_run: If True, don't actually reprocess

    @returns: Dict with counts {processed, failed, skipped}
    """
    consumer = Consumer({
        'bootstrap.servers': DEST_BOOTSTRAP,
        'group.id': 'dlq-reprocessor',
        'auto.offset.reset': 'earliest',
    })
    consumer.subscribe(['audit.dlq.v1'])

    stats = {'processed': 0, 'failed': 0, 'skipped': 0}

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                break

            dlq_event = orjson.loads(msg.value())
            original = orjson.loads(dlq_event['original_value'])

            if dry_run:
                print(f"Would reprocess: {dlq_event['source_offset']}")
                stats['skipped'] += 1
            else:
                try:
                    process_event(original)
                    stats['processed'] += 1
                except Exception as e:
                    stats['failed'] += 1

            if limit and sum(stats.values()) >= limit:
                break
    finally:
        consumer.close()

    return stats
```

---

## Alerting on DLQ

### CloudWatch Alarm (AWS)

```hcl
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "auditlens-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "MessagesInDLQ"
  namespace           = "AuditLens"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "DLQ has accumulated messages"
}
```

### Prometheus Alert

```yaml
groups:
  - name: auditlens
    rules:
      - alert: DLQMessagesAccumulating
        expr: auditlens_dlq_sent_total > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "DLQ has {{ $value }} messages"
```

---

## Error Handling

### Common DLQ Errors

| Error | Cause | Resolution |
|-------|-------|------------|
| `KeyError: 'resourceName'` | Missing field in event | Check event schema version |
| `JSONDecodeError` | Malformed JSON | Source data corruption |
| `UnicodeDecodeError` | Invalid encoding | Check producer encoding |
| `TypeError` | Unexpected data type | Update classification logic |

### Failure to Write to DLQ

If sending to DLQ fails:
1. Error is logged (not raised)
2. `dlq_stats["failed"]` is incremented
3. Original processing continues
4. Event is effectively lost

```python
except Exception as e:
    dlq_stats["failed"] += 1
    logger.warning("Failed to send to DLQ: %s", e)
```

---

## Best Practices

1. **Monitor DLQ Size**: Set up alerts when DLQ accumulates messages
2. **Regular Review**: Check DLQ weekly for patterns
3. **Retention Policy**: Keep DLQ events for at least 30 days
4. **Reprocessing**: Fix root cause before bulk reprocessing
5. **Separate Credentials**: Use dedicated API key for DLQ topic
6. **Documentation**: Document known error patterns and resolutions

---

*Last Updated: 2025-12-14 | Version: 2.2.0*
