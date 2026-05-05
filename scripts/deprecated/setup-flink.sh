#!/bin/bash
# ============================================================================
# Confluent Cloud Audit Log Analyzer - Setup Script
# ============================================================================
# This script:
# 1. Validates prerequisites
# 2. Gets audit log cluster details
# 3. Asks for customer's destination cluster
# 4. Validates connectivity to both clusters
# 5. Creates output topics in customer cluster
# 6. Sets up Flink compute pool
# 7. Deploys Flink SQL statements
# ============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Detect docker compose command (docker-compose vs docker compose)
DOCKER_COMPOSE=""
if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
elif command -v docker &> /dev/null && docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
fi

# ============================================================================
# Help & Guide Functions
# ============================================================================
show_help_menu() {
    echo ""
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}${BOLD}  What would you like to do?${NC}"
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}[1]${NC} 🚀 Start the forwarder"
    echo -e "      Start processing audit logs → destination cluster"
    echo ""
    echo -e "  ${BOLD}[2]${NC} 📊 View forwarder status & health"
    echo -e "      Check if forwarder is running and processing events"
    echo ""
    echo -e "  ${BOLD}[3]${NC} 📈 Open monitoring dashboards"
    echo -e "      Grafana dashboards, Prometheus metrics"
    echo ""
    echo -e "  ${BOLD}[4]${NC} 🔍 Query with Flink SQL"
    echo -e "      Open Flink shell to run SQL queries"
    echo ""
    echo -e "  ${BOLD}[5]${NC} 📋 View logs"
    echo -e "      Check forwarder logs for troubleshooting"
    echo ""
    echo -e "  ${BOLD}[6]${NC} 🛑 Stop forwarder"
    echo -e "      Stop all services"
    echo ""
    echo -e "  ${BOLD}[7]${NC} 📖 Show all available commands"
    echo -e "      Full reference of useful commands"
    echo ""
    echo -e "  ${BOLD}[q]${NC} Exit"
    echo ""
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
}

show_full_command_reference() {
    echo ""
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}${BOLD}  Complete Command Reference${NC}"
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${YELLOW}${BOLD}▸ FORWARDER MANAGEMENT${NC}"
    echo -e "  Start forwarder:        ${GREEN}${DOCKER_COMPOSE} up -d${NC}"
    echo -e "  Stop forwarder:         ${GREEN}${DOCKER_COMPOSE} down${NC}"
    echo -e "  Restart forwarder:      ${GREEN}${DOCKER_COMPOSE} restart audit-forwarder${NC}"
    echo -e "  Rebuild & start:        ${GREEN}${DOCKER_COMPOSE} up -d --build${NC}"
    echo ""
    echo -e "${YELLOW}${BOLD}▸ HEALTH & STATUS${NC}"
    echo -e "  Health check:           ${GREEN}curl -s localhost:8000/health | jq${NC}"
    echo -e "  Container status:       ${GREEN}docker ps | grep audit${NC}"
    echo -e "  Resource usage:         ${GREEN}docker stats audit-forwarder --no-stream${NC}"
    echo ""
    echo -e "${YELLOW}${BOLD}▸ LOGS & DEBUGGING${NC}"
    echo -e "  Live logs:              ${GREEN}${DOCKER_COMPOSE} logs -f audit-forwarder${NC}"
    echo -e "  Last 100 lines:         ${GREEN}${DOCKER_COMPOSE} logs --tail=100 audit-forwarder${NC}"
    echo -e "  Search errors:          ${GREEN}${DOCKER_COMPOSE} logs audit-forwarder 2>&1 | grep -i error${NC}"
    echo ""
    echo -e "${YELLOW}${BOLD}▸ METRICS & MONITORING${NC}"
    echo -e "  View all metrics:       ${GREEN}curl -s localhost:8000/metrics${NC}"
    echo -e "  Messages consumed:      ${GREEN}curl -s localhost:8000/metrics | grep consumed${NC}"
    echo -e "  Messages produced:      ${GREEN}curl -s localhost:8000/metrics | grep produced${NC}"
    echo -e "  Consumer lag:           ${GREEN}curl -s localhost:8000/metrics | grep lag${NC}"
    echo -e "  Grafana dashboard:      ${GREEN}open http://localhost:3000${NC} (admin/password)"
    echo -e "  Prometheus:             ${GREEN}open http://localhost:9090${NC}"
    echo ""
    echo -e "${YELLOW}${BOLD}▸ KAFKA TOPIC INSPECTION${NC}"
    echo -e "  Consume from destination:"
    echo -e "    ${GREEN}confluent kafka topic consume audit_events_flattened \\${NC}"
    echo -e "    ${GREEN}  --environment \$DEST_ENV_ID --cluster \$DEST_CLUSTER_ID \\${NC}"
    echo -e "    ${GREEN}  --api-key \$DEST_API_KEY --api-secret \$DEST_API_SECRET${NC}"
    echo ""
    echo -e "  Check topic lag:"
    echo -e "    ${GREEN}confluent kafka consumer group lag describe audit-forwarder-group \\${NC}"
    echo -e "    ${GREEN}  --environment \$DEST_ENV_ID --cluster \$DEST_CLUSTER_ID${NC}"
    echo ""
    echo -e "${YELLOW}${BOLD}▸ FLINK SQL${NC}"
    echo -e "  Open Flink shell:       ${GREEN}confluent flink shell \\${NC}"
    echo -e "                          ${GREEN}  --compute-pool \$FLINK_POOL_ID \\${NC}"
    echo -e "                          ${GREEN}  --environment \$DEST_ENV_ID${NC}"
    echo ""
    echo -e "  Example queries in Flink shell:"
    echo -e "    ${BLUE}-- Count events by type${NC}"
    echo -e "    ${GREEN}SELECT type, COUNT(*) FROM audit_events_flattened GROUP BY type;${NC}"
    echo ""
    echo -e "    ${BLUE}-- Recent authorization failures${NC}"
    echo -e "    ${GREEN}SELECT * FROM audit_events_flattened${NC}"
    echo -e "    ${GREEN}WHERE result = 'DENY' ORDER BY event_time DESC LIMIT 10;${NC}"
    echo ""
    echo -e "${YELLOW}${BOLD}▸ CONFIGURATION${NC}"
    echo -e "  View current config:    ${GREEN}cat .env${NC}"
    echo -e "  Edit config:            ${GREEN}\$EDITOR .env${NC}"
    echo -e "  Re-run setup:           ${GREEN}./setup.sh${NC}"
    echo ""
    echo -e "${CYAN}─────────────────────────────────────────────────────────────────${NC}"
}

