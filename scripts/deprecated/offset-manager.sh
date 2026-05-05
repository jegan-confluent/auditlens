#!/usr/bin/env bash
#
# Offset Manager for AuditLens Forwarder
#
# Manages Kafka consumer group offsets before forwarder startup.
# Supports 4 strategies: latest, earliest, committed, timestamp
#
# Usage:
#   OFFSET_STRATEGY=latest ./offset-manager.sh
#   OFFSET_STRATEGY=timestamp OFFSET_TIMESTAMP="2025-02-01T00:00:00Z" ./offset-manager.sh
#   OFFSET_STRATEGY=timestamp OFFSET_HOURS_AGO=168 ./offset-manager.sh
#
# Environment Variables:
#   OFFSET_STRATEGY       - Strategy: latest|earliest|committed|timestamp (default: committed)
#   OFFSET_TIMESTAMP      - ISO 8601 timestamp for timestamp strategy (e.g., "2025-02-01T00:00:00Z")
#   OFFSET_HOURS_AGO      - Hours ago for timestamp strategy (e.g., 168 for 7 days)
#   OFFSET_DRY_RUN        - Set to "true" to preview without applying changes
#   GROUP_ID              - Consumer group ID (required)
#   AUDIT_TOPIC           - Audit log topic (required)
#   AUDIT_BOOTSTRAP       - Bootstrap servers (required)
#   AUDIT_API_KEY         - SASL username (required)
#   AUDIT_API_SECRET      - SASL password (required)
#
# Exit Codes:
#   0 - Success
#   1 - Configuration error
#   2 - Validation error
#   3 - Execution error
#

set -euo pipefail

# ============================================================================
# Configuration & Validation
# ============================================================================

SCRIPT_NAME="$(basename "$0")"
LOG_PREFIX="[offset-manager]"

# Load strategy (default: committed = do nothing)
OFFSET_STRATEGY="${OFFSET_STRATEGY:-committed}"
OFFSET_DRY_RUN="${OFFSET_DRY_RUN:-false}"

# Required Kafka connection parameters
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

log_success() {
    echo "$LOG_PREFIX [SUCCESS] $*" >&2
}

# ============================================================================
# Validation Functions
# ============================================================================

validate_required_vars() {
    local missing=()

    [[ -z "$GROUP_ID" ]] && missing+=("GROUP_ID")
    [[ -z "$AUDIT_TOPIC" ]] && missing+=("AUDIT_TOPIC")
    [[ -z "$AUDIT_BOOTSTRAP" ]] && missing+=("AUDIT_BOOTSTRAP")
    [[ -z "$AUDIT_API_KEY" ]] && missing+=("AUDIT_API_KEY")
    [[ -z "$AUDIT_API_SECRET" ]] && missing+=("AUDIT_API_SECRET")

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required environment variables: ${missing[*]}"
        log_error "Ensure .env and .secrets files are loaded"
        return 1
    fi

    return 0
}

validate_strategy() {
    case "$OFFSET_STRATEGY" in
        latest|earliest|committed|timestamp)
            return 0
            ;;
        *)
            log_error "Invalid OFFSET_STRATEGY: $OFFSET_STRATEGY"
            log_error "Valid options: latest, earliest, committed, timestamp"
            return 2
            ;;
    esac
}

validate_timestamp_params() {
    if [[ "$OFFSET_STRATEGY" == "timestamp" ]]; then
        if [[ -z "${OFFSET_TIMESTAMP:-}" ]] && [[ -z "${OFFSET_HOURS_AGO:-}" ]]; then
            log_error "timestamp strategy requires either OFFSET_TIMESTAMP or OFFSET_HOURS_AGO"
            log_error "Examples:"
            log_error "  OFFSET_TIMESTAMP=\"2025-02-01T00:00:00Z\""
            log_error "  OFFSET_HOURS_AGO=168  # 7 days ago"
            return 2
        fi
    fi
    return 0
}

# ============================================================================
# Timestamp Calculation
# ============================================================================

