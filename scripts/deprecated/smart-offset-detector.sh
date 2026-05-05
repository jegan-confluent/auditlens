#!/usr/bin/env bash
#
# Smart Offset Detector for AuditLens Forwarder
#
# Automatically determines the optimal offset strategy based on:
# 1. First-time setup vs restart
# 2. Consumer lag (if group exists)
# 3. Backlog size and age
#
# Returns: Strategy name (latest|committed|timestamp) with reasoning
#
# Exit Codes:
#   0 - Success (strategy determined)
#   1 - Configuration error
#   2 - Detection failed (falls back to safe default)
#

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

LOG_PREFIX="[smart-offset-detector]"
SETUP_MARKER="/app/.setup-complete"
AUDIT_TRAIL="/tmp/offset-detection-audit.log"

# Thresholds for decision logic
LAG_THRESHOLD_1H=3600        # 1 hour worth of events (~3600 events at 1/sec baseline)
LAG_THRESHOLD_SMALL=10000    # Small backlog - process all
LAG_THRESHOLD_MEDIUM=50000   # Medium backlog - use timestamp
TIMESTAMP_LOOKBACK_HOURS=24  # For medium/large backlogs, start from 24h ago

# Required environment variables
GROUP_ID="${GROUP_ID:-}"
AUDIT_TOPIC="${AUDIT_TOPIC:-}"
AUDIT_BOOTSTRAP="${AUDIT_BOOTSTRAP:-}"
AUDIT_API_KEY="${AUDIT_API_KEY:-}"
AUDIT_API_SECRET="${AUDIT_API_SECRET:-}"

# ============================================================================
# Logging Functions
# ============================================================================

log_info() {
    echo "$LOG_PREFIX [INFO] $*" >&2
}

log_warn() {
    echo "$LOG_PREFIX [WARN] $*" >&2
}

log_error() {
    echo "$LOG_PREFIX [ERROR] $*" >&2
}

log_decision() {
    local strategy=$1
    local reason=$2
    echo "$LOG_PREFIX [DECISION] Strategy: $strategy | Reason: $reason" >&2

    # Log to audit trail (ensure directory exists)
    mkdir -p "$(dirname "$AUDIT_TRAIL")" 2>/dev/null || true
    cat >> "$AUDIT_TRAIL" <<EOF
$(date -u +"%Y-%m-%dT%H:%M:%SZ") | GROUP: $GROUP_ID | STRATEGY: $strategy | REASON: $reason
EOF
}

# ============================================================================
# Validation
# ============================================================================

validate_config() {
    local missing=()

    [[ -z "$GROUP_ID" ]] && missing+=("GROUP_ID")
    [[ -z "$AUDIT_TOPIC" ]] && missing+=("AUDIT_TOPIC")
    [[ -z "$AUDIT_BOOTSTRAP" ]] && missing+=("AUDIT_BOOTSTRAP")
    [[ -z "$AUDIT_API_KEY" ]] && missing+=("AUDIT_API_KEY")
    [[ -z "$AUDIT_API_SECRET" ]] && missing+=("AUDIT_API_SECRET")

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required environment variables: ${missing[*]}"
        return 1
    fi

    return 0
}

# ============================================================================
# Consumer Group Detection (using Python + confluent-kafka)
# ============================================================================

check_consumer_group_exists() {
    log_info "Checking if consumer group exists: $GROUP_ID"

    # Use Python with confluent-kafka AdminClient to check consumer group
    python3 -u - <<'PYTHON_EOF'
import sys
import os
from confluent_kafka.admin import AdminClient

# Get config from environment
config = {
    "bootstrap.servers": os.environ["AUDIT_BOOTSTRAP"],
    "security.protocol": "SASL_SSL",
    "sasl.mechanism": "PLAIN",
    "sasl.username": os.environ["AUDIT_API_KEY"],
    "sasl.password": os.environ["AUDIT_API_SECRET"],
    "socket.timeout.ms": 30000,
    "api.version.request.timeout.ms": 30000,
}

try:
    admin = AdminClient(config)
    group_id = os.environ["GROUP_ID"]

    # List consumer groups
    groups = admin.list_consumer_groups(timeout=30)
    group_ids = [g.group_id for g in groups.valid]

    # Check if our group exists
    exists = group_id in group_ids

    # Output result (0 = not exists, 1 = exists)
    print("1" if exists else "0")
    sys.exit(0)

except Exception as e:
    # On error, assume group doesn't exist (safe default)
    print(f"ERROR: {e}", file=sys.stderr)
    print("0")
    sys.exit(0)
PYTHON_EOF
}

# ============================================================================
# Consumer Lag Detection (using Python + confluent-kafka)
# ============================================================================

