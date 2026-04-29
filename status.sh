#!/bin/bash
# ============================================================================
# AuditLens - Interactive Status Menu
# ============================================================================
# Interactive menu to check status, view logs, system health
# Usage: ./status.sh
# ============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

# Load config
[ -f ".env" ] && source .env
[ -f ".secrets" ] && source .secrets

# Ports (with defaults)
DASHBOARD_PORT="${DASHBOARD_PORT:-8503}"
METRICS_PORT="${METRICS_PORT:-8003}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"

# Format large numbers
format_number() {
    local num=$1
    if [ -z "$num" ] || [ "$num" = "null" ]; then echo "0"; return; fi
    # Remove decimal part if present
    num=${num%.*}
    if [ "$num" -ge 1000000 ] 2>/dev/null; then
        printf "%.2fM" $(echo "$num / 1000000" | bc -l 2>/dev/null || echo "0")
    elif [ "$num" -ge 1000 ] 2>/dev/null; then
        printf "%.1fK" $(echo "$num / 1000" | bc -l 2>/dev/null || echo "0")
    else
        echo "$num"
    fi
}

# Show header
show_header() {
    clear
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║${NC}               ${BOLD}AuditLens - System Status${NC}                         ${CYAN}${BOLD}║${NC}"
    echo -e "${CYAN}${BOLD}║${NC}        Confluent Audit Log Intelligence System                   ${CYAN}${BOLD}║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "   ${GRAY}Checked: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo ""
}

# Show service status
show_services() {
    echo -e "${BOLD}SERVICES${NC}"
    echo ""

    # Forwarder
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "audit-forwarder"; then
        local status=$(docker ps --format "{{.Status}}" --filter "name=audit-forwarder" 2>/dev/null)
        local uptime=$(echo "$status" | grep -oE "Up [^(]+" | head -1)
        echo -e "   ${GREEN}●${NC}  Forwarder .......... ${GREEN}Running${NC} ($uptime)"

        # Memory usage
        local mem=$(docker stats --no-stream --format "{{.MemUsage}}" audit-forwarder 2>/dev/null | head -1)
        if [ -n "$mem" ]; then
            echo -e "       └─ Memory: $mem"
        fi
    else
        echo -e "   ${RED}●${NC}  Forwarder .......... ${RED}Stopped${NC}"
    fi

    # Dashboard
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "audit-dashboard"; then
        local status=$(docker ps --format "{{.Status}}" --filter "name=audit-dashboard" 2>/dev/null)
        echo -e "   ${GREEN}●${NC}  Dashboard .......... ${GREEN}Running${NC} (port $DASHBOARD_PORT)"
    else
        echo -e "   ${RED}●${NC}  Dashboard .......... ${RED}Stopped${NC}"
    fi

    # Grafana
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "grafana"; then
        echo -e "   ${GREEN}●${NC}  Grafana ............ ${GREEN}Running${NC} (port $GRAFANA_PORT)"
    else
        echo -e "   ${GRAY}○${NC}  Grafana ............ ${GRAY}Not running${NC}"
    fi

    # Prometheus
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "prometheus"; then
        echo -e "   ${GREEN}●${NC}  Prometheus ......... ${GREEN}Running${NC} (port $PROMETHEUS_PORT)"
    else
        echo -e "   ${GRAY}○${NC}  Prometheus ......... ${GRAY}Not running${NC}"
    fi

    # Loki
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "loki"; then
        echo -e "   ${GREEN}●${NC}  Loki ............... ${GREEN}Running${NC}"
    else
        echo -e "   ${GRAY}○${NC}  Loki ............... ${GRAY}Not running${NC}"
    fi

    echo ""
}

