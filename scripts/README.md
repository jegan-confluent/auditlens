# AuditLens Scripts

This directory contains operational scripts for managing the AuditLens forwarder.

## Scripts

### `offset-manager.sh`

**Purpose**: Manages Kafka consumer group offsets before forwarder startup

**Features**:
- 4 offset strategies: committed, latest, earliest, timestamp
- Dry run mode for testing
- Audit trail logging
- Comprehensive error handling

**Usage**:
```bash
# Automatic (via docker-compose)
OFFSET_STRATEGY=latest docker compose up -d audit-forwarder

# Manual execution
export GROUP_ID=audit-fwd-v3-feb
export AUDIT_TOPIC=confluent-audit-log-events
export AUDIT_BOOTSTRAP=pkc-xxxxx.aws.confluent.cloud:9092
export AUDIT_API_KEY=your-key
export AUDIT_API_SECRET=your-secret
export OFFSET_STRATEGY=latest
./offset-manager.sh
```

**Documentation**: See [docs/OFFSET_MANAGEMENT.md](../docs/OFFSET_MANAGEMENT.md)

---

### `entrypoint.sh`

**Purpose**: Container entrypoint that runs offset management before starting forwarder

**Features**:
- Pre-startup offset configuration
- Environment variable validation
- Graceful error handling

**Usage**: Automatically invoked by docker-compose (no manual execution needed)

---

### `test-offset-strategies.sh`

**Purpose**: Test suite for all offset management strategies

**Features**:
- Tests all 4 strategies in dry run mode
- Error handling validation
- Interactive and batch modes
- Safe to run (no production changes)

**Usage**:
```bash
# Run all tests
./test-offset-strategies.sh

# Interactive mode
./test-offset-strategies.sh --interactive

# Run specific test
./test-offset-strategies.sh committed
./test-offset-strategies.sh latest
./test-offset-strategies.sh earliest
./test-offset-strategies.sh timestamp-abs
```

---

### Other Scripts

- `setup-wizard.sh` - Interactive setup wizard for initial configuration
- `bootstrap_auditlens.py` - First-time AuditLens bootstrap for Docker or Kubernetes
- `setup-wizard.sh` - Compatibility wrapper to the bootstrap command
- `audit_report.py` - Generate audit reports from processed events
- `audit_search.py` - Search audit logs by various criteria
- `generate_load.py` - Load testing tool for Kafka topics
- `build-dist.sh` - Build distribution packages
- `session_start.sh` - Print the repo-local session brief before editing
- `session_end_draft.sh` - Draft the next append-only session log entry
- `append_changelog_entry.sh` - Append a confirmed session draft to `CHANGELOG.md`

---

## Quick Reference

### Test Offset Strategies (Safe)
```bash
cd scripts
./test-offset-strategies.sh
```

### Apply Offset Strategy (Production)
```bash
# 1. Set strategy in .env
echo "OFFSET_STRATEGY=latest" >> ../.env

# 2. Restart forwarder
docker compose restart audit-forwarder

# 3. Verify in logs
docker logs -f audit-forwarder | grep offset
```

### View Audit Trail
```bash
docker exec -it audit-forwarder cat /tmp/offset-manager-audit.log
```

---

## Documentation

- [Offset Management Guide](../docs/OFFSET_MANAGEMENT.md) - Comprehensive guide
- [Quick Reference](../docs/OFFSET_MANAGEMENT_QUICK_REFERENCE.md) - Cheat sheet
- [Strategy Comparison](../docs/OFFSET_STRATEGY_COMPARISON.md) - Decision matrix
- [Examples](../docs/examples/offset-strategy-examples.env) - Configuration snippets
- [Session Memory Workflow](../docs/SESSION_MEMORY_WORKFLOW.md) - Codex start/end workflow
- [Bootstrap Setup](../docs/BOOTSTRAP_SETUP.md) - first-time user setup flow

---

## Support

For issues or questions:
1. Check documentation in `docs/`
2. Review test output from `test-offset-strategies.sh`
3. Check audit logs in `/tmp/offset-manager-audit.log`
4. Contact your Kafka ops team