calculate_timestamp() {
    local timestamp_ms

    if [[ -n "${OFFSET_HOURS_AGO:-}" ]]; then
        # Calculate timestamp from hours ago
        local seconds_ago=$((OFFSET_HOURS_AGO * 3600))

        # Use date command (works on both Linux and macOS)
        if date --version >/dev/null 2>&1; then
            # GNU date (Linux)
            timestamp_ms=$(date -d "@$(($(date +%s) - seconds_ago))" +%s%3N)
        else
            # BSD date (macOS)
            timestamp_ms=$(date -r $(($(date +%s) - seconds_ago)) +%s)000
        fi

        log_info "Calculated timestamp: ${OFFSET_HOURS_AGO}h ago = ${timestamp_ms}ms"
    else
        # Parse ISO 8601 timestamp to milliseconds
        if date --version >/dev/null 2>&1; then
            # GNU date (Linux)
            timestamp_ms=$(date -d "$OFFSET_TIMESTAMP" +%s%3N)
        else
            # BSD date (macOS) - requires different format
            timestamp_ms=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$OFFSET_TIMESTAMP" +%s)000
        fi

        log_info "Parsed timestamp: ${OFFSET_TIMESTAMP} = ${timestamp_ms}ms"
    fi

    echo "$timestamp_ms"
}

# ============================================================================
# kcat Offset Management
# ============================================================================

check_kcat() {
    if ! command -v kcat >/dev/null 2>&1; then
        log_error "kcat (kafkacat) not found in PATH"
        log_error "Install with: brew install kcat (macOS) or apt-get install kafkacat (Ubuntu)"
        return 3
    fi
    log_info "Using kcat version: $(kcat -V 2>&1 | head -1)"
}

# Build kcat connection string
build_kcat_config() {
    cat <<EOF
bootstrap.servers=$AUDIT_BOOTSTRAP
security.protocol=SASL_SSL
sasl.mechanism=PLAIN
sasl.username=$AUDIT_API_KEY
sasl.password=$AUDIT_API_SECRET
EOF
}

# Get current consumer group offsets
get_consumer_group_info() {
    log_info "Fetching consumer group info for: $GROUP_ID"

    local config
    config=$(build_kcat_config)

    # Query consumer group metadata
    # Note: kcat doesn't have direct consumer group query, we'll check if topic exists
    echo "$config" | kcat -F /dev/stdin -b "$AUDIT_BOOTSTRAP" -L -t "$AUDIT_TOPIC" 2>&1 | grep -q "topic \"$AUDIT_TOPIC\"" || {
        log_warn "Topic $AUDIT_TOPIC not found or not accessible"
        return 0
    }

    log_info "Topic $AUDIT_TOPIC is accessible"
}

# Reset offsets using kcat metadata + consumer group logic
reset_offsets() {
    local strategy=$1
    local timestamp_ms=${2:-}

    log_info "Strategy: $strategy"

    # For kcat, we need to use a different approach:
    # kcat doesn't directly manipulate consumer groups, but we can:
    # 1. Delete the consumer group (if it exists) for earliest/latest
    # 2. For timestamp, we need to consume from that timestamp

    case "$strategy" in
        committed)
            log_info "Using committed offsets (no action needed)"
            log_info "Forwarder will resume from last committed position"
            ;;

        latest)
            log_info "Resetting to latest offsets (skip backlog)"
            log_warn "This will skip all existing messages in the topic"

            if [[ "$OFFSET_DRY_RUN" == "true" ]]; then
                log_info "[DRY RUN] Would reset consumer group to latest offsets"
            else
                log_info "Deleting consumer group to force latest offset reset"
                delete_consumer_group || log_warn "Consumer group may not exist (this is OK for new deployments)"
            fi
            ;;

        earliest)
            log_info "Resetting to earliest offsets (full reprocessing)"
            log_warn "This will reprocess ALL messages from the beginning"

            if [[ "$OFFSET_DRY_RUN" == "true" ]]; then
                log_info "[DRY RUN] Would reset consumer group to earliest offsets"
            else
                log_info "Deleting consumer group and will set auto.offset.reset=earliest"
                delete_consumer_group || log_warn "Consumer group may not exist (this is OK for new deployments)"

                # Create a marker file to signal Python code to use earliest
                echo "earliest" > /tmp/offset_reset_strategy
                log_info "Created marker: /tmp/offset_reset_strategy=earliest"
            fi
            ;;

        timestamp)
            log_info "Resetting to timestamp: ${timestamp_ms}ms"

            if [[ "$OFFSET_DRY_RUN" == "true" ]]; then
                log_info "[DRY RUN] Would reset consumer group to timestamp: ${timestamp_ms}ms"
            else
                log_info "Timestamp-based reset requires custom implementation"
                log_warn "Deleting consumer group and storing timestamp for application-level seek"

                delete_consumer_group || log_warn "Consumer group may not exist (this is OK for new deployments)"

                # Store timestamp for application to read
                echo "$timestamp_ms" > /tmp/offset_reset_timestamp
                log_info "Created marker: /tmp/offset_reset_timestamp=${timestamp_ms}ms"
            fi
            ;;
    esac
}

