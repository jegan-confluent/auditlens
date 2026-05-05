#!/bin/bash
#
# AuditLens Distribution Build Script
# Creates a customer-ready distribution package
# Compatible with bash 3.2+ (macOS default)
#
# Usage: ./scripts/build-dist.sh [--version X.Y.Z] [--output-dir DIR]
#

set -e

# ============================================================================
# CONFIGURATION
# ============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/dist"
VERSION=""
OUTPUT_DIR=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Detect color support
if [[ ! -t 1 ]] || [[ -n "${NO_COLOR:-}" ]]; then
    RED='' GREEN='' YELLOW='' CYAN='' BOLD='' DIM='' NC=''
fi

# ============================================================================
# HELPERS
# ============================================================================
print_header() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  AuditLens Distribution Builder${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

print_step() { echo -e "   ${CYAN}▸${NC} $1"; }
print_success() { echo -e "   ${GREEN}✓${NC} $1"; }
print_error() { echo -e "   ${RED}✗${NC} $1"; }
print_warn() { echo -e "   ${YELLOW}!${NC} $1"; }
print_info() { echo -e "   ${DIM}$1${NC}"; }

usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Creates a customer-ready distribution package of AuditLens.

Options:
    --version VERSION    Set version string (default: from VERSION file)
    --output-dir DIR     Output directory (default: ./dist)
    --no-docker          Skip Docker image build
    --help               Show this help message

Examples:
    $(basename "$0")
    $(basename "$0") --version 3.0.1
    $(basename "$0") --output-dir /tmp/release

Output:
    Creates: auditlens-{VERSION}.tar.gz
    Contains:
      - Source code and scripts
      - Docker Compose configuration
      - Documentation
      - Example configuration files
      - Grafana dashboards and Prometheus config
EOF
    exit 0
}

# ============================================================================
# PARSE ARGUMENTS
# ============================================================================
SKIP_DOCKER=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --no-docker)
            SKIP_DOCKER=true
            shift
            ;;
        --help|-h)
            usage
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            ;;
    esac
done

# ============================================================================
# GET VERSION
# ============================================================================
get_version() {
    if [[ -n "$VERSION" ]]; then
        echo "$VERSION"
        return
    fi

    if [[ -f "$PROJECT_DIR/VERSION" ]]; then
        cat "$PROJECT_DIR/VERSION" | tr -d '[:space:]'
    else
        echo "0.0.0-dev"
    fi
}

