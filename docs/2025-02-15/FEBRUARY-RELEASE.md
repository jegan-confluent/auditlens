# AuditLens v3.0.0 - February 2025 Release

## Overview

The February 2025 release brings major improvements to scalability, identity resolution, and security analytics. This release removes the file-based offset tracking that was blocking horizontal scaling, adds identity enrichment for human-readable principal names, and introduces two new dashboard tabs for topic-identity analysis.

## Breaking Changes

### Offset Storage Migration

**Before (v2.x):** File-based offset tracking with `OFFSET_FILE` environment variable
**After (v3.0):** Kafka consumer group commits exclusively

```
┌─────────────────────────────────────────────────────────────┐
│  v2.x Architecture (File-Based)                            │
│  ┌─────────┐      ┌──────────────┐      ┌──────────────┐   │
│  │ Kafka   │──────│  Forwarder   │──────│ offset.json  │   │
│  │ Consumer│      │  (single)    │      │ (local file) │   │
│  └─────────┘      └──────────────┘      └──────────────┘   │
│                          ↓                                  │
│              ❌ Cannot scale horizontally                   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  v3.0 Architecture (Kafka Consumer Groups)                  │
│  ┌─────────┐      ┌──────────────┐      ┌──────────────┐   │
│  │ Kafka   │──────│  Forwarder   │──────│ Kafka        │   │
│  │ Consumer│      │  Instance 1  │      │ Consumer     │   │
│  └─────────┘      └──────────────┘      │ Group        │   │
│  ┌─────────┐      ┌──────────────┐      │ Offsets      │   │
│  │ Kafka   │──────│  Forwarder   │──────│ (__consumer_ │   │
│  │ Consumer│      │  Instance 2  │      │  offsets)    │   │
│  └─────────┘      └──────────────┘      └──────────────┘   │
│                          ↓                                  │
│              ✅ Horizontal scaling enabled                  │
└─────────────────────────────────────────────────────────────┘
```

**Migration Steps:**
1. Update consumer group ID (default: `audit-fwd-v3-feb`)
2. Remove OFFSET_FILE environment variable
3. Remove volume mount for offset file
4. Initial consumption will start from latest (or earliest if configured)

## New Features

### 1. Identity Enrichment Module

Resolves Confluent Cloud principal IDs to human-readable names.

**Module:** `src/identity/enricher.py`

```python
from src.identity import get_enricher, resolve_principal

# Get human-readable name
display = resolve_principal("sa-abc123")  # Returns "payments-service (sa-abc123)"

# Batch resolution
enricher = get_enricher()
results = enricher.batch_resolve(["sa-abc", "u-def", "pool-ghi"])
```

**Features:**
- TTLCache with 1-hour expiry (configurable)
- Thread-safe design with locking
- Graceful fallback when API unavailable
- Supports service accounts, users, and identity pools

**Configuration:**
```bash
CONFLUENT_CLOUD_API_KEY=your-cloud-api-key
CONFLUENT_CLOUD_API_SECRET=your-cloud-api-secret
```

### 2. Confluent Cloud Admin API Client

REST API client for cluster, topic, and ACL management.

**Module:** `src/confluent_api/admin_client.py`

```python
from src.confluent_api import get_client

client = get_client()
environments = client.list_environments()
clusters = client.list_clusters(environment_id="env-abc123")
topics = client.list_topics(cluster_id, api_key, api_secret, rest_endpoint)
acls = client.list_acls(cluster_id, api_key, api_secret, rest_endpoint)
```

**Features:**
- Pagination handling for large datasets
- Rate limit handling with Retry-After
- Response caching (5-minute TTL)
- Thread-safe design

### 3. Topic × Identity Matrix Dashboard Tab

Shows relationships between topics and identities from audit data.

**Tab:** `dashboard/tabs/topic_identity.py`

**Views:**
1. **Topic → Identities**: Expand any topic to see which identities access it
2. **Identity → Topics**: Select an identity to see all topics they access
3. **Stale ACLs**: Find ACLs for principals with no recent activity

**Features:**
- Configurable stale threshold (7-90 days)
- Sankey diagram visualization
- CSV export for stale ACLs
- Real-time filtering by cluster

### 4. Identity Activity Timeline Dashboard Tab

Detailed view of individual identity activity patterns.

**Tab:** `dashboard/tabs/identity_activity.py`

**Features:**
- Identity profile card with metadata
- Activity timeline visualization
- Risk score calculation (LOW/MEDIUM/HIGH/CRITICAL)
- Risk indicators:
  - High failure rate (>50% denials)
  - Off-hours activity
  - Burst activity (>100 events/min)
- Detailed activity table with filtering
- CSV export

## Code Quality Improvements

### Fixed Bare Except Clauses

