# Deployment Guide - Refactored AuditLens Dashboard v10.15

## Quick Start

### 1. Verify Structure
```bash
cd /Users/jegan/playground/audit-forwarder/dashboard

# Should see this structure:
tree -L 2 -I '__pycache__|*.pyc'
# dashboard/
# ├── app.py (229 lines)
# ├── config.py
# ├── components/
# ├── data/
# ├── tabs/
# └── static/
```

### 2. Test Locally (Optional)
```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (from parent directory)
cd /Users/jegan/playground/audit-forwarder
streamlit run dashboard/app.py --server.port=8501

# Open browser: http://localhost:8501
```

### 3. Build Docker Image
```bash
cd /Users/jegan/playground/audit-forwarder/dashboard

# Build with v10.15 tag
docker build -t audit-dashboard:v10.15 .

# Verify image
docker images | grep audit-dashboard
```

### 4. Stop Old Container
```bash
# Stop and remove existing container
docker stop audit-dashboard
docker rm audit-dashboard
```

### 5. Deploy New Container
```bash
# Run new container
docker run -d \
  --name audit-dashboard \
  --network audit-network \
  -p 8503:8501 \
  --env-file /Users/jegan/playground/audit-forwarder/.env \
  --env-file /Users/jegan/playground/audit-forwarder/.secrets \
  -v /Users/jegan/playground/audit-forwarder/dashboard/email_cache.json:/app/email_cache.json \
  -v /Users/jegan/playground/audit-forwarder/dashboard/user_mapping.json:/app/user_mapping.json \
  audit-dashboard:v10.15
```

### 6. Verify Deployment
```bash
# Check container is running
docker ps | grep audit-dashboard

# Check logs
docker logs -f audit-dashboard

# Expected logs:
# [AuditLens] Loaded 170 users from Confluent Cloud IAM API
# [AuditLens] Merged 33 users from static mapping (fallback)
# You can now view your Streamlit app in your browser.
# Network URL: http://0.0.0.0:8501
```

### 7. Test Dashboard
```bash
# Open in browser
open http://localhost:8503

# Or use curl
curl -I http://localhost:8503
# Should return: HTTP/1.1 200 OK
```

## Verification Checklist

### ✅ Pre-Deployment Checks
- [ ] Backup original app.py exists (app.py.backup)
- [ ] All modules import successfully
- [ ] requirements.txt includes cachetools==5.3.2
- [ ] Dockerfile copies new directories (components/, data/, tabs/)
- [ ] .env and .secrets files exist in parent directory

### ✅ Post-Deployment Checks
- [ ] Container is running (`docker ps`)
- [ ] Logs show IAM API users loaded
- [ ] Dashboard accessible at http://localhost:8503
- [ ] All 10 tabs render without errors
- [ ] Metrics display correctly
- [ ] Quick filters work
- [ ] Export functionality works
- [ ] Security alerts tab loads

## Functionality Test Plan

### Test 1: Data Loading
1. Open dashboard
2. Verify "Loading audit events from Kafka..." progress bar appears
3. Verify events load successfully
4. Check that metrics show non-zero counts

**Expected**: Events load within 5-10 seconds

### Test 2: Tabs
Visit each tab and verify it renders:
1. 🔍 Audit Trail - Shows data table
2. 🚨 All Failures - Shows filtered failures
3. 🗑️ Deletions - Shows deletion events
4. 🔑 API Keys - Shows API key operations
5. 🛡️ Security - Shows RBAC/ACL charts
6. 📊 Details - Event inspector works
7. 📈 Analytics - Charts render
8. ⏰ Time Insights - Time-based charts
9. 💾 Export - Download buttons work
10. 🔔 Security Alerts - Alerts load

**Expected**: All tabs render without errors

### Test 3: Filters
1. Click quick filter buttons (🚨 All Failures, 🗑️ Deletions, etc.)
2. Verify data updates
3. Check that active filter is highlighted

**Expected**: Filters apply correctly

### Test 4: Controls
1. Change time window (15 min → 1 hour)
2. Change criticality filter (All → CRITICAL)
3. Toggle "Hide internal operations"
4. Click "Refresh Data"

**Expected**: Controls update data correctly

### Test 5: Email Resolution
1. Check Audit Trail tab
2. Verify "Who (Principal)" column shows emails in parentheses
3. Click "Refresh User Cache" in sidebar
4. Verify success message appears

**Expected**: Emails displayed correctly

### Test 6: Export
1. Go to Export tab
2. Click "Download CSV"
3. Click "Download JSON"
4. Verify files download

**Expected**: Both exports work

## Troubleshooting

### Issue: Container Fails to Start

**Symptoms**:
```bash
docker logs audit-dashboard
# Error: No module named 'config'
```

**Solution**:
```bash
# Rebuild with correct structure
docker build -t audit-dashboard:v10.15 . --no-cache

# Verify Dockerfile includes:
# COPY config.py .
# COPY components/ components/
# COPY data/ data/
# COPY tabs/ tabs/
```

### Issue: Import Errors

**Symptoms**:
```
ModuleNotFoundError: No module named 'cachetools'
```

**Solution**:
```bash
# Verify requirements.txt includes cachetools
cat requirements.txt | grep cachetools

# Rebuild image
docker build -t audit-dashboard:v10.15 . --no-cache
```

### Issue: No Data Loading

**Symptoms**:
- Dashboard shows "No events to display"
- Progress bar appears but no data loads

**Solution**:
```bash
# Check Kafka connectivity
docker exec audit-dashboard env | grep DEST_BOOTSTRAP

# Verify .env and .secrets are mounted correctly
docker inspect audit-dashboard | grep -A 10 "Env"

# Check forwarder is running
docker ps | grep audit-forwarder
```