# ============================================================================
# MAIN BUILD
# ============================================================================
main() {
    print_header

    VERSION=$(get_version)
    OUTPUT_DIR="${OUTPUT_DIR:-$BUILD_DIR}"
    DIST_NAME="auditlens-$VERSION"
    DIST_DIR="$OUTPUT_DIR/$DIST_NAME"
    ARCHIVE_NAME="$DIST_NAME.tar.gz"

    print_step "Building AuditLens v$VERSION"
    echo ""

    # Create output directory
    mkdir -p "$OUTPUT_DIR"

    # Clean previous build
    if [[ -d "$DIST_DIR" ]]; then
        print_step "Cleaning previous build..."
        rm -rf "$DIST_DIR"
    fi

    mkdir -p "$DIST_DIR"

    # ========================================================================
    # COPY FILES
    # ========================================================================
    print_step "Copying source files..."

    # Core Python source
    cp -r "$PROJECT_DIR/src" "$DIST_DIR/"
    cp -r "$PROJECT_DIR/dashboard" "$DIST_DIR/"
    cp "$PROJECT_DIR/audit_forwarder.py" "$DIST_DIR/"
    cp "$PROJECT_DIR/requirements.txt" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/requirements-v2.txt" ]] && cp "$PROJECT_DIR/requirements-v2.txt" "$DIST_DIR/"

    print_success "Source code"

    # Scripts
    mkdir -p "$DIST_DIR/scripts"
    cp "$PROJECT_DIR/scripts/setup-wizard.sh" "$DIST_DIR/scripts/"
    [[ -f "$PROJECT_DIR/scripts/verify.sh" ]] && cp "$PROJECT_DIR/scripts/verify.sh" "$DIST_DIR/scripts/"
    cp "$PROJECT_DIR/setup.sh" "$DIST_DIR/"
    cp "$PROJECT_DIR/status.sh" "$DIST_DIR/"

    # Make scripts executable
    chmod +x "$DIST_DIR/setup.sh"
    chmod +x "$DIST_DIR/status.sh"
    chmod +x "$DIST_DIR/scripts/"*.sh

    print_success "Scripts"

    # Docker files
    cp "$PROJECT_DIR/Dockerfile" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/Dockerfile.alpine" ]] && cp "$PROJECT_DIR/Dockerfile.alpine" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/Dockerfile.distroless" ]] && cp "$PROJECT_DIR/Dockerfile.distroless" "$DIST_DIR/"
    cp "$PROJECT_DIR/docker-compose.yml" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/.dockerignore" ]] && cp "$PROJECT_DIR/.dockerignore" "$DIST_DIR/"

    print_success "Docker configuration"

    # Monitoring configs
    [[ -d "$PROJECT_DIR/grafana" ]] && cp -r "$PROJECT_DIR/grafana" "$DIST_DIR/"
    [[ -d "$PROJECT_DIR/prometheus" ]] && cp -r "$PROJECT_DIR/prometheus" "$DIST_DIR/"
    [[ -d "$PROJECT_DIR/loki" ]] && cp -r "$PROJECT_DIR/loki" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/promtail-config.yml" ]] && cp "$PROJECT_DIR/promtail-config.yml" "$DIST_DIR/"

    print_success "Monitoring stack configs"

    # Config directory
    [[ -d "$PROJECT_DIR/config" ]] && cp -r "$PROJECT_DIR/config" "$DIST_DIR/"
    [[ -d "$PROJECT_DIR/schemas" ]] && cp -r "$PROJECT_DIR/schemas" "$DIST_DIR/"

    print_success "Configuration schemas"

    # Version file
    echo "$VERSION" > "$DIST_DIR/VERSION"

    # ========================================================================
    # EXAMPLE CONFIG FILES
    # ========================================================================
    print_step "Creating example configuration files..."

    # .env.example
    cat > "$DIST_DIR/.env.example" << 'EOF'
# AuditLens Environment Configuration
# Copy this file to .env and customize
# Generated by build-dist.sh

# ============================================================================
# AUDIT SOURCE (Required)
# ============================================================================
# Audit topic containing Confluent audit events
AUDIT_TOPIC=confluent-audit-log-events

# ============================================================================
# DESTINATION TOPICS
# ============================================================================
# Events are routed to these topics based on criticality
AUDIT_TOPIC_CRITICAL=audit_events_critical
AUDIT_TOPIC_HIGH=audit_events_high
AUDIT_TOPIC_MEDIUM=audit_events_medium
AUDIT_TOPIC_LOW=audit_events_low
AUDIT_TOPIC_ALERTS=audit_events_alerts
DLQ_TOPIC=audit_events_dlq

# ============================================================================
# FEATURE FLAGS
# ============================================================================
# Route events to separate topics by criticality
ENABLE_MULTI_TOPIC_ROUTING=true

# Drop LOW criticality events (saves ~89% storage)
DROP_LOW_EVENTS=true

# Aggregate similar denials to reduce alert noise
ENABLE_DENIAL_AGGREGATION=true

# Enable Dead Letter Queue for failed events
ENABLE_DLQ=true

# ============================================================================
# PORTS
# ============================================================================
# Forwarder metrics endpoint
METRICS_PORT=8003

# Streamlit dashboard
DASHBOARD_PORT=8503

# Grafana (optional, set in docker-compose)
GRAFANA_PORT=3000

# Prometheus (optional, set in docker-compose)
PROMETHEUS_PORT=9090

# ============================================================================
# ANOMALY DETECTION
# ============================================================================
# Number of auth failures to trigger anomaly alert
ANOMALY_AUTH_FAILURE_THRESHOLD=10

# Number of deletions to trigger anomaly alert
ANOMALY_DELETION_THRESHOLD=5

# ============================================================================
# DENIAL AGGREGATION
# ============================================================================
# Window size in seconds for aggregating similar denials
DENIAL_AGGREGATOR_WINDOW=60

