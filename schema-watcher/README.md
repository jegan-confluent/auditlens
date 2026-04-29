# Schema Watcher

Automated monitoring service for Confluent Audit Log schema changes.

## Overview

The Schema Watcher continuously monitors Confluent's audit log documentation for schema changes, automatically detects new event types, methods, and fields, and updates the classification rules accordingly.

## Features

- **Automated Schema Detection**: Scrapes Confluent audit log documentation daily
- **Intelligent Classification**: Uses heuristics to classify new methods by criticality
  - Delete/Remove/Purge → CRITICAL
  - CreateAcls/DeleteAcls → CRITICAL
  - API Key operations → HIGH
  - Service Account operations → HIGH
  - Create/Update operations → MEDIUM
  - Read operations → LOW
- **Auto-Update**: Appends new methods to `src/classification/methods.py`
- **Slack Alerts**: Sends notifications when schema changes are detected
- **Version Tracking**: Maintains history in `schema_versions.json`
- **Security Hardened**: Non-root user, minimal dependencies, read-only filesystem (except data volume)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Schema Watcher                             │
│                                                                 │
│  ┌───────────────┐    ┌──────────────┐    ┌────────────────┐  │
│  │ Fetch Schema  │ -> │  Compare     │ -> │  Classify      │  │
│  │ from Docs     │    │  Versions    │    │  New Methods   │  │
│  └───────────────┘    └──────────────┘    └────────────────┘  │
│         │                      │                    │          │
│         v                      v                    v          │
│  ┌───────────────┐    ┌──────────────┐    ┌────────────────┐  │
│  │ Extract:      │    │ Detect:      │    │ Update:        │  │
│  │ • Methods     │    │ • Added      │    │ • methods.py   │  │
│  │ • Event Types │    │ • Removed    │    │ • Slack Alert  │  │
│  │ • Fields      │    │ • Changed    │    │ • Version Log  │  │
│  └───────────────┘    └──────────────┘    └────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `METHODS_FILE` | `/app/src/classification/methods.py` | Path to methods classification file |
| `VERSIONS_FILE` | `/app/data/schema_versions.json` | Path to version history file |
| `CHECK_INTERVAL_HOURS` | `24` | Hours between checks |
| `DRY_RUN` | `false` | If true, don't update files or send alerts |
| `SLACK_WEBHOOK_URL` | - | Slack webhook URL for alerts (optional) |

### Docker Compose

```yaml
schema-watcher:
  image: schema-watcher:v1.0.0
  environment:
    - CHECK_INTERVAL_HOURS=24
    - SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
  volumes:
    - ./src/classification:/app/src/classification:rw
    - schema_watcher_data:/app/data
```

## Classification Heuristics

The watcher uses pattern matching to classify new methods:

### CRITICAL
- Any method containing: `Delete`, `Remove`, `Purge`, `Drop`
- ACL operations: `CreateAcls`, `DeleteAcls`
- Audit log changes: `UpdateAuditLogConfig`, `DeleteAuditLogConfig`
- Cluster pause: `PauseKafkaCluster`
- Service account deletion: `DeleteServiceAccount`
- Identity provider deletion: `DeleteIdentityProvider`

### HIGH
- API Key operations: `CreateApiKey`, `DeleteApiKey`, `RotateApiKey`
- Service Account operations: `CreateServiceAccount`, `UpdateServiceAccount`
- Role Binding operations: `CreateRoleBinding`, `DeleteRoleBinding`
- Identity operations: `CreateIdentityProvider`, `UpdateIdentityPool`
- Network operations: `CreatePrivateLinkAccess`, `CreatePeering`
- BYOK/Encryption: `CreateByokKey`, `EncryptTopic`

### MEDIUM
- Create operations: `CreateKafkaCluster`, `CreateTopic`
- Update operations: `UpdateEnvironment`, `AlterConfigs`
- Pause/Resume operations: `PauseConnector`, `ResumeExporter`

### LOW
- Read operations: `GetKafkaCluster`, `ListEnvironments`, `DescribeConfigs`
- Authentication: `kafka.Authentication`, `Authenticate`
- Produce/Consume: `kafka.Produce`, `kafka.Fetch`, `kafka.OffsetCommit`

## Version History Format

Each schema check creates a version entry:

```json
[
  {
    "version": 1,
    "timestamp": "2025-02-19T12:00:00Z",
    "checksum": "sha256_hash_of_docs",
    "source_url": "https://docs.confluent.io/...",
    "event_types_count": 45,
    "methods_count": 234,
    "fields_count": 28,
    "changes": {
      "methods": {
        "added": ["CreateFlinkCompute", "DeleteFlinkCompute"],
        "removed": []
      }
    }
  }
]
```

## Slack Alert Format

When changes are detected, Slack receives:

