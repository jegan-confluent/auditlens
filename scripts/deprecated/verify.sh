#!/bin/bash
# =============================================================================
# Confluent AuditLens - Health Verification Script
# =============================================================================
# Checks the health of all AuditLens services
# Usage: ./scripts/verify.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Read version
VERSION=$(cat VERSION 2>/dev/null || echo "2.1.0")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       Confluent AuditLens v${VERSION} - Health Check           ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

ERRORS=0
WARNINGS=0

# =============================================================================
# Container Status
# =============================================================================
echo -e "${BLUE}━━━ Container Status ━━━${NC}"
echo ""

check_container() {
    local name=$1
    local port=$2
    local health_url=$3

    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${name}$"; then
        local status=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null)
        local health=$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null || echo "none")

        if [ "$status" = "running" ]; then
            if [ "$health" = "healthy" ]; then
                echo -e "  ${GREEN}✓${NC} $name: running (healthy)"
            elif [ "$health" = "unhealthy" ]; then
                echo -e "  ${YELLOW}!${NC} $name: running (unhealthy)"
                ((WARNINGS++))
            else
                echo -e "  ${GREEN}✓${NC} $name: running"
            fi

            # Check HTTP endpoint
            if [ -n "$health_url" ]; then
                local http_code=$(curl -s -o /dev/null -w "%{http_code}" "$health_url" --max-time 5 2>/dev/null)
                if echo "$http_code" | grep -qE "200|301|302"; then
                    echo -e "      └─ HTTP: ${GREEN}OK${NC} ($http_code)"
                elif [ "$http_code" = "401" ]; then
                    echo -e "      └─ HTTP: ${GREEN}OK${NC} (auth required)"
                else
                    echo -e "      └─ HTTP: ${YELLOW}$http_code${NC}"
                fi
            fi
            return 0
        else
            echo -e "  ${RED}✗${NC} $name: $status"
            ((ERRORS++))
            return 1
        fi
    else
        echo -e "  ${RED}✗${NC} $name: not found"
        ((ERRORS++))
        return 1
    fi
}

check_container "auditlens-forwarder" "8003" "http://localhost:8003/health"
check_container "dashboard" "8503" "http://localhost:8503"
check_container "audit-prometheus" "9090" "http://localhost:9090/-/ready"
check_container "audit-grafana" "3000" "http://localhost:3000/api/health"
check_container "loki" "3100" "http://localhost:3100/ready"
check_container "promtail" "" ""

echo ""

# =============================================================================
# Network Status
# =============================================================================
echo -e "${BLUE}━━━ Network Status ━━━${NC}"
echo ""

for network in kafka-network monitoring frontend-network; do
    if docker network inspect "$network" &>/dev/null 2>&1; then
        containers=$(docker network inspect "$network" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | tr -s ' ')
        count=$(echo "$containers" | wc -w | tr -d ' ')
        echo -e "  ${GREEN}✓${NC} $network: $count container(s)"
    elif docker network inspect "audit-forwarder_${network}" &>/dev/null 2>&1; then
        containers=$(docker network inspect "audit-forwarder_${network}" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | tr -s ' ')
        count=$(echo "$containers" | wc -w | tr -d ' ')
        echo -e "  ${GREEN}✓${NC} $network: $count container(s)"
    else
        echo -e "  ${YELLOW}!${NC} $network: not found"
    fi
done

echo ""

# =============================================================================
# Forwarder Metrics
# =============================================================================
echo -e "${BLUE}━━━ Forwarder Metrics ━━━${NC}"
echo ""

METRICS=$(curl -s http://localhost:8003/metrics 2>/dev/null)

if [ -n "$METRICS" ] && echo "$METRICS" | grep -q "audit"; then
    # Extract key metrics
    UPTIME=$(echo "$METRICS" | grep "audit_forwarder_uptime_seconds" | grep -v "^#" | awk '{printf "%.0f", $2}' | head -1)
    CONSUMED=$(echo "$METRICS" | grep "audit_messages_consumed_total" | grep -v "^#" | awk '{printf "%.0f", $2}' | head -1)
    PRODUCED=$(echo "$METRICS" | grep "audit_messages_produced_total" | grep -v "^#" | awk '{printf "%.0f", $2}' | head -1)
    ERRORS_COUNT=$(echo "$METRICS" | grep "audit_processing_errors_total" | grep -v "^#" | awk '{printf "%.0f", $2}' | head -1)

    # Format uptime
    if [ -n "$UPTIME" ] && [ "$UPTIME" -gt 0 ]; then
        HOURS=$((UPTIME / 3600))
        MINS=$(((UPTIME % 3600) / 60))
        echo -e "  Uptime:           ${GREEN}${HOURS}h ${MINS}m${NC}"
    fi

    echo -e "  Messages consumed: ${CONSUMED:-0}"
    echo -e "  Messages produced: ${PRODUCED:-0}"

    if [ -n "$ERRORS_COUNT" ] && [ "$ERRORS_COUNT" -gt 0 ]; then
        echo -e "  Processing errors: ${RED}${ERRORS_COUNT}${NC}"
    else
        echo -e "  Processing errors: ${GREEN}0${NC}"
    fi

    # Per-criticality breakdown
    CRITICAL=$(echo "$METRICS" | grep "audit_messages_routed_total.*criticality=\"critical\"" | awk '{printf "%.0f", $2}' | head -1)
    HIGH=$(echo "$METRICS" | grep "audit_messages_routed_total.*criticality=\"high\"" | awk '{printf "%.0f", $2}' | head -1)
    MEDIUM=$(echo "$METRICS" | grep "audit_messages_routed_total.*criticality=\"medium\"" | awk '{printf "%.0f", $2}' | head -1)

    if [ -n "$CRITICAL" ] || [ -n "$HIGH" ] || [ -n "$MEDIUM" ]; then
        echo ""
        echo "  By criticality:"
        echo -e "    CRITICAL: ${CRITICAL:-0}"
        echo -e "    HIGH:     ${HIGH:-0}"
        echo -e "    MEDIUM:   ${MEDIUM:-0}"
    fi
else
    echo -e "  ${YELLOW}!${NC} Metrics not available (forwarder may be starting)"
fi

echo ""

# =============================================================================
# Recent Logs
# =============================================================================
echo -e "${BLUE}━━━ Recent Activity ━━━${NC}"
echo ""

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^auditlens-forwarder$"; then
    RECENT=$(docker logs auditlens-forwarder --tail 5 2>&1 | tail -3)
    if [ -n "$RECENT" ]; then
        echo "  Last log entries:"
        echo "$RECENT" | while read -r line; do
            echo "    $line"
        done
    fi
else
    echo -e "  ${YELLOW}!${NC} Forwarder not running"
fi

echo ""

# =============================================================================
# Summary
# =============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All checks passed!${NC}"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}${BOLD}$WARNINGS warning(s), no errors${NC}"
else
    echo -e "${RED}${BOLD}$ERRORS error(s), $WARNINGS warning(s)${NC}"
fi

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BOLD}Quick Links:${NC}"
echo "  Dashboard:  http://localhost:8503"
echo "  Grafana:    http://localhost:3000"
echo "  Prometheus: http://localhost:9090"
echo "  Metrics:    http://localhost:8003/metrics"
echo ""

exit $ERRORS
