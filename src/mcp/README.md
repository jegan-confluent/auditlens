# MCP Server for Audit Forwarder

Model Context Protocol (MCP) server that provides AI agents with structured access to Confluent audit log data.

## Overview

The MCP server exposes audit log intelligence through a standard protocol that can be consumed by AI assistants like Claude. It provides:

- **Query Tools**: Search and filter audit events by time, principal, cluster, event type
- **Security Analysis**: Analyze authentication failures, authorization denials, and access transparency events
- **Export Tools**: Export logs to S3/GCS for long-term storage and compliance
- **Forwarder Monitoring**: Check health and metrics of the audit forwarder

## Architecture

```
┌─────────────┐
│ AI Agent    │
│ (Claude)    │
└──────┬──────┘
       │ MCP Protocol
       │ (HTTP/JSON)
       ▼
┌─────────────────────┐
│  MCP Server         │
│  Port 8080          │
│  - Tools            │
│  - Resources        │
│  - Health Check     │
└──────┬──────────────┘
       │
       ├─► Kafka Topics (audit_events_*)
       ├─► S3/GCS (exports)
       └─► Forwarder Metrics
```

## Tools

### Query Tools

1. **list_audit_events** - Retrieve audit events with filtering
   - Filter by: time window, event type, service, principal, cluster
   - Pagination support (offset/limit)
   - Returns structured event data

2. **search_audit_events** - Full-text search across audit logs
   - Search across all text fields or specific fields
   - Time window filtering
   - Returns matching events with context

3. **get_security_events** - Get security-relevant events
   - Authentication failures
   - Authorization denials
   - Access transparency events (Confluent personnel access)
   - Severity filtering (all/high/critical)

### Export Tools

4. **export_to_s3** - Export audit logs to Amazon S3
   - Configurable format (Parquet, JSON, CSV)
   - Compression (Snappy, Gzip, None)
   - Partitioning (hour, day, event_type, service)
   - Returns job ID for tracking

5. **export_to_gcs** - Export audit logs to Google Cloud Storage
   - Same features as S3 export
   - GCP project ID support

### Analysis Tools

6. **analyze_auth_failures** - Analyze authentication/authorization failures
   - Group by: principal, cluster, client IP, API key, hour
   - Minimum failure threshold
   - Anomaly detection
   - Actionable recommendations

7. **get_access_transparency** - Retrieve Access Transparency events
   - Track Confluent personnel access to customer resources
   - Filter by resource type (cluster, environment, organization)
   - Compliance reporting

### Monitoring Tools

8. **get_forwarder_status** - Check forwarder health and metrics
   - Uptime, processing rate, error count
   - Consumer lag metrics
   - Sink status (Kafka, S3, GCS)

9. **get_export_job_status** - Check export job progress
   - Query by job ID
   - Returns status, progress, errors

## Resources

The MCP server also exposes static resources:

1. **audit://schema/v1** - JSON Schema for audit events
2. **audit://categories** - Event type categories and descriptions
3. **audit://methods** - Method names by service
4. **metrics://forwarder** - Current forwarder metrics

## Quick Start

### 1. Set Environment Variables

```bash
# Generate authentication token
export MCP_AUTH_TOKEN=$(openssl rand -hex 32)

# Add to .env file
echo "MCP_AUTH_TOKEN=$MCP_AUTH_TOKEN" >> .env

# Optional: Cloud storage credentials for exports
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export GCS_PROJECT_ID=your_project
```

### 2. Start with Docker Compose

```bash
# Build and start all services including MCP server
docker-compose up -d

# Check MCP server logs
docker logs -f audit-mcp-server

# Test health endpoint
curl http://localhost:8080/health
```

### 3. Test MCP Server

```bash
# List available tools
curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  http://localhost:8080/tools

# Query audit events
curl -X POST \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "list_audit_events",
    "arguments": {
      "start_time": "2026-03-01T00:00:00Z",
      "end_time": "2026-03-10T23:59:59Z",
      "limit": 10
    }
  }' \
  http://localhost:8080/call_tool
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCP_PORT` | No | 8080 | MCP server port |
| `MCP_HOST` | No | 0.0.0.0 | Bind address |
| `MCP_AUTH_TOKEN` | No | - | Bearer token for API auth |
| `BOOTSTRAP_SERVERS` | Yes | - | Kafka bootstrap servers |
| `SASL_USERNAME` | Yes | - | Kafka API key |
| `SASL_PASSWORD` | Yes | - | Kafka API secret |
| `AUDIT_TOPIC_CRITICAL` | No | audit_events_critical | Critical events topic |
| `AUDIT_TOPIC_HIGH` | No | audit_events_high | High priority events topic |
| `AUDIT_TOPIC_MEDIUM` | No | audit_events_medium | Medium priority events topic |
| `AWS_ACCESS_KEY_ID` | No | - | AWS credentials for S3 exports |
| `AWS_SECRET_ACCESS_KEY` | No | - | AWS credentials for S3 exports |
| `GCS_PROJECT_ID` | No | - | GCP project for GCS exports |

### Resource Limits

The docker-compose configuration sets conservative resource limits:

- **CPU**: 1.0 limit, 0.25 reservation
- **Memory**: 1GB limit, 256MB reservation

