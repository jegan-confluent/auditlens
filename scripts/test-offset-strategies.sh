#!/usr/bin/env bash
#
# Test Script for Offset Management Strategies
#
# This script demonstrates all 4 offset strategies with dry run mode
# Safe to run - does not apply any changes to production
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=================================================="
echo "Offset Strategy Testing Suite"
echo "=================================================="
echo "Project Root: $PROJECT_ROOT"
echo "Test Mode: DRY RUN (no changes applied)"
echo "=================================================="
echo ""

# Load environment (if .env exists)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
    echo "✓ Loaded .env configuration"
fi

if [[ -f "$PROJECT_ROOT/.secrets" ]]; then
    set -a
    source "$PROJECT_ROOT/.secrets"
    set +a
    echo "✓ Loaded .secrets configuration"
fi

echo ""
echo "Current Configuration:"
echo "  GROUP_ID: ${GROUP_ID:-audit-fwd-v3-feb}"
echo "  AUDIT_TOPIC: ${AUDIT_TOPIC:-confluent-audit-log-events}"
echo "  BOOTSTRAP: ${AUDIT_BOOTSTRAP:-not set}"
echo ""

# Export dry run mode
export OFFSET_DRY_RUN=true

# ============================================================================
# Test 1: committed (default)
# ============================================================================

test_committed() {
    echo "=================================================="
    echo "TEST 1: committed Strategy (Resume Normal)"
    echo "=================================================="
    echo "Description: Resume from last committed offset"
    echo "Use Case: Normal restarts, production default"
    echo ""

    export OFFSET_STRATEGY=committed

    echo "Running: $SCRIPT_DIR/offset-manager.sh"
    echo ""

    bash "$SCRIPT_DIR/offset-manager.sh" || echo "Test completed with status: $?"

    echo ""
    echo "✓ Test 1 completed"
    echo ""
}

# ============================================================================
# Test 2: latest
# ============================================================================

test_latest() {
    echo "=================================================="
    echo "TEST 2: latest Strategy (Skip Backlog)"
    echo "=================================================="
    echo "Description: Skip backlog, start from newest events"
    echo "Use Case: Fast recovery after extended downtime"
    echo ""

    export OFFSET_STRATEGY=latest

    echo "Running: $SCRIPT_DIR/offset-manager.sh"
    echo ""

    bash "$SCRIPT_DIR/offset-manager.sh" || echo "Test completed with status: $?"

    echo ""
    echo "✓ Test 2 completed"
    echo ""
}

# ============================================================================
# Test 3: earliest
# ============================================================================

test_earliest() {
    echo "=================================================="
    echo "TEST 3: earliest Strategy (Full Reprocessing)"
    echo "=================================================="
    echo "Description: Reprocess all events from beginning"
    echo "Use Case: Compliance audit, data rebuild"
    echo ""

    export OFFSET_STRATEGY=earliest

    echo "Running: $SCRIPT_DIR/offset-manager.sh"
    echo ""

    bash "$SCRIPT_DIR/offset-manager.sh" || echo "Test completed with status: $?"

    echo ""
    echo "✓ Test 3 completed"
    echo ""
}

# ============================================================================
# Test 4: timestamp (absolute)
# ============================================================================

test_timestamp_absolute() {
    echo "=================================================="
    echo "TEST 4: timestamp Strategy (Absolute Date)"
    echo "=================================================="
    echo "Description: Start from specific timestamp"
    echo "Use Case: Disaster recovery to known-good point"
    echo ""

    export OFFSET_STRATEGY=timestamp
    export OFFSET_TIMESTAMP="2025-02-01T00:00:00Z"

    echo "Running: $SCRIPT_DIR/offset-manager.sh"
    echo ""

    bash "$SCRIPT_DIR/offset-manager.sh" || echo "Test completed with status: $?"

    unset OFFSET_TIMESTAMP

    echo ""
    echo "✓ Test 4 completed"
    echo ""
}

# ============================================================================
# Test 5: timestamp (relative)
# ============================================================================

test_timestamp_relative() {
    echo "=================================================="
    echo "TEST 5: timestamp Strategy (Relative Time)"
    echo "=================================================="
    echo "Description: Start from N hours ago"
    echo "Use Case: Reprocess last 7 days of data"
    echo ""

    export OFFSET_STRATEGY=timestamp
    export OFFSET_HOURS_AGO=168  # 7 days

    echo "Running: $SCRIPT_DIR/offset-manager.sh"
    echo ""

    bash "$SCRIPT_DIR/offset-manager.sh" || echo "Test completed with status: $?"

    unset OFFSET_HOURS_AGO

    echo ""
    echo "✓ Test 5 completed"
    echo ""
}

