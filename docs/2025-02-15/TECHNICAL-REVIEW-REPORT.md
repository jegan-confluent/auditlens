# Audit Forwarder v3.0.0-feb — Technical Review Report

**Review Date:** February 15, 2025
**Reviewer:** Staff Engineer Review (Pre-Demo Quality Gate)
**Verdict:** ⚠️ NOT READY FOR DEMO - Critical issues must be fixed first

---

## Executive Summary

The v3.0.0-feb release has **critical data integrity bugs** that could cause **silent data loss**. The claimed "at-least-once" delivery guarantee is actually **at-most-once** due to incorrect producer flush logic. Additionally, file-based offset references were NOT fully removed (5 locations remain), and there is no SIGTERM handler in the main forwarder. **Do NOT demo this version** until the critical issues are fixed.

---

## Delivery Guarantee

**Claimed:** At-least-once (commit after produce)
**Actual:** ⚠️ **AT-MOST-ONCE** (data loss on crash)

### Root Cause

`audit_forwarder.py:809` uses `producer.poll(0)` before `consumer.commit()`:

```python
# Line 809 - INCORRECT
producer.poll(0)  # Returns immediately, doesn't wait for delivery!

# Line 814
consumer.commit(asynchronous=False)  # Commits offsets for potentially undelivered events
```

**The `poll(0)` call does NOT wait for messages to be delivered.** It only triggers delivery callbacks for already-completed deliveries. Messages in-flight are NOT waited for.

### Crash Scenario

1. Forwarder consumes 5000 events
2. Produces 4800 to broker, 200 still in-flight
3. Calls `producer.poll(0)` → returns immediately
4. Calls `consumer.commit()` → commits offset for all 5000
5. Process crashes
6. On restart: resumes from committed offset (after 5000)
7. **200 events LOST permanently**

### Fix Required

```python
# Line 809 - CORRECT
producer.flush(timeout=30)  # Wait for ALL in-flight messages

# Then commit
consumer.commit(asynchronous=False)
```

---

## Critical Issues (Must Fix Before Demo)

### 1. Broken Delivery Guarantee

| Aspect | Expected | Actual |
|--------|----------|--------|
| Guarantee | At-least-once | At-most-once |
| Data loss risk | No | Yes - on any crash |
| Fix complexity | Low (1 line) | N/A |

**File:** `audit_forwarder.py:809`
**Fix:** Change `producer.poll(0)` to `producer.flush(timeout=30)`

### 2. File-Based Offset References NOT Fully Removed

| File | Line | Content |
|------|------|---------|
| `Dockerfile` | 84 | `ENV OFFSET_FILE=/app/data/offsets.json` |
| `deploy/docker/docker-compose.yml` | 47 | `OFFSET_FILE=/app/data/offsets.json` |
| `deploy/kubernetes/configmap.yaml` | 19 | `OFFSET_FILE: "/app/data/offsets.json"` |
| `src/config/settings.py` | 236 | `offset_file: str = "./data/offsets.json"` |
| `src/config/settings.py` | 44 | `enable_auto_commit: bool = True` (contradicts main forwarder) |

The main `docker-compose.yml` was updated correctly, but alternative deployment configs were missed.

### 3. No SIGTERM Handler in Main Forwarder

**File:** `audit_forwarder.py`

The forwarder only catches `KeyboardInterrupt`:

```python
except KeyboardInterrupt:
    logger.info("Interrupted by user")
```

Docker sends SIGTERM on `docker stop`. Without a signal handler:
- No clean shutdown on container stop
- In-flight messages may be lost
- Consumer offsets may not be committed

**Fix Required:** Add signal handler:

```python
import signal

def signal_handler(sig, frame):
    logger.info("Received signal %s, shutting down...", sig)
    raise KeyboardInterrupt()

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
```

### 4. Test Suite Has 25 Failures + 10 Errors

```
====== 25 failed, 172 passed, 5 skipped, 24 warnings, 10 errors in 8.64s =======
```