Adjust in `docker-compose.yml` based on your workload.

### Security

The MCP server container follows security best practices:

1. **Non-root user** (uid: 1001, gid: 1001)
2. **Read-only filesystem** (with tmpfs for /tmp and /app/cache)
3. **No new privileges** (security_opt: no-new-privileges)
4. **Minimal capabilities** (drop ALL, add NET_BIND_SERVICE)
5. **Bearer token authentication** (MCP_AUTH_TOKEN)
6. **Network segmentation** (kafka-network, monitoring, frontend-network)

## Multi-Cloud Compatibility

The MCP server is designed to work across all deployment environments:

### AWS
- Native S3 support for exports
- IAM role support (set AWS_ACCESS_KEY_ID/SECRET)
- VPC networking compatible

### GCP
- Native GCS support for exports
- Service account support (GOOGLE_APPLICATION_CREDENTIALS)
- VPC networking compatible

### Azure
- S3-compatible storage (MinIO, etc.)
- Virtual network compatible

### On-Premises
- Self-hosted Kafka clusters
- Local storage or S3-compatible object storage
- Docker Swarm or Kubernetes deployment

## API Examples

### List Recent Security Events

```bash
curl -X POST \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "get_security_events",
    "arguments": {
      "start_time": "2026-03-10T00:00:00Z",
      "end_time": "2026-03-10T23:59:59Z",
      "severity": "high",
      "include_access_transparency": true
    }
  }' \
  http://localhost:8080/call_tool
```

### Export Logs to S3

```bash
curl -X POST \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "export_to_s3",
    "arguments": {
      "bucket": "my-audit-logs",
      "prefix": "confluent/audit/",
      "start_time": "2026-03-01T00:00:00Z",
      "end_time": "2026-03-07T23:59:59Z",
      "format": "parquet",
      "compression": "snappy",
      "partition_by": "day"
    }
  }' \
  http://localhost:8080/call_tool
```

### Analyze Auth Failures

```bash
curl -X POST \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "analyze_auth_failures",
    "arguments": {
      "start_time": "2026-03-10T00:00:00Z",
      "end_time": "2026-03-10T23:59:59Z",
      "group_by": "principal",
      "min_failures": 5
    }
  }' \
  http://localhost:8080/call_tool
```

## Health Checks

The MCP server exposes a health endpoint:

```bash
curl http://localhost:8080/health
```

Returns:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "kafka_connected": true,
  "cache_size": 1234
}
```

## Monitoring

### Prometheus Metrics

The MCP server is integrated with the monitoring stack:

- **Network**: Connected to `monitoring` network
- **Metrics**: Exposed via Prometheus client library
- **Dashboards**: Available in Grafana

Key metrics:
- `mcp_requests_total` - Total API requests
- `mcp_request_duration_seconds` - Request latency
- `mcp_errors_total` - Error count
- `mcp_kafka_messages_consumed` - Messages read from Kafka
- `mcp_export_jobs_total` - Export jobs created
- `mcp_cache_hits_total` - Cache hit rate

### Logs

View MCP server logs:

```bash
# Real-time logs
docker logs -f audit-mcp-server

# Last 100 lines
docker logs --tail 100 audit-mcp-server

# Logs in Loki (via Grafana)
# Visit http://localhost:3000 and query:
# {container_name="audit-mcp-server"}
```

## Development

### Local Testing

```bash
# Run MCP server directly (without Docker)
cd src/mcp
python -m pip install -r requirements.txt
python server.py
```

### Building

```bash
# Build MCP server image
docker build -t audit-mcp-server:v1.0.0 -f src/mcp/Dockerfile src/mcp

# Build with BuildKit cache
DOCKER_BUILDKIT=1 docker build \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  -t audit-mcp-server:v1.0.0 \
  -f src/mcp/Dockerfile \
  src/mcp
```

### Debugging

Enable debug logging:

```bash
# In .env file
LOG_LEVEL=DEBUG

# Restart container
docker-compose restart mcp-server
```

## Troubleshooting

### MCP server won't start

1. Check logs: `docker logs audit-mcp-server`
2. Verify Kafka connection: `echo $BOOTSTRAP_SERVERS`
3. Check port conflicts: `lsof -i :8080`
4. Verify authentication: `echo $MCP_AUTH_TOKEN`

### Can't query events

1. Ensure audit forwarder is running: `docker ps | grep audit-forwarder`
2. Check topic names: `docker exec audit-mcp-server env | grep AUDIT_TOPIC`
3. Verify consumer group has committed offsets
4. Check network connectivity: `docker network inspect kafka-network`

### Export fails

1. Verify cloud credentials are set
2. Check S3/GCS bucket permissions
3. Ensure bucket exists
4. Check export job logs: `curl http://localhost:8080/call_tool -d '{"name":"get_export_job_status","arguments":{"job_id":"xyz"}}'`

### High memory usage

1. Reduce cache size in server.py
2. Adjust resource limits in docker-compose.yml
3. Monitor with: `docker stats audit-mcp-server`

## License

Apache 2.0

## Support

For issues and questions:
- Check logs: `docker logs audit-mcp-server`
- Review health: `curl http://localhost:8080/health`
- File GitHub issue with logs and config (redact secrets!)
