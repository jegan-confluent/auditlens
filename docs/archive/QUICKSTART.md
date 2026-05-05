# 🚀 Quick Start Guide - Audit Log Intelligence System v8.0

**Goal:** Get your audit log monitoring running in 30 minutes

---

## 📋 Prerequisites (5 minutes)

### 1. Check You Have Everything

```bash
# Check Confluent CLI
confluent version

# Check Docker
docker --version

# Check Python
python3 --version
```

### 2. Install Missing Prerequisites

**If Confluent CLI is missing:**
```bash
# macOS
brew install confluentinc/tap/cli

# Linux
curl -sL --http1.1 https://cnfl.io/cli | sh -s -- latest
```

---

## 🔐 Step 1: Get API Keys from Confluent Cloud (10 minutes)

You need API keys from Confluent Cloud UI:

1. **Cloud API Keys** (for admin operations)
   - Profile icon → Cloud API keys → Add key
   
2. **Kafka Cluster API Keys** (for destination cluster)
   - Select cluster → API keys → Add key

3. **Schema Registry API Keys** (optional)
   - Environment → Schema Registry → API credentials → Add key

**Save all keys securely - you'll need them in Step 2!**

---

## 🛠️ Step 2: Configure (.env and .secrets files)

```bash
cd /Users/jegan/playground/audit-forwarder

# Create .secrets with YOUR actual keys
nano .secrets
```

Paste this template and replace with YOUR keys:
```bash
DEST_API_KEY=your-actual-dest-api-key
DEST_API_SECRET=your-actual-dest-secret
AUDIT_API_KEY=your-actual-dest-api-key
AUDIT_API_SECRET=your-actual-dest-secret
SCHEMA_REGISTRY_KEY=your-sr-key
SCHEMA_REGISTRY_SECRET=your-sr-secret
CONFLUENT_CLOUD_API_KEY=your-cloud-key
CONFLUENT_CLOUD_API_SECRET=your-cloud-secret
```

```bash
# Create .env with YOUR cluster URLs
nano .env
```

Update these lines with YOUR actual values:
```bash
AUDIT_BOOTSTRAP=pkc-xxxxx.us-east-1.aws.confluent.cloud:9092
DEST_BOOTSTRAP=pkc-yyyyy.us-east-1.aws.confluent.cloud:9092
SCHEMA_REGISTRY_URL=https://psrc-xxxxx.us-east-1.aws.confluent.cloud
ENABLE_MULTI_TOPIC_ROUTING=true
DROP_LOW_EVENTS=true
```

---

## 🎯 Step 3: Create Topics (5 minutes)

```bash
# Use your environment and cluster
confluent environment use env-xxxxx
confluent kafka cluster use lkc-xxxxx

# Create destination topics
confluent kafka topic create audit_events_critical --partitions 3
confluent kafka topic create audit_events_high --partitions 3
confluent kafka topic create audit_events_medium --partitions 3

# Verify
confluent kafka topic list
```

---

## 🐳 Step 4: Start System (2 minutes)

```bash
# Start everything
docker-compose up -d

# Check logs
docker logs -f audit-forwarder
# Should see: "Version: 8.0"
```

---

## 🖥️ Step 5: Open Dashboard (1 minute)

```bash
open http://localhost:8503
```

**Expected:** Dashboard showing real-time events with v8.0 badge

**If you see "0 events":** Generate test activity:
```bash
confluent kafka topic create test-topic
confluent kafka topic delete test-topic
# Refresh dashboard - should see events!
```

---

## ✅ Success Checklist

- [ ] Docker containers running
- [ ] Dashboard accessible at http://localhost:8503
- [ ] Events visible (or test event created)
- [ ] Forwarder status shows "Healthy"

**All checked?** 🎉 **You're done!**

---

## 🔍 Troubleshooting

**Dashboard shows 0 events?**
- Wait 1-2 min for first events
- Create test topic to generate events
- Check forwarder logs: `docker logs audit-forwarder`

**Forwarder errors?**
- Verify API keys in .secrets
- Check cluster URLs in .env
- Test: `confluent kafka topic list`

**Need help?**
- Read IMPLEMENTATION_SUMMARY.md for details
- Check logs: `docker-compose logs`