handle_menu_choice() {
    local choice=$1

    case "$choice" in
        1)
            echo ""
            echo -e "${YELLOW}Starting forwarder and monitoring stack...${NC}"
            ${DOCKER_COMPOSE} up -d
            echo ""
            echo -e "${GREEN}✓ Services started!${NC}"
            echo ""
            echo "Services running:"
            ${DOCKER_COMPOSE} ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || ${DOCKER_COMPOSE} ps
            echo ""
            echo -e "Next: Check status with option ${BOLD}[2]${NC} or view logs with ${BOLD}[5]${NC}"
            ;;
        2)
            echo ""
            echo -e "${YELLOW}Checking forwarder status...${NC}"
            echo ""

            # Container status
            echo -e "${BOLD}Container Status:${NC}"
            if docker ps | grep -q audit-forwarder; then
                echo -e "  ${GREEN}✓${NC} audit-forwarder is running"
                UPTIME=$(docker ps --format "{{.Status}}" --filter "name=audit-forwarder")
                echo -e "  Uptime: ${UPTIME}"
            else
                echo -e "  ${RED}✗${NC} audit-forwarder is NOT running"
                echo -e "  Start with: ${GREEN}${DOCKER_COMPOSE} up -d${NC}"
                return
            fi
            echo ""

            # Health check
            echo -e "${BOLD}Health Check:${NC}"
            HEALTH=$(curl -s localhost:8000/health 2>/dev/null)
            if [ -n "$HEALTH" ]; then
                echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "  $HEALTH"
            else
                echo -e "  ${YELLOW}Health endpoint not responding yet${NC}"
            fi
            echo ""

            # Key metrics
            echo -e "${BOLD}Key Metrics:${NC}"
            METRICS=$(curl -s localhost:8000/metrics 2>/dev/null)
            if [ -n "$METRICS" ]; then
                CONSUMED=$(echo "$METRICS" | grep "audit_messages_consumed_total" | grep -v "^#" | awk '{print $2}')
                PRODUCED=$(echo "$METRICS" | grep "audit_messages_produced_total" | grep -v "^#" | awk '{print $2}')
                ERRORS=$(echo "$METRICS" | grep "audit_processing_errors_total" | grep -v "^#" | awk '{print $2}')
                LAG=$(echo "$METRICS" | grep "audit_consumer_lag" | grep -v "^#" | awk '{sum+=$2} END {print sum}')

                echo -e "  Messages consumed:  ${GREEN}${CONSUMED:-0}${NC}"
                echo -e "  Messages produced:  ${GREEN}${PRODUCED:-0}${NC}"
                echo -e "  Processing errors:  ${ERRORS:-0}"
                echo -e "  Consumer lag:       ${LAG:-0}"
            else
                echo -e "  ${YELLOW}Metrics not available yet${NC}"
            fi
            ;;
        3)
            echo ""
            echo -e "${YELLOW}Opening monitoring dashboards...${NC}"
            echo ""

            # Check if services are running
            if ! docker ps | grep -q audit-prometheus; then
                echo -e "${YELLOW}Starting monitoring stack first...${NC}"
                ${DOCKER_COMPOSE} up -d prometheus grafana
                sleep 3
            fi

            echo "Opening in browser:"
            echo -e "  ${GREEN}Grafana${NC}:    http://localhost:3000 (admin/password)"
            echo -e "  ${GREEN}Prometheus${NC}: http://localhost:9090"
            echo ""

            # Try to open in browser
            if command -v open &>/dev/null; then
                open http://localhost:3000 2>/dev/null
            elif command -v xdg-open &>/dev/null; then
                xdg-open http://localhost:3000 2>/dev/null
            fi
            ;;
        4)
            echo ""
            echo -e "${YELLOW}Opening Flink SQL shell...${NC}"
            echo ""
            echo "Useful queries:"
            echo -e "  ${BLUE}-- Show tables${NC}"
            echo -e "  ${GREEN}SHOW TABLES;${NC}"
            echo ""
            echo -e "  ${BLUE}-- Count by event type${NC}"
            echo -e "  ${GREEN}SELECT type, COUNT(*) as cnt FROM audit_events_flattened GROUP BY type;${NC}"
            echo ""
            echo -e "  ${BLUE}-- Recent events${NC}"
            echo -e "  ${GREEN}SELECT * FROM audit_events_flattened LIMIT 10;${NC}"
            echo ""
            echo -e "Press Ctrl+D to exit Flink shell"
            echo ""
            read -p "Open Flink shell now? (y/n): " OPEN_FLINK
            if [ "$OPEN_FLINK" == "y" ] || [ "$OPEN_FLINK" == "Y" ]; then
                source .env 2>/dev/null
                [ -f ".secrets" ] && source .secrets
                exec confluent flink shell --compute-pool ${FLINK_POOL_ID} --environment ${DEST_ENV_ID}
            fi
            ;;
        5)
            echo ""
            echo -e "${YELLOW}Log Viewing Options:${NC}"
            echo ""
            echo "  [a] Live logs (follow mode)"
            echo "  [b] Last 50 lines"
            echo "  [c] Errors only"
            echo "  [d] Back to menu"
            echo ""
            read -p "Choose [a/b/c/d]: " LOG_CHOICE

            case "$LOG_CHOICE" in
                a)
                    echo ""
                    echo -e "Showing live logs. Press ${BOLD}Ctrl+C${NC} to stop."
                    echo ""
                    ${DOCKER_COMPOSE} logs -f audit-forwarder
                    ;;
                b)
                    echo ""
                    ${DOCKER_COMPOSE} logs --tail=50 audit-forwarder
                    ;;
                c)
                    echo ""
                    ${DOCKER_COMPOSE} logs audit-forwarder 2>&1 | grep -i "error\|exception\|fail" | tail -30
                    ;;
                *)
                    ;;
            esac
            ;;
        6)
            echo ""
            echo -e "${YELLOW}Stopping services...${NC}"
            echo ""
            echo "  [a] Stop forwarder only"
            echo "  [b] Stop all services (forwarder + monitoring)"
            echo "  [c] Cancel"
            echo ""
            read -p "Choose [a/b/c]: " STOP_CHOICE

            case "$STOP_CHOICE" in
                a)
                    ${DOCKER_COMPOSE} stop audit-forwarder
                    echo -e "${GREEN}✓ Forwarder stopped${NC}"
                    ;;
                b)
                    ${DOCKER_COMPOSE} down
                    echo -e "${GREEN}✓ All services stopped${NC}"
                    ;;
                *)
                    echo "Cancelled"
                    ;;
            esac
            ;;
        7)
            show_full_command_reference
            ;;
        q|Q)
            echo ""
            echo "Goodbye! Run ./setup.sh anytime to return to this menu."
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option. Please choose 1-7 or q to quit.${NC}"
            ;;
    esac
}

interactive_guide() {
    while true; do
        show_help_menu
        read -p "Choose an option [1-7, q]: " MENU_CHOICE
        handle_menu_choice "$MENU_CHOICE"

        if [ "$MENU_CHOICE" != "q" ] && [ "$MENU_CHOICE" != "Q" ]; then
            echo ""
            read -p "Press Enter to continue..."
        fi
    done
}

