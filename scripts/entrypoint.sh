#!/usr/bin/env bash
#
# Entrypoint for AuditLens Forwarder Container
#
# Uses smart-offset-detector.sh for zero-config offset management
# Automatically chooses the right strategy based on context
#

set -euo pipefail

echo "[entrypoint] Starting AuditLens Forwarder v3.0.1"
echo "[entrypoint] Offset Strategy: ${OFFSET_STRATEGY:-auto}"

# ============================================================================
# Smart Offset Detection
# ============================================================================

detect_offset_strategy() {
    local strategy="${OFFSET_STRATEGY:-auto}"

    # If explicit strategy is set (not "auto" or empty), use it
    if [[ -n "$strategy" ]] && [[ "$strategy" != "auto" ]]; then
        echo "[entrypoint] Using manual override: $strategy"
        echo "$strategy"
        return 0
    fi

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
}

# ============================================================================
# Apply Offset Strategy
# ============================================================================

apply_offset_strategy() {
    local strategy=$1

    echo "[entrypoint] ================================================"
    echo "[entrypoint] Applying offset strategy: $strategy"
    echo "[entrypoint] ================================================"

    case "$strategy" in
        committed)
            echo "[entrypoint] Strategy: committed"
            echo "[entrypoint] → Forwarder will resume from last committed offset"
            echo "[entrypoint] → No offset reset needed"
            ;;

        latest)
            echo "[entrypoint] Strategy: latest"
            echo "[entrypoint] → Forwarder will skip backlog and start from newest events"
            echo "[entrypoint] → Consumer group will be deleted (if exists)"

            # Delete consumer group using Python
            delete_consumer_group
            ;;

        timestamp)
            echo "[entrypoint] Strategy: timestamp"
            local hours_ago="${OFFSET_HOURS_AGO:-24}"
            echo "[entrypoint] → Forwarder will start from ${hours_ago}h ago"
            echo "[entrypoint] → Consumer group will be deleted and timestamp marker created"

            # Delete consumer group and create timestamp marker
            delete_consumer_group
            create_timestamp_marker "$hours_ago"
            ;;

        earliest)
            echo "[entrypoint] Strategy: earliest"
            echo "[entrypoint] → Forwarder will reprocess ALL events from beginning"
            echo "[entrypoint] → Consumer group will be deleted"

            delete_consumer_group
            ;;

        *)
            echo "[entrypoint] ERROR: Invalid strategy: $strategy"
            exit 1
            ;;
    esac
}

# ============================================================================
# Helper Functions
# ============================================================================

delete_consumer_group() {
    echo "[entrypoint] Deleting consumer group: ${GROUP_ID}"

    python3 -u - <<'PYTHON_EOF'
import sys
import os
from confluent_kafka.admin import AdminClient

config = {
    "bootstrap.servers": os.environ["AUDIT_BOOTSTRAP"],
    "security.protocol": "SASL_SSL",
    "sasl.mechanism": "PLAIN",
    "sasl.username": os.environ["AUDIT_API_KEY"],
    "sasl.password": os.environ["AUDIT_API_SECRET"],
    "socket.timeout.ms": 30000,
}

try:
    admin = AdminClient(config)
    group_id = os.environ["GROUP_ID"]

    # Delete consumer group
    result = admin.delete_consumer_groups([group_id], request_timeout=30)

    # Wait for completion
    for group, future in result.items():
        try:
            future.result()
            print(f"Consumer group deleted: {group}")
        except Exception as e:
            # Group may not exist - this is OK
            print(f"Consumer group deletion (may not exist): {e}")

except Exception as e:
    print(f"Error deleting consumer group: {e}")
    sys.exit(0)  # Don't fail - group may not exist
PYTHON_EOF
}

create_timestamp_marker() {
    local hours_ago=$1

    echo "[entrypoint] Creating timestamp marker: ${hours_ago}h ago"

    # Calculate timestamp in milliseconds
    if date --version >/dev/null 2>&1; then
        # GNU date (Linux)
        timestamp_ms=$(date -d "@$(($(date +%s) - hours_ago * 3600))" +%s%3N)
    else
        # BSD date (macOS)
        timestamp_ms=$(date -r $(($(date +%s) - hours_ago * 3600)) +%s)000
    fi

    # Store for application to use
    echo "$timestamp_ms" > /tmp/offset_reset_timestamp
    echo "[entrypoint] Timestamp marker created: ${timestamp_ms}ms"
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    echo "[entrypoint] ================================================"
    echo "[entrypoint] AuditLens Forwarder - Container Startup"
    echo "[entrypoint] ================================================"
    echo "[entrypoint] Consumer Group: ${GROUP_ID:-audit-fwd-v3-feb}"
    echo "[entrypoint] Audit Topic: ${AUDIT_TOPIC:-confluent-audit-log-events}"
    echo "[entrypoint] Mode: ${OFFSET_STRATEGY:-auto} (smart detection)"
    echo "[entrypoint] ================================================"

    # Detect optimal offset strategy
    local strategy
    strategy=$(detect_offset_strategy)

    # Apply the strategy
    apply_offset_strategy "$strategy"

    echo "[entrypoint] ================================================"
    echo "[entrypoint] Starting audit forwarder..."
    echo "[entrypoint] ================================================"

    # Execute the forwarder
    exec python -u audit_forwarder.py
}

# Run main
main "$@"