**Files fixed:**
- `dashboard/data/transformations.py:164`
- `dashboard/data/kafka_consumer.py:87`
- `dashboard/data/email_cache.py:28,106,254`

**Before:**
```python
try:
    data = json.loads(raw)
except:
    return None
```

**After:**
```python
try:
    data = json.loads(raw)
except (json.JSONDecodeError, KeyError, TypeError) as e:
    logger.warning("Failed to parse: %s", e)
    return None
```

### Consistent orjson Usage

**File:** `src/routing/topic_router.py`

Changed `json.dumps` to `orjson.dumps` for consistent fast JSON serialization.

## Configuration Changes

### docker-compose.yml

```yaml
services:
  audit-forwarder:
    image: audit-forwarder:v3.0.0
    environment:
      - GROUP_ID=${GROUP_ID:-audit-fwd-v3-feb}
      # OFFSET_FILE removed
    read_only: true  # Now stateless

  dashboard:
    image: audit-dashboard:v11.0
    environment:
      - CONFLUENT_CLOUD_API_KEY=${CONFLUENT_CLOUD_API_KEY:-}
      - CONFLUENT_CLOUD_API_SECRET=${CONFLUENT_CLOUD_API_SECRET:-}
```

### New Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CONFLUENT_CLOUD_API_KEY` | Cloud API key for identity enrichment | (none) |
| `CONFLUENT_CLOUD_API_SECRET` | Cloud API secret for identity enrichment | (none) |
| `GROUP_ID` | Kafka consumer group ID | `audit-fwd-v3-feb` |

### Removed Environment Variables

| Variable | Reason |
|----------|--------|
| `OFFSET_FILE` | Replaced by Kafka consumer group commits |

## Test Coverage

### New Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_identity_enricher.py` | 23 | Identity enrichment, caching, API mocking |
| `tests/test_admin_client.py` | 21 | Admin API, pagination, rate limiting |
| `tests/test_topic_identity_tab.py` | 25 | Aggregation, stale ACLs, risk scores |

**Total new tests:** 69

## File Changes Summary

### New Files
```
src/identity/__init__.py
src/identity/enricher.py
src/confluent_api/__init__.py
src/confluent_api/admin_client.py
dashboard/tabs/topic_identity.py
dashboard/tabs/identity_activity.py
tests/test_identity_enricher.py
tests/test_admin_client.py
tests/test_topic_identity_tab.py
docs/2025-02-15/FEBRUARY-RELEASE.md
```

### Modified Files
```
audit_forwarder.py         - Removed file-based offset tracking
docker-compose.yml         - Updated versions, removed offset volume
dashboard/app.py           - Added new tabs (11, 12)
dashboard/tabs/__init__.py - Exported new tab modules
dashboard/config.py        - Added Cloud API config, version bump
dashboard/data/transformations.py - Fixed bare except
dashboard/data/kafka_consumer.py  - Fixed bare except
dashboard/data/email_cache.py     - Fixed bare excepts, added logging
src/routing/topic_router.py       - Changed json to orjson
VERSION                    - Updated to 3.0.0-feb
```

### Deleted Files (Phase 0 Cleanup)
```
dashboard/app_original.py  - Dead code (2,667 lines)
flink-sql/                 - Deprecated directory
backup/                    - Old backups
archive/v2_experimental/   - Experimental code
```

## Upgrade Guide

### 1. Backup Current State
```bash
# Save current offsets (if needed for rollback)
cp data/forwarder_offsets.json data/forwarder_offsets.backup.json
```

### 2. Update Configuration
```bash
# Add to .env
CONFLUENT_CLOUD_API_KEY=your-key
CONFLUENT_CLOUD_API_SECRET=your-secret

# Update group ID (will start fresh)
GROUP_ID=audit-fwd-v3-feb
```

### 3. Deploy
```bash
docker-compose pull
docker-compose up -d
```

### 4. Verify
```bash
# Check health
curl http://localhost:8003/health | jq

# Check logs
docker logs -f audit-forwarder

# Access dashboard
open http://localhost:8503
```

## Known Limitations

1. **Initial Offset:** After migration, consumer will start from latest offsets. Historical data before migration point is not reprocessed.

2. **Identity Enrichment API Limits:** Confluent Cloud API has rate limits. The client handles 429 responses but heavy usage may cause delays.

3. **Stale ACL Detection:** Requires both audit data AND cluster API access. If either is missing, stale detection is disabled.

## Support

For issues or questions:
- GitHub Issues: https://github.com/your-org/audit-forwarder/issues
- Documentation: `/docs/` directory
- Architecture: `/docs/END_TO_END_FLOW.md`

---

**Release Date:** February 15, 2025
**Version:** 3.0.0-feb