# Minimum denials to create aggregated alert
DENIAL_AGGREGATOR_THRESHOLD=10
EOF

    print_success ".env.example"

    # .secrets.example
    cat > "$DIST_DIR/.secrets.example" << 'EOF'
# AuditLens Secrets Configuration
# Copy this file to .secrets and add your credentials
# WARNING: Never commit .secrets to version control!
#
# Generated by build-dist.sh

# ============================================================================
# SOURCE CLUSTER - Confluent Cloud Audit Log Cluster (Required)
# ============================================================================
# Find these in: Confluent Cloud > Organization > Audit Log Settings
# The audit log cluster is automatically created by Confluent Cloud

# Bootstrap server (e.g., pkc-xxxxx.region.provider.confluent.cloud:9092)
AUDIT_BOOTSTRAP=

# API Key for audit log cluster
AUDIT_API_KEY=

# API Secret for audit log cluster
AUDIT_API_SECRET=

# ============================================================================
# DESTINATION CLUSTER (Required)
# ============================================================================
# Where classified events will be routed
# Find these in: Confluent Cloud > Your Cluster > API Keys

# Bootstrap server for destination cluster
DEST_BOOTSTRAP=

# API Key for destination cluster
DEST_API_KEY=

# API Secret for destination cluster
DEST_API_SECRET=

# ============================================================================
# CONFLUENT CLOUD API (Optional)
# ============================================================================
# Enables identity enrichment: sa-xxxxx -> Real service account names
# Find these in: Confluent Cloud > Right Menu > Cloud API Keys

# Cloud API Key
CLOUD_API_KEY=

# Cloud API Secret
CLOUD_API_SECRET=

# ============================================================================
# GRAFANA (Required if using monitoring stack)
# ============================================================================
# Admin password for Grafana (minimum 8 characters)
GF_ADMIN_PASSWORD=

# ============================================================================
# ALERTING (Optional)
# ============================================================================
# Slack webhook URL for alerts
# Create at: https://api.slack.com/messaging/webhooks
SLACK_WEBHOOK_URL=
EOF

    print_success ".secrets.example"

    # ========================================================================
    # DOCUMENTATION
    # ========================================================================
    print_step "Including documentation..."

    # Copy main docs
    [[ -f "$PROJECT_DIR/README.md" ]] && cp "$PROJECT_DIR/README.md" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/QUICKSTART.md" ]] && cp "$PROJECT_DIR/QUICKSTART.md" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/GETTING_STARTED.md" ]] && cp "$PROJECT_DIR/GETTING_STARTED.md" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/FEATURES.md" ]] && cp "$PROJECT_DIR/FEATURES.md" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/CHANGELOG.md" ]] && cp "$PROJECT_DIR/CHANGELOG.md" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/DEPLOYMENT.md" ]] && cp "$PROJECT_DIR/DEPLOYMENT.md" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/ARCHITECTURE.md" ]] && cp "$PROJECT_DIR/ARCHITECTURE.md" "$DIST_DIR/"
    [[ -f "$PROJECT_DIR/SLACK_SETUP.md" ]] && cp "$PROJECT_DIR/SLACK_SETUP.md" "$DIST_DIR/"

    # Include docs directory if it exists
    if [[ -d "$PROJECT_DIR/docs" ]]; then
        mkdir -p "$DIST_DIR/docs"
        # Copy specific useful docs, not everything
        [[ -f "$PROJECT_DIR/docs/END_TO_END_FLOW.md" ]] && cp "$PROJECT_DIR/docs/END_TO_END_FLOW.md" "$DIST_DIR/docs/"
        [[ -f "$PROJECT_DIR/docs/DLQ_API.md" ]] && cp "$PROJECT_DIR/docs/DLQ_API.md" "$DIST_DIR/docs/"
    fi

    print_success "Documentation"

    # ========================================================================
    # CREATE GITIGNORE
    # ========================================================================
    cat > "$DIST_DIR/.gitignore" << 'EOF'
# Secrets - NEVER COMMIT
.secrets
*.secret
*.key

# Environment
.env
!.env.example

# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
*.so
.eggs/
*.egg-info/
*.egg
venv/
.venv/
env/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# Logs
*.log
logs/

# Docker
.docker/

# Distribution
dist/
build/

