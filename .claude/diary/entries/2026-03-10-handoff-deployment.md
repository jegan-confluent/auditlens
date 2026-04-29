# Session Handoff: AuditLens v3.0.1 Deployment

**Date:** 2026-03-10
**Session Focus:** Production deployment of AuditLens v3.0.1 with all v3.0 features

---

## TL;DR

- ✅ Successfully deployed all 8 containers (forwarder, dashboard, MCP server, schema watcher, monitoring stack)
- ✅ Smart offset detection working correctly - auto-detected "latest" strategy for first-time setup
- ✅ Fixed Docker build issues (credential helper, MCP server paths, missing pandas dependency)
- ✅ All infrastructure healthy: Dashboard (8503), Grafana (3000), Prometheus (9090), MCP (8080)
- ⚠️ **BLOCKER:** Forwarder cannot authenticate to AUDIT source cluster - API key authentication failing

---

## Project Context

**Application:** AuditLens (audit-forwarder)
Confluent Audit Log Intelligence System - consumes audit events from Confluent Cloud, classifies by criticality, routes to dedicated topics, and visualizes in real-time dashboard.

**Tech Stack:**
- **Backend:** Python 3.11, confluent-kafka, orjson
- **Dashboard:** Streamlit, Pandas
- **Monitoring:** Prometheus, Grafana, Loki, Promtail
- **Deployment:** Docker Compose (8 containers)
- **New in v3.0:** MCP Server (FastAPI), Schema Watcher, Smart Offset Detection

**Current Focus:** Production deployment and operational readiness

---

## Session Summary

### What We Discussed/Planned
1. Deployment steps for AuditLens v3.0.1 with all new features
2. Pre-deployment verification (config files, Docker status)
3. Build strategy for 4 custom images + 4 official images
4. Health verification and monitoring setup

### What We Reviewed
- `.env` configuration (24 environment variables)
- `.secrets` file (Kafka credentials for AUDIT and DEST clusters)
- `docker-compose.yml` (8 services, 3 networks, 4 volumes)
- `scripts/verify.sh` (health check script)
- `scripts/smart-offset-detector.sh` (auto-detection logic)
- `scripts/entrypoint.sh` (container startup orchestration)
- `src/mcp/Dockerfile` and `src/mcp/requirements.txt`

### What We Changed/Fixed

#### Fix 1: Docker Credential Helper Issue
**Problem:** Build failed with `docker-credential-desktop: executable file not found in $PATH`

**Fix:** Removed `credsStore` from `~/.docker/config.json`
```bash
# Backup and update Docker config
cp ~/.docker/config.json ~/.docker/config.json.backup
cat ~/.docker/config.json | jq 'del(.credsStore)' > ~/.docker/config.json.tmp
mv ~/.docker/config.json.tmp ~/.docker/config.json
```

#### Fix 2: MCP Server Build Context
**Problem:** Dockerfile couldn't find `../config/`, `../classification/`, etc. (paths were relative)

**Fix:** Changed build context to project root
- `docker-compose.yml`: `context: .` → `dockerfile: src/mcp/Dockerfile`
- Updated all COPY paths in Dockerfile to use `src/` prefix

#### Fix 3: MCP Server Missing Pandas
**Problem:** Container crash loop with `ModuleNotFoundError: No module named 'pandas'`

**Fix:** Added pandas to `src/mcp/requirements.txt`
```python
# Data analysis (for Kafka data processing)
pandas==2.2.3
```

#### Fix 4: Smart Offset Detection Output Parsing
**Problem:** `entrypoint.sh` was capturing multi-line output from detector, causing invalid strategy error

**Fix:** Updated `entrypoint.sh` to grep only the final strategy line
```bash
# Before: captured all stdout/stderr
detected_strategy=$("$detector_script" 2>&1 | tee /dev/stderr | tail -1)

# After: grep only valid strategy names
detected_strategy=$("$detector_script" 2>&1 | grep -E "^(latest|committed|timestamp|earliest)$" | tail -1)
```

#### Fix 5: Setup Marker Volume Mount
**Problem:** `.setup-complete` was mounted as directory instead of file

**Fix:** Removed volume mount from `docker-compose.yml` - marker managed in tmpfs
```yaml
# Removed this line:
# - ./.setup-complete:/app/.setup-complete:rw

# Added comment:
# NOTE: .setup-complete marker managed in tmpfs for stateless container
```

