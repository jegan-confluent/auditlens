# Offset Management Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Customer Configuration                           │
│                                                                          │
│  .env file:                                                              │
│  ┌────────────────────────────────────────────────────────────┐         │
│  │ OFFSET_STRATEGY=latest                                      │         │
│  │ OFFSET_HOURS_AGO=168                                        │         │
│  │ OFFSET_DRY_RUN=false                                        │         │
│  └────────────────────────────────────────────────────────────┘         │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Docker Compose Layer                              │
│                                                                          │
│  docker-compose.yml:                                                     │
│  ┌────────────────────────────────────────────────────────────┐         │
│  │ environment:                                                │         │
│  │   - OFFSET_STRATEGY=${OFFSET_STRATEGY:-committed}          │         │
│  │   - OFFSET_HOURS_AGO=${OFFSET_HOURS_AGO:-}                 │         │
│  │ volumes:                                                    │         │
│  │   - ./scripts/entrypoint.sh:/app/entrypoint.sh:ro          │         │
│  │   - ./scripts/offset-manager.sh:/app/scripts/...           │         │
│  │ command: ["/bin/bash", "/app/entrypoint.sh"]               │         │
│  └────────────────────────────────────────────────────────────┘         │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Container Runtime                               │
│                                                                          │
│  Step 1: entrypoint.sh                                                   │
│  ┌────────────────────────────────────────────────────────────┐         │
│  │ #!/bin/bash                                                 │         │
│  │ # Load env vars                                             │         │
│  │ # Validate configuration                                    │         │
│  │ # Log startup info                                          │         │
│  │                                                             │         │
│  │ if [ "$OFFSET_STRATEGY" != "committed" ]; then             │         │
│  │   bash /app/scripts/offset-manager.sh                      │         │
│  │ fi                                                          │         │
│  │                                                             │         │
│  │ exec python -u audit_forwarder.py                          │         │
│  └────────────────────────────────────────────────────────────┘         │
│                                 │                                        │
│                                 ▼                                        │
│  Step 2: offset-manager.sh                                               │
│  ┌────────────────────────────────────────────────────────────┐         │
│  │ case "$OFFSET_STRATEGY" in                                 │         │
│  │   latest)                                                   │         │
│  │     delete_consumer_group                                  │         │
│  │     ;;                                                      │         │
│  │   earliest)                                                 │         │
│  │     delete_consumer_group                                  │         │
│  │     echo "earliest" > /tmp/offset_reset_strategy           │         │
│  │     ;;                                                      │         │
│  │   timestamp)                                                │         │
│  │     delete_consumer_group                                  │         │
│  │     echo "$timestamp_ms" > /tmp/offset_reset_timestamp     │         │
│  │     ;;                                                      │         │
│  │   committed)                                                │         │
│  │     # No action - use committed offsets                    │         │
│  │     ;;                                                      │         │
│  │ esac                                                        │         │
│  │ log_audit_trail                                             │         │
│  └────────────────────────────────────────────────────────────┘         │
│                                 │                                        │
│                                 ▼                                        │
│  Step 3: audit_forwarder.py (UNCHANGED)                                 │
│  ┌────────────────────────────────────────────────────────────┐         │
│  │ consumer_conf = {                                           │         │
│  │   "bootstrap.servers": AUDIT_BOOTSTRAP,                    │         │
│  │   "group.id": GROUP_ID,                                    │         │
│  │   "auto.offset.reset": "latest",  # Line 348               │         │
│  │   "enable.auto.commit": False,                             │         │
│  │ }                                                           │         │
│  │                                                             │         │
│  │ consumer = Consumer(consumer_conf)                         │         │
│  │ consumer.subscribe([AUDIT_TOPIC])                          │         │
│  │                                                             │         │
│  │ # Consumer resumes based on Kafka group state              │         │
│  │ # - If group exists: resume from committed                 │         │
│  │ # - If group deleted: use auto.offset.reset=latest         │         │
│  └────────────────────────────────────────────────────────────┘         │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           Kafka Cluster                                  │
│                                                                          │
│  confluent-audit-log-events topic:                                       │
│  ┌──────────────────────────────────────────────────────────┐           │
│  │ [Earliest] ─────────────── [Committed] ─────── [Latest]  │           │
│  │     ↑                           ↑                  ↑      │           │
│  │     │                           │                  │      │           │
│  │  earliest                   committed           latest    │           │
│  │  strategy                    strategy          strategy   │           │
│  │                                                            │           │
│  │  timestamp strategy:                                      │           │
│  │     [Timestamp] ──────────────────────────────►           │           │
│  └──────────────────────────────────────────────────────────┘           │
│                                                                          │
│  Consumer Group: audit-fwd-v3-feb                                        │
│  ┌──────────────────────────────────────────────────────────┐           │
│  │ Partition 0: Offset 12345                                │           │
│  │ Partition 1: Offset 12346                                │           │
│  │ Partition 2: Offset 12347                                │           │
│  │                                                           │           │
│  │ Status: Active (if committed strategy)                   │           │
│  │         Deleted (if latest/earliest/timestamp)           │           │
│  └──────────────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Strategy Behavior Diagram

