# Schema Watcher - Quick Reference

## Overview

Automated service that monitors Confluent audit log documentation for schema changes and updates classification rules.

## Quick Start

```bash
# 1. Optional: Configure Slack alerts
echo "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL" >> .env

# 2. Start the watcher
docker-compose up -d schema-watcher

# 3. View logs
docker logs -f schema-watcher

# 4. Check version history
docker exec schema-watcher cat /app/data/schema_versions.json | jq
```

## How It Works

```
┌─────────────────┐
│ Confluent Docs  │
│  (Daily Fetch)  │
└────────┬────────┘
         │
         v
┌─────────────────┐
│ Extract Schema  │
│ • Methods       │
│ • Event Types   │
│ • Fields        │
└────────┬────────┘
         │
         v
┌─────────────────┐
│ Compare with    │
│ Last Version    │
└────────┬────────┘
         │
         v
    ┌────┴────┐
    │ Changes?│
    └────┬────┘
         │
    ┌────┴────────────────┐
    │                     │
    v                     v
┌───────┐          ┌─────────────┐
│  No   │          │     Yes     │
└───────┘          └──────┬──────┘
                          │
                ┌─────────┼─────────┐
                │         │         │
                v         v         v
         ┌──────────┐ ┌──────┐ ┌───────┐
         │ Classify │ │Update│ │ Slack │
         │ Methods  │ │File  │ │ Alert │
         └──────────┘ └──────┘ └───────┘
```

## Classification Rules

When new methods are detected, they are automatically classified:

| Pattern | Level | Examples |
|---------|-------|----------|
| Delete*, Remove*, Purge* | CRITICAL | DeleteKafkaCluster, RemoveUser |
| *Acl* + Create/Delete | CRITICAL | CreateAcls, DeleteAcls |
| *Audit* + Update/Delete | CRITICAL | UpdateAuditLogConfig |
| *ApiKey* | HIGH | CreateApiKey, RotateApiKey |
| *ServiceAccount* | HIGH | CreateServiceAccount |
| *RoleBinding* | HIGH | CreateRoleBinding |
| *Identity* | HIGH | CreateIdentityProvider |
| Create*, Update* | MEDIUM | CreateTopic, UpdateCluster |
| Get*, List*, Describe* | LOW | GetCluster, ListTopics |

## Configuration

### Environment Variables

```bash
# Check interval (default: 24 hours)
SCHEMA_CHECK_INTERVAL_HOURS=24

# Dry run mode (test without updating files)
SCHEMA_WATCHER_DRY_RUN=false

# Slack webhook URL (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

### Docker Compose

The service is already configured in `docker-compose.yml`:

```yaml
schema-watcher:
  image: schema-watcher:v1.0.0
  volumes:
    - ./src/classification:/app/src/classification:rw  # Updates methods.py
    - schema_watcher_data:/app/data                    # Version history
  deploy:
    resources:
      limits:
        cpus: '0.25'
        memory: 256M
```

## Common Tasks

### View Current Schema Version

```bash
docker exec schema-watcher cat /app/data/schema_versions.json | jq '.[0]'
```

### View All Schema Changes

```bash
docker exec schema-watcher cat /app/data/schema_versions.json | jq '.[] | select(.changes)'
```

### Force Immediate Check

```bash
docker-compose restart schema-watcher
```

### Test Without Updating Files

```bash
docker-compose run --rm \
  -e DRY_RUN=true \
  schema-watcher python watcher.py
```

### View Latest Schema Snapshot

```bash
# List snapshots
docker exec schema-watcher ls -lh /app/data/schema_snapshot_*.json

# View latest
LATEST=$(docker exec schema-watcher ls /app/data/schema_snapshot_*.json | tail -1)
docker exec schema-watcher cat $LATEST | jq
```

### Check What Changed

```bash
# Get latest changes
docker exec schema-watcher cat /app/data/schema_versions.json | \
  jq '.[-1].changes'

# Count new methods
docker exec schema-watcher cat /app/data/schema_versions.json | \
  jq '.[-1].changes.methods.added | length'
```

## Monitoring

### Health Check

```bash
docker inspect schema-watcher --format='{{.State.Health.Status}}'
```

### View Logs

```bash
# Real-time
docker logs -f schema-watcher

# Last 50 lines
docker logs --tail 50 schema-watcher

# Search for errors
docker logs schema-watcher 2>&1 | grep ERROR

# Search for changes detected
docker logs schema-watcher 2>&1 | grep "Schema changes detected"
```

### Key Log Messages

| Message | Meaning |
|---------|---------|
| `Starting schema check cycle` | Check initiated |
| `Extracted N methods` | Schema fetched successfully |
| `Schema changes detected!` | New changes found |
| `Updated methods.py with N new methods` | File updated |
| `Sent Slack alert successfully` | Alert sent |
| `No schema changes detected` | No changes this cycle |

## Slack Alert Example

When changes are detected, you'll receive a Slack message like:

```
🔔 Confluent Audit Log Schema Change Detected