```
🔔 Confluent Audit Log Schema Change Detected

Detected at: 2025-02-19 12:00:00 UTC
Source: https://docs.confluent.io/...

New Methods Detected:

🔴 CRITICAL:
  • DeleteFlinkCompute
  • DeleteFlinkStatement

🟠 HIGH:
  • CreateFlinkApiKey

🟡 MEDIUM:
  • CreateFlinkCompute
  • UpdateFlinkStatement

Action Required:
  • Review new methods in src/classification/methods.py
  • Verify auto-classification is correct
  • Update dashboard filters if needed
  • Test forwarder routing with new event types
```

## Usage

### Run Standalone (Development)

```bash
cd schema-watcher

# Install dependencies
pip install -r requirements.txt

# Run with dry-run (no updates)
export DRY_RUN=true
export METHODS_FILE=../src/classification/methods.py
export VERSIONS_FILE=./schema_versions.json
python watcher.py

# Run actual check (updates files)
export DRY_RUN=false
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
python watcher.py
```

### Run in Docker Compose

```bash
# Build and start
docker-compose up -d schema-watcher

# View logs
docker logs -f schema-watcher

# Check version history
docker exec schema-watcher cat /app/data/schema_versions.json | jq

# Trigger immediate check (restart container)
docker-compose restart schema-watcher
```

### Manual Schema Check

```bash
# Run one-time check
docker-compose run --rm schema-watcher python watcher.py
```

## Testing

### Dry Run Mode

Test the watcher without making changes:

```bash
docker-compose run --rm \
  -e DRY_RUN=true \
  schema-watcher python watcher.py
```

### View Extracted Schema

```bash
# Check latest schema snapshot
docker exec schema-watcher ls -lh /app/data/schema_snapshot_*.json

# View snapshot content
docker exec schema-watcher cat /app/data/schema_snapshot_1.json | jq
```

## Monitoring

### Health Check

The watcher has a health check that verifies version history exists:

```bash
docker inspect schema-watcher --format='{{.State.Health.Status}}'
```

### Logs

```bash
# View real-time logs
docker logs -f schema-watcher

# Check for errors
docker logs schema-watcher 2>&1 | grep ERROR

# View last check
docker logs schema-watcher 2>&1 | grep "Starting schema check"
```

### Metrics

Key log messages to monitor:

- `Starting schema check cycle` - Check initiated
- `Extracted N methods, M event types, P fields` - Schema fetched
- `Schema changes detected!` - Changes found
- `Updated methods.py with N new methods` - File updated
- `Sent Slack alert successfully` - Alert sent
- `No schema changes detected` - No changes

## Troubleshooting

### Watcher Not Starting

```bash
# Check container status
docker-compose ps schema-watcher

# View startup logs
docker logs schema-watcher

# Verify volume mounts
docker inspect schema-watcher | jq '.[0].Mounts'
```

### Methods File Not Updating

1. Check file permissions:
```bash
ls -la src/classification/methods.py
```

2. Verify volume mount is read-write:
```bash
docker inspect schema-watcher | grep -A5 classification
```

3. Check for errors in logs:
```bash
docker logs schema-watcher 2>&1 | grep "Error updating methods file"
```

### Slack Alerts Not Sending

1. Verify webhook URL is set:
```bash
docker exec schema-watcher env | grep SLACK_WEBHOOK_URL
```

2. Test webhook manually:
```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test from schema-watcher"}' \
  $SLACK_WEBHOOK_URL
```

3. Check for HTTP errors in logs:
```bash
docker logs schema-watcher 2>&1 | grep "Error sending Slack alert"
```

## Security

### Non-Root User

The watcher runs as user `watcher` (UID 1000) for security:

```dockerfile
RUN groupadd -r watcher && useradd -r -g watcher -u 1000 watcher
USER watcher
```

### Minimal Permissions

- Read/write access only to `/app/src/classification` and `/app/data`
- No network access except HTTPS to Confluent docs and Slack
- No Docker socket access
- All capabilities dropped

### Secrets Management

Slack webhook URL should be stored in `.secrets` file or environment variable, never committed to git.

## Future Enhancements

- [ ] Support for multiple documentation sources
- [ ] Machine learning-based classification
- [ ] Diff viewer for schema changes
- [ ] Integration with CI/CD pipelines
- [ ] GitHub PR auto-creation for schema updates
- [ ] Email alerts in addition to Slack
- [ ] Webhook for custom integrations
- [ ] Schema validation against CloudEvents spec

## Changelog

### v1.0.0 (2025-02-19)

- Initial release
- Confluent docs scraping
- Heuristic-based classification
- Auto-update methods.py
- Slack alerts
- Version tracking
- Docker deployment

## License

Same as parent project (audit-forwarder).