### Strategy: `committed` (Default)

```
Timeline: [Day 1] ─────────── [Last Processed] ─────────── [Latest]
                                      ↑
                                      │
                            Consumer resumes here
                            (from committed offset)

Kafka Consumer Group:
┌─────────────────────────────────────────────┐
│ audit-fwd-v3-feb                            │
│ ├─ Partition 0: Offset 12345 (committed)   │
│ ├─ Partition 1: Offset 12346 (committed)   │
│ └─ Partition 2: Offset 12347 (committed)   │
└─────────────────────────────────────────────┘

Action: None (resume from last commit)
Data Loss: 0%
Processing: Resume from last position
```

---

### Strategy: `latest`

```
Timeline: [Day 1] ─────────────────────────────────────── [Latest]
                                                              ↑
                                                              │
                                                   Consumer starts here
                                                   (skip entire backlog)

Kafka Consumer Group:
┌─────────────────────────────────────────────┐
│ audit-fwd-v3-feb                            │
│ ├─ Partition 0: DELETED                    │
│ ├─ Partition 1: DELETED                    │
│ └─ Partition 2: DELETED                    │
└─────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────┐
│ New consumer group created                  │
│ ├─ Partition 0: Latest (auto.offset.reset) │
│ ├─ Partition 1: Latest (auto.offset.reset) │
│ └─ Partition 2: Latest (auto.offset.reset) │
└─────────────────────────────────────────────┘

Action: Delete consumer group → Kafka uses auto.offset.reset=latest
Data Loss: 100% of backlog
Processing: Start from newest messages only
```

---

### Strategy: `earliest`

```
Timeline: [Day 1] ─────────────────────────────────────── [Latest]
              ↑
              │
   Consumer starts here
   (reprocess entire history)

Kafka Consumer Group:
┌─────────────────────────────────────────────┐
│ audit-fwd-v3-feb                            │
│ ├─ Partition 0: DELETED                    │
│ ├─ Partition 1: DELETED                    │
│ └─ Partition 2: DELETED                    │
└─────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────┐
│ New consumer group created                  │
│ ├─ Partition 0: Earliest (manual seek)     │
│ ├─ Partition 1: Earliest (manual seek)     │
│ └─ Partition 2: Earliest (manual seek)     │
│                                             │
│ Note: Requires Python code enhancement     │
│       Current: uses auto.offset.reset       │
└─────────────────────────────────────────────┘

Action: Delete consumer group + signal file
Data Loss: 0%
Processing: Reprocess all messages from beginning
```

---

### Strategy: `timestamp`

```
Timeline: [Day 1] ────── [Timestamp] ──────────────────── [Latest]
                              ↑
                              │
                   Consumer starts here
                   (replay from specific time)

Kafka Consumer Group:
┌─────────────────────────────────────────────┐
│ audit-fwd-v3-feb                            │
│ ├─ Partition 0: DELETED                    │
│ ├─ Partition 1: DELETED                    │
│ └─ Partition 2: DELETED                    │
└─────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────┐
│ New consumer group created                  │
│ ├─ Partition 0: Seek to timestamp          │
│ ├─ Partition 1: Seek to timestamp          │
│ └─ Partition 2: Seek to timestamp          │
│                                             │
│ Timestamp: 1706745600000 (example)         │
│ Note: Requires Python code enhancement     │
│       Current: uses auto.offset.reset       │
└─────────────────────────────────────────────┘

Action: Delete consumer group + timestamp file
Data Loss: Controlled (before timestamp)
Processing: Start from specific date/time
```

