#!/bin/bash
# ============================================================================
# Audit Log Forwarder - Interactive Status Menu
# ============================================================================
# Interactive menu to check status, view logs, consume messages
# Usage: ./status.sh
# ============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Load config
[ -f ".env" ] && source .env
[ -f ".secrets" ] && source .secrets

# Format large numbers
format_number() {
    local num=$1
    if [ -z "$num" ]; then echo "0"; return; fi
    if [ "$num" -ge 1000000 ]; then
        printf "%.2fM" $(echo "$num / 1000000" | bc -l)
    elif [ "$num" -ge 1000 ]; then
        printf "%.1fK" $(echo "$num / 1000" | bc -l)
    else
        echo "$num"
    fi
}

# Show header
show_header() {
    clear
    echo ""
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}${BOLD}  Audit Log Forwarder - Interactive Menu${NC}"
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Show status
show_status() {
    show_header
    echo -e "${BOLD}1. Container Status:${NC}"
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "audit-forwarder"; then
        UPTIME=$(docker ps --format "{{.Status}}" --filter "name=audit-forwarder" 2>/dev/null)
        echo -e "   ${GREEN}✓${NC} audit-forwarder is running"
        echo -e "   Uptime: ${UPTIME}"
    else
        echo -e "   ${RED}✗${NC} audit-forwarder is NOT running"
        echo -e "   Start with: ${GREEN}docker compose up -d${NC}"
    fi
    echo ""

    echo -e "${BOLD}2. Health Check:${NC}"
    HEALTH=$(curl -s localhost:8003/health 2>/dev/null)
    if [ -n "$HEALTH" ]; then
        echo "   $HEALTH" | python3 -m json.tool 2>/dev/null | sed 's/^/   /' || echo "   $HEALTH"
    else
        echo -e "   ${YELLOW}Health endpoint not responding${NC}"
    fi
    echo ""

    echo -e "${BOLD}3. Metrics:${NC}"
    METRICS=$(curl -s localhost:8003/metrics 2>/dev/null)
    if [ -n "$METRICS" ]; then
        PROCESSED=$(echo "$METRICS" | grep "audit_forwarder_processed_messages_total" | grep -v "^#" | awk '{print $2}')
        RATE=$(echo "$METRICS" | grep "audit_forwarder_processing_rate_per_second" | grep -v "^#" | awk '{printf "%.1f", $2}')
        ERRORS=$(echo "$METRICS" | grep "audit_forwarder_error_count_total" | grep -v "^#" | awk '{print $2}')
        LAG=$(echo "$METRICS" | grep "audit_forwarder_consumer_lag_total" | grep -v "^#" | awk '{printf "%.0f", $2}')
        UPTIME_SEC=$(echo "$METRICS" | grep "audit_forwarder_uptime_seconds" | grep -v "^#" | awk '{printf "%.0f", $2}')

        if [ -n "$UPTIME_SEC" ]; then
            HOURS=$((UPTIME_SEC / 3600))
            MINS=$(((UPTIME_SEC % 3600) / 60))
            SECS=$((UPTIME_SEC % 60))
            UPTIME_FMT="${HOURS}h ${MINS}m ${SECS}s"
        else
            UPTIME_FMT="N/A"
        fi

        PROCESSED_FMT=$(format_number "${PROCESSED:-0}")
        LAG_FMT=$(format_number "${LAG:-0}")

        echo -e "   Messages Processed:  ${GREEN}${PROCESSED_FMT}${NC} (${PROCESSED:-0})"
        echo -e "   Processing Rate:     ${GREEN}${RATE:-0} msg/sec${NC}"
        echo -e "   Consumer Lag:        ${YELLOW}${LAG_FMT}${NC} (${LAG:-0})"
        echo -e "   Errors:              ${ERRORS:-0}"
        echo -e "   Forwarder Uptime:    ${UPTIME_FMT}"
    else
        echo -e "   ${RED}Metrics not available${NC}"
    fi
    echo ""

    echo -e "${BOLD}4. Source Topic Offsets:${NC}"
    if [ -f "data/offsets.json" ]; then
        TOTAL_OFFSET=0
        while IFS=: read -r partition offset; do
            partition=$(echo "$partition" | tr -d '", ')
            offset=$(echo "$offset" | tr -d ', ')
            if [ -n "$offset" ]; then
                TOTAL_OFFSET=$((TOTAL_OFFSET + offset))
            fi
        done < <(grep -o '"confluent-audit-log-events_[0-9]*": [0-9]*' data/offsets.json)

        TOTAL_FMT=$(format_number "$TOTAL_OFFSET")
        echo -e "   Total offset position: ${GREEN}${TOTAL_FMT}${NC} (${TOTAL_OFFSET})"
        echo -e "   Partitions tracked: $(grep -c 'confluent-audit-log-events' data/offsets.json)"
    else
        echo -e "   ${YELLOW}No offsets file found${NC}"
    fi
    echo ""
}