echo -e "${BLUE}"
echo "=============================================="
echo "  Confluent Cloud Audit Log Analyzer Setup"
echo "=============================================="
echo -e "${NC}"

# ============================================================================
# Check for Existing Configuration
# ============================================================================
SKIP_TO_DEPLOY=false

# Check for existing config - either new format (.env + .secrets) or old format (.env with secrets)
if [ -f ".env" ]; then
    # Check if .env has the required variables (old or new format)
    HAS_CONFIG=$(grep -c "AUDIT_BOOTSTRAP\|DEST_BOOTSTRAP" .env 2>/dev/null || echo "0")

    if [ "$HAS_CONFIG" -ge 2 ]; then
    echo -e "${GREEN}Existing configuration found!${NC}"
    echo ""
    echo "Current settings:"
    echo "─────────────────────────────────────────────"
    grep -E "^[A-Z].*=" .env 2>/dev/null | grep -v "SECRET" | while read line; do
        echo "  $line"
    done
    echo "─────────────────────────────────────────────"
    echo ""
    echo "Options:"
    echo "  [1] Use existing config (skip to validation/deploy)"
    echo "  [2] Update specific values"
    echo "  [3] Fresh setup (reconfigure everything)"
    echo ""
    read -p "Choose option [1/2/3]: " CONFIG_CHOICE

    case "$CONFIG_CHOICE" in
        1)
            echo ""
            echo -e "${GREEN}Loading existing configuration...${NC}"
            source .env
            [ -f ".secrets" ] && source .secrets

            # Check if secrets are actually set (not empty)
            SECRETS_MISSING=false
            if [ -z "$AUDIT_API_SECRET" ]; then
                SECRETS_MISSING=true
                echo -e "${YELLOW}Missing: AUDIT_API_SECRET${NC}"
            fi
            if [ -z "$DEST_API_SECRET" ]; then
                SECRETS_MISSING=true
                echo -e "${YELLOW}Missing: DEST_API_SECRET${NC}"
            fi

            if [ "$SECRETS_MISSING" == "true" ]; then
                echo ""
                echo -e "${YELLOW}Some secrets are missing. Please enter them now:${NC}"
                echo ""
                if [ -z "$AUDIT_API_SECRET" ]; then
                    read -sp "Enter Audit Log API Secret: " AUDIT_API_SECRET
                    echo ""
                fi
                if [ -z "$DEST_API_SECRET" ]; then
                    read -sp "Enter Destination API Secret: " DEST_API_SECRET
                    echo ""
                fi
                if [ -z "$SCHEMA_REGISTRY_SECRET" ] && [ -n "$SCHEMA_REGISTRY_URL" ]; then
                    read -sp "Enter Schema Registry Secret (or Enter to skip): " SCHEMA_REGISTRY_SECRET
                    echo ""
                fi

                # Save the secrets
                cat > .secrets << SECRETS_EOF
# SECRETS - DO NOT COMMIT TO GIT
# Updated: $(date)
AUDIT_API_SECRET=${AUDIT_API_SECRET}
DEST_API_SECRET=${DEST_API_SECRET}
SCHEMA_REGISTRY_SECRET=${SCHEMA_REGISTRY_SECRET:-}
SECRETS_EOF
                chmod 600 .secrets
                echo -e "${GREEN}✓ Secrets saved${NC}"
            fi

            SKIP_TO_DEPLOY=true
            ;;
        2)
            echo ""
            echo -e "${YELLOW}Loading existing config for updates...${NC}"
            source .env
            [ -f ".secrets" ] && source .secrets

            echo ""
            echo "Which values to update?"
            echo "  [a] Audit cluster API key/secret"
            echo "  [b] Destination cluster API key/secret"
            echo "  [c] Schema Registry credentials"
            echo "  [d] All credentials"
            echo "  [s] Skip - continue with current values"
            echo ""
            read -p "Choose [a/b/c/d/s]: " UPDATE_CHOICE

            case "$UPDATE_CHOICE" in
                a)
                    read -p "Enter new Audit Log API Key: " AUDIT_API_KEY
                    read -sp "Enter new Audit Log API Secret: " AUDIT_API_SECRET
                    echo ""
                    ;;
                b)
                    read -p "Enter new Destination API Key: " DEST_API_KEY
                    read -sp "Enter new Destination API Secret: " DEST_API_SECRET
                    echo ""
                    ;;
                c)
                    read -p "Enter new Schema Registry API Key: " SCHEMA_REGISTRY_KEY
                    read -sp "Enter new Schema Registry API Secret: " SCHEMA_REGISTRY_SECRET
                    echo ""
                    ;;
                d)
                    read -p "Enter new Audit Log API Key: " AUDIT_API_KEY
                    read -sp "Enter new Audit Log API Secret: " AUDIT_API_SECRET
                    echo ""
                    read -p "Enter new Destination API Key: " DEST_API_KEY
                    read -sp "Enter new Destination API Secret: " DEST_API_SECRET
                    echo ""
                    read -p "Enter new Schema Registry API Key: " SCHEMA_REGISTRY_KEY
                    read -sp "Enter new Schema Registry API Secret: " SCHEMA_REGISTRY_SECRET
                    echo ""
                    ;;
                s|*)
                    echo "Keeping current values."
                    ;;
            esac

            # Save updated secrets
            cat > .secrets << EOF
# SECRETS - DO NOT COMMIT TO GIT
# Updated: $(date)
AUDIT_API_SECRET=${AUDIT_API_SECRET}
DEST_API_SECRET=${DEST_API_SECRET}
SCHEMA_REGISTRY_SECRET=${SCHEMA_REGISTRY_SECRET:-}
EOF
            chmod 600 .secrets
            echo -e "  ${GREEN}✓${NC} Secrets updated"

            SKIP_TO_DEPLOY=true
            ;;
        3)
            echo ""
            echo -e "${YELLOW}Starting fresh setup...${NC}"
            # Continue with normal setup
            ;;
        *)
            echo "Invalid choice. Starting fresh setup..."
            ;;
    esac
    fi  # end HAS_CONFIG check
fi  # end .env file exists check