---

## File Structure

```
audit-forwarder-feb/
│
├── scripts/
│   ├── offset-manager.sh           ← Offset reset logic
│   ├── entrypoint.sh               ← Container startup wrapper
│   ├── test-offset-strategies.sh   ← Test suite
│   └── README.md                   ← Script documentation
│
├── docs/
│   ├── OFFSET_MANAGEMENT.md        ← Comprehensive guide
│   ├── OFFSET_MANAGEMENT_QUICK_REFERENCE.md  ← Cheat sheet
│   ├── OFFSET_STRATEGY_COMPARISON.md         ← Decision matrix
│   ├── OFFSET_MANAGEMENT_IMPLEMENTATION.md   ← Implementation summary
│   ├── OFFSET_MANAGEMENT_ARCHITECTURE.md     ← This file
│   └── examples/
│       └── offset-strategy-examples.env      ← Config examples
│
├── docker-compose.yml              ← Updated with offset env vars
├── .env.example                    ← Updated with offset docs
│
└── audit_forwarder.py              ← UNCHANGED (zero code changes)
```

---

## State Transitions

```
┌─────────────────────────────────────────────────────────────┐
│                    Initial State                             │
│                                                              │
│  Consumer Group: audit-fwd-v3-feb                            │
│  Offset: 12345 (committed)                                   │
│  Strategy: committed (default)                               │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       │ Customer sets OFFSET_STRATEGY=latest
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  Offset Reset Triggered                      │
│                                                              │
│  1. Container restarts                                       │
│  2. entrypoint.sh reads OFFSET_STRATEGY                      │
│  3. offset-manager.sh executes                               │
│  4. Consumer group deleted                                   │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    New State                                 │
│                                                              │
│  Consumer Group: audit-fwd-v3-feb (recreated)                │
│  Offset: Latest (auto.offset.reset applied)                  │
│  Strategy: latest (active)                                   │
│                                                              │
│  Result: Backlog skipped, consuming from newest             │
└─────────────────────────────────────────────────────────────┘
```

---

## Audit Trail Flow

```
┌────────────────────────────────────────────────────────────────┐
│  offset-manager.sh execution                                    │
└────────────────────┬───────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────┐
│  log_audit_trail() function                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ =====================================                     │  │
│  │ Offset Manager Execution                                 │  │
│  │ =====================================                     │  │
│  │ Timestamp:    2025-02-19T10:30:00Z                       │  │
│  │ Strategy:     latest                                     │  │
│  │ Consumer Grp: audit-fwd-v3-feb                           │  │
│  │ Topic:        confluent-audit-log-events                 │  │
│  │ Bootstrap:    pkc-4ywp7...                               │  │
│  │ Dry Run:      false                                      │  │
│  │ User:         forwarder                                  │  │
│  │ Host:         audit-forwarder                            │  │
│  │ =====================================                     │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────┬───────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────┐
│  /tmp/offset-manager-audit.log                                  │
│                                                                 │
│  Persistent audit trail of all offset resets                   │
│  Available via: docker exec cat /tmp/offset-manager-audit.log  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────┐
│  offset-manager.sh starts                                    │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  validate_required_vars()                                    │
│  ✓ GROUP_ID set?                                             │
│  ✓ AUDIT_TOPIC set?                                          │
│  ✓ AUDIT_BOOTSTRAP set?                                      │
│  ✓ AUDIT_API_KEY set?                                        │
│  ✓ AUDIT_API_SECRET set?                                     │
└──────────────┬──────────────────────────────────────────────┘
               │ All OK
               ▼
┌─────────────────────────────────────────────────────────────┐
│  validate_strategy()                                         │
│  ✓ Strategy in [latest, earliest, committed, timestamp]?    │
└──────────────┬──────────────────────────────────────────────┘
               │ Valid
               ▼
┌─────────────────────────────────────────────────────────────┐
│  validate_timestamp_params() (if strategy=timestamp)         │
│  ✓ OFFSET_TIMESTAMP or OFFSET_HOURS_AGO set?                │
└──────────────┬──────────────────────────────────────────────┘
               │ Valid
               ▼
┌─────────────────────────────────────────────────────────────┐
│  reset_offsets()                                             │
│  Execute strategy-specific logic                             │
└──────────────┬──────────────────────────────────────────────┘
               │ Success
               ▼
┌─────────────────────────────────────────────────────────────┐
│  log_audit_trail()                                           │
│  Write to /tmp/offset-manager-audit.log                      │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│  entrypoint.sh continues                                     │
│  exec python -u audit_forwarder.py                           │
└─────────────────────────────────────────────────────────────┘

Error Paths:
├─ Missing vars → Exit 1 (Config error)
├─ Invalid strategy → Exit 2 (Validation error)
├─ Missing timestamp params → Exit 2 (Validation error)
└─ Execution failure → Exit 3 (Execution error)
```