**Failing Test Categories:**
- `test_anomaly.py` - Auth failure detection tests
- `test_cloudevents.py` - Event parsing tests (12 failures)
- `test_crn_parser.py` - CRN parsing tests
- `test_integration.py` - Sink manager integration
- `test_retry.py` - Retry policy tests
- `test_circuit_breaker.py` - All 10 tests ERROR (import issue)

**Root Cause Analysis Needed:** The circuit breaker tests error with `TypeError`, suggesting the module interface changed but tests weren't updated.

---

## Medium Issues (Fix Before Customer POC)

### 1. Memory Leak in RateTracker

**File:** `src/anomaly/rate_tracker.py`

The `cleanup()` method exists (line 440) but is **never called** from `audit_forwarder.py`.

```python
# Rate tracker creates unbounded dictionaries
self._principal_activity: Dict[str, RateCounter] = defaultdict(...)
self._principal_auth_failures: Dict[str, RateCounter] = defaultdict(...)
# ... 6 more dictionaries

# cleanup() exists but never called
def cleanup(self):  # Line 440
    """Clean up old tracking data."""
```

**Risk:** Memory grows unbounded with unique principals/IPs over time.

**Fix:** Add periodic cleanup call in main loop (every 5 minutes):

```python
if now - last_cleanup >= 300:
    anomaly_tracker.cleanup()
    last_cleanup = now
```

### 2. docker-compose.yml Validation Fails Without GF_ADMIN_PASSWORD

```bash
$ docker compose config
error: required variable GF_ADMIN_PASSWORD is missing a value
```

This is **correct security behavior** (no default passwords), but needs documentation in QUICKSTART.md.

### 3. Settings Module Has Conflicting Defaults

**File:** `src/config/settings.py:44`

```python
class KafkaSourceConfig(BaseModel):
    enable_auto_commit: bool = True  # Line 44 - WRONG!
```

The main forwarder uses `enable.auto.commit: False`. These should match.

### 4. Dashboard Consumer Missing Explicit auto.offset.reset

**File:** `dashboard/data/kafka_consumer.py`

Consumer config doesn't explicitly set `auto.offset.reset`:

```python
consumer_config = {
    'bootstrap.servers': DEST_BOOTSTRAP,
    # ... no auto.offset.reset
}
```

Default is `latest`, which is likely correct, but should be explicit.

---

## Low Issues (Tech Debt, Fix Later)

| Issue | Location | Impact |
|-------|----------|--------|
| `pytest-asyncio` not installed | tests/ | 10+ test warnings |
| Producer retries only 3 | audit_forwarder.py:333 | Could miss transient issues |
| No healthcheck on identity enricher | src/identity/enricher.py | API failures silent |
| Denial aggregator uses `json.dumps` not `orjson` | denial_aggregator.py:452 | Minor performance |

---

## Deployment Readiness

| Mode | Ready? | Blockers |
|------|--------|----------|
| Docker Compose (local) | ❌ No | Critical bugs, requires GF_ADMIN_PASSWORD |
| Docker Compose (deploy/) | ❌ No | Stale OFFSET_FILE reference |
| Kubernetes | ❌ No | Stale OFFSET_FILE in configmap |
| EC2/VM (systemd) | ❌ No | No systemd unit file, no install docs |

### Docker Compose Issues

1. Main `docker-compose.yml` requires `GF_ADMIN_PASSWORD` env var
2. `deploy/docker/docker-compose.yml` still has `OFFSET_FILE`
3. Dockerfile still has `ENV OFFSET_FILE`

### Kubernetes Issues

1. `deploy/kubernetes/configmap.yaml` still has `OFFSET_FILE`
2. No PodDisruptionBudget
3. No HorizontalPodAutoscaler
4. No NetworkPolicy

### EC2/VM Issues

1. No systemd unit file
2. No install script
3. No log rotation config

---

## Test Coverage Summary