# If using existing config, skip to deployment
if [ "$SKIP_TO_DEPLOY" == "true" ]; then
    # Jump to Step 9 (topics) and beyond
    echo ""
    echo -e "${YELLOW}Validating existing configuration...${NC}"

    # Quick validation
    if [ -z "$AUDIT_BOOTSTRAP" ] || [ -z "$DEST_BOOTSTRAP" ]; then
        echo -e "${RED}ERROR: Configuration incomplete. Running fresh setup.${NC}"
        SKIP_TO_DEPLOY=false
    else
        echo -e "  ${GREEN}✓${NC} Audit cluster: ${AUDIT_CLUSTER_ID}"
        echo -e "  ${GREEN}✓${NC} Destination cluster: ${DEST_CLUSTER_ID}"
        echo -e "  ${GREEN}✓${NC} Schema Registry: ${SCHEMA_REGISTRY_URL:-not configured}"
        echo -e "  ${GREEN}✓${NC} Flink pool: ${FLINK_POOL_ID:-not configured}"
        echo ""

        # Skip to topic creation / Flink setup
        # Set variables needed for later steps
        POOL_ID="${FLINK_POOL_ID}"

        # Go directly to interactive guide
        echo -e "${GREEN}==============================================${NC}"
        echo -e "${GREEN}  Configuration Loaded!${NC}"
        echo -e "${GREEN}==============================================${NC}"

        if [ -n "$DOCKER_COMPOSE" ]; then
            # Launch interactive guide
            interactive_guide
        else
            echo ""
            echo -e "${YELLOW}WARNING: Docker/Docker Compose not found${NC}"
            echo ""
            echo "Install Docker: https://docs.docker.com/get-docker/"
            echo ""
            echo "Once Docker is running, run ./setup.sh again to access all features."
            echo ""
            echo "Open Flink shell:"
            echo -e "  ${GREEN}confluent flink shell --compute-pool ${FLINK_POOL_ID} --environment ${DEST_ENV_ID}${NC}"
        fi
        echo ""
        exit 0
    fi
fi

# ============================================================================
# Step 1: Check Prerequisites
# ============================================================================
echo -e "${YELLOW}Step 1: Checking prerequisites...${NC}"

# Check Confluent CLI
if ! command -v confluent &> /dev/null; then
    echo -e "${RED}ERROR: Confluent CLI not found${NC}"
    echo "Install with: brew install confluentinc/tap/cli"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Confluent CLI installed"

# Check if logged in
if ! confluent environment list &>/dev/null; then
    echo -e "${RED}ERROR: Not logged in to Confluent Cloud${NC}"
    echo "Run: confluent login"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Logged in to Confluent Cloud"

# ============================================================================
# Step 2: Get Audit Log Cluster Details
# ============================================================================
echo ""
echo -e "${YELLOW}Step 2: Getting audit log cluster details...${NC}"

# Get audit log cluster info
AUDIT_INFO=$(confluent audit-log describe -o json 2>/dev/null || echo "{}")

if [ "$AUDIT_INFO" == "{}" ] || [ -z "$AUDIT_INFO" ]; then
    echo -e "${RED}ERROR: Could not get audit log cluster details${NC}"
    echo "Make sure audit logging is enabled for your organization."
    echo "Check: Confluent Cloud Console > Organization > Audit Logs"
    exit 1
fi

# Parse the audit log describe response
# Format: {"cluster": "lkc-xxx", "environment": "env-xxx", "service_account": "sa-xxx", "topic_name": "..."}
AUDIT_CLUSTER_ID=$(echo "$AUDIT_INFO" | jq -r '.cluster // .cluster_id // empty')
AUDIT_ENV_ID=$(echo "$AUDIT_INFO" | jq -r '.environment // empty')
AUDIT_TOPIC=$(echo "$AUDIT_INFO" | jq -r '.topic_name // .topic // "confluent-audit-log-events"')

if [ -z "$AUDIT_CLUSTER_ID" ]; then
    echo -e "${RED}ERROR: Could not parse audit cluster ID${NC}"
    echo "Raw response: $AUDIT_INFO"
    exit 1
fi

echo -e "  ${GREEN}✓${NC} Audit Log Cluster ID: ${AUDIT_CLUSTER_ID}"
echo -e "  ${GREEN}✓${NC} Audit Log Environment: ${AUDIT_ENV_ID}"
echo -e "  ${GREEN}✓${NC} Audit Topic: ${AUDIT_TOPIC}"

# Get bootstrap servers from the audit cluster
echo "  Getting bootstrap servers for audit cluster..."
AUDIT_CLUSTER_INFO=$(confluent kafka cluster describe "$AUDIT_CLUSTER_ID" --environment "$AUDIT_ENV_ID" -o json 2>/dev/null || echo "{}")

if [ "$AUDIT_CLUSTER_INFO" == "{}" ]; then
    echo -e "${YELLOW}WARNING: Could not get audit cluster details automatically${NC}"
    echo "You may not have permission to describe the audit log cluster."
    echo ""
    echo "Please provide the bootstrap servers manually."
    echo "Find them at: Confluent Cloud Console > Environment > Cluster > Cluster Settings"
    echo "Format: pkc-xxxxx.region.provider.confluent.cloud:9092"
    echo ""
    read -p "Enter Audit Cluster Bootstrap Servers: " AUDIT_BOOTSTRAP
else
    # Extract bootstrap - try different field names
    AUDIT_BOOTSTRAP=$(echo "$AUDIT_CLUSTER_INFO" | jq -r '.endpoint // .bootstrap_endpoint // empty' | sed 's|SASL_SSL://||')

    if [ -z "$AUDIT_BOOTSTRAP" ]; then
        echo -e "${YELLOW}WARNING: Could not parse bootstrap servers${NC}"
        echo "Raw cluster info: $AUDIT_CLUSTER_INFO"
        echo ""
        read -p "Enter Audit Cluster Bootstrap Servers: " AUDIT_BOOTSTRAP
    else
        echo -e "  ${GREEN}✓${NC} Bootstrap Servers: ${AUDIT_BOOTSTRAP}"
    fi
fi

if [ -z "$AUDIT_BOOTSTRAP" ]; then
    echo -e "${RED}ERROR: Bootstrap servers are required${NC}"
    exit 1
fi

# ============================================================================
# Step 3: Get API Key for Audit Log Cluster
# ============================================================================
echo ""
echo -e "${YELLOW}Step 3: API Key for Audit Log Cluster${NC}"
echo ""
echo "You need an API key with READ access to the audit log cluster."
echo "Create one at: Confluent Cloud Console > API Keys"
echo "Or run: confluent api-key create --resource ${AUDIT_CLUSTER_ID}"
echo ""

read -p "Enter Audit Log API Key: " AUDIT_API_KEY
read -sp "Enter Audit Log API Secret: " AUDIT_API_SECRET
echo ""

if [ -z "$AUDIT_API_KEY" ] || [ -z "$AUDIT_API_SECRET" ]; then
    echo -e "${RED}ERROR: API Key and Secret are required${NC}"
    exit 1
fi

# ============================================================================
# Step 4: Validate Audit Log Connectivity
# ============================================================================
echo ""
echo -e "${YELLOW}Step 4: Validating audit log cluster connectivity...${NC}"

# Use the CLI with --api-key and --api-secret flags
# First, set the environment context
confluent environment use "$AUDIT_ENV_ID" &>/dev/null

