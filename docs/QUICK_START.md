# Quick Start: Query Your Confluent Audit Logs

Get answers to "who did what and when" in 5 minutes.

## Option 1: Direct Athena Query (Fastest)

If you have Tableflow enabled with AWS Glue:

```sql
-- Open Athena, select your Glue database, and run:

-- Who deleted anything in last 7 days?
SELECT
    time,
    data.authenticationInfo.principal AS who,
    data.methodName AS action,
    data.result.status
FROM confluent_audit_log_events
WHERE data.methodName LIKE 'Delete%'
  AND time > CURRENT_TIMESTAMP - INTERVAL '7' DAY;
```

## Option 2: CLI Quick Search

```bash
# Install confluent CLI
brew install confluentinc/tap/cli

# Login
confluent login

# Search audit logs (last 24h)
confluent audit-log search \
  --start-time "24h" \
  --filter "methodName=DeleteKafkaCluster"
```

## Option 3: Export & Query Locally

```bash
# Export to JSON
confluent audit-log describe \
  --start-time "2025-01-01T00:00:00Z" \
  --end-time "2025-01-02T00:00:00Z" \
  --output json > audit_logs.json

# Query with jq
cat audit_logs.json | jq '
  .[] |
  select(.data.methodName | contains("Delete")) |
  {
    time: .time,
    who: .data.authenticationInfo.principal,
    action: .data.methodName,
    status: .data.result.status
  }
'
```

## Common Questions - Copy & Paste Queries

### "Who created topic X?"
```bash
confluent audit-log search \
  --filter "methodName=kafka.CreateTopics" \
  --filter "request.topicName=YOUR_TOPIC_NAME"
```

### "Who deleted cluster X?"
```bash
confluent audit-log search \
  --filter "methodName=DeleteKafkaCluster" \
  --filter "source=*kafka=YOUR_CLUSTER_ID*"
```

### "Show all failed logins"
```bash
confluent audit-log search \
  --filter "type=*authentication*" \
  --filter "result.status=UNAUTHENTICATED"
```

### "What did user X do?"
```bash
confluent audit-log search \
  --filter "authenticationInfo.principal=User:someone@company.com"
```

### "Activity from IP address"
```bash
confluent audit-log search \
  --filter "requestMetadata.clientAddress=10.0.1.100"
```

## Next Steps

- [Full Query Reference](./AUDIT_QUERIES.md) - 15+ ready-to-use queries
- [Set up Tableflow](../deploy/terraform/confluent-cloud/) - For Athena integration
- [Python Forwarder](../README.md) - For GCS/BigQuery

## Key Fields to Know

| Field Path | What It Contains |
|------------|------------------|
| `time` | When it happened |
| `data.authenticationInfo.principal` | Who did it |
| `data.methodName` | What action |
| `source` | Which resource (contains CRN) |
| `data.result.status` | Success or failure |
| `data.requestMetadata.clientAddress` | From which IP |