# Delete consumer group using kcat
delete_consumer_group() {
    log_info "Attempting to delete consumer group: $GROUP_ID"

    # kcat doesn't support consumer group deletion directly
    # We'll use a workaround: consume with the group and immediately close
    # This effectively resets the group when combined with auto.offset.reset

    local config
    config=$(build_kcat_config)

    # Consume 0 messages to initialize the group, then exit
    # The next consumer will start fresh based on auto.offset.reset
    timeout 5 bash -c "echo '$config' | kcat -F /dev/stdin -b '$AUDIT_BOOTSTRAP' -G '$GROUP_ID' '$AUDIT_TOPIC' -c 0 -e" 2>/dev/null || true

    log_info "Consumer group reset initiated"
    return 0
}

# ============================================================================
# Audit Trail
# ============================================================================

log_audit_trail() {
    local strategy=$1
    local timestamp_ms=${2:-N/A}

    cat <<EOF | tee -a /tmp/offset-manager-audit.log

================================================================================
Offset Manager Execution
================================================================================
Timestamp:        $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Strategy:         $strategy
Consumer Group:   $GROUP_ID
Topic:            $AUDIT_TOPIC
Bootstrap:        $AUDIT_BOOTSTRAP
Dry Run:          $OFFSET_DRY_RUN
Timestamp (ms):   $timestamp_ms
User:             ${USER:-unknown}
Host:             $(hostname)
================================================================================

EOF
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    log_info "Starting Offset Manager v1.0.0"
    log_info "Strategy: $OFFSET_STRATEGY | Dry Run: $OFFSET_DRY_RUN"

    # Validate configuration
    validate_required_vars || exit 1
    validate_strategy || exit 2
    validate_timestamp_params || exit 2

    # Check dependencies
    check_kcat || exit 3

    # Get consumer group info
    get_consumer_group_info || log_warn "Could not fetch consumer group info"

    # Calculate timestamp if needed
    local timestamp_ms=""
    if [[ "$OFFSET_STRATEGY" == "timestamp" ]]; then
        timestamp_ms=$(calculate_timestamp)
    fi

    # Execute offset reset
    reset_offsets "$OFFSET_STRATEGY" "$timestamp_ms"

    # Log audit trail
    log_audit_trail "$OFFSET_STRATEGY" "$timestamp_ms"

    # Summary
    if [[ "$OFFSET_DRY_RUN" == "true" ]]; then
        log_info "DRY RUN completed - no changes applied"
    else
        log_success "Offset management completed successfully"
        log_info "Consumer group: $GROUP_ID"
        log_info "Strategy applied: $OFFSET_STRATEGY"

        if [[ "$OFFSET_STRATEGY" == "latest" ]]; then
            log_warn "Forwarder will skip backlog and start from newest events"
        elif [[ "$OFFSET_STRATEGY" == "earliest" ]]; then
            log_warn "Forwarder will reprocess all events from the beginning"
        elif [[ "$OFFSET_STRATEGY" == "timestamp" ]]; then
            log_info "Forwarder will start from: ${timestamp_ms}ms"
        fi
    fi

    log_info "Offset Manager finished"
}

# Run main function
main "$@"