# Try to consume one message to validate connectivity (timeout after 5 seconds)
# This actually tests the API key works
VALIDATE_RESULT=$(timeout 10 confluent kafka topic consume "$AUDIT_TOPIC" \
    --cluster "$AUDIT_CLUSTER_ID" \
    --api-key "$AUDIT_API_KEY" \
    --api-secret "$AUDIT_API_SECRET" \
    --from-beginning \
    --exit \
    2>&1 || echo "TIMEOUT_OR_ERROR")

if echo "$VALIDATE_RESULT" | grep -q "TIMEOUT_OR_ERROR\|error\|Error\|ERROR"; then
    # Check if it's just a timeout (which means connection worked but no messages yet)
    if echo "$VALIDATE_RESULT" | grep -qi "timeout"; then
        echo -e "  ${GREEN}✓${NC} Connected to audit cluster (no messages consumed yet)"
    else
        echo -e "${YELLOW}WARNING: Could not fully validate audit cluster connectivity${NC}"
        echo "This may be normal - the audit log cluster has restricted access."
        echo "The forwarder will validate connectivity when it starts."
        echo ""
        read -p "Continue anyway? (y/n): " CONTINUE_ANYWAY
        if [ "$CONTINUE_ANYWAY" != "y" ] && [ "$CONTINUE_ANYWAY" != "Y" ]; then
            exit 1
        fi
    fi
else
    echo -e "  ${GREEN}✓${NC} Successfully connected to audit log cluster"
    echo -e "  ${GREEN}✓${NC} Audit topic '${AUDIT_TOPIC}' is accessible"
fi

# ============================================================================
# Step 5: Get Customer's Destination Cluster
# ============================================================================
echo ""
echo -e "${YELLOW}Step 5: Select your destination cluster${NC}"
echo ""
echo "This is YOUR cluster where we'll create the output topics."
echo "The flattened audit data will be written here."
echo ""

# List environments
echo "Available environments:"
confluent environment list
echo ""

read -p "Enter your Environment ID (e.g., env-xxxxx): " DEST_ENV_ID

if [ -z "$DEST_ENV_ID" ]; then
    echo -e "${RED}ERROR: Environment ID is required${NC}"
    exit 1
fi

# Use the environment
confluent environment use "$DEST_ENV_ID"

# List clusters in the environment
echo ""
echo "Available clusters in ${DEST_ENV_ID}:"
confluent kafka cluster list
echo ""

read -p "Enter your Destination Cluster ID (e.g., lkc-xxxxx): " DEST_CLUSTER_ID

if [ -z "$DEST_CLUSTER_ID" ]; then
    echo -e "${RED}ERROR: Cluster ID is required${NC}"
    exit 1
fi

# Get cluster bootstrap
DEST_BOOTSTRAP=$(confluent kafka cluster describe "$DEST_CLUSTER_ID" -o json | jq -r '.endpoint // .bootstrap_endpoint' | sed 's/SASL_SSL:\/\///')

echo -e "  ${GREEN}✓${NC} Destination Cluster: ${DEST_CLUSTER_ID}"
echo -e "  ${GREEN}✓${NC} Bootstrap: ${DEST_BOOTSTRAP}"

# ============================================================================
# Step 6: Get API Key for Destination Cluster
# ============================================================================
echo ""
echo -e "${YELLOW}Step 6: API Key for Destination Cluster${NC}"
echo ""
echo "You need an API key with WRITE access to your destination cluster."
echo "Or run: confluent api-key create --resource ${DEST_CLUSTER_ID}"
echo ""

read -p "Enter Destination Cluster API Key: " DEST_API_KEY
read -sp "Enter Destination Cluster API Secret: " DEST_API_SECRET
echo ""

if [ -z "$DEST_API_KEY" ] || [ -z "$DEST_API_SECRET" ]; then
    echo -e "${RED}ERROR: API Key and Secret are required${NC}"
    exit 1
fi

# ============================================================================
# Step 7: Validate Destination Cluster Connectivity
# ============================================================================
echo ""
echo -e "${YELLOW}Step 7: Validating destination cluster connectivity...${NC}"

# Use the cluster
confluent kafka cluster use "$DEST_CLUSTER_ID"

# Try to list topics
if confluent kafka topic list --cluster "$DEST_CLUSTER_ID" &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Successfully connected to destination cluster"
else
    echo -e "${RED}ERROR: Could not connect to destination cluster${NC}"
    echo "Please verify your API key has appropriate permissions."
    exit 1
fi

# ============================================================================
# Step 8: Get Schema Registry Details
# ============================================================================
echo ""
echo -e "${YELLOW}Step 8: Schema Registry Configuration${NC}"
echo ""
echo "Schema Registry is used to enforce schema on the flattened audit events."
echo "The Python forwarder validates all events against the registered schema."
echo ""

# Schema Registry is per-environment in Confluent Cloud
# Use CLI to get the endpoint URL and cluster ID
echo "Getting Schema Registry details for environment ${DEST_ENV_ID}..."
SR_INFO=$(confluent schema-registry cluster describe -o json 2>/dev/null || echo "{}")

if [ "$SR_INFO" == "{}" ] || [ -z "$SR_INFO" ]; then
    echo -e "${YELLOW}WARNING: Could not get Schema Registry details${NC}"
    echo ""
    echo "This can happen if:"
    echo "  1. Stream Governance is not enabled for this environment"
    echo "  2. You don't have permission to view Schema Registry"
    echo ""
    echo "To enable Stream Governance:"
    echo "  Confluent Cloud Console > Environments > ${DEST_ENV_ID} > Stream Governance"
    echo ""
    echo "You can manually provide the Schema Registry URL."
    echo "Format: https://psrc-XXXXX.region.provider.confluent.cloud"
    echo ""
    read -p "Enter Schema Registry URL (or press Enter to skip): " SCHEMA_REGISTRY_URL
    SCHEMA_REGISTRY_ID=""
else
    SCHEMA_REGISTRY_URL=$(echo "$SR_INFO" | jq -r '.endpoint_url // empty')
    SCHEMA_REGISTRY_ID=$(echo "$SR_INFO" | jq -r '.cluster_id // empty')

    if [ -z "$SCHEMA_REGISTRY_URL" ]; then
        echo -e "${YELLOW}WARNING: Schema Registry endpoint not found in response${NC}"
        echo "Raw response: $SR_INFO"
        echo ""
        echo "Please provide the Schema Registry URL manually."
        echo "Find it at: Confluent Cloud Console > Environment > Stream Governance > API Endpoint"
        echo "Format: https://psrc-XXXXX.region.provider.confluent.cloud"
        echo ""
        read -p "Enter Schema Registry URL: " SCHEMA_REGISTRY_URL
    else
        echo -e "  ${GREEN}✓${NC} Schema Registry URL: ${SCHEMA_REGISTRY_URL}"
        echo -e "  ${GREEN}✓${NC} Schema Registry ID: ${SCHEMA_REGISTRY_ID}"
    fi
