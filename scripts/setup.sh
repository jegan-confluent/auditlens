#!/bin/bash
# =============================================================================
# Confluent AuditLens - Setup Script v2.1
# =============================================================================
# One-command setup for the Audit Log Intelligence System
#
# Usage: ./scripts/setup.sh [--quick|--full|--dev]
#   --quick  Skip rebuilding images (use existing)
#   --full   Full setup with image rebuild (default)
#   --dev    Development mode with live code mounting
# =============================================================================

set -e

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Read version from VERSION file
VERSION=$(cat VERSION 2>/dev/null || echo "2.1.0")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Parse arguments
MODE="full"
for arg in "$@"; do
    case $arg in
        --quick) MODE="quick" ;;
        --full) MODE="full" ;;
        --dev) MODE="dev" ;;
        --help|-h)
            echo "Usage: ./scripts/setup.sh [--quick|--full|--dev]"
            echo "  --quick  Skip rebuilding images"
            echo "  --full   Full setup with rebuild (default)"
            echo "  --dev    Development mode"
            exit 0
            ;;
    esac
done

# Banner
echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                                                                      ║"
echo "║     ██████╗ ██╗   ██╗██████╗ ██╗████████╗██╗     ███████╗███╗   ██╗███████╗  ║"
echo "║    ██╔═══██╗██║   ██║██╔══██╗██║╚══██╔══╝██║     ██╔════╝████╗  ██║██╔════╝  ║"
echo "║    ███████║██║   ██║██║  ██║██║   ██║   ██║     █████╗  ██╔██╗ ██║███████╗  ║"
echo "║    ██╔══██║██║   ██║██║  ██║██║   ██║   ██║     ██╔══╝  ██║╚██╗██║╚════██║  ║"
echo "║    ██║  ██║╚██████╔╝██████╔╝██║   ██║   ███████╗███████╗██║ ╚████║███████║  ║"
echo "║    ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝   ╚═╝   ╚══════╝╚══════╝╚═╝  ╚═══╝╚══════╝  ║"
echo "║                                                                      ║"
echo "║          Confluent Audit Log Intelligence System v${VERSION}            ║"
echo "║                                                                      ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""

# =============================================================================
# Step 1: Check Prerequisites
# =============================================================================
echo -e "${BLUE}━━━ Step 1: Checking Prerequisites ━━━${NC}"
echo ""

ERRORS=0

# Docker
if ! command -v docker &> /dev/null; then
    echo -e "  ${RED}✗${NC} Docker not found"
    echo "    Install: https://docker.com/products/docker-desktop"
    ((ERRORS++))
else
    if docker info &> /dev/null 2>&1; then
        DOCKER_VERSION=$(docker --version | awk '{print $3}' | tr -d ',')
        echo -e "  ${GREEN}✓${NC} Docker ${DOCKER_VERSION}"
    else
        echo -e "  ${RED}✗${NC} Docker is not running"
        echo "    Please start Docker Desktop"
        ((ERRORS++))
    fi
fi

# Docker Compose
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || echo "v2+")
    echo -e "  ${GREEN}✓${NC} Docker Compose ${COMPOSE_VERSION}"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(docker-compose --version | awk '{print $4}' | tr -d ',')
    echo -e "  ${GREEN}✓${NC} Docker Compose ${COMPOSE_VERSION}"
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "  ${RED}✗${NC} Docker Compose not found"
    ((ERRORS++))
fi

# Set compose command
if [ -z "$DOCKER_COMPOSE" ]; then
    if docker compose version &> /dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
    else
        DOCKER_COMPOSE="docker-compose"
    fi
fi

# Python (optional, for local development)
if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 --version | awk '{print $2}')
    echo -e "  ${GREEN}✓${NC} Python ${PY_VERSION}"
else
    echo -e "  ${YELLOW}!${NC} Python 3 not found (optional for local dev)"
fi

if [ $ERRORS -gt 0 ]; then
    echo ""
    echo -e "${RED}Please fix the above errors and try again.${NC}"
    exit 1
fi

echo ""