Detected at: 2025-02-19 12:00:00 UTC
Source: https://docs.confluent.io/cloud/current/monitoring/audit-logging/audit-log-events.html

New Methods Detected:

🔴 CRITICAL:
  • DeleteFlinkCompute
  • DeleteFlinkStatement

🟠 HIGH:
  • CreateFlinkApiKey

🟡 MEDIUM:
  • CreateFlinkCompute
  • UpdateFlinkStatement

New Event Types:
  • io.confluent.flink.compute.created
  • io.confluent.flink.compute.deleted

Action Required:
  • Review new methods in src/classification/methods.py
  • Verify auto-classification is correct
  • Update dashboard filters if needed
  • Test forwarder routing with new event types
```

## Troubleshooting

### Service Not Starting

```bash
# Check status
docker-compose ps schema-watcher

# View startup logs
docker logs schema-watcher

# Check volume mounts
docker inspect schema-watcher | jq '.[0].Mounts'
```

### Methods File Not Updating

1. Check volume mount is read-write:
```bash
docker inspect schema-watcher | jq '.[0].Mounts[] | select(.Destination=="/app/src/classification")'
```

2. Check file permissions:
```bash
ls -la src/classification/methods.py
```

3. Verify DRY_RUN is false:
```bash
docker exec schema-watcher env | grep DRY_RUN
```

### No Slack Alerts

1. Verify webhook URL:
```bash
docker exec schema-watcher env | grep SLACK_WEBHOOK_URL
```

2. Test webhook manually:
```bash
curl -X POST \
  -H 'Content-type: application/json' \
  --data '{"text":"Test from schema-watcher"}' \
  $SLACK_WEBHOOK_URL
```

3. Check for HTTP errors:
```bash
docker logs schema-watcher 2>&1 | grep "Error sending Slack alert"
```

### Manual Testing

```bash
# Run one-time check with dry-run
docker-compose run --rm \
  -e DRY_RUN=true \
  -e CHECK_INTERVAL_HOURS=0 \
  schema-watcher python watcher.py

# Run actual check (will update files)
docker-compose run --rm \
  -e DRY_RUN=false \
  schema-watcher python watcher.py
```

## Version History Format

Each check creates a version entry in `schema_versions.json`:

```json
{
  "version": 1,
  "timestamp": "2025-02-19T12:00:00Z",
  "checksum": "sha256_of_docs_html",
  "source_url": "https://docs.confluent.io/...",
  "event_types_count": 45,
  "methods_count": 234,
  "fields_count": 28,
  "changes": {
    "methods": {
      "added": ["CreateFlinkCompute", "DeleteFlinkCompute"],
      "removed": []
    },
    "event_types": {
      "added": ["io.confluent.flink.compute.created"],
      "removed": []
    },
    "fields": {
      "added": ["flink_compute_id"],
      "removed": []
    }
  }
}
```

## Security

- Runs as non-root user (UID 1000)
- Minimal Docker image (python:3.9-slim)
- Read-only filesystem (except data volume)
- All capabilities dropped
- Network access only to Confluent docs and Slack

## Resource Usage

- CPU: 0.1-0.25 cores (only during checks)
- Memory: 128-256 MB
- Disk: ~10 MB for version history
- Network: ~5 MB per check (downloading docs)

## Integration with Forwarder

The watcher automatically updates `src/classification/methods.py`, which is mounted read-only in the forwarder container. To apply changes:

```bash
# After schema update, restart forwarder
docker-compose restart audit-forwarder

# Verify new methods are loaded
docker logs audit-forwarder | grep "Loaded classification rules"
```

## Manual Method Addition

If you want to manually add methods (without waiting for watcher):

1. Edit `src/classification/methods.py`:
```python
_CRITICAL_METHODS_DEFAULT = {
    # ... existing methods ...
    'YourNewMethod',  # Manual addition
}
```

2. Restart forwarder:
```bash
docker-compose restart audit-forwarder
```

## Further Reading

- Full documentation: `schema-watcher/README.md`
- Classification rules: `src/classification/methods.py`
- Docker configuration: `schema-watcher/Dockerfile`
- Confluent audit logs: https://docs.confluent.io/cloud/current/monitoring/audit-logging/

## Support

For issues or questions:

1. Check logs: `docker logs schema-watcher`
2. Review version history: `cat schema-watcher/schema_versions.json | jq`
3. Test manually: `docker-compose run --rm -e DRY_RUN=true schema-watcher python watcher.py`
