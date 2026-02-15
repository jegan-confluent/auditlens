#!/bin/bash
# =============================================================================
# Confluent AuditLens - Stop Services
# =============================================================================
# Usage: ./scripts/stop.sh [--all|--keep-data]
#   --all        Stop and remove all containers, networks, and volumes
#   --keep-data  Stop containers but preserve data volumes (default)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Parse arguments
REMOVE_VOLUMES=false
for arg in "$@"; do
    case $arg in
        --all) REMOVE_VOLUMES=true ;;
        --keep-data) REMOVE_VOLUMES=false ;;
    esac
done

echo ""
echo "Stopping Confluent AuditLens services..."
echo ""

# Detect docker compose command
if docker compose version &> /dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

if [ "$REMOVE_VOLUMES" = true ]; then
    echo -e "${YELLOW}Removing all containers, networks, and volumes...${NC}"
    $DOCKER_COMPOSE down -v --remove-orphans 2>/dev/null || true
    echo -e "${GREEN}✓${NC} All resources removed"
else
    echo "Stopping containers (preserving data)..."
    $DOCKER_COMPOSE down --remove-orphans 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Containers stopped"
fi

# Also stop any manually started containers
MANUAL_CONTAINERS="audit-forwarder dashboard audit-grafana audit-prometheus loki promtail"
for container in $MANUAL_CONTAINERS; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
        docker rm -f "$container" 2>/dev/null || true
    fi
done

echo ""
echo -e "${GREEN}All services stopped.${NC}"
echo ""
echo "To restart: ./scripts/setup.sh --quick"
echo ""