# View logs
view_logs() {
    show_header
    echo -e "${BOLD}Viewing Forwarder Logs (Ctrl+C to stop, then press any key to return to menu)${NC}"
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo ""

    # Show logs with trap to return to menu
    docker compose logs -f --tail=50 audit-forwarder 2>&1 || true
}

# View recent logs (non-streaming)
view_recent_logs() {
    show_header
    echo -e "${BOLD}Recent Logs (last 50 entries):${NC}"
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo ""

    docker compose logs --tail=50 audit-forwarder 2>&1 | while read line; do
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

# Consume messages
consume_messages() {
    show_header
    echo -e "${BOLD}Consuming Recent Messages from audit_events_flattened${NC}"
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo ""
    echo -e "${YELLOW}Showing last 10 messages (timeout 15s)...${NC}"
    echo ""

    timeout 15 confluent kafka topic consume audit_events_flattened \
        --cluster "$DEST_CLUSTER_ID" \
        --environment "$DEST_ENV_ID" \
        --api-key "$DEST_API_KEY" \
        --api-secret "$DEST_API_SECRET" \
        --from-beginning \
        --print-offset 2>&1 | head -20 || echo -e "${YELLOW}Timeout or no messages${NC}"
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
    echo ""
    echo -e "  ${YELLOW}Monitoring:${NC}"
    echo -e "    Dashboard:       ${GREEN}open http://localhost:8501${NC}"
    echo -e "    Grafana:         ${GREEN}open http://localhost:3000${NC}"
    echo -e "    Prometheus:      ${GREEN}open http://localhost:9090${NC}"
    echo -e "    Full metrics:    ${GREEN}curl localhost:8003/metrics${NC}"
    echo ""
    echo -e "  ${YELLOW}Kafka Topics:${NC}"
    echo -e "    List topics:     ${GREEN}confluent kafka topic list --cluster $DEST_CLUSTER_ID${NC}"
    echo -e "    Consume data:    ${GREEN}confluent kafka topic consume audit_events_flattened --print-offset${NC}"
    echo ""
    echo -e "  ${YELLOW}Flink SQL:${NC}"
    echo -e "    Open shell:      ${GREEN}confluent flink shell --compute-pool $FLINK_POOL_ID --environment $DEST_ENV_ID${NC}"
    echo ""
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo -e "${BOLD}Example Flink Queries:${NC}"
    echo ""
    echo -e "  ${YELLOW}-- Count events by type${NC}"
    echo -e "  ${GREEN}SELECT methodName, COUNT(*) as cnt FROM audit_events_flattened GROUP BY methodName;${NC}"
    echo ""
    echo -e "  ${YELLOW}-- Recent events${NC}"
    echo -e "  ${GREEN}SELECT * FROM audit_events_flattened LIMIT 10;${NC}"
    echo ""
}

# Open dashboard
open_dashboard() {
    echo -e "${GREEN}Opening Streamlit Dashboard...${NC}"
    open http://localhost:8501 2>/dev/null || xdg-open http://localhost:8501 2>/dev/null || echo "Open http://localhost:8501 in your browser"
}

# Show menu
show_menu() {
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
    echo -e "${BOLD}Menu:${NC}"
    echo ""
    echo -e "  ${GREEN}1${NC}) View Status"
    echo -e "  ${GREEN}2${NC}) View Logs (streaming)"
    echo -e "  ${GREEN}3${NC}) View Recent Logs (last 50)"
    echo -e "  ${GREEN}4${NC}) Consume Messages"
    echo -e "  ${GREEN}5${NC}) Quick Commands Help"
    echo -e "  ${GREEN}6${NC}) Open Dashboard"
    echo -e "  ${GREEN}7${NC}) Restart Forwarder"
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

# Restart forwarder
restart_forwarder() {
    show_header
    echo -e "${YELLOW}Restarting forwarder...${NC}"
    docker compose restart audit-forwarder
    echo -e "${GREEN}Done!${NC}"
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
                show_status
                wait_for_key
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
                consume_messages
                wait_for_key
                ;;
            5)
                show_commands
                wait_for_key
                ;;
            6)
                open_dashboard
                sleep 1
                ;;
            7)
                restart_forwarder
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
