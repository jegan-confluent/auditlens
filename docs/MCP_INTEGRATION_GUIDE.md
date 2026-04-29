# AuditLens MCP Integration Guide

**Query Confluent Audit Logs with Natural Language via Claude Code**

---

## Table of Contents

1. [What is MCP?](#what-is-mcp)
2. [Why Use MCP with AuditLens?](#why-use-mcp-with-auditlens)
3. [Setup Instructions](#setup-instructions)
4. [Example Natural Language Queries](#example-natural-language-queries)
5. [Security Configuration](#security-configuration)
6. [Troubleshooting](#troubleshooting)

---

## What is MCP?

**MCP (Model Context Protocol)** is an open protocol that lets AI agents like Claude Code access external data sources and tools. Instead of manually querying dashboards or writing SQL, you can ask questions in natural language:

```
You: "Show me all failed authorization attempts in the last hour"

Claude Code (via MCP):
  ✅ Calls AuditLens MCP tool: list_audit_events
  ✅ Filters: granted=false, time=last_1h
  ✅ Returns: 47 events from sa-prod-analytics on topics orders, payments, users
  ✅ Analysis: "Likely misconfiguration - all denials from single service account"
```

**Key Benefits:**
- **Natural Language Queries:** No need to learn dashboard filters
- **Automated Analysis:** Claude identifies patterns, anomalies, root causes
- **Cross-System Context:** Combine audit logs with code, docs, infrastructure
- **Security Investigation:** AI-assisted incident response

---

## Why Use MCP with AuditLens?

### Traditional Workflow (Manual)
```
1. Open AuditLens dashboard
2. Select filters (time, principal, method, criticality)
3. Browse table
4. Export to CSV
5. Open spreadsheet
6. Pivot table / charts
7. Write summary report
```
**Time:** 30-60 minutes

---

### MCP Workflow (Automated)
```
You: "Summarize authorization failures by principal in last 24 hours"

Claude Code:
  - Queries AuditLens via MCP
  - Groups by principal
  - Generates summary table
  - Identifies top 3 offenders
  - Suggests remediation
```
**Time:** 10 seconds

---

### Use Cases

| Persona | Manual Task | MCP Query |
|---------|-------------|-----------|
| **Security Engineer** | Check dashboard daily for suspicious activity | "Any unusual access patterns today?" |
| **Compliance Officer** | Generate quarterly audit report (30+ pages) | "Create SOC2 report for Q4 2024" |
| **SRE** | Investigate incident - correlate logs + audit events | "What happened to prod cluster at 14:37?" |
| **Data Governance** | Review access permissions across 50+ topics | "Which service accounts haven't accessed their topics in 90 days?" |

---

## Setup Instructions

### Prerequisites

1. **AuditLens Running:**
   ```bash
   ./scripts/verify.sh
   # ✓ Forwarder: http://localhost:8003
   # ✓ Dashboard: http://localhost:8503
   ```

2. **Claude Code Installed:**
   - Download from [claude.com/claude-code](https://claude.com/claude-code)
   - Or use Claude desktop app with MCP support

---

### Step 1: Start AuditLens MCP Server

AuditLens includes a built-in MCP server exposing audit log tools.

**Option A: Standalone MCP Server (Recommended for Production)**

```bash
# Start MCP server on port 8004
python3 -m src.mcp.server --port 8004

# Verify it's running
curl http://localhost:8004/health
# {"status": "healthy", "protocol_version": "2024-11-05"}
```

**Option B: Docker Compose (Development)**

```yaml
# Add to docker-compose.yml
services:
  audit-mcp-server:
    build: .
    command: python3 -m src.mcp.server --port 8004
    ports:
      - "8004:8004"
    environment:
      - METRICS_AUTH_TOKEN=${MCP_AUTH_TOKEN}
    networks:
      - kafka-network
```

```bash
docker compose up -d audit-mcp-server
```

---

### Step 2: Configure Claude Code

**2.1 Generate Authentication Token**

```bash
# Generate secure token
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Output: Xj8kL9pQ2rT5vW7yZ0aB3cD4eF5gH6iJ7kL8mN9oP0qR1s
```

Save this token - you'll need it for both server and client configuration.

**2.2 Add to Environment**

```bash
# Add to .env file
MCP_AUTH_TOKEN=Xj8kL9pQ2rT5vW7yZ0aB3cD4eF5gH6iJ7kL8mN9oP0qR1s
MCP_SERVER_PORT=8004
```

**2.3 Configure Claude Code MCP Client**

Create `~/.config/claude-code/mcp.json` (macOS/Linux) or `%APPDATA%\claude-code\mcp.json` (Windows):

```json
{
  "mcpServers": {
    "auditlens": {
      "url": "http://localhost:8004",
      "description": "Confluent Audit Log Intelligence",
      "auth": {
        "type": "bearer",
        "token": "Xj8kL9pQ2rT5vW7yZ0aB3cD4eF5gH6iJ7kL8mN9oP0qR1s"
      },
      "tools": [
        "list_audit_events",
        "search_audit_events",
        "get_security_events",
        "export_to_s3",
        "export_to_gcs",
        "analyze_auth_failures",
        "get_access_transparency",
        "get_forwarder_status",
        "get_export_job_status"
      ]
    }
  }
}
```

**2.4 Restart Claude Code**

```bash
# Restart Claude Code to load MCP configuration
# On macOS: Cmd+Q then reopen
# On Windows: Right-click taskbar → Quit, then reopen
```

---

### Step 3: Verify MCP Integration

**3.1 Test Connection**

In Claude Code, type:

```
Check if AuditLens MCP server is accessible
```

Expected response:
```
✓ Connected to AuditLens MCP server
✓ Available tools:
  - list_audit_events
  - search_audit_events
  - get_security_events
  - export_to_s3
  - analyze_auth_failures
  - get_forwarder_status
```

**3.2 Test Query**

```
Show me the last 10 audit events
```

Expected response:
```
Retrieved 10 audit events from AuditLens:

1. 2025-02-19 15:23:45 - sa-prod-analytics - kafka.Fetch - orders - SUCCESS
2. 2025-02-19 15:22:11 - user:jane@company.com - kafka.CreateTopics - dev-test - SUCCESS
3. 2025-02-19 15:20:33 - sa-terraform-ci - kafka.DeleteTopics - old-data - SUCCESS
...
```

---

## Example Natural Language Queries

### Security Queries

#### Query 1: Detect Authorization Failures

**You ask:**
```
Are there any repeated authorization failures in the last hour?
```

**Claude Code:**
1. Calls `list_audit_events` with filters:
   ```json
   {
     "start_time": "2025-02-19T14:23:00Z",
     "end_time": "2025-02-19T15:23:00Z",
     "granted": false
   }
   ```
2. Groups results by principal
3. Responds:
   ```
   Yes, found 47 authorization failures:

   Principal: sa-prod-analytics
   Failures: 47
   Resources: orders (23), payments (15), users (9)
   Time: All within 60 seconds (14:35-14:36)
   Source IP: 10.0.1.45

   Analysis: Likely misconfiguration, not attack:
   - Single source IP (not distributed)
   - All failures on Read operation
   - Service account exists (not deleted)

   Recommendation: Check ACLs for sa-prod-analytics on these topics.
   ```

---

#### Query 2: Investigate Suspicious Access

**You ask:**
```
Did anyone access production topics after 6 PM yesterday?
```

**Claude Code:**
1. Determines time range (yesterday 18:00-23:59)
2. Calls `list_audit_events` filtering by:
   ```json
   {
     "start_time": "2025-02-18T18:00:00Z",
     "end_time": "2025-02-18T23:59:59Z",
     "cluster_id": "lkc-production"
   }
   ```
3. Responds:
   ```
   Yes, 3 after-hours accesses detected:

   1. 19:45:23 - user:alice@ops.com - kafka.UpdateClusterConfig
      Action: Changed retention.ms on prod-orders
      Justification: Likely maintenance window

   2. 21:15:47 - sa-emergency-runbook - kafka.Fetch on prod-payments
      Read: 1,247 messages
      Justification: Incident response (check PagerDuty logs)

   3. 22:33:11 - user:contractor@external.com - kafka.Fetch on prod-users
      ⚠️ DENIED (no access)
      Risk: HIGH - contractor should not access production

   Recommendation: Review contractor's attempted access.
   ```

---

### Compliance Queries

#### Query 3: Generate SOC2 Evidence

**You ask:**
```
Generate a SOC2 audit report for topic customer-pii in December 2024
```

**Claude Code:**
1. Calls `list_audit_events`:
   ```json
   {
     "start_time": "2024-12-01T00:00:00Z",
     "end_time": "2024-12-31T23:59:59Z"
   }
   ```
2. Filters events containing `customer-pii`
3. Analyzes access patterns
4. Generates report:
   ```markdown
   # SOC2 Audit Report: customer-pii Access Log
   **Period:** December 1-31, 2024
   **Generated:** 2025-02-19 by AuditLens MCP

   ## Executive Summary
   - Total Access Events: 1,247
   - Unique Principals: 3
   - Failed Access Attempts: 5
   - Compliance Status: ✅ PASS

   ## Access Summary by Principal
   | Principal               | Access Type | Event Count | Last Access |
   |-------------------------|-------------|-------------|-------------|
   | sa-compliance-exporter  | Read        | 1,150       | 2024-12-31  |
   | user:jane@legal.com     | Read        | 92          | 2024-12-15  |
   | user:bob@finance.com    | Read        | 5           | 2024-12-03  |

   ## Failed Access Attempts
   | Time       | Principal           | Reason          |
   |------------|---------------------|-----------------|
   | 2024-12-05 | sa-analytics-team   | DENIED (no ACL) |
   | 2024-12-12 | user:contractor     | DENIED (no ACL) |
   | 2024-12-20 | sa-external-vendor  | DENIED (no ACL) |

   ## Compliance Controls Verified
   ✅ AU-2: Audit Events - All access to customer-pii logged
   ✅ AU-3: Content of Audit Records - Principal, time, resource captured
   ✅ AC-2: Account Management - Only authorized accounts granted access
   ✅ AC-6: Least Privilege - Denials demonstrate RBAC enforcement

   ## Attestation
   This report was generated from Confluent Audit Logs via AuditLens MCP.
   All data is cryptographically signed and tamper-evident.
   ```

---

#### Query 4: Access Certification

**You ask:**
```
Which service accounts can access PII topics and when did they last use that access?
```

**Claude Code:**
1. Searches for PII-related topics
2. Groups access by service account
3. Calculates last access time
4. Responds:
   ```
   Service Account Access to PII Topics:

   1. sa-compliance-exporter
      Topics: customer-pii, customer-ssn, patient-records
      Last Access: 2025-02-19 (active)
      Justification: Compliance data export (approved)

   2. user:jane@legal.com
      Topics: customer-pii
      Last Access: 2025-01-05 (44 days ago)
      Status: ⚠️ Stale - review if still needed

   3. sa-analytics-team
      Topics: customer-pii, customer-ssn
      Last Access: N/A (all attempts DENIED ✓)
      Status: ✅ Correctly blocked

   4. user:bob@finance.com
      Topics: customer-ssn
      Last Access: 2024-11-01 (109 days ago)
      Status: ⚠️ STALE - revoke access

   Recommendation: Revoke bob's access (unused for 109 days).
   Review jane's access (44 days - near threshold).
   ```

---

### Operational Queries

#### Query 5: Incident Investigation

**You ask:**
```
What happened to our Kafka cluster at 2:37 PM today? Show me all CRITICAL and HIGH events in a 10-minute window.
```

**Claude Code:**
1. Calculates time range (14:32-14:42)
2. Calls `list_audit_events`:
   ```json
   {
     "start_time": "2025-02-19T14:32:00Z",
     "end_time": "2025-02-19T14:42:00Z"
   }
   ```
3. Filters CRITICAL + HIGH events
4. Creates timeline:
   ```
   Incident Timeline (14:32-14:42):

   14:32:15 [MEDIUM] kafka.CreateTopics
            Principal: sa-app-team
            Topic: orders-v2
            Status: SUCCESS

   14:34:22 [HIGH] UpdateKafkaClusterConfig
            Principal: sa-platform-team
            Config: retention.ms = 86400000 → 3600000 (24h → 1h)
            Status: SUCCESS

   14:35:47 [HIGH] kafka.DeleteTopics
            Principal: sa-terraform-ci
            Topic: orders-v1
            Status: SUCCESS

   14:36:10 [CRITICAL] kafka.Produce (multiple producers)
            Topic: orders-v2
            Status: FAILURE
            Error: Topic not fully replicated

   14:37:00 OUTAGE DETECTED

   ROOT CAUSE ANALYSIS:
   1. App team created new topic orders-v2
   2. Platform team reduced retention (unrelated)
   3. Terraform deleted old topic orders-v1
   4. Producers not updated - wrote to non-existent topic
   5. Consumer lag spiked → cascading failures

   RECOMMENDATION:
   - Implement topic migration runbook
   - Require producer config updates before deleting old topics
   - Add canary checks for topic existence before writes
   ```

---

#### Query 6: Anomaly Detection

**You ask:**
```
Are there any unusual patterns in today's audit logs?
```

**Claude Code:**
1. Calls `analyze_auth_failures` for baseline
2. Compares to historical averages
3. Flags anomalies:
   ```
   Anomalies Detected:

   1. API Key Creation Spike
      Normal: 2-3 keys/day
      Today: 15 keys created
      Time: 10:00-11:00 AM
      Principal: user:contractor@external.com (12 keys!)
      Risk: HIGH - investigate credential harvesting

   2. After-Hours Topic Deletion
      Normal: 0 deletions after 8 PM
      Today: 3 topics deleted at 2:47 AM
      Principal: sa-terraform-ci
      Topics: prod-orders-v1, prod-payments-v1, prod-users-v1
      Risk: CRITICAL - verify if planned maintenance

   3. Failed Schema Registrations
      Normal: <1% failure rate
      Today: 23% failure rate (47 of 200 attempts)
      Principal: sa-orders-producer
      Error: INCOMPATIBLE_SCHEMA
      Risk: MEDIUM - breaking schema change

   Recommendations:
   1. Immediately revoke contractor's API keys
   2. Contact platform team - confirm Terraform run was planned
   3. Review schema change - coordinate with consumers
   ```

---

### Data Governance Queries

#### Query 7: Find Stale Permissions

**You ask:**
```
Which service accounts have not used their topic access in 90+ days?
```

**Claude Code:**
1. Calls `list_audit_events` for all service accounts
2. Groups by topic access
3. Calculates last access time
4. Filters >90 days:
   ```
   Stale Service Account Permissions:

   1. sa-legacy-connector
      Topics: old-events-v1, deprecated-logs
      Last Access: 147 days ago
      Status: HIGH RISK - likely deprecated
      Recommendation: Revoke ACLs

   2. sa-dev-testing
      Topics: prod-orders (Read ACL exists)
      Last Access: 92 days ago
      Status: MEDIUM RISK - dev SA with prod access
      Recommendation: Review if needed, revoke if not

   3. sa-contractor-temp
      Topics: staging-data
      Last Access: 115 days ago
      Status: LOW RISK - staging only
      Recommendation: Revoke (contractor likely offboarded)

   Total Stale Permissions: 3
   Estimated Risk Reduction: Removing 3 unused access grants
   ```

---

#### Query 8: Cross-Environment Access Audit

**You ask:**
```
Show me any service accounts that access both production and development environments
```

**Claude Code:**
1. Calls `list_audit_events` for all environments
2. Groups by principal + environment
3. Flags cross-environment access:
   ```
   Cross-Environment Access Detected:

   1. sa-platform-team
      Environments: lkc-production, lkc-staging, lkc-dev
      Justification: ✅ Platform team needs full access
      Last Access: Today
      Status: APPROVED

   2. sa-data-pipeline
      Environments: lkc-production, lkc-dev
      Access Pattern:
        - Reads from prod-orders (production)
        - Writes to dev-test-sink (development)
      Justification: ⚠️ QUESTIONABLE - dev SA writing to prod?
      Status: REVIEW NEEDED

   3. user:alice@ops.com
      Environments: lkc-production, lkc-dev
      Access Pattern:
        - UpdateKafkaClusterConfig (both envs)
      Justification: ✅ Ops team maintains both
      Status: APPROVED

   Recommendation: Review sa-data-pipeline - should not write prod data to dev.
   ```

---

## MCP Tools Reference

### Available Tools

| Tool | Description | Example Query |
|------|-------------|---------------|
| `list_audit_events` | Retrieve events with filtering | "Show all events from sa-prod in last hour" |
| `search_audit_events` | Full-text search | "Find all events mentioning 'customer-pii'" |
| `get_security_events` | Security-focused events only | "Show me auth failures" |
| `export_to_s3` | Export logs to S3 | "Export December logs to S3 bucket audit-archive" |
| `export_to_gcs` | Export logs to GCS | "Export Q4 logs to GCS bucket compliance-logs" |
| `analyze_auth_failures` | Failure pattern analysis | "Analyze auth failures by principal" |
| `get_access_transparency` | Confluent personnel access | "Show access transparency events" |
| `get_forwarder_status` | Health metrics | "Is the forwarder healthy?" |

### Tool Parameters

#### `list_audit_events`
```json
{
  "start_time": "2025-02-19T00:00:00Z",  // ISO8601 format
  "end_time": "2025-02-19T23:59:59Z",
  "event_type": "authorization",         // authentication, authorization, request
  "service": "kafka",                    // kafka, schema-registry, ksqldb, flink
  "principal": "sa-prod-analytics",
  "granted": false,                      // true, false, or omit
  "cluster_id": "lkc-production",
  "limit": 100,
  "offset": 0
}
```

#### `search_audit_events`
```json
{
  "query": "customer-pii",               // Search string
  "fields": ["resourceName", "methodName"], // Fields to search
  "start_time": "2025-02-01T00:00:00Z",
  "end_time": "2025-02-28T23:59:59Z",
  "limit": 50
}
```

#### `analyze_auth_failures`
```json
{
  "start_time": "2025-02-19T00:00:00Z",
  "end_time": "2025-02-19T23:59:59Z",
  "group_by": "principal",               // principal, cluster, client_ip, hour
  "min_failures": 5                      // Minimum failure count to include
}
```

---

## Security Configuration

### Authentication Methods

#### Bearer Token (Recommended)

**Server Configuration:**
```bash
# .env
METRICS_AUTH_ENABLED=true
METRICS_AUTH_TOKEN=Xj8kL9pQ2rT5vW7yZ0aB3cD4eF5gH6iJ7kL8mN9oP0qR1s
```

**Client Configuration:**
```json
{
  "mcpServers": {
    "auditlens": {
      "auth": {
        "type": "bearer",
        "token": "Xj8kL9pQ2rT5vW7yZ0aB3cD4eF5gH6iJ7kL8mN9oP0qR1s"
      }
    }
  }
}
```

**Security Benefits:**
- Constant-time token comparison (prevents timing attacks)
- Token rotation support
- No password transmission

---

#### Basic Auth (Alternative)

**Server Configuration:**
```bash
# .env
METRICS_AUTH_ENABLED=true
METRICS_AUTH_USERNAME=auditlens
METRICS_AUTH_PASSWORD=your-secure-password
```

**Client Configuration:**
```json
{
  "mcpServers": {
    "auditlens": {
      "auth": {
        "type": "basic",
        "username": "auditlens",
        "password": "your-secure-password"
      }
    }
  }
}
```

---

### IP Allowlist (Additional Security Layer)

```bash
# .env
METRICS_AUTH_ALLOWED_IPS=127.0.0.1,10.0.1.0/24,192.168.1.100
```

**Behavior:**
- Requests from allowed IPs + valid token = ✅ Allowed
- Requests from allowed IPs, no token configured = ✅ Allowed (IP-only mode)
- Requests from other IPs without token = ❌ Denied
- Localhost (127.0.0.1, ::1) always allowed

---

### Token Rotation

**1. Generate New Token:**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# New token: YnZ3aA9cB2dE4fG5hI6jK7lM8nO9pQ0rS1tU2vW3xY4zA5b
```

**2. Update Server:**
```bash
# .env
METRICS_AUTH_TOKEN=YnZ3aA9cB2dE4fG5hI6jK7lM8nO9pQ0rS1tU2vW3xY4zA5b

# Restart MCP server
docker compose restart audit-mcp-server
```

**3. Update Claude Code Client:**
```json
{
  "mcpServers": {
    "auditlens": {
      "auth": {
        "token": "YnZ3aA9cB2dE4fG5hI6jK7lM8nO9pQ0rS1tU2vW3xY4zA5b"
      }
    }
  }
}
```

**4. Restart Claude Code**

**Best Practice:** Rotate tokens quarterly or after personnel changes.

---

### Network Security

#### Production Deployment

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  Claude Code    │─────▶│  API Gateway    │─────▶│  MCP Server     │
│  (User laptop)  │ HTTPS│  (nginx/ALB)    │ HTTP │  (Internal)     │
└─────────────────┘      └─────────────────┘      └─────────────────┘
                              ↓
                         TLS termination
                         Rate limiting
                         IP filtering
```

**nginx Configuration:**
```nginx
server {
    listen 443 ssl;
    server_name auditlens-mcp.company.com;

    ssl_certificate /etc/ssl/certs/auditlens.crt;
    ssl_certificate_key /etc/ssl/private/auditlens.key;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=mcp:10m rate=10r/s;
    limit_req zone=mcp burst=20;

    location / {
        proxy_pass http://audit-mcp-server:8004;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

### Audit Logging for MCP Access

Enable MCP access logging:

```bash
# .env
MCP_AUDIT_LOG_ENABLED=true
MCP_AUDIT_LOG_PATH=/var/log/auditlens-mcp.log
```

**Log Format:**
```json
{
  "timestamp": "2025-02-19T15:23:45Z",
  "client_ip": "192.168.1.100",
  "user": "claude-code-session-abc123",
  "tool": "list_audit_events",
  "parameters": {
    "start_time": "2025-02-19T14:00:00Z",
    "granted": false
  },
  "result_count": 47,
  "duration_ms": 125
}
```

**Use Cases:**
- Track who queried what via Claude Code
- Detect abuse (excessive queries)
- Compliance (audit the auditing system)

---

## Troubleshooting

### Issue 1: "Cannot connect to MCP server"

**Symptoms:**
```
Claude Code: ❌ Error: Connection refused to http://localhost:8004
```

**Solutions:**

1. **Verify MCP server is running:**
   ```bash
   curl http://localhost:8004/health
   # Expected: {"status": "healthy"}
   ```

2. **Check logs:**
   ```bash
   docker logs audit-mcp-server --tail 50
   # Look for startup errors
   ```

3. **Check port availability:**
   ```bash
   lsof -i :8004
   # Expected: python3 process
   ```

4. **Restart MCP server:**
   ```bash
   docker compose restart audit-mcp-server
   ```

---

### Issue 2: "Unauthorized" error

**Symptoms:**
```
Claude Code: ❌ 401 Unauthorized
```

**Solutions:**

1. **Verify token matches:**
   ```bash
   # Server side (.env)
   echo $METRICS_AUTH_TOKEN

   # Client side (mcp.json)
   cat ~/.config/claude-code/mcp.json | jq '.mcpServers.auditlens.auth.token'
   ```

2. **Test token manually:**
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" \
        http://localhost:8004/metrics
   # Expected: Prometheus metrics output
   ```

3. **Regenerate token if lost:**
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   # Update both server and client
   ```

---

### Issue 3: "No data returned"

**Symptoms:**
```
Claude Code: Successfully connected, but returns 0 events
```

**Solutions:**

1. **Verify forwarder is processing events:**
   ```bash
   curl http://localhost:8003/metrics | grep processed_messages_total
   # audit_forwarder_processed_messages_total 12547
   ```

2. **Check dashboard shows data:**
   ```bash
   open http://localhost:8503
   # Navigate to Audit Trail - should show events
   ```

3. **Verify time range:**
   ```
   You: "Show events from last 24 hours"
   # vs
   You: "Show events from December 2024"
   # Adjust time range if empty
   ```

---

### Issue 4: Claude Code not recognizing MCP tools

**Symptoms:**
```
Claude Code: "I don't have access to audit log tools"
```

**Solutions:**

1. **Restart Claude Code:**
   - macOS: Cmd+Q then reopen
   - Windows: Right-click taskbar → Quit, then reopen

2. **Verify mcp.json syntax:**
   ```bash
   cat ~/.config/claude-code/mcp.json | jq .
   # Should parse without errors
   ```

3. **Check Claude Code logs:**
   ```bash
   # macOS
   tail -f ~/Library/Logs/Claude\ Code/mcp.log

   # Windows
   type %APPDATA%\Claude Code\Logs\mcp.log
   ```

4. **Explicitly ask Claude Code:**
   ```
   You: "List available MCP tools"
   ```

---

### Issue 5: Slow query performance

**Symptoms:**
```
Claude Code: Query takes 30+ seconds
```

**Solutions:**

1. **Reduce time range:**
   ```
   Bad:  "Show all events from 2024"
   Good: "Show events from last 7 days"
   ```

2. **Add filters:**
   ```
   Bad:  "Show all events"
   Good: "Show CRITICAL events from sa-prod-analytics in last hour"
   ```

3. **Check forwarder metrics:**
   ```bash
   curl http://localhost:8003/metrics | grep consumer_lag
   # High lag = slow queries
   ```

4. **Optimize dashboard data loading:**
   ```bash
   # Reduce max events in config
   # dashboard/config.py
   MAX_EVENTS_PER_QUERY = 1000  # Default 5000
   ```

---

## Advanced Use Cases

### Multi-Step Analysis

**Scenario:** Investigate incident with context from multiple sources

**You ask:**
```
At 14:37 today our Kafka cluster had an outage.
1. Show me audit events around that time
2. Correlate with error logs in ./logs/kafka-broker.log
3. Check if any infrastructure changes in terraform state
4. Generate incident report
```

**Claude Code:**
1. Calls AuditLens MCP: `list_audit_events(14:32-14:42)`
2. Reads local log file: `./logs/kafka-broker.log`
3. Runs `terraform state list` and `terraform show`
4. Correlates all data sources
5. Generates report:
   ```markdown
   # Incident Report: Kafka Outage 2025-02-19 14:37

   ## Timeline
   14:34:22 - Terraform applied config change (retention.ms)
   14:35:47 - Topic deleted (orders-v1)
   14:36:10 - Producers failed (topic not found)
   14:37:00 - Broker errors spiked (kafka-broker.log)

   ## Root Cause
   Terraform deleted topic before producers updated

   ## Impact
   5 minutes of producer failures, 127 messages lost

   ## Remediation
   1. Implement topic migration runbook
   2. Add pre-delete validation
   3. Configure producer topic auto-creation
   ```

**Value:** Single natural language query → complete incident report with cross-system correlation

---

### Scheduled Compliance Reports

**Scenario:** Weekly compliance report sent to management

**Setup:**
```bash
# Create script: weekly-report.sh
#!/bin/bash
claude-code --mcp-query "
Generate SOC2 compliance report for last 7 days.
Include:
- Total access events
- Failed access attempts
- New API keys created
- Permission changes
- Export to PDF
"
```

**Cron job:**
```bash
0 9 * * MON /home/user/weekly-report.sh
# Every Monday at 9 AM
```

---

## Best Practices

### 1. Query Optimization

**Do:**
- ✅ Add time ranges: "in last 24 hours"
- ✅ Filter by principal/topic: "from sa-prod-analytics"
- ✅ Specify criticality: "CRITICAL and HIGH events"

**Don't:**
- ❌ "Show all events" (unbounded query)
- ❌ "Search for anything suspicious" (vague)
- ❌ Query year+ of data without filters

---

### 2. Security Hygiene

**Do:**
- ✅ Rotate tokens quarterly
- ✅ Use separate tokens for dev/prod MCP servers
- ✅ Enable audit logging for MCP access
- ✅ Restrict Claude Code to specific users

**Don't:**
- ❌ Share MCP tokens in Slack/email
- ❌ Commit tokens to git (use environment variables)
- ❌ Use same token for multiple services

---

### 3. Result Validation

**Do:**
- ✅ Cross-check Claude's analysis with dashboard
- ✅ Verify event counts make sense
- ✅ Review recommendations before implementing

**Don't:**
- ❌ Blindly trust AI-generated security conclusions
- ❌ Skip manual verification for critical incidents
- ❌ Use AI analysis as sole source for compliance reports

---

## Next Steps

- **Read:** [Customer Use Cases](./CUSTOMER_USE_CASES.md) for scenario-based queries
- **Read:** [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) for alert configuration
- **Read:** [Compliance Templates](./COMPLIANCE_TEMPLATES.md) for pre-built report formats

---

**Version:** 1.0
**Last Updated:** 2025-02-19
**Compatible with:** AuditLens v11.0+, Claude Code 1.5+, MCP Protocol 2024-11-05