# =============================================================================
# Step 2: Check Configuration Files
# =============================================================================
echo -e "${BLUE}━━━ Step 2: Checking Configuration ━━━${NC}"
echo ""

# Check .secrets file
if [ ! -f ".secrets" ]; then
    echo -e "  ${YELLOW}!${NC} .secrets file not found"
    echo ""

    if [ -f ".secrets.example" ]; then
        echo -e "  Creating .secrets from template..."
        cp .secrets.example .secrets
        chmod 600 .secrets
        echo -e "  ${GREEN}✓${NC} Created .secrets"
        echo ""
        echo -e "  ${YELLOW}${BOLD}ACTION REQUIRED:${NC}"
        echo "  Edit .secrets with your Confluent Cloud credentials:"
        echo ""
        echo -e "    ${CYAN}nano .secrets${NC}"
        echo ""
        echo "  Required values:"
        echo "    - AUDIT_BOOTSTRAP, AUDIT_API_KEY, AUDIT_API_SECRET"
        echo "    - DEST_BOOTSTRAP, DEST_API_KEY, DEST_API_SECRET"
        echo "    - SCHEMA_REGISTRY_URL, SCHEMA_REGISTRY_KEY, SCHEMA_REGISTRY_SECRET"
        echo "    - GF_ADMIN_PASSWORD (Grafana password)"
        echo ""
        read -p "  Press Enter after editing .secrets to continue..."
    else
        echo -e "  ${RED}✗${NC} .secrets.example not found"
        echo "  Please create .secrets manually"
        exit 1
    fi
fi

# Validate .secrets has real values (not placeholders)
if grep -qE "YOUR_|pkc-xxxxx|psrc-xxxxx" .secrets 2>/dev/null; then
    echo -e "  ${RED}✗${NC} .secrets still contains placeholder values"
    echo ""
    echo "  Please edit .secrets with your actual credentials:"
    echo -e "    ${CYAN}nano .secrets${NC}"
    echo ""
    exit 1
fi

echo -e "  ${GREEN}✓${NC} .secrets configured"

# Check .env file
if [ ! -f ".env" ]; then
    echo -e "  ${YELLOW}!${NC} .env not found, creating defaults..."
    cat > .env << 'ENVEOF'
# Confluent AuditLens Configuration v2.1
# Non-sensitive configuration (safe to commit)

# Multi-topic routing (recommended)
ENABLE_MULTI_TOPIC_ROUTING=true
AUDIT_TOPIC_CRITICAL=audit_events_critical
AUDIT_TOPIC_HIGH=audit_events_high
AUDIT_TOPIC_MEDIUM=audit_events_medium
AUDIT_TOPIC_LOW=audit_events_low

# Drop LOW criticality events (saves ~89% of throughput)
DROP_LOW_EVENTS=true

# Source topic (usually don't change)
AUDIT_TOPIC=confluent-audit-log-events

# Consumer group
GROUP_ID=audit-forwarder-v2

# Metrics
METRICS_PORT=8003

# Dry run mode (true = don't actually produce, just log)
AUDIT_ROUTER_DRY_RUN=false

# Grafana admin user
GF_ADMIN_USER=admin
ENVEOF
    echo -e "  ${GREEN}✓${NC} Created .env with defaults"
else
    echo -e "  ${GREEN}✓${NC} .env exists"
fi

# Create required directories
mkdir -p data logs
echo -e "  ${GREEN}✓${NC} Directories ready (data/, logs/)"

echo ""

# =============================================================================
# Step 3: Build/Pull Images
# =============================================================================
echo -e "${BLUE}━━━ Step 3: Preparing Docker Images ━━━${NC}"
echo ""

if [ "$MODE" = "quick" ]; then
    echo -e "  ${YELLOW}!${NC} Quick mode - skipping rebuild"
    echo "    Using existing images (if available)"
else
    echo "  Building images (this may take a few minutes)..."
    echo ""

    # Build forwarder
    echo -e "  ${CYAN}Building audit-forwarder:${VERSION}...${NC}"
    $DOCKER_COMPOSE build --quiet audit-forwarder 2>/dev/null || \
        docker build -t audit-forwarder:${VERSION} . -q
    echo -e "  ${GREEN}✓${NC} audit-forwarder:${VERSION}"

    # Build dashboard
    echo -e "  ${CYAN}Building audit-dashboard...${NC}"
    $DOCKER_COMPOSE build --quiet dashboard 2>/dev/null || \
        docker build -t audit-dashboard:${VERSION} dashboard/ -q
    echo -e "  ${GREEN}✓${NC} audit-dashboard"