| Module | Tests | Pass | Fail | Error | Coverage Gap |
|--------|-------|------|------|-------|--------------|
| identity/enricher.py | 23 | 23 | 0 | 0 | ✅ Good |
| confluent_api/admin_client.py | 21 | 21 | 0 | 0 | ✅ Good |
| topic_identity_tab.py | 25 | 25 | 0 | 0 | ✅ Good |
| anomaly/rate_tracker.py | 10 | 8 | 2 | 0 | Auth spike detection |
| cloudevents/*.py | 12 | 0 | 12 | 0 | ❌ All failing |
| resilience/circuit_breaker.py | 10 | 0 | 0 | 10 | ❌ Import errors |
| audit_forwarder.py | 0 | N/A | N/A | N/A | ❌ No tests! |

**Critical Gap:** The main `audit_forwarder.py` has **zero unit tests**. The consumption → produce → commit loop is completely untested.

---

## Security Assessment

### Pass ✅

- [x] Non-root user in Dockerfile (line 98: `USER forwarder`)
- [x] Multi-stage build (builder → runtime)
- [x] No hardcoded secrets found in code
- [x] `pydantic` Field `repr=False` on secrets
- [x] Grafana requires password (no default)
- [x] Container security options (no-new-privileges, cap_drop)
- [x] Read-only filesystem for forwarder container

### Fail ❌

- [ ] SIGTERM not handled (unclean shutdown)
- [ ] Health endpoint doesn't expose sensitive data (verified: OK)
- [ ] Metrics endpoint auth (`METRICS_AUTH_ENABLED`) - needs verification

### Needs Verification

- Metrics endpoint authentication - is it enabled by default?
- Slack webhook URL handling - is it logged anywhere?

---

## Performance Characteristics

| Metric | Value | Source |
|--------|-------|--------|
| Batch size | 5000 messages | audit_forwarder.py:720 |
| Producer batch | 2MB / 20K msgs | producer_conf |
| Compression | LZ4 | producer_conf |
| Kafka acks | all | producer_conf |
| Idempotence | enabled | producer_conf |
| Socket timeout | 30s | consumer_conf |
| Session timeout | 45s | consumer_conf |

**Expected Throughput:** Based on batch settings, approximately 5000 events/second sustained.

**Memory Estimate:**
- Consumer prefetch: 500MB (`queued.max.messages.kbytes`)
- Producer buffer: 3GB (`queue.buffering.max.kbytes`)
- Rate tracker: Unbounded (memory leak) - assume 100MB after 1 hour
- Total: ~4GB peak

Docker resource limits (4GB) are appropriate but memory leak will eventually cause OOM.

---

## Recommendations

### Immediate (Before Any Demo)

1. **Fix `producer.poll(0)` → `producer.flush(timeout=30)`** (5 min)
2. **Add SIGTERM handler** (10 min)
3. **Remove OFFSET_FILE from Dockerfile, deploy/*** (5 min)

### Before Customer POC

1. Fix or skip failing tests (test suite should be green)
2. Add `anomaly_tracker.cleanup()` periodic call
3. Document GF_ADMIN_PASSWORD requirement
4. Fix settings.py `enable_auto_commit` default

### Before Production

1. Add tests for `audit_forwarder.py` main loop
2. Create systemd unit file for non-Docker deployment
3. Add Kubernetes HPA and PDB
4. Profile actual memory usage under load
5. Add circuit breaker for Confluent Cloud API calls
6. Consider adding Prometheus histogram for processing latency

---

## Appendix: Commands for Verification

```bash
# Check for stale OFFSET_FILE references
grep -rn "OFFSET_FILE\|offset_file" --include="*.py" --include="*.yml" --include="*.yaml" .

# Verify signal handling
grep -n "signal\|SIGTERM" audit_forwarder.py

# Run tests
python3 -m pytest tests/ -v --tb=short

# Validate docker-compose
GF_ADMIN_PASSWORD=test docker compose config --quiet

# Check producer commit sequence (should see flush() before commit())
grep -A5 "producer.poll\|producer.flush\|consumer.commit" audit_forwarder.py
```

---

**Report Generated:** 2025-02-15
**Next Review:** After critical issues fixed
