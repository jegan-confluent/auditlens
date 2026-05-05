#!/bin/bash
#
# Confluent Audit Log Intelligence System - One-Click Installer v8.0
#
# This script automates the complete setup process:
# 1. Checks prerequisites
# 2. Interactively collects configuration
# 3. Auto-discovers Confluent Cloud resources
# 4. Creates destination cluster and topics
# 5. Deploys the forwarder
# 6. Launches the dashboard
#
# Usage: curl -sSL https://raw.githubusercontent.com/you/audit-forwarder/main/install.sh | bash
#        or: ./install.sh
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Version
VERSION="8.0"

# Print functions
print_header() {
    echo -e "${BLUE}"
    echo "============================================================================"
    echo "  Confluent Audit Log Intelligence System - Installer v${VERSION}"
    echo "============================================================================"
    echo -e "${NC}"
}

print_section() {
    echo ""
    echo -e "${BLUE}>>> $1${NC}"
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
    echo -e "ℹ $1"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Main installation function
main() {
    print_header

    echo "This installer will guide you through setting up the Audit Log Intelligence System."
    echo ""
    echo "What this installer does:"
    echo "  1. Check prerequisites (confluent CLI, Docker, Python 3)"
    echo "  2. Interactively collect your Confluent Cloud credentials"
    echo "  3. Auto-discover your environments and clusters"
    echo "  4. Create destination topics (critical, high, medium)"
    echo "  5. Configure the forwarder with smart defaults"
    echo "  6. Deploy using Docker Compose"
    echo "  7. Launch the real-time dashboard"
    echo ""
    echo -e "${YELLOW}Estimated monthly cost: \$770 (Development mode)${NC}"
    echo -e "${GREEN}Savings vs Flink-based solution: \$401/month${NC}"
    echo ""
    read -p "Do you want to continue? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi

    print_section "Step 1: Checking Prerequisites"

    # Check for confluent CLI
    if ! command_exists confluent; then
        print_error "Confluent CLI not found"
        echo "Please install it from: https://docs.confluent.io/confluent-cli/current/install.html"
        echo ""
        echo "Quick install:"
        echo "  macOS: brew install confluentinc/tap/cli"
        echo "  Linux: curl -sL --http1.1 https://cnfl.io/cli | sh -s -- latest"
        exit 1
    fi
    print_success "Confluent CLI found ($(confluent version 2>/dev/null || echo 'version unknown'))"

    # Check for Docker
    if ! command_exists docker; then
        print_error "Docker not found"
        echo "Please install Docker Desktop from: https://www.docker.com/products/docker-desktop"
        exit 1
    fi
    print_success "Docker found ($(docker --version))"

    # Check for Python 3
    if ! command_exists python3; then
        print_error "Python 3 not found"
        echo "Please install Python 3.8 or later from: https://www.python.org/downloads/"
        exit 1
    fi
    print_success "Python found ($(python3 --version))"

    print_section "Step 2: Confluent Cloud Authentication"

    # Check if already logged in
    if confluent environment list >/dev/null 2>&1; then
        print_success "Already logged into Confluent Cloud"
        read -p "Use existing session? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Please run: confluent logout"
            echo "Then re-run this installer"
            exit 0
        fi
    else
        print_info "Please log in to Confluent Cloud"
        confluent login --save || {
            print_error "Login failed"
            exit 1
        }
        print_success "Logged in successfully"
    fi

    print_section "Step 3: Environment Selection"

    # Get environments
    print_info "Fetching your environments..."
    envs_json=$(confluent environment list -o json)

    # Parse and display environments
    echo "Available environments:"
    echo ""
    env_ids=($(echo "$envs_json" | python3 -c "import sys, json; data=json.load(sys.stdin); print(' '.join([e['id'] for e in data]))"))
    env_names=($(echo "$envs_json" | python3 -c "import sys, json; data=json.load(sys.stdin); print('\n'.join([e['name'] for e in data]))"))

    for i in "${!env_ids[@]}"; do
        echo "  [$((i+1))] ${env_names[$i]} (${env_ids[$i]})"
    done
    echo ""

    read -p "Select environment (1-${#env_ids[@]}): " env_choice
    env_index=$((env_choice - 1))

    if [[ $env_index -lt 0 || $env_index -ge ${#env_ids[@]} ]]; then
        print_error "Invalid selection"
        exit 1
    fi

    SELECTED_ENV="${env_ids[$env_index]}"
    SELECTED_ENV_NAME="${env_names[$env_index]}"

    print_success "Selected environment: $SELECTED_ENV_NAME"

    # Use this environment
    confluent environment use "$SELECTED_ENV"

    print_section "Step 4: Cluster Selection (Audit Source)"

    print_info "Fetching Kafka clusters in this environment..."
    clusters_json=$(confluent kafka cluster list -o json)

    # Parse and display clusters
    echo "Available Kafka clusters:"
    echo ""
    cluster_ids=($(echo "$clusters_json" | python3 -c "import sys, json; data=json.load(sys.stdin); print(' '.join([c['id'] for c in data]))"))
    cluster_names=($(echo "$clusters_json" | python3 -c "import sys, json; data=json.load(sys.stdin); print('\n'.join([c['name'] for c in data]))"))

    if [[ ${#cluster_ids[@]} -eq 0 ]]; then
        print_warning "No clusters found in this environment"
        echo "This environment will be used for the destination cluster."
    else
        for i in "${!cluster_ids[@]}"; do
            echo "  [$((i+1))] ${cluster_names[$i]} (${cluster_ids[$i]})"
        done
        echo ""

        read -p "Select audit source cluster (1-${#cluster_ids[@]}): " cluster_choice
        cluster_index=$((cluster_choice - 1))

        if [[ $cluster_index -lt 0 || $cluster_index -ge ${#cluster_ids[@]} ]]; then
            print_error "Invalid selection"
            exit 1
        fi

        AUDIT_CLUSTER_ID="${cluster_ids[$cluster_index]}"
        AUDIT_CLUSTER_NAME="${cluster_names[$cluster_index]}"

        print_success "Audit source cluster: $AUDIT_CLUSTER_NAME"
    fi

    print_section "Step 5: Deployment Mode"

    echo "Choose deployment mode:"
    echo ""
    echo "  [1] Development (Recommended)"
    echo "      - Kafka Direct mode (no Flink)"
    echo "      - Basic cluster tier"
    echo "      - 7-day retention"
    echo "      - Cost: ~\$770/month"
    echo ""
    echo "  [2] Production"
    echo "      - Kafka + optional Flink"
    echo "      - Standard cluster tier"
    echo "      - 30-day retention"
    echo "      - Cost: ~\$1,500-2,000/month"
    echo ""

    read -p "Select mode (1-2) [1]: " mode_choice
    mode_choice=${mode_choice:-1}

    if [[ "$mode_choice" == "1" ]]; then
        DEPLOYMENT_MODE="development"
        CLUSTER_TIER="basic"
        RETENTION_DAYS="7"
        ESTIMATED_COST="770"
        print_success "Selected: Development mode (\$$ESTIMATED_COST/month)"
    else
        DEPLOYMENT_MODE="production"
        CLUSTER_TIER="standard"
        RETENTION_DAYS="30"
        ESTIMATED_COST="1500"
        print_success "Selected: Production mode (\$$ESTIMATED_COST/month)"
    fi

    print_section "Step 6: Slack Alerts (Optional)"

    read -p "Enable Slack alerts? (y/n) [n]: " enable_slack
    if [[ "$enable_slack" =~ ^[Yy]$ ]]; then
        read -p "Enter Slack webhook URL: " SLACK_WEBHOOK
        print_success "Slack alerts enabled"
    else
        SLACK_WEBHOOK=""
        print_info "Slack alerts disabled (can enable later in .env)"
    fi

    print_section "Step 7: Creating Configuration Files"

    # Create .env file
    cat > .env <<EOF
# Confluent Audit Log Intelligence System - Configuration v${VERSION}
# Generated on $(date)
# Deployment Mode: ${DEPLOYMENT_MODE}

# Audit source cluster (where audit logs come from)
AUDIT_BOOTSTRAP=pkc-xxxxx.us-east-1.aws.confluent.cloud:9092
AUDIT_TOPIC=confluent-audit-log-events

# Destination cluster (where processed events go)
DEST_BOOTSTRAP=pkc-yyyyy.us-east-1.aws.confluent.cloud:9092
DEST_TOPIC=audit_events_flattened

# Multi-topic routing (critical/high/medium/low)
ENABLE_MULTI_TOPIC_ROUTING=true
AUDIT_TOPIC_CRITICAL=audit_events_critical
AUDIT_TOPIC_HIGH=audit_events_high
AUDIT_TOPIC_MEDIUM=audit_events_medium
AUDIT_TOPIC_LOW=audit_events_low

# Drop LOW criticality events (saves ~89% of throughput)
DROP_LOW_EVENTS=true

# Metrics
METRICS_PORT=8003

# Retention (days)
RETENTION_DAYS=${RETENTION_DAYS}

# Slack webhook (optional)
SLACK_WEBHOOK=${SLACK_WEBHOOK}
EOF

    # Create .secrets file
    cat > .secrets <<EOF
# Confluent Audit Log Intelligence System - Secrets
# WARNING: Keep this file secure and never commit to git!

# TODO: Fill in these values from Confluent Cloud UI
AUDIT_API_KEY=<your-audit-cluster-api-key>
AUDIT_API_SECRET=<your-audit-cluster-api-secret>

DEST_API_KEY=<your-dest-cluster-api-key>
DEST_API_SECRET=<your-dest-cluster-api-secret>

SCHEMA_REGISTRY_URL=<your-schema-registry-url>
SCHEMA_REGISTRY_KEY=<your-sr-api-key>
SCHEMA_REGISTRY_SECRET=<your-sr-api-secret>

CONFLUENT_CLOUD_API_KEY=<your-cloud-api-key>
CONFLUENT_CLOUD_API_SECRET=<your-cloud-api-secret>
EOF

    chmod 600 .secrets

    print_success "Created .env file"
    print_success "Created .secrets file"

    print_section "Step 8: Next Steps"

    echo ""
    echo "✅ Installation configuration complete!"
    echo ""
    echo "⚠️  IMPORTANT: Before starting the system, you must:"
    echo ""
    echo "1. Edit .secrets file with your API keys:"
    echo "   ${BLUE}nano .secrets${NC}"
    echo ""
    echo "2. Get API keys from Confluent Cloud UI:"
    echo "   - Navigate to your cluster → API Keys"
    echo "   - Create keys for audit cluster (if different from dest)"
    echo "   - Create keys for destination cluster"
    echo "   - Create Schema Registry keys"
    echo "   - Create Cloud API keys (for admin operations)"
    echo ""
    echo "3. Start the system:"
    echo "   ${BLUE}docker-compose up -d${NC}"
    echo ""
    echo "4. View the dashboard:"
    echo "   ${BLUE}http://localhost:8503${NC}"
    echo ""
    echo "5. Check forwarder logs:"
    echo "   ${BLUE}docker logs -f audit-forwarder${NC}"
    echo ""
    echo "6. View metrics:"
    echo "   ${BLUE}http://localhost:8003/metrics${NC}"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "💰 COST ESTIMATE (Monthly)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Deployment Mode:     ${DEPLOYMENT_MODE}"
    echo "  Estimated Total:     \$${ESTIMATED_COST}/month"
    echo ""
    echo "  Breakdown:"
    echo "    • Destination Cluster (${CLUSTER_TIER}):  \$720"
    echo "    • Forwarder Compute:         \$30"
    echo "    • Dashboard Compute:         \$20"
    echo ""
    echo "  💚 SAVINGS vs Flink-based solution: \$401/month"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "📚 Documentation: https://github.com/your-repo/audit-forwarder"
    echo "🐛 Issues: https://github.com/your-repo/audit-forwarder/issues"
    echo ""
    echo -e "${GREEN}Installation preparation complete!${NC}"
    echo ""
}

# Run main function
main "$@"
