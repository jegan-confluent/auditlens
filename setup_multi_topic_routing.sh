#!/bin/bash
# ============================================================================
# Multi-Topic Routing Setup Script
# ============================================================================
# This script helps you enable and manage multi-topic routing for the
# Confluent Audit Log Intelligence System.
#
# WHAT IT DOES:
#   1. Creates 4 destination topics (critical, high, medium, low)
#   2. Optionally creates an "all events" topic
#   3. Updates .env configuration
#   4. Validates the setup
#   5. Provides instructions for starting the forwarder
#
# WHEN TO USE:
#   - Need tiered retention policies (keep CRITICAL for 1 year, LOW for 7 days)
#   - Want separate alerting streams (alert only on CRITICAL topic)
#   - Need to reduce volume (drop LOW events to save ~89% throughput)
#
# PREREQUISITES:
#   - Confluent CLI installed and authenticated
#   - Environment ID and Cluster ID in .env file
#   - API keys with topic creation permissions
# ============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Functions
# ============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}============================================================================${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}============================================================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Load environment variables
load_env() {
    if [ -f .env ]; then
        export $(grep -v '^#' .env | xargs)
        print_success "Loaded .env file"
    else
        print_error ".env file not found!"
        exit 1
    fi
}

# Check prerequisites
check_prerequisites() {
    print_header "Checking Prerequisites"

    # Check Confluent CLI
    if ! command -v confluent &> /dev/null; then
        print_error "Confluent CLI not found. Please install: https://docs.confluent.io/confluent-cli/current/install.html"
        exit 1
    fi
    print_success "Confluent CLI found"

    # Check authentication
    if ! confluent environment list &> /dev/null; then
        print_error "Not authenticated with Confluent Cloud. Run: confluent login"
        exit 1
    fi
    print_success "Authenticated with Confluent Cloud"

    # Check required env vars
    required_vars=("DEST_ENV_ID" "DEST_CLUSTER_ID" "DEST_BOOTSTRAP")
    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            print_error "Missing required environment variable: $var"
            exit 1
        fi
    done
    print_success "All required environment variables present"
}

# Get topic configuration from user
get_topic_config() {
    print_header "Topic Configuration"

    # Default topic names
    DEFAULT_CRITICAL="audit_events_critical"
    DEFAULT_HIGH="audit_events_high"
    DEFAULT_MEDIUM="audit_events_medium"
    DEFAULT_LOW="audit_events_low"
    DEFAULT_ALL="audit_events_all"

    echo "Enter topic names (press Enter to use defaults):"
    echo ""

    read -p "Critical topic [$DEFAULT_CRITICAL]: " TOPIC_CRITICAL
    TOPIC_CRITICAL=${TOPIC_CRITICAL:-$DEFAULT_CRITICAL}

    read -p "High topic [$DEFAULT_HIGH]: " TOPIC_HIGH
    TOPIC_HIGH=${TOPIC_HIGH:-$DEFAULT_HIGH}

    read -p "Medium topic [$DEFAULT_MEDIUM]: " TOPIC_MEDIUM
    TOPIC_MEDIUM=${TOPIC_MEDIUM:-$DEFAULT_MEDIUM}

    read -p "Low topic [$DEFAULT_LOW]: " TOPIC_LOW
    TOPIC_LOW=${TOPIC_LOW:-$DEFAULT_LOW}

    echo ""
    read -p "Create 'all events' topic? (y/n) [n]: " CREATE_ALL
    if [[ "$CREATE_ALL" =~ ^[Yy]$ ]]; then
        read -p "All events topic [$DEFAULT_ALL]: " TOPIC_ALL
        TOPIC_ALL=${TOPIC_ALL:-$DEFAULT_ALL}
        ENABLE_ALL="true"
    else
        TOPIC_ALL=""
        ENABLE_ALL="false"
    fi

    echo ""
    read -p "Drop LOW criticality events? (saves ~89% volume) (y/n) [n]: " DROP_LOW_INPUT
    if [[ "$DROP_LOW_INPUT" =~ ^[Yy]$ ]]; then
        DROP_LOW="true"
        print_warning "LOW events will be DROPPED (not produced)"
    else
        DROP_LOW="false"
    fi

    # Summary
    echo ""
    print_info "Configuration Summary:"
    echo "  CRITICAL topic: $TOPIC_CRITICAL"
    echo "  HIGH topic:     $TOPIC_HIGH"
    echo "  MEDIUM topic:   $TOPIC_MEDIUM"
    echo "  LOW topic:      $TOPIC_LOW"
    if [ -n "$TOPIC_ALL" ]; then
        echo "  ALL topic:      $TOPIC_ALL"
    fi
    echo "  Drop LOW:       $DROP_LOW"
    echo ""

    read -p "Proceed with this configuration? (y/n): " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        print_error "Aborted by user"
        exit 0
    fi
}