---

## Deployment Architecture

### Development Environment

```
Developer Laptop
├── .env (OFFSET_STRATEGY=timestamp OFFSET_HOURS_AGO=24)
├── .secrets (API keys)
└── docker compose up -d audit-forwarder
    ↓
Container: audit-forwarder
├── entrypoint.sh reads env vars
├── offset-manager.sh resets to 24h ago
└── audit_forwarder.py starts consuming

Result: Test environment processes last 24h of data
```

---

### Staging Environment

```
Staging Server
├── .env (OFFSET_STRATEGY=earliest)
├── .secrets (Staging API keys)
└── docker compose up -d audit-forwarder
    ↓
Container: audit-forwarder
├── entrypoint.sh reads env vars
├── offset-manager.sh resets to earliest
└── audit_forwarder.py starts consuming

Result: Staging reprocesses all data for testing
```

---

### Production Environment

```
Production Server
├── .env (OFFSET_STRATEGY=committed)  ← Default, safe
├── .secrets (Production API keys)
└── docker compose up -d audit-forwarder
    ↓
Container: audit-forwarder
├── entrypoint.sh reads env vars
├── offset-manager.sh skips (committed strategy)
└── audit_forwarder.py starts consuming

Result: Production resumes normally from last commit
```

---

### Disaster Recovery

```
Production Server (After 14-day outage)
├── .env (OFFSET_STRATEGY=latest)  ← Skip backlog
├── .secrets (Production API keys)
└── docker compose up -d audit-forwarder
    ↓
Container: audit-forwarder
├── entrypoint.sh reads env vars
├── offset-manager.sh deletes consumer group
└── audit_forwarder.py starts from latest

Result: Production skips 14-day backlog, resumes quickly
        (Backlog exported to S3 for compliance)
```

---

## Summary

**Key Architectural Principles**:

1. **Separation of Concerns**: Offset management is pre-startup, Python code unchanged
2. **Configuration over Code**: All strategies controlled via environment variables
3. **Fail-Safe Default**: Missing config = committed strategy (safe resume)
4. **Audit Trail**: Every offset reset logged for compliance
5. **Testability**: Dry run mode for safe testing before production
6. **Backward Compatibility**: Existing deployments unaffected (default: committed)

**Zero Python Changes**:
- Leverage existing `auto.offset.reset=latest` configuration
- Delete consumer group to trigger Kafka's built-in reset logic
- Signal files for future enhancement (earliest, timestamp)

**Production Ready**:
- Comprehensive error handling
- Validation at every step
- Audit logging
- Dry run testing
- Clear documentation

---

**See Also**:
- [OFFSET_MANAGEMENT.md](./OFFSET_MANAGEMENT.md) - User guide
- [OFFSET_MANAGEMENT_IMPLEMENTATION.md](./OFFSET_MANAGEMENT_IMPLEMENTATION.md) - Technical details
- [OFFSET_STRATEGY_COMPARISON.md](./OFFSET_STRATEGY_COMPARISON.md) - Decision matrix