get_consumer_lag() {
    log_info "Calculating consumer lag for group: $GROUP_ID"

    # Use Python to calculate lag (committed offset vs high watermark)
    python3 -u - <<'PYTHON_EOF'
import sys
import os
from confluent_kafka import Consumer, TopicPartition, KafkaError

# Get config from environment
config = {
    "bootstrap.servers": os.environ["AUDIT_BOOTSTRAP"],
    "security.protocol": "SASL_SSL",
    "sasl.mechanism": "PLAIN",
    "sasl.username": os.environ["AUDIT_API_KEY"],
    "sasl.password": os.environ["AUDIT_API_SECRET"],
    "group.id": os.environ["GROUP_ID"],
    "enable.auto.commit": False,
    "socket.timeout.ms": 30000,
    "session.timeout.ms": 45000,
}

try:
    consumer = Consumer(config)
    topic = os.environ["AUDIT_TOPIC"]

    # Get topic metadata to find partitions
    metadata = consumer.list_topics(topic, timeout=30)
    if topic not in metadata.topics:
        print("ERROR: Topic not found", file=sys.stderr)
        print("0")
        sys.exit(0)

    partitions = metadata.topics[topic].partitions

    # Calculate lag for each partition
    total_lag = 0
    for partition_id in partitions.keys():
        tp = TopicPartition(topic, partition_id)

        # Get committed offset
        committed = consumer.committed([tp], timeout=30)
        committed_offset = committed[0].offset if committed[0].offset >= 0 else 0

        # Get high watermark (latest offset)
        low, high = consumer.get_watermark_offsets(tp, timeout=30)

        # Calculate lag
        lag = high - committed_offset
        total_lag += lag

        print(f"Partition {partition_id}: committed={committed_offset}, high={high}, lag={lag}", file=sys.stderr)

    # Output total lag
    print(total_lag)
    consumer.close()
    sys.exit(0)

except Exception as e:
    # On error, return 0 lag (safe default)
    print(f"ERROR: {e}", file=sys.stderr)
    print("0")
    sys.exit(0)
PYTHON_EOF
}

# ============================================================================
# Detection Logic
# ============================================================================

detect_strategy() {
    log_info "Starting smart offset detection..."
    log_info "Consumer Group: $GROUP_ID | Topic: $AUDIT_TOPIC"

    # ────────────────────────────────────────────────────────────────
    # Scenario 1: First-time setup
    # ────────────────────────────────────────────────────────────────

    if [[ ! -f "$SETUP_MARKER" ]]; then
        log_decision "latest" "First-time setup (no .setup-complete marker)"
        log_info "Creating setup marker: $SETUP_MARKER"

        # Create marker with metadata
        # Use mkdir -p to ensure directory exists (in case /app doesn't exist)
        mkdir -p "$(dirname "$SETUP_MARKER")" 2>/dev/null || true

        cat > "$SETUP_MARKER" <<EOF
First setup: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Consumer Group: $GROUP_ID
Initial Strategy: latest (skip historical backlog)
EOF

        log_info "Setup marker created successfully"
        echo "latest"
        return 0
    fi

    # ────────────────────────────────────────────────────────────────
    # Scenario 2: Check if consumer group exists
    # ────────────────────────────────────────────────────────────────

    local group_exists
    group_exists=$(check_consumer_group_exists)

    if [[ "$group_exists" == "0" ]]; then
        # Marker exists but consumer group doesn't - user deleted it
        log_decision "latest" "Consumer group deleted (intentional reset signal)"
        echo "latest"
        return 0
    fi

    # ────────────────────────────────────────────────────────────────
    # Scenario 3: Consumer group exists - check lag
    # ────────────────────────────────────────────────────────────────

    log_info "Consumer group exists - calculating lag..."

    local total_lag
    total_lag=$(get_consumer_lag)

    log_info "Total consumer lag: $total_lag messages"

    # Sub-scenario 3a: Small lag (< 1 hour worth)
    if [[ $total_lag -lt $LAG_THRESHOLD_1H ]]; then
        log_decision "committed" "Normal restart (lag: $total_lag < ${LAG_THRESHOLD_1H} threshold)"
        echo "committed"
        return 0
    fi

    # Sub-scenario 3b: Medium lag (1h - 24h worth) - check backlog size
    if [[ $total_lag -lt $LAG_THRESHOLD_SMALL ]]; then
        log_decision "committed" "Small backlog (lag: $total_lag < ${LAG_THRESHOLD_SMALL}) - process all"
        echo "committed"
        return 0
    elif [[ $total_lag -lt $LAG_THRESHOLD_MEDIUM ]]; then
        log_decision "timestamp" "Medium backlog (lag: $total_lag < ${LAG_THRESHOLD_MEDIUM}) - last ${TIMESTAMP_LOOKBACK_HOURS}h"
        # Export timestamp for entrypoint to use
        export OFFSET_HOURS_AGO=$TIMESTAMP_LOOKBACK_HOURS
        echo "timestamp"
        return 0
    else
        log_decision "latest" "Large backlog (lag: $total_lag > ${LAG_THRESHOLD_MEDIUM}) - skip old events"
        echo "latest"
        return 0
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    log_info "═══════════════════════════════════════════════════════════"
    log_info "Smart Offset Detector v1.0.0"
    log_info "═══════════════════════════════════════════════════════════"

    # Validate configuration
    if ! validate_config; then
        log_error "Configuration validation failed"
        log_warn "Falling back to safe default: latest"
        echo "latest"
        exit 2
    fi

    # Detect strategy
    local strategy
    if strategy=$(detect_strategy); then
        log_info "═══════════════════════════════════════════════════════════"
        log_info "Detection complete: $strategy"
        log_info "═══════════════════════════════════════════════════════════"
        echo "$strategy"
        exit 0
    else
        log_error "Detection failed"
        log_warn "Falling back to safe default: latest"
        echo "latest"
        exit 2
    fi
}

# Run main
main "$@"