# Create topics
create_topics() {
    print_header "Creating Topics"

    # Use destination cluster
    confluent environment use $DEST_ENV_ID
    confluent kafka cluster use $DEST_CLUSTER_ID

    # Topic defaults
    PARTITIONS=6
    RETENTION_CRITICAL=$((365 * 24 * 60 * 60 * 1000))  # 1 year in ms
    RETENTION_HIGH=$((90 * 24 * 60 * 60 * 1000))       # 90 days in ms
    RETENTION_MEDIUM=$((30 * 24 * 60 * 60 * 1000))     # 30 days in ms
    RETENTION_LOW=$((7 * 24 * 60 * 60 * 1000))         # 7 days in ms

    # Create CRITICAL topic
    print_info "Creating $TOPIC_CRITICAL (retention: 365 days)..."
    if confluent kafka topic create $TOPIC_CRITICAL \
        --partitions $PARTITIONS \
        --config retention.ms=$RETENTION_CRITICAL \
        --config cleanup.policy=delete 2>/dev/null; then
        print_success "Created $TOPIC_CRITICAL"
    else
        print_warning "$TOPIC_CRITICAL already exists or creation failed"
    fi

    # Create HIGH topic
    print_info "Creating $TOPIC_HIGH (retention: 90 days)..."
    if confluent kafka topic create $TOPIC_HIGH \
        --partitions $PARTITIONS \
        --config retention.ms=$RETENTION_HIGH \
        --config cleanup.policy=delete 2>/dev/null; then
        print_success "Created $TOPIC_HIGH"
    else
        print_warning "$TOPIC_HIGH already exists or creation failed"
    fi

    # Create MEDIUM topic
    print_info "Creating $TOPIC_MEDIUM (retention: 30 days)..."
    if confluent kafka topic create $TOPIC_MEDIUM \
        --partitions $PARTITIONS \
        --config retention.ms=$RETENTION_MEDIUM \
        --config cleanup.policy=delete 2>/dev/null; then
        print_success "Created $TOPIC_MEDIUM"
    else
        print_warning "$TOPIC_MEDIUM already exists or creation failed"
    fi

    # Create LOW topic (unless dropping)
    if [ "$DROP_LOW" = "false" ]; then
        print_info "Creating $TOPIC_LOW (retention: 7 days)..."
        if confluent kafka topic create $TOPIC_LOW \
            --partitions $PARTITIONS \
            --config retention.ms=$RETENTION_LOW \
            --config cleanup.policy=delete 2>/dev/null; then
            print_success "Created $TOPIC_LOW"
        else
            print_warning "$TOPIC_LOW already exists or creation failed"
        fi
    else
        print_info "Skipping $TOPIC_LOW creation (DROP_LOW_EVENTS=true)"
    fi

    # Create ALL topic if requested
    if [ -n "$TOPIC_ALL" ]; then
        print_info "Creating $TOPIC_ALL (retention: 30 days)..."
        if confluent kafka topic create $TOPIC_ALL \
            --partitions $PARTITIONS \
            --config retention.ms=$RETENTION_MEDIUM \
            --config cleanup.policy=delete 2>/dev/null; then
            print_success "Created $TOPIC_ALL"
        else
            print_warning "$TOPIC_ALL already exists or creation failed"
        fi
    fi
}

# Update .env file
update_env() {
    print_header "Updating Configuration"

    # Backup .env
    cp .env .env.backup
    print_success "Backed up .env to .env.backup"

    # Remove old routing config if exists
    sed -i.tmp '/^ENABLE_MULTI_TOPIC_ROUTING=/d' .env
    sed -i.tmp '/^AUDIT_TOPIC_CRITICAL=/d' .env
    sed -i.tmp '/^AUDIT_TOPIC_HIGH=/d' .env
    sed -i.tmp '/^AUDIT_TOPIC_MEDIUM=/d' .env
    sed -i.tmp '/^AUDIT_TOPIC_LOW=/d' .env
    sed -i.tmp '/^AUDIT_TOPIC_ALL=/d' .env
    sed -i.tmp '/^AUDIT_ENABLE_ALL_EVENTS=/d' .env
    sed -i.tmp '/^DROP_LOW_EVENTS=/d' .env
    sed -i.tmp '/^AUDIT_ROUTER_DRY_RUN=/d' .env
    rm -f .env.tmp

    # Add new routing config
    cat >> .env << EOF

# Multi-Topic Routing Configuration (added by setup_multi_topic_routing.sh)
ENABLE_MULTI_TOPIC_ROUTING=true
AUDIT_TOPIC_CRITICAL=$TOPIC_CRITICAL
AUDIT_TOPIC_HIGH=$TOPIC_HIGH
AUDIT_TOPIC_MEDIUM=$TOPIC_MEDIUM
AUDIT_TOPIC_LOW=$TOPIC_LOW
EOF

    if [ -n "$TOPIC_ALL" ]; then
        echo "AUDIT_TOPIC_ALL=$TOPIC_ALL" >> .env
        echo "AUDIT_ENABLE_ALL_EVENTS=$ENABLE_ALL" >> .env
    fi

    echo "DROP_LOW_EVENTS=$DROP_LOW" >> .env
    echo "AUDIT_ROUTER_DRY_RUN=false" >> .env

    print_success "Updated .env file with multi-topic routing configuration"
}