# ============================================================================
# Test 6: Error handling - invalid strategy
# ============================================================================

test_invalid_strategy() {
    echo "=================================================="
    echo "TEST 6: Error Handling (Invalid Strategy)"
    echo "=================================================="
    echo "Description: Test validation of invalid strategy"
    echo "Expected: Should fail with clear error message"
    echo ""

    export OFFSET_STRATEGY=invalid_strategy

    echo "Running: $SCRIPT_DIR/offset-manager.sh"
    echo ""

    if bash "$SCRIPT_DIR/offset-manager.sh" 2>&1; then
        echo "❌ Test failed - should have rejected invalid strategy"
    else
        echo "✓ Test passed - correctly rejected invalid strategy"
    fi

    echo ""
    echo "✓ Test 6 completed"
    echo ""
}

# ============================================================================
# Test 7: Error handling - timestamp without params
# ============================================================================

test_timestamp_missing_params() {
    echo "=================================================="
    echo "TEST 7: Error Handling (Missing Timestamp Params)"
    echo "=================================================="
    echo "Description: Test timestamp strategy without required params"
    echo "Expected: Should fail with clear error message"
    echo ""

    export OFFSET_STRATEGY=timestamp
    unset OFFSET_TIMESTAMP OFFSET_HOURS_AGO

    echo "Running: $SCRIPT_DIR/offset-manager.sh"
    echo ""

    if bash "$SCRIPT_DIR/offset-manager.sh" 2>&1; then
        echo "❌ Test failed - should have required timestamp params"
    else
        echo "✓ Test passed - correctly required timestamp params"
    fi

    echo ""
    echo "✓ Test 7 completed"
    echo ""
}

# ============================================================================
# Run all tests
# ============================================================================

run_all_tests() {
    test_committed
    sleep 2

    test_latest
    sleep 2

    test_earliest
    sleep 2

    test_timestamp_absolute
    sleep 2

    test_timestamp_relative
    sleep 2

    test_invalid_strategy
    sleep 2

    test_timestamp_missing_params

    echo "=================================================="
    echo "All Tests Completed"
    echo "=================================================="
    echo ""
    echo "Summary:"
    echo "  ✓ 7 tests executed"
    echo "  ✓ All tests ran in DRY RUN mode"
    echo "  ✓ No changes applied to production"
    echo ""
    echo "Next Steps:"
    echo "  1. Review test output above"
    echo "  2. Check audit log: /tmp/offset-manager-audit.log"
    echo "  3. Apply strategy in production by setting OFFSET_DRY_RUN=false"
    echo ""
}

# ============================================================================
# Interactive mode
# ============================================================================

interactive_mode() {
    echo "Select test to run:"
    echo "  1) committed (default)"
    echo "  2) latest (skip backlog)"
    echo "  3) earliest (full reprocessing)"
    echo "  4) timestamp (absolute date)"
    echo "  5) timestamp (relative hours)"
    echo "  6) Invalid strategy (error test)"
    echo "  7) Missing timestamp params (error test)"
    echo "  8) Run all tests"
    echo "  q) Quit"
    echo ""
    read -p "Choice [1-8/q]: " choice

    case "$choice" in
        1) test_committed ;;
        2) test_latest ;;
        3) test_earliest ;;
        4) test_timestamp_absolute ;;
        5) test_timestamp_relative ;;
        6) test_invalid_strategy ;;
        7) test_timestamp_missing_params ;;
        8) run_all_tests ;;
        q|Q) echo "Exiting..."; exit 0 ;;
        *) echo "Invalid choice"; exit 1 ;;
    esac
}

# ============================================================================
# Main
# ============================================================================

main() {
    if [[ $# -eq 0 ]]; then
        # No arguments - run all tests
        run_all_tests
    elif [[ "$1" == "--interactive" ]] || [[ "$1" == "-i" ]]; then
        # Interactive mode
        interactive_mode
    else
        # Run specific test
        case "$1" in
            committed) test_committed ;;
            latest) test_latest ;;
            earliest) test_earliest ;;
            timestamp-abs) test_timestamp_absolute ;;
            timestamp-rel) test_timestamp_relative ;;
            error-strategy) test_invalid_strategy ;;
            error-params) test_timestamp_missing_params ;;
            all) run_all_tests ;;
            *)
                echo "Unknown test: $1"
                echo "Usage: $0 [test-name|--interactive]"
                echo "Tests: committed, latest, earliest, timestamp-abs, timestamp-rel, all"
                exit 1
                ;;
        esac
    fi
}

# Run main
main "$@"