#### Fix 6: Old Container Conflicts
**Problem:** `docker compose up` failed with container name conflicts (old Loki, Prometheus, etc.)

**Fix:** Full cleanup before fresh deployment
```bash
docker compose down
docker stop audit-forwarder c42c9ff7ced7_promtail audit-grafana loki audit-prometheus
docker rm audit-forwarder c42c9ff7ced7_promtail audit-grafana loki audit-prometheus dashboard auditlog-connect
docker compose up -d
```

### What We Tested
1. ✅ Docker build process (4 custom images)
2. ✅ Container startup (8 services)
3. ✅ Smart offset detection (chose "latest" for first-time setup)
4. ✅ Health checks via `scripts/verify.sh`
5. ✅ Dashboard accessibility (http://localhost:8503 - HTTP 200)
6. ✅ Grafana accessibility (http://localhost:3000 - HTTP 200)
7. ⚠️ Forwarder Kafka connectivity (FAILED - authentication error)

---

## Files Modified

| File | Purpose | Changes |
|------|---------|---------|
| `~/.docker/config.json` | Docker config | Removed `credsStore: "desktop"` to fix credential helper issue |
| `docker-compose.yml` | Container orchestration | Changed MCP server build context from `./src/mcp` to `.` with `dockerfile: src/mcp/Dockerfile`; Removed `.setup-complete` volume mount |
| `src/mcp/Dockerfile` | MCP server image | Updated all COPY paths to use `src/` prefix (e.g., `COPY src/mcp/server.py .`) |
| `src/mcp/requirements.txt` | MCP dependencies | Added `pandas==2.2.3` |
| `scripts/entrypoint.sh` | Container startup | Fixed output parsing with grep for strategy detection; Added stderr redirection (`>&2`) for log messages |

---

## Key Code Snippets

### scripts/entrypoint.sh - Fixed Strategy Detection
```bash
# File: scripts/entrypoint.sh (lines 28-52)

# Use smart detection
echo "[entrypoint] Using smart offset detection (zero-config mode)" >&2

# Check if smart-offset-detector.sh exists
local detector_script="/app/scripts/smart-offset-detector.sh"
if [[ ! -f "$detector_script" ]]; then
    echo "[entrypoint] WARNING: smart-offset-detector.sh not found" >&2
    echo "[entrypoint] Falling back to safe default: latest" >&2
    echo "latest"
    return 0
fi

# Run detector and capture ONLY the final result line
local detected_strategy
detected_strategy=$("$detector_script" 2>&1 | grep -E "^(latest|committed|timestamp|earliest)$" | tail -1)

if [[ -n "$detected_strategy" ]]; then
    echo "[entrypoint] Auto-detected strategy: $detected_strategy" >&2
    echo "$detected_strategy"
    return 0
else
    echo "[entrypoint] WARNING: Detection failed, using safe default: latest" >&2
    echo "latest"
    return 0
fi
```

### docker-compose.yml - Fixed MCP Server Build
```yaml
# File: docker-compose.yml (lines 265-270)

mcp-server:
  build:
    context: .                    # Changed from ./src/mcp
    dockerfile: src/mcp/Dockerfile  # Explicit path
    args:
      BUILDKIT_INLINE_CACHE: 1
```

### src/mcp/Dockerfile - Fixed COPY Paths
```dockerfile
# File: src/mcp/Dockerfile (lines 27-28, 68-79)

# Copy requirements from src/mcp directory
COPY src/mcp/requirements.txt .

# ... later in runtime stage ...

# Copy MCP server code
COPY --chown=mcp:mcp src/mcp/server.py .
COPY --chown=mcp:mcp src/mcp/__init__.py .

# Copy shared modules from src directory
COPY --chown=mcp:mcp src/config/ ./config/
COPY --chown=mcp:mcp src/classification/ ./classification/
COPY --chown=mcp:mcp src/routing/ ./routing/
COPY --chown=mcp:mcp src/anomaly/ ./anomaly/
COPY --chown=mcp:mcp src/metrics/ ./metrics/
COPY --chown=mcp:mcp src/sinks/ ./sinks/
COPY --chown=mcp:mcp src/identity/ ./identity/
COPY --chown=mcp:mcp src/confluent_api/ ./confluent_api/
```

---

## Decisions Made

| Decision | Options | Choice | Why |
|----------|---------|--------|-----|
| Docker credential storage | (1) Fix PATH to docker-credential-desktop<br>(2) Remove credsStore from config | **(2) Remove credsStore** | Faster fix; credentials not needed for public images |
| MCP server build context | (1) Keep `./src/mcp` and use `../` in Dockerfile<br>(2) Change to project root `.` | **(2) Project root** | Docker best practice; avoids parent directory access issues |
| Setup marker storage | (1) Volume mount `.setup-complete` file<br>(2) Manage in tmpfs | **(2) tmpfs** | Aligns with stateless container design; simpler deployment |
| Output parsing for strategy | (1) Parse multi-line output<br>(2) Grep only strategy keywords | **(2) Grep keywords** | More robust; avoids parsing log messages |
| Container cleanup approach | (1) Manual stop/rm each container<br>(2) docker compose down + force remove | **(2) Force cleanup** | Ensures clean state; removes all old artifacts |

---

## Implementation Status

| Item | Status | Priority | Notes |
|------|--------|----------|-------|
| Build all Docker images | ✅ | H | 4 custom images built successfully |
| Deploy all 8 containers | ✅ | H | audit-forwarder, dashboard, mcp-server, schema-watcher, prometheus, grafana, loki, promtail |
| Smart offset detection | ✅ | H | Auto-detected "latest" strategy for first-time setup |
| Dashboard UI accessible | ✅ | H | http://localhost:8503 returns HTTP 200 |
| Grafana UI accessible | ✅ | H | http://localhost:3000 returns HTTP 200 |
| MCP server running | ✅ | M | Fixed pandas dependency, container healthy |
| Schema watcher running | ✅ | M | Container healthy, ready for daily checks |
| Fix AUDIT cluster auth | ⏳ | **H** | **BLOCKER - Authentication failing** |
| Verify DEST cluster connectivity | ⏳ | H | Needs testing after AUDIT auth fixed |
| Test end-to-end event flow | ⏳ | H | Blocked by AUDIT auth issue |
| Configure Grafana dashboards | ⏳ | M | Waiting for metrics data |
| Test MCP server queries | ⏳ | L | Waiting for data in Kafka topics |

---

## Next Steps

### 1. **Immediate:** Fix AUDIT Cluster Authentication

**Action Required:**
1. Log into Confluent Cloud Console
2. Navigate to cluster `pkc-4ywp7.us-west-2.aws.confluent.cloud`
3. Check API Keys section:
   - Find key `W253C2JXNLRUWCLA`
   - Verify status = Active (not expired/deleted)
   - Verify permissions = Read access to topic `confluent-audit-log-events`

**If key missing/wrong:**
```bash
# Create new API key in Confluent Cloud UI
# - Cluster: pkc-4ywp7 (us-west-2)
# - Permission: Read on topic "confluent-audit-log-events"

# Update .secrets file
nano .secrets
# Update:
# AUDIT_API_KEY=<new-key>
# AUDIT_API_SECRET=<new-secret>

# Restart forwarder
docker compose restart audit-forwarder

# Monitor logs
docker logs -f audit-forwarder
```

### 2. **Near-term:** Verify Full System Operation

Once authentication is fixed:
```bash
# 1. Check forwarder consuming events
docker logs -f audit-forwarder | grep "Consumed"

# 2. Check events being produced to DEST topics
# Look for: "Produced to audit_events_critical/high/medium/low"

# 3. Verify dashboard showing data
open http://localhost:8503
# Check Overview tab for event counts

# 4. Check Prometheus metrics
curl http://localhost:8003/metrics | grep audit_messages

# 5. Test MCP server
curl http://localhost:8080/health
```

### 3. **Backlog:** Post-Deployment Tasks

- [ ] Configure Grafana data source (Prometheus)
- [ ] Import pre-built Grafana dashboards
- [ ] Set up alerting rules (Prometheus AlertManager)
- [ ] Test schema-watcher (trigger with `SCHEMA_CHECK_INTERVAL_HOURS=1`)
- [ ] Test MCP server with Claude Code integration
- [ ] Configure log retention in Loki
- [ ] Performance tuning (if needed)
- [ ] Document customer-specific deployment steps

---

## Blockers

| Blocker | Impact | Resolution |
|---------|--------|------------|
| **AUDIT cluster authentication failure** | **HIGH** - Forwarder cannot consume audit logs | User must verify/update API key `W253C2JXNLRUWCLA` in Confluent Cloud and update `.secrets` file |
| Docker Desktop not running (initially) | HIGH - Cannot build/run containers | **RESOLVED** - User started Docker Desktop |
| Old containers using same names | MEDIUM - Deployment conflicts | **RESOLVED** - Cleaned up with `docker compose down` + manual removal |

---

## Quick Start Commands

### Resume Next Session
```bash
# Navigate to project
cd /Users/jegan/playground/audit-forwarder-feb

# Check current status
docker ps --format "table {{.Names}}\t{{.Status}}"

# View forwarder logs
docker logs -f audit-forwarder

# Run health check
./scripts/verify.sh

# Access services
open http://localhost:8503   # Dashboard
open http://localhost:3000   # Grafana (admin/admin or check .secrets for GF_ADMIN_PASSWORD)
open http://localhost:9090   # Prometheus
```

### If Authentication Still Failing
```bash
# 1. Check credentials
grep "AUDIT_API" .secrets

# 2. Update credentials (if needed)
nano .secrets
# Update AUDIT_API_KEY and AUDIT_API_SECRET

# 3. Restart forwarder
docker compose restart audit-forwarder

# 4. Watch logs for success
docker logs -f audit-forwarder 2>&1 | grep -E "Subscribed|Consumed|ERROR"
```

### Troubleshooting
```bash
# View all container logs
docker compose logs -f

# Check specific service
docker logs -f <container-name>

# Restart specific service
docker compose restart <service-name>

# Full restart (if needed)
docker compose down
docker compose up -d

# Check resource usage
docker stats
```

---

## Environment Details

**Configuration Files:**
- `.env` - 24 environment variables (topics, ports, feature flags)
- `.secrets` - Kafka credentials (AUDIT source + DEST destination clusters)

**Current Settings:**
- Consumer Group: `audit-fwd-v3-feb`
- Audit Topic: `confluent-audit-log-events`
- Offset Strategy: `auto` (smart detection)
- Multi-topic Routing: **enabled** (critical/high/medium/low)
- DROP_LOW_EVENTS: **true** (saves 89% storage)

**Service Ports:**
- 8003 - Forwarder metrics/health
- 8503 - Dashboard (Streamlit)
- 8080 - MCP Server
- 9090 - Prometheus
- 3000 - Grafana
- 3100 - Loki

**Networks:**
- `kafka-network` - Kafka communication
- `monitoring` - Metrics collection (internal)
- `frontend-network` - User-facing services

---

## Smart Offset Detection Summary

**How it works:**
1. First-time setup: Auto-detects no `.setup-complete` marker → Uses `latest` strategy
2. Normal restart: Checks consumer lag → Uses `committed` if lag < 1 hour
3. Small backlog: Lag < 10K events → Uses `committed` (process all)
4. Medium backlog: Lag 10K-50K → Uses `timestamp` (last 24 hours)
5. Large backlog: Lag > 50K → Uses `latest` (skip old events)

**Current behavior:** Detected "First-time setup" → Using `latest` strategy → Deleting consumer group

**Override (if needed):**
```bash
# Set explicit strategy
echo "OFFSET_STRATEGY=committed" >> .env
docker compose restart audit-forwarder
```

---

## Version Information

- **AuditLens:** v3.0.1
- **Dashboard:** v11.0 (12 tabs)
- **MCP Server:** v1.0.0
- **Schema Watcher:** v1.0.0
- **Forwarder Image:** audit-forwarder:v3.0.0
- **Python:** 3.11
- **Docker Compose:** v2.x

---

## Key Learnings

1. **Docker build context matters** - Using project root (`.`) as context is cleaner than relative paths (`../`)
2. **Output parsing needs robustness** - Grep for specific patterns instead of capturing all output
3. **Stateless containers are simpler** - Avoid volume mounts for temporary files, use tmpfs
4. **Clean slate is fastest** - When containers conflict, full cleanup (`docker compose down` + manual rm) is faster than debugging
5. **Smart detection working as designed** - Auto-detected "latest" for first-time setup is correct behavior

---

**Session End:** 2026-03-10 10:42 UTC
**Next Session Priority:** Fix AUDIT cluster authentication (blocker for all data flow)