# Validate setup
validate_setup() {
    print_header "Validating Setup"

    # Check topics exist
    print_info "Checking topics exist..."
    TOPICS_TO_CHECK=($TOPIC_CRITICAL $TOPIC_HIGH $TOPIC_MEDIUM)
    if [ "$DROP_LOW" = "false" ]; then
        TOPICS_TO_CHECK+=($TOPIC_LOW)
    fi
    if [ -n "$TOPIC_ALL" ]; then
        TOPICS_TO_CHECK+=($TOPIC_ALL)
    fi

    for topic in "${TOPICS_TO_CHECK[@]}"; do
        if confluent kafka topic describe $topic &> /dev/null; then
            print_success "Topic exists: $topic"
        else
            print_error "Topic not found: $topic"
        fi
    done

    # Check .env configuration
    print_info "Checking .env configuration..."
    if grep -q "ENABLE_MULTI_TOPIC_ROUTING=true" .env; then
        print_success "Multi-topic routing enabled in .env"
    else
        print_error "ENABLE_MULTI_TOPIC_ROUTING not set correctly in .env"
    fi
}

# Print next steps
print_next_steps() {
    print_header "Next Steps"

    echo "Multi-topic routing is now configured! Here's what to do next:"
    echo ""
    echo "1. ${YELLOW}Test in dry-run mode first:${NC}"
    echo "   AUDIT_ROUTER_DRY_RUN=true python3 audit_forwarder.py"
    echo ""
    echo "2. ${YELLOW}Check the logs for routing decisions:${NC}"
    echo "   Look for: \"[DRY RUN] Would route to: audit_events_critical\""
    echo ""
    echo "3. ${YELLOW}Start the forwarder in production mode:${NC}"
    echo "   python3 audit_forwarder.py"
    echo ""
    echo "4. ${YELLOW}Monitor the routing stats:${NC}"
    echo "   curl http://localhost:8003/metrics | grep routing"
    echo ""
    echo "5. ${YELLOW}View events by criticality:${NC}"
    echo "   confluent kafka topic consume $TOPIC_CRITICAL"
    echo "   confluent kafka topic consume $TOPIC_HIGH"
    echo ""

    if [ "$DROP_LOW" = "true" ]; then
        print_warning "Remember: LOW events are being DROPPED (not produced)"
        echo "   This saves ~89% of volume but you won't have LOW events for analysis"
        echo ""
    fi

    echo "${GREEN}Topic Retention Policies:${NC}"
    echo "  • CRITICAL: 365 days (important security events)"
    echo "  • HIGH:     90 days (significant operations)"
    echo "  • MEDIUM:   30 days (routine changes)"
    if [ "$DROP_LOW" = "false" ]; then
        echo "  • LOW:      7 days (high-volume routine events)"
    fi
    echo ""

    echo "${BLUE}To disable multi-topic routing later:${NC}"
    echo "  1. Set ENABLE_MULTI_TOPIC_ROUTING=false in .env"
    echo "  2. Restart the forwarder"
    echo "  3. All events will go to DEST_TOPIC instead"
    echo ""
}

# ============================================================================
# Main Script
# ============================================================================

main() {
    clear
    print_header "Multi-Topic Routing Setup for Audit Log Intelligence System"

    echo "This script will:"
    echo "  1. Create 4 destination topics (critical, high, medium, low)"
    echo "  2. Configure tiered retention policies"
    echo "  3. Update .env with routing configuration"
    echo "  4. Validate the setup"
    echo ""

    read -p "Continue? (y/n): " START
    if [[ ! "$START" =~ ^[Yy]$ ]]; then
        print_error "Aborted by user"
        exit 0
    fi

    load_env
    check_prerequisites
    get_topic_config
    create_topics
    update_env
    validate_setup
    print_next_steps

    print_success "Setup complete!"
}

# Run main function
main