# Show health and metrics
show_metrics() {
    echo -e "${BOLD}FORWARDER METRICS${NC}"
    echo ""

    local health=$(curl -s "localhost:$METRICS_PORT/health" 2>/dev/null)
    if [ -n "$health" ]; then
        local status=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null)
        if [ "$status" = "healthy" ]; then
            echo -e "   ${GREEN}●${NC}  Health ............. ${GREEN}$status${NC}"
        else
            echo -e "   ${YELLOW}●${NC}  Health ............. ${YELLOW}$status${NC}"
        fi
    else
        echo -e "   ${RED}●${NC}  Health ............. ${RED}Unavailable${NC}"
        echo ""
        return
    fi

    local metrics=$(curl -s "localhost:$METRICS_PORT/metrics" 2>/dev/null)
    if [ -n "$metrics" ]; then
        local processed=$(echo "$metrics" | grep "audit_forwarder_processed_messages_total" | grep -v "^#" | awk '{print $2}' | head -1)
        local rate=$(echo "$metrics" | grep "audit_forwarder_processing_rate_per_second" | grep -v "^#" | awk '{printf "%.1f", $2}' | head -1)
        local errors=$(echo "$metrics" | grep "audit_forwarder_error_count_total" | grep -v "^#" | awk '{print $2}' | head -1)
        local lag=$(echo "$metrics" | grep "audit_forwarder_consumer_lag_total" | grep -v "^#" | awk '{printf "%.0f", $2}' | head -1)
        local uptime_sec=$(echo "$metrics" | grep "audit_forwarder_uptime_seconds" | grep -v "^#" | awk '{printf "%.0f", $2}' | head -1)

        local processed_fmt=$(format_number "${processed:-0}")
        local lag_fmt=$(format_number "${lag:-0}")

        if [ -n "$uptime_sec" ] && [ "$uptime_sec" != "0" ]; then
            local hours=$((uptime_sec / 3600))
            local mins=$(((uptime_sec % 3600) / 60))
            local uptime_fmt="${hours}h ${mins}m"
        else
            uptime_fmt="N/A"
        fi

        echo -e "   ${GRAY}●${NC}  Processed .......... ${GREEN}$processed_fmt${NC} (${processed:-0})"
        echo -e "   ${GRAY}●${NC}  Rate ............... ${GREEN}${rate:-0} msg/sec${NC}"
        echo -e "   ${GRAY}●${NC}  Consumer Lag ....... ${YELLOW}$lag_fmt${NC}"
        echo -e "   ${GRAY}●${NC}  Errors ............. ${errors:-0}"
        echo -e "   ${GRAY}●${NC}  Uptime ............. $uptime_fmt"
    fi

    echo ""
}

# Show URLs
show_urls() {
    echo -e "${BOLD}ACCESS URLS${NC}"
    echo ""
    echo -e "   📊 Dashboard:   ${CYAN}http://localhost:$DASHBOARD_PORT${NC}"
    echo -e "   📈 Grafana:     ${CYAN}http://localhost:$GRAFANA_PORT${NC}"
    echo -e "   📉 Prometheus:  ${CYAN}http://localhost:$PROMETHEUS_PORT${NC}"
    echo -e "   🔧 Health API:  ${CYAN}http://localhost:$METRICS_PORT/health${NC}"
    echo -e "   📏 Metrics:     ${CYAN}http://localhost:$METRICS_PORT/metrics${NC}"
    echo ""
}

# Show features
show_features() {
    echo -e "${BOLD}DASHBOARD FEATURES${NC}"
    echo ""
    echo -e "   ┌────────────────────────────┬────────┬─────────────────────────┐"
    echo -e "   │ Feature                    │ Status │ Tab/Location            │"
    echo -e "   ├────────────────────────────┼────────┼─────────────────────────┤"
    echo -e "   │ Welcome & Guide            │ ${GREEN}✓${NC}      │ Dashboard → Welcome     │"
    echo -e "   │ Audit Trail                │ ${GREEN}✓${NC}      │ Dashboard → Audit Trail │"
    echo -e "   │ Failure Analysis           │ ${GREEN}✓${NC}      │ Dashboard → Failures    │"
    echo -e "   │ Deletion Tracking          │ ${GREEN}✓${NC}      │ Dashboard → Deletions   │"
    echo -e "   │ API Key Operations         │ ${GREEN}✓${NC}      │ Dashboard → API Keys    │"
    echo -e "   │ Security View              │ ${GREEN}✓${NC}      │ Dashboard → Security    │"
    echo -e "   │ Analytics & Charts         │ ${GREEN}✓${NC}      │ Dashboard → Analytics   │"
    echo -e "   │ Time Insights (Heatmap)    │ ${GREEN}✓${NC}      │ Dashboard → Time        │"
    echo -e "   │ Security Alerts            │ ${GREEN}✓${NC}      │ Dashboard → Alerts      │"
    echo -e "   │ Topic × Identity Matrix    │ ${GREEN}✓${NC}      │ Dashboard → Topic×ID    │"
    echo -e "   │ Identity Activity          │ ${GREEN}✓${NC}      │ Dashboard → Identity    │"
    echo -e "   │ PDF Compliance Report      │ ${GREEN}✓${NC}      │ Dashboard → Export      │"
    echo -e "   │ Anomaly Detection          │ ${GREEN}✓${NC}      │ Forwarder (automatic)   │"
    echo -e "   └────────────────────────────┴────────┴─────────────────────────┘"
    echo ""
}

# View logs
view_logs() {
    show_header
    echo -e "${BOLD}Viewing Forwarder Logs (Ctrl+C to stop)${NC}"
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo ""
    docker compose logs -f --tail=50 audit-forwarder 2>&1 || true
}

# View recent logs (non-streaming)
view_recent_logs() {
    show_header
    echo -e "${BOLD}Recent Logs (last 50 entries):${NC}"
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo ""

    docker compose logs --tail=50 audit-forwarder 2>&1 | while read -r line; do
        if echo "$line" | grep -qi "error\|exception\|fail"; then
            echo -e "${RED}$line${NC}"
        elif echo "$line" | grep -qi "success\|processed\|forwarded"; then
            echo -e "${GREEN}$line${NC}"
        else
            echo "$line"
        fi
    done
    echo ""
}

