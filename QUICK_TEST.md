# Quick Testing Guide

Run automated tests in one command!

## Prerequisites

1. Ensure you have `.env` and `.secrets` files configured
2. Docker Desktop must be running
3. You're in the `audit-forwarder` directory

## Run All Tests (Steps 1-6)

```bash
./scripts/test-setup.sh
```

This single command will:
- ✅ **Step 1:** Verify all prerequisites (Docker, Python, env files)
- ✅ **Step 2:** Build the new secure image (v2.1.0)
- ✅ **Step 3:** Run security scan with Trivy
- ✅ **Step 4:** Test forwarder in dry-run mode for 60 seconds
- ✅ **Step 5:** Verify metrics and health endpoints
- ✅ **Step 6:** Start full Docker Compose stack

**Total time:** ~5-8 minutes

## What You'll See

The script provides real-time feedback:
```
========================================
🧪 Audit Forwarder - Automated Testing
========================================

Step 1/6: Verify Prerequisites
✓ Docker installed: 24.0.5
✓ Docker Compose installed: 2.20.2
✓ Python installed: 3.11.5
✓ Docker daemon running
✓ Found .env file
✓ Found .secrets file

Step 2/6: Build New Secure Image
✓ Image built successfully in 125s
✓ Image verified: 387MB

Step 3/6: Run Security Scan
✓ No critical or high vulnerabilities found

Step 4/6: Test Forwarder (Dry Run Mode)
✓ Container started successfully
✓ Container is running
✓ No errors in startup logs
✓ Forwarder started successfully
✓ Metrics server started
✓ Consumer connected to Kafka
✓ No runtime errors detected

Step 5/6: Test Metrics Endpoint
✓ Health endpoint responding
✓ Metrics endpoint responding
✓ Metrics in valid Prometheus format

Step 6/6: Test Full Docker Compose Stack
✓ Docker Compose services started
✓ audit-forwarder is running
✓ prometheus is running
✓ grafana is running
✓ loki is running
✓ promtail is running

========================================
📊 Test Results Summary
========================================

Total Tests: 35
✓ Passed: 35
✗ Failed: 0

Success Rate: 100%
```

## After Script Completes

If all tests pass, you'll have a running stack:

- **Audit Forwarder:** http://localhost:8003/metrics
- **Prometheus:** http://localhost:9090
- **Grafana:** http://localhost:3000 (admin/changeme)
- **Loki:** http://localhost:3100

## Useful Commands After Testing

```bash
# View forwarder logs
docker-compose logs -f audit-forwarder

# Check all services
docker-compose ps

# Stop everything
docker-compose down

# Restart forwarder only
docker-compose restart audit-forwarder

# See full Makefile commands
make help
```

## Troubleshooting

### Script fails at Step 1
**Issue:** Prerequisites not met

**Fix:**
```bash
# Install missing tools
brew install docker trivy

# Start Docker Desktop
open -a Docker

# Create .env and .secrets files
cp .env.example .env
# Edit .env with your values

# Create .secrets file
cat > .secrets << EOF
AUDIT_API_KEY=your-key
AUDIT_API_SECRET=your-secret
DEST_API_KEY=your-key
DEST_API_SECRET=your-secret
SCHEMA_REGISTRY_KEY=your-key
SCHEMA_REGISTRY_SECRET=your-secret
EOF
```

### Script fails at Step 2
**Issue:** Build error

**Fix:**
```bash
# Clean Docker cache
docker builder prune -a

# Try manual build
docker build -t audit-forwarder:2.1.0 .
```

### Script fails at Step 3
**Issue:** Trivy not installed

**Note:** Security scan is optional. Install with:
```bash
brew install trivy
```

### Script fails at Step 4
**Issue:** Container won't start

**Fix:**
```bash
# Check logs
docker logs audit-forwarder-test

# Verify Kafka connectivity
source .env
source .secrets
confluent kafka cluster list
```

### Script fails at Step 5
**Issue:** Metrics endpoint not responding

**Fix:**
```bash
# Check if port 8003 is already in use
lsof -i :8003

# Kill process if needed
kill -9 <PID>

# Restart test
./scripts/test-setup.sh
```

### Script fails at Step 6
**Issue:** Docker Compose services won't start

**Fix:**
```bash
# Check what's running
docker-compose ps

# View logs for specific service
docker-compose logs <service-name>

# Stop and restart
docker-compose down
docker-compose up -d
```

## Manual Testing (Alternative)

If you prefer to run steps manually:

```bash
# Step 1: Prerequisites
docker --version
docker-compose --version
ls .env .secrets

# Step 2: Build
make build

# Step 3: Scan
make scan-image

# Step 4: Dry run test
docker run --rm -it \
  --env-file .env \
  --env-file .secrets \
  -e AUDIT_ROUTER_DRY_RUN=true \
  -p 8003:8003 \
  -v $(pwd)/data:/app/data \
  audit-forwarder:2.1.0

# Step 5: Test metrics (in another terminal)
curl http://localhost:8003/health
curl http://localhost:8003/metrics

# Step 6: Full stack
make run-compose
```

## Next Steps

After successful testing:
1. ✅ Monitor for 30 minutes
2. ✅ Share with team (see TEAM_ANNOUNCEMENT.md)
3. ✅ Deploy to cloud (make deploy-gcp/aws/azure)

## Support

- **Documentation:** docs/2025-12-06/
- **Security Guide:** docs/2025-12-06/security/02-DOCKER_SECURITY.md
- **Troubleshooting:** docs/2025-12-06/troubleshooting/01-ERROR_HANDLING.md