# OS
.DS_Store
Thumbs.db
EOF

    print_success ".gitignore"

    # ========================================================================
    # VERIFY NO SECRETS
    # ========================================================================
    print_step "Verifying no secrets in distribution..."

    local secrets_found=false

    # Check for actual secret files
    if [[ -f "$DIST_DIR/.secrets" ]]; then
        print_error "Found .secrets file in distribution!"
        secrets_found=true
    fi

    # Check for hardcoded credentials - exclude variable references ($VAR) and examples
    # Look for patterns like AUDIT_API_SECRET=abc123xyz (literal values, not $variables)
    local hardcoded_secrets=$(grep -r -E "^[^#]*(AUDIT_API_SECRET|DEST_API_SECRET|CLOUD_API_SECRET|GF_ADMIN_PASSWORD|SLACK_WEBHOOK_URL)=[^$\"][A-Za-z0-9]+" \
        "$DIST_DIR" --include="*.sh" --include="*.py" --include="*.yml" --include=".env" 2>/dev/null \
        | grep -v ".example" \
        | grep -v "YOUR_" \
        | grep -v "your-" \
        | head -3)

    if [[ -n "$hardcoded_secrets" ]]; then
        print_error "Found potential hardcoded secrets!"
        echo "$hardcoded_secrets" | while read -r line; do
            print_warn "  $line"
        done
        secrets_found=true
    fi

    # Check for API keys with literal long values (not variables)
    # This pattern looks for: key='literal_value' or key="literal_value" where value is 20+ chars
    local literal_credentials=$(grep -r -E "(api_key|api_secret|password)\s*[:=]\s*['\"][A-Za-z0-9+/]{20,}['\"]" \
        "$DIST_DIR" --include="*.py" --include="*.sh" 2>/dev/null \
        | grep -v ".example" \
        | grep -v '\$' \
        | head -3)

    if [[ -n "$literal_credentials" ]]; then
        print_warn "Found potential credential patterns (verify manually):"
        echo "$literal_credentials" | while read -r line; do
            print_info "  $line"
        done
    fi

    if [[ "$secrets_found" == "true" ]]; then
        print_error "Build aborted - secrets detected in distribution!"
        rm -rf "$DIST_DIR"
        exit 1
    fi

    print_success "No secrets found"

    # ========================================================================
    # CREATE ARCHIVE
    # ========================================================================
    print_step "Creating archive..."

    cd "$OUTPUT_DIR"
    tar -czf "$ARCHIVE_NAME" "$DIST_NAME"

    local archive_size=$(du -h "$ARCHIVE_NAME" | cut -f1)

    print_success "Created $ARCHIVE_NAME ($archive_size)"

    # ========================================================================
    # SUMMARY
    # ========================================================================
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  Build Complete${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "   ${BOLD}Archive:${NC}    $OUTPUT_DIR/$ARCHIVE_NAME"
    echo -e "   ${BOLD}Size:${NC}       $archive_size"
    echo -e "   ${BOLD}Version:${NC}    $VERSION"
    echo ""
    echo -e "   ${BOLD}Contents:${NC}"
    echo -e "   ${DIM}├── src/              # Python source code"
    echo -e "   ├── dashboard/        # Streamlit dashboard"
    echo -e "   ├── scripts/          # Setup & management scripts"
    echo -e "   ├── grafana/          # Grafana dashboards"
    echo -e "   ├── prometheus/       # Prometheus config"
    echo -e "   ├── docker-compose.yml"
    echo -e "   ├── Dockerfile"
    echo -e "   ├── .env.example"
    echo -e "   ├── .secrets.example"
    echo -e "   └── README.md${NC}"
    echo ""
    echo -e "   ${BOLD}Customer Instructions:${NC}"
    echo -e "   ${DIM}1. Extract: tar -xzf $ARCHIVE_NAME"
    echo -e "   2. Copy: cp .env.example .env && cp .secrets.example .secrets"
    echo -e "   3. Edit: nano .secrets  # Add your credentials"
    echo -e "   4. Run:  ./setup.sh${NC}"
    echo ""

    # Cleanup uncompressed directory
    rm -rf "$DIST_DIR"

    print_success "Build complete!"
}

# Run main
main