# Quick commands help
show_commands() {
    show_header
    echo -e "${BOLD}Quick Commands Reference:${NC}"
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo ""
    echo -e "  ${YELLOW}Forwarder:${NC}"
    echo -e "    View logs:       ${GREEN}docker compose logs -f audit-forwarder${NC}"
    echo -e "    Restart:         ${GREEN}docker compose restart audit-forwarder${NC}"
    echo -e "    Stop:            ${GREEN}docker compose down${NC}"
    echo -e "    Start:           ${GREEN}docker compose up -d${NC}"
    echo ""
    echo -e "  ${YELLOW}Monitoring:${NC}"
    echo -e "    Dashboard:       ${GREEN}open http://localhost:$DASHBOARD_PORT${NC}"
    echo -e "    Grafana:         ${GREEN}open http://localhost:$GRAFANA_PORT${NC}"
    echo -e "    Prometheus:      ${GREEN}open http://localhost:$PROMETHEUS_PORT${NC}"
    echo -e "    Full metrics:    ${GREEN}curl localhost:$METRICS_PORT/metrics${NC}"
    echo ""
    echo -e "  ${YELLOW}Setup:${NC}"
    echo -e "    Re-run setup:    ${GREEN}./setup.sh${NC}"
    echo -e "    System status:   ${GREEN}./status.sh${NC}"
    echo ""
}

# Open dashboard
open_dashboard() {
    echo -e "${GREEN}Opening Dashboard...${NC}"
    open "http://localhost:$DASHBOARD_PORT" 2>/dev/null || \
    xdg-open "http://localhost:$DASHBOARD_PORT" 2>/dev/null || \
    echo "Open http://localhost:$DASHBOARD_PORT in your browser"
}

# Open Grafana
open_grafana() {
    echo -e "${GREEN}Opening Grafana...${NC}"
    open "http://localhost:$GRAFANA_PORT" 2>/dev/null || \
    xdg-open "http://localhost:$GRAFANA_PORT" 2>/dev/null || \
    echo "Open http://localhost:$GRAFANA_PORT in your browser"
}

# Restart services
restart_services() {
    show_header
    echo -e "${YELLOW}Restarting all services...${NC}"
    docker compose restart
    echo -e "${GREEN}Done!${NC}"
}

# Stop services
stop_services() {
    show_header
    echo -e "${YELLOW}Stopping all services...${NC}"
    docker compose stop
    echo -e "${GREEN}Done!${NC}"
}

# Start services
start_services() {
    show_header
    echo -e "${YELLOW}Starting all services...${NC}"
    docker compose up -d
    echo -e "${GREEN}Done!${NC}"
}

# Show menu
show_menu() {
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo -e "${BOLD}QUICK ACTIONS${NC}"
    echo ""
    echo -e "  ${GREEN}1${NC}) Refresh Status        ${GREEN}6${NC}) Open Grafana"
    echo -e "  ${GREEN}2${NC}) View Logs (streaming) ${GREEN}7${NC}) Restart Services"
    echo -e "  ${GREEN}3${NC}) View Recent Logs      ${GREEN}8${NC}) Stop Services"
    echo -e "  ${GREEN}4${NC}) Show Commands Help    ${GREEN}9${NC}) Start Services"
    echo -e "  ${GREEN}5${NC}) Open Dashboard        ${GREEN}0${NC}) Show Features"
    echo ""
    echo -e "  ${GREEN}q${NC}) Exit"
    echo ""
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
}

# Wait for key press
wait_for_key() {
    echo ""
    echo -e "${YELLOW}Press any key to return to menu...${NC}"
    read -n 1 -s
}

# Main display (no menu)
show_status() {
    show_header
    show_services
    show_metrics
    show_urls
}

# Main loop
main() {
    while true; do
        show_status
        show_menu

        echo -n "Select option: "
        read -n 1 choice
        echo ""

        case $choice in
            1)
                # Just refresh - loop will show status
                ;;
            2)
                view_logs
                wait_for_key
                ;;
            3)
                view_recent_logs
                wait_for_key
                ;;
            4)
                show_commands
                wait_for_key
                ;;
            5)
                open_dashboard
                sleep 1
                ;;
            6)
                open_grafana
                sleep 1
                ;;
            7)
                restart_services
                wait_for_key
                ;;
            8)
                stop_services
                wait_for_key
                ;;
            9)
                start_services
                wait_for_key
                ;;
            0)
                show_header
                show_features
                wait_for_key
                ;;
            q|Q)
                echo ""
                echo -e "${GREEN}Goodbye!${NC}"
                echo ""
                exit 0
                ;;
            *)
                echo -e "${RED}Invalid option${NC}"
                sleep 1
                ;;
        esac
    done
}

# Run main
main