### Issue: Email Cache Not Loading

**Symptoms**:
```
[AuditLens] Warning: Could not fetch users from API: <error>
```

**Solution**:
```bash
# Verify Confluent Cloud API credentials
docker exec audit-dashboard env | grep CONFLUENT_CLOUD_API

# Check IAM API access
docker logs audit-dashboard | grep "Loaded.*users from"

# Fallback to static mapping
# Verify user_mapping.json exists and is mounted
```

### Issue: Tabs Not Rendering

**Symptoms**:
- Clicking tab shows blank page
- Error in logs: "No module named 'tabs.audit_trail'"

**Solution**:
```bash
# Verify tabs/ directory structure
docker exec audit-dashboard ls -la tabs/

# Should show:
# __init__.py
# audit_trail.py
# failures.py
# ... (all 10 tab files)

# Rebuild if missing
docker build -t audit-dashboard:v10.15 . --no-cache
```

## Rollback Procedure

If issues arise, rollback to original version:

### Option 1: Use Backup File
```bash
# Stop new container
docker stop audit-dashboard

# Restore original app.py
cd /Users/jegan/playground/audit-forwarder/dashboard
cp app.py.backup app.py

# Rebuild and redeploy
docker build -t audit-dashboard:v10.14-original .
docker run -d --name audit-dashboard ... audit-dashboard:v10.14-original
```

### Option 2: Use Previous Docker Image
```bash
# Stop new container
docker stop audit-dashboard
docker rm audit-dashboard

# Run previous version (if available)
docker run -d --name audit-dashboard ... audit-dashboard:v10.13
```

## Monitoring

### Check Container Health
```bash
# View logs (real-time)
docker logs -f audit-dashboard

# Check resource usage
docker stats audit-dashboard

# Check container details
docker inspect audit-dashboard
```

### Check Application Health
```bash
# HTTP health check
curl -I http://localhost:8503/_stcore/health
# Should return: HTTP/1.1 200 OK

# Check Streamlit metrics
curl http://localhost:8503/_stcore/metrics
```

## Performance Optimization

### LRU Cache Stats
The email cache is configured with:
- **Max Size**: 10,000 items
- **Persistence**: email_cache.json
- **Auto-eviction**: Oldest entries removed when full

To monitor cache performance:
```bash
# Check cache size
docker exec audit-dashboard wc -l email_cache.json
# ~170 users initially, grows as new users are discovered
```

### Streamlit Cache
Data is cached for 60 seconds (@st.cache_data):
```python
@st.cache_data(ttl=60)
def load_events_from_kafka(...)
```

To force refresh:
- Click "🔄 Refresh Data" in sidebar
- Or wait 60 seconds for auto-refresh

## Security Checklist

### Secrets Management
- [ ] .env contains only non-sensitive config
- [ ] .secrets contains API keys and passwords
- [ ] Both files have restricted permissions (600)
- [ ] No secrets in Docker image or logs

### Network Security
- [ ] Container on isolated network (audit-network)
- [ ] Only port 8503 exposed to host
- [ ] No direct internet access required (except Confluent Cloud)

### Data Privacy
- [ ] Email cache stays local (email_cache.json)
- [ ] No data sent to external services except IAM API
- [ ] User data stays within Kafka ecosystem

## Backup Recommendations

### Before Deployment
```bash
# Backup current state
cp -r /Users/jegan/playground/audit-forwarder/dashboard /tmp/dashboard-backup-$(date +%Y%m%d)

# Backup email cache
cp /Users/jegan/playground/audit-forwarder/dashboard/email_cache.json /tmp/email_cache-backup-$(date +%Y%m%d).json
```

### Regular Backups
```bash
# Cron job to backup email cache daily
0 2 * * * cp /Users/jegan/playground/audit-forwarder/dashboard/email_cache.json /backups/email_cache-$(date +%Y%m%d).json
```

## Next Steps

After successful deployment:

1. **Monitor for 24 hours**: Watch logs for errors
2. **User Acceptance Testing**: Have users test all features
3. **Performance Tuning**: Adjust cache TTL if needed
4. **Documentation**: Update team wiki with new structure
5. **Training**: Brief team on new modular architecture

## Support

### Logs Location
- **Container logs**: `docker logs audit-dashboard`
- **Application logs**: Streamed to stdout/stderr
- **Streamlit logs**: In container at `/app/.streamlit/`

### Common Commands
```bash
# Restart container
docker restart audit-dashboard

# Shell into container
docker exec -it audit-dashboard /bin/bash

# View environment
docker exec audit-dashboard env | sort

# Check Python imports
docker exec audit-dashboard python -c "import data.email_cache; print('OK')"
```

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v10.15 | 2025-12-12 | Modular refactoring, LRU cache |
| v10.14 | 2025-12-11 | Performance optimizations |
| v10.13 | 2025-12-10 | Topic name extraction |
| v10.12 | 2025-12-09 | Timezone selector |
| v10.11 | 2025-12-08 | Security alerts tab |

## Success Criteria

Deployment is successful when:
- ✅ Container runs without crashes for 24 hours
- ✅ All 10 tabs render correctly
- ✅ Data loads from Kafka within 10 seconds
- ✅ Email cache loads 150+ users from IAM API
- ✅ Quick filters apply correctly
- ✅ Export functionality works
- ✅ No Python errors in logs
- ✅ Memory usage stable (<500MB)
- ✅ Users can perform all previous tasks

---

**Deployment checklist complete!** 🚀