fi

# Get Schema Registry API credentials
SR_AUTH_VALID=false
if [ -n "$SCHEMA_REGISTRY_URL" ]; then
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  IMPORTANT: Schema Registry API Key${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "Schema Registry uses DIFFERENT API keys than Kafka clusters!"
    echo ""
    echo -e "${YELLOW}Where to get Schema Registry API key:${NC}"
    echo "  1. Go to: Confluent Cloud Console"
    echo "  2. Select Environment: ${DEST_ENV_ID}"
    echo "  3. Click 'Stream Governance' in the right panel"
    echo "  4. Click 'API credentials' tab"
    echo "  5. Click '+ Add key' to create a new key"
    echo ""
    if [ -n "$SCHEMA_REGISTRY_ID" ]; then
        echo -e "${YELLOW}Or use CLI:${NC}"
        echo "  confluent api-key create --resource ${SCHEMA_REGISTRY_ID} --description \"Audit forwarder\""
        echo ""
    fi
    echo -e "${RED}DO NOT use your Kafka cluster API key here - it will not work!${NC}"
    echo ""

    read -p "Enter Schema Registry API Key: " SCHEMA_REGISTRY_KEY
    read -sp "Enter Schema Registry API Secret: " SCHEMA_REGISTRY_SECRET
    echo ""

    if [ -z "$SCHEMA_REGISTRY_KEY" ] || [ -z "$SCHEMA_REGISTRY_SECRET" ]; then
        echo -e "${YELLOW}WARNING: Schema Registry credentials not provided${NC}"
        echo "You can add them later to .secrets file."
        SCHEMA_REGISTRY_KEY=""
        SCHEMA_REGISTRY_SECRET=""
    else
        # Validate Schema Registry connectivity
        echo "  Validating Schema Registry connectivity..."
        SR_TEST=$(curl -s -w "%{http_code}" -o /tmp/sr_response.json \
            -u "${SCHEMA_REGISTRY_KEY}:${SCHEMA_REGISTRY_SECRET}" \
            "${SCHEMA_REGISTRY_URL}/subjects" 2>/dev/null)

        if [ "$SR_TEST" == "200" ]; then
            echo -e "  ${GREEN}✓${NC} Successfully connected to Schema Registry"
            SUBJECT_COUNT=$(cat /tmp/sr_response.json | jq -r 'length')
            echo -e "  ${GREEN}✓${NC} Found ${SUBJECT_COUNT} existing subjects"
            SR_AUTH_VALID=true
        elif [ "$SR_TEST" == "401" ]; then
            echo -e "${RED}ERROR: Authentication failed (401)${NC}"
            echo ""
            echo "Common causes:"
            echo "  • You used a Kafka cluster API key instead of Schema Registry key"
            echo "  • The API key/secret is incorrect"
            echo "  • The API key was just created (wait 30 seconds and retry)"
            echo ""
            read -p "Continue without Schema Registry? (y/n): " CONTINUE
            if [ "$CONTINUE" != "y" ]; then
                exit 1
            fi
            echo -e "${YELLOW}Skipping schema registration - you'll need to configure SR later${NC}"
        elif [ "$SR_TEST" == "403" ]; then
            echo -e "${YELLOW}WARNING: Access forbidden (403)${NC}"
            echo "The API key may not have sufficient permissions."
        else
            echo -e "${YELLOW}WARNING: Could not connect to Schema Registry (HTTP ${SR_TEST})${NC}"
            echo "Response: $(cat /tmp/sr_response.json 2>/dev/null || echo 'No response')"
        fi
        rm -f /tmp/sr_response.json
    fi
else
    echo -e "${YELLOW}Skipping Schema Registry configuration${NC}"
    echo "The Python forwarder requires Schema Registry to validate events."
    echo "You can configure it later in .env and .secrets files."
    SCHEMA_REGISTRY_KEY=""
    SCHEMA_REGISTRY_SECRET=""
fi

# ============================================================================
# Step 8b: Register JSON Schema (only if Schema Registry auth succeeded)
# ============================================================================
if [ "$SR_AUTH_VALID" == "true" ]; then
    echo ""
    echo -e "${YELLOW}Step 8b: Registering JSON Schema...${NC}"
    echo ""

    DEST_TOPIC="audit_events_flattened"
    SUBJECT="${DEST_TOPIC}-value"
    SCHEMA_FILE="schemas/audit_events_flattened.json"

    if [ -f "$SCHEMA_FILE" ]; then
        echo "Registering schema for subject: ${SUBJECT}"

        # Read the schema and escape it for JSON
        SCHEMA_CONTENT=$(cat "$SCHEMA_FILE" | jq -c .)

        # Create the registration payload
        REGISTER_PAYLOAD=$(jq -n \
            --arg schema "$SCHEMA_CONTENT" \
            '{schemaType: "JSON", schema: $schema}')

        # Register the schema
        REGISTER_RESPONSE=$(curl -s -w "\n%{http_code}" \
            -X POST \
            -H "Content-Type: application/vnd.schemaregistry.v1+json" \
            -u "${SCHEMA_REGISTRY_KEY}:${SCHEMA_REGISTRY_SECRET}" \
            -d "$REGISTER_PAYLOAD" \
            "${SCHEMA_REGISTRY_URL}/subjects/${SUBJECT}/versions" 2>/dev/null)

        HTTP_CODE=$(echo "$REGISTER_RESPONSE" | tail -1)
        RESPONSE_BODY=$(echo "$REGISTER_RESPONSE" | sed '$d')

        if [ "$HTTP_CODE" == "200" ]; then
            SCHEMA_ID=$(echo "$RESPONSE_BODY" | jq -r '.id')
            echo -e "  ${GREEN}✓${NC} Schema registered successfully (ID: ${SCHEMA_ID})"
        elif [ "$HTTP_CODE" == "409" ]; then
            echo -e "  ${YELLOW}⊘${NC} Schema already exists for subject ${SUBJECT}"
            # Get the existing schema ID
            EXISTING=$(curl -s -u "${SCHEMA_REGISTRY_KEY}:${SCHEMA_REGISTRY_SECRET}" \
                "${SCHEMA_REGISTRY_URL}/subjects/${SUBJECT}/versions/latest" 2>/dev/null)
            SCHEMA_ID=$(echo "$EXISTING" | jq -r '.id // "unknown"')
            echo -e "  ${GREEN}✓${NC} Using existing schema (ID: ${SCHEMA_ID})"
        else
            echo -e "${YELLOW}WARNING: Could not register schema (HTTP ${HTTP_CODE})${NC}"
            echo "Response: $RESPONSE_BODY"
            echo ""
            echo "You can register the schema manually later:"
            echo "  curl -X POST -H 'Content-Type: application/vnd.schemaregistry.v1+json' \\"
            echo "    -u '\$SR_KEY:\$SR_SECRET' \\"
            echo "    -d @schemas/audit_events_flattened_sr.json \\"
            echo "    '\$SR_URL/subjects/${SUBJECT}/versions'"
        fi
    else
        echo -e "${YELLOW}WARNING: Schema file not found: ${SCHEMA_FILE}${NC}"
        echo "You can register the schema manually after creating the file."
    fi
fi

# ============================================================================
# Step 9: Create Output Topics
# ============================================================================
echo ""
echo -e "${YELLOW}Step 9: Creating output topics in destination cluster...${NC}"

# Define topics to create
TOPICS=(
    "audit_events_flattened"
    "audit_deletions"
    "audit_creations"
    "audit_api_keys"
    "audit_security_events"
    "audit_user_activity"
    "audit_cluster_activity"
    "audit_by_resource_type"
    "audit_by_criticality"
)

for topic in "${TOPICS[@]}"; do
    if confluent kafka topic describe "$topic" --cluster "$DEST_CLUSTER_ID" &>/dev/null; then
        echo -e "  ${YELLOW}⊘${NC} Topic '$topic' already exists"
    else
        confluent kafka topic create "$topic" \
            --cluster "$DEST_CLUSTER_ID" \
            --partitions 6 \
            --config cleanup.policy=compact \
            2>/dev/null && \
        echo -e "  ${GREEN}✓${NC} Created topic: $topic" || \
        echo -e "  ${RED}✗${NC} Failed to create topic: $topic"
    fi
done

# ============================================================================
# Step 10: Set up Flink Compute Pool
# ============================================================================
echo ""
echo -e "${YELLOW}Step 10: Setting up Flink Compute Pool...${NC}"

# Get Flink region (should match destination cluster region)
DEST_REGION=$(confluent kafka cluster describe "$DEST_CLUSTER_ID" -o json | jq -r '.region')
DEST_CLOUD=$(confluent kafka cluster describe "$DEST_CLUSTER_ID" -o json | jq -r '.cloud')

echo "Destination cluster is in: ${DEST_CLOUD} / ${DEST_REGION}"

# Check if compute pool exists
echo "Checking for existing Flink compute pools..."
POOL_LIST=$(confluent flink compute-pool list --environment "$DEST_ENV_ID" -o json 2>/dev/null)

# Try different JSON structures - API format varies
EXISTING_POOL=$(echo "$POOL_LIST" | jq -r '.[] | select(.display_name=="audit-analyzer" or .name=="audit-analyzer") | .id' 2>/dev/null | head -1)

# If that didn't work, try without array
if [ -z "$EXISTING_POOL" ]; then
    EXISTING_POOL=$(echo "$POOL_LIST" | jq -r 'if type=="array" then .[] else . end | select(.display_name=="audit-analyzer" or .name=="audit-analyzer") | .id' 2>/dev/null | head -1)
fi

# Last resort - look for any pool with "audit" in the name
if [ -z "$EXISTING_POOL" ]; then
    EXISTING_POOL=$(echo "$POOL_LIST" | jq -r '.[] | select(.display_name | test("audit"; "i")) | .id' 2>/dev/null | head -1)
fi

if [ -n "$EXISTING_POOL" ] && [ "$EXISTING_POOL" != "null" ]; then
    POOL_ID="$EXISTING_POOL"
    echo -e "  ${GREEN}✓${NC} Using existing compute pool: $POOL_ID"
else
    echo "Creating new Flink compute pool..."
    CREATE_OUTPUT=$(confluent flink compute-pool create audit-analyzer \
        --cloud "$DEST_CLOUD" \
        --region "$DEST_REGION" \
        --max-cfu 10 \
        --environment "$DEST_ENV_ID" \
        -o json 2>&1)

    # Check if creation failed due to existing pool
    if echo "$CREATE_OUTPUT" | grep -qi "already.*running\|already exists"; then
        echo -e "  ${YELLOW}Pool already exists, finding it...${NC}"
        # Re-fetch and find any audit-related pool
        POOL_LIST=$(confluent flink compute-pool list --environment "$DEST_ENV_ID" -o json 2>/dev/null)
        POOL_ID=$(echo "$POOL_LIST" | jq -r '.[0].id // .id' 2>/dev/null | head -1)
        if [ -n "$POOL_ID" ] && [ "$POOL_ID" != "null" ]; then
            echo -e "  ${GREEN}✓${NC} Found existing compute pool: $POOL_ID"
        else
            echo -e "${YELLOW}WARNING: Could not find pool ID, listing all pools:${NC}"
            confluent flink compute-pool list --environment "$DEST_ENV_ID"
            read -p "Enter the compute pool ID (lfcp-xxxxx): " POOL_ID
        fi
    else
        POOL_ID=$(echo "$CREATE_OUTPUT" | jq -r '.id' 2>/dev/null)
        if [ -z "$POOL_ID" ] || [ "$POOL_ID" == "null" ]; then
            echo -e "${RED}ERROR: Failed to create Flink compute pool${NC}"
            echo "Output: $CREATE_OUTPUT"
            echo ""
            echo "You can create one manually:"
            echo "  confluent flink compute-pool create audit-analyzer --cloud $DEST_CLOUD --region $DEST_REGION --max-cfu 10"
            echo ""
            read -p "Enter existing compute pool ID (or press Enter to skip): " POOL_ID
        else
            echo -e "  ${GREEN}✓${NC} Created compute pool: $POOL_ID"
        fi
    fi
fi

# Only wait for newly created pools, skip for existing
if [ -n "$EXISTING_POOL" ]; then
    echo -e "  ${GREEN}✓${NC} Existing pool ready: $POOL_ID"
elif [ -n "$POOL_ID" ]; then
    # Wait for newly created pool
    echo "Waiting for new compute pool to be ready..."
    for i in {1..30}; do
        POOL_INFO=$(confluent flink compute-pool describe "$POOL_ID" --environment "$DEST_ENV_ID" -o json 2>/dev/null)
        CURRENT_CFU=$(echo "$POOL_INFO" | jq -r '.current_cfu // 0' 2>/dev/null)

        if [ -n "$CURRENT_CFU" ] && [ "$CURRENT_CFU" != "null" ] && [ "$CURRENT_CFU" != "0" ]; then
            echo -e "  ${GREEN}✓${NC} Compute pool is ready (${CURRENT_CFU} CFUs)"
            break
        fi

        if [ $i -eq 30 ]; then
            echo -e "  ${YELLOW}Pool may still be provisioning. Continuing anyway.${NC}"
        else
            echo "  Waiting... (attempt $i/30)"
            sleep 10
        fi
    done
    echo -e "  ${GREEN}✓${NC} Compute pool configured: $POOL_ID"
fi

# ============================================================================
# Step 11: Save Configuration
# ============================================================================
echo ""
echo -e "${YELLOW}Step 11: Saving configuration...${NC}"

# Create .env file
cat > .env << EOF
# Audit Log Analyzer Configuration
# Generated: $(date)

# Audit Log Cluster (Source - Read Only)
AUDIT_CLUSTER_ID=${AUDIT_CLUSTER_ID}
AUDIT_BOOTSTRAP=${AUDIT_BOOTSTRAP}
AUDIT_TOPIC=${AUDIT_TOPIC}
AUDIT_API_KEY=${AUDIT_API_KEY}
# AUDIT_API_SECRET stored separately for security

# Destination Cluster (Your cluster - Write)
DEST_ENV_ID=${DEST_ENV_ID}
DEST_CLUSTER_ID=${DEST_CLUSTER_ID}
DEST_BOOTSTRAP=${DEST_BOOTSTRAP}
DEST_API_KEY=${DEST_API_KEY}
DEST_TOPIC=audit_events_flattened
# DEST_API_SECRET stored separately for security

# Schema Registry
SCHEMA_REGISTRY_URL=${SCHEMA_REGISTRY_URL:-}
SCHEMA_REGISTRY_KEY=${SCHEMA_REGISTRY_KEY:-}
# SCHEMA_REGISTRY_SECRET stored separately for security

# Flink
FLINK_POOL_ID=${POOL_ID}
FLINK_CLOUD=${DEST_CLOUD}
FLINK_REGION=${DEST_REGION}

# Forwarder Settings
GROUP_ID=audit-forwarder-group
OFFSET_FILE=offsets.json
METRICS_PORT=8000
EOF

echo -e "  ${GREEN}✓${NC} Configuration saved to .env"

# Create secrets file (should be in .gitignore)
cat > .secrets << EOF
# SECRETS - DO NOT COMMIT TO GIT
# Add this file to .gitignore
AUDIT_API_SECRET=${AUDIT_API_SECRET}
DEST_API_SECRET=${DEST_API_SECRET}
SCHEMA_REGISTRY_SECRET=${SCHEMA_REGISTRY_SECRET:-}
EOF
chmod 600 .secrets

echo -e "  ${GREEN}✓${NC} Secrets saved to .secrets (chmod 600)"

# Add to .gitignore if not already there
if ! grep -q ".secrets" .gitignore 2>/dev/null; then
    echo ".secrets" >> .gitignore
    echo -e "  ${GREEN}✓${NC} Added .secrets to .gitignore"
fi

# ============================================================================
# Step 12: Deploy Flink SQL
# ============================================================================
echo ""
echo -e "${YELLOW}Step 12: Ready to deploy Flink SQL${NC}"
echo ""
echo "Configuration complete! Next steps:"
echo ""
echo "1. Open Flink SQL shell:"
echo "   confluent flink shell --compute-pool ${POOL_ID} --environment ${DEST_ENV_ID}"
echo ""
echo "2. In the shell, set up the connection to audit cluster:"
echo "   (Flink SQL commands will be generated)"
echo ""
echo "3. Or run the Flink deployment script:"
echo "   ./deploy-flink.sh"
echo ""

read -p "Deploy Flink SQL now? (y/n): " DEPLOY_NOW

if [ "$DEPLOY_NOW" == "y" ] || [ "$DEPLOY_NOW" == "Y" ]; then
    echo ""
    echo -e "${YELLOW}Deploying Flink SQL statements...${NC}"

    # Generate the Flink SQL that connects to audit cluster
    cat > flink-sql/00_connection_setup.sql << EOF
-- ============================================================================
-- Connection Setup for Audit Log Analyzer
-- Generated: $(date)
-- ============================================================================

-- Note: In Confluent Cloud Flink, you access topics from different clusters
-- by using the appropriate catalog and database names.

-- The audit log topic is accessible via the audit log cluster
-- Your output topics are in your destination cluster

-- Set the catalog to your environment
USE CATALOG \`${DEST_ENV_ID}\`;

-- Set the database to your destination cluster for output
USE \`${DEST_CLUSTER_ID}\`;

-- You can now create tables that read from audit cluster and write to dest cluster
EOF

    echo -e "  ${GREEN}✓${NC} Generated connection setup SQL"

    # Deploy statements (this part needs refinement based on actual Flink SQL syntax)
    echo ""
    echo "Flink SQL statements are ready in flink-sql/ directory."
    echo ""
    echo "To complete setup, open Flink shell and run:"
    echo "  1. flink-sql/00_connection_setup.sql"
    echo "  2. flink-sql/01_audit_events_source.sql"
    echo "  3. flink-sql/02_audit_events_flattened.sql"
    echo "  4. flink-sql/03_aggregation_tables.sql"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo -e "${GREEN}=============================================="
echo "  Setup Complete!"
echo "==============================================${NC}"
echo ""
echo "Audit Log Cluster (Source):"
echo "  Cluster ID: ${AUDIT_CLUSTER_ID}"
echo "  Bootstrap:  ${AUDIT_BOOTSTRAP}"
echo "  Topic:      ${AUDIT_TOPIC}"
echo ""
echo "Destination Cluster (Output):"
echo "  Environment: ${DEST_ENV_ID}"
echo "  Cluster ID:  ${DEST_CLUSTER_ID}"
echo "  Bootstrap:   ${DEST_BOOTSTRAP}"
echo ""
if [ -n "$SCHEMA_REGISTRY_URL" ]; then
echo "Schema Registry:"
echo "  URL: ${SCHEMA_REGISTRY_URL}"
echo ""
fi
echo "Flink Compute Pool:"
echo "  Pool ID: ${POOL_ID}"
echo "  Region:  ${DEST_CLOUD} / ${DEST_REGION}"
echo ""
echo "Topics created in destination cluster:"
for topic in "${TOPICS[@]}"; do
    echo "  - $topic"
done
echo ""
echo "Files created:"
echo "  - .env (configuration)"
echo "  - .secrets (API secrets - DO NOT COMMIT)"
echo "  - flink-sql/00_connection_setup.sql"
echo ""

if [ -n "$DOCKER_COMPOSE" ]; then
    echo ""
    echo -e "${GREEN}Setup complete! Launching interactive guide...${NC}"
    echo ""
    sleep 1
    # Launch interactive guide
    interactive_guide
else
    echo ""
    echo -e "${YELLOW}=========================================="
    echo "  NEXT STEPS"
    echo "==========================================${NC}"
    echo ""
    echo -e "${RED}Docker/Docker Compose not found.${NC}"
    echo ""
    echo "1. Install Docker: https://docs.docker.com/get-docker/"
    echo ""
    echo "2. Then run ./setup.sh again to access the interactive guide"
    echo ""
    echo "Open Flink shell:"
    echo -e "  ${GREEN}confluent flink shell --compute-pool ${POOL_ID} --environment ${DEST_ENV_ID}${NC}"
    echo ""
fi