fi

echo ""

# =============================================================================
# Step 4: Start Services
# =============================================================================
echo -e "${BLUE}━━━ Step 4: Starting Services ━━━${NC}"
echo ""

# Stop existing containers
echo "  Stopping any existing containers..."
$DOCKER_COMPOSE down --remove-orphans 2>/dev/null || true

# Start services
echo "  Starting all services..."
if [ "$MODE" = "dev" ]; then
    echo -e "  ${YELLOW}Development mode:${NC} Code changes reflect immediately"
    $DOCKER_COMPOSE up -d
else
    $DOCKER_COMPOSE up -d
fi

echo -e "  ${GREEN}✓${NC} Services started"
echo ""

# =============================================================================
# Step 5: Wait for Services to be Ready
# =============================================================================
echo -e "${BLUE}━━━ Step 5: Waiting for Services ━━━${NC}"
echo ""

wait_for_service() {
    local name=$1
    local url=$2
    local max_wait=${3:-60}
    local counter=0

    printf "  Waiting for %-20s " "$name..."

    while [ $counter -lt $max_wait ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" --max-time 2 2>/dev/null | grep -qE "200|301|302|401"; then
            echo -e "${GREEN}ready${NC}"
            return 0
        fi
        printf "."
        sleep 2
        counter=$((counter + 2))
    done

    echo -e "${YELLOW}timeout${NC}"
    return 1
}

# Wait for each service
wait_for_service "Forwarder" "http://localhost:8003/health" 60
wait_for_service "Dashboard" "http://localhost:8503" 60
wait_for_service "Prometheus" "http://localhost:9090/-/ready" 30
wait_for_service "Grafana" "http://localhost:3000/api/health" 30

echo ""

# =============================================================================
# Step 6: Verify Health
# =============================================================================
echo -e "${BLUE}━━━ Step 6: Health Check ━━━${NC}"
echo ""

$SCRIPT_DIR/verify.sh 2>/dev/null || {
    echo -e "  ${YELLOW}!${NC} Some services may still be initializing"
    echo "    Run './scripts/verify.sh' to check status"
}

echo ""

# =============================================================================
# Success!
# =============================================================================
echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                     Setup Complete!                                  ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
echo -e "${BOLD}Access Your Services:${NC}"
echo ""
echo -e "  ${CYAN}AuditLens Dashboard${NC}    http://localhost:8503"
echo -e "  ${CYAN}Grafana${NC}                http://localhost:3000"
echo -e "  ${CYAN}Prometheus${NC}             http://localhost:9090"
echo -e "  ${CYAN}Forwarder Metrics${NC}      http://localhost:8003/metrics"
echo ""
echo -e "${BOLD}Helpful Commands:${NC}"
echo ""
echo -e "  ${YELLOW}View forwarder logs:${NC}    docker logs -f audit-forwarder"
echo -e "  ${YELLOW}View dashboard logs:${NC}    docker logs -f dashboard"
echo -e "  ${YELLOW}Check service health:${NC}   ./scripts/verify.sh"
echo -e "  ${YELLOW}Stop all services:${NC}      ./scripts/stop.sh"
echo -e "  ${YELLOW}Restart services:${NC}       docker compose restart"
echo ""
echo -e "${BOLD}Documentation:${NC}"
echo ""
echo -e "  ${CYAN}Getting Started:${NC}        cat GETTING_STARTED.md"
echo -e "  ${CYAN}Full Documentation:${NC}     cat docs/README.md"
echo ""

# Open dashboard in browser (macOS)
if command -v open &> /dev/null; then
    echo "Opening dashboard in browser..."
    sleep 2
    open http://localhost:8503 2>/dev/null || true
fi

echo -e "${GREEN}Happy auditing!${NC}"
echo ""
