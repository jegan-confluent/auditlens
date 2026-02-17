#!/bin/bash
#
# AuditLens Setup Wizard v2.0
# Smart interactive CLI with connectivity testing at each step
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'
BOLD='\033[1m'

# Config files
SECRETS_FILE=".secrets"
ENV_FILE=".env"

# Loaded values
declare -A CURRENT
declare -A NEW

print_banner() {
    clear
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}              ${BOLD}AuditLens Setup Wizard v2.0${NC}                        ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}        Confluent Audit Log Intelligence System                   ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    echo ""
    echo -e "${BLUE}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
    echo -e "${BLUE}┃${NC} ${BOLD}Step $1${NC}                                                          ${BLUE}┃${NC}"
    echo -e "${BLUE}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
}

print_info() {
    echo -e "   ${YELLOW}ℹ${NC}  $1"
}

print_success() {
    echo -e "   ${GREEN}✓${NC}  $1"
}

print_error() {
    echo -e "   ${RED}✗${NC}  $1"
}

print_status() {
    local status="$1"
    local text="$2"
    if [ "$status" = "ok" ]; then
        echo -e "   ${GREEN}●${NC}  $text"
    elif [ "$status" = "warn" ]; then
        echo -e "   ${YELLOW}●${NC}  $text"
    elif [ "$status" = "error" ]; then
        echo -e "   ${RED}●${NC}  $text"
    else
        echo -e "   ${GRAY}○${NC}  $text"
    fi
}

mask_value() {
    local value="$1"
    local show_chars="${2:-4}"
    if [ -z "$value" ]; then
        echo "${GRAY}(not set)${NC}"
    elif [ ${#value} -le 8 ]; then
        echo "****"
    else
        echo "${value:0:$show_chars}****${value: -4}"
    fi
}

# Load existing configuration
load_existing_config() {
    # Load from .secrets
    if [ -f "$SECRETS_FILE" ]; then
        while IFS='=' read -r key value; do
            # Skip comments and empty lines
            [[ "$key" =~ ^#.*$ ]] && continue
            [[ -z "$key" ]] && continue
            # Remove leading/trailing whitespace
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | xargs)
            [ -n "$key" ] && CURRENT[$key]="$value"
        done < "$SECRETS_FILE"
    fi

    # Load from .env
    if [ -f "$ENV_FILE" ]; then
        while IFS='=' read -r key value; do
            [[ "$key" =~ ^#.*$ ]] && continue
            [[ -z "$key" ]] && continue
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | xargs)
            [ -n "$key" ] && CURRENT[$key]="$value"
        done < "$ENV_FILE"
    fi
}

# Show current settings preview
show_current_settings() {
    echo ""
    echo -e "${BOLD}Current Configuration:${NC}"
    echo ""

    echo -e "   ${CYAN}Source (Audit Cluster)${NC}"
    print_status "$([ -n "${CURRENT[AUDIT_BOOTSTRAP]}" ] && echo "ok" || echo "none")" \
        "Bootstrap: ${CURRENT[AUDIT_BOOTSTRAP]:-${GRAY}(not set)${NC}}"
    print_status "$([ -n "${CURRENT[AUDIT_API_KEY]}" ] && echo "ok" || echo "none")" \
        "API Key:   $(mask_value "${CURRENT[AUDIT_API_KEY]}")"

    echo ""
    echo -e "   ${CYAN}Destination Cluster${NC}"
    print_status "$([ -n "${CURRENT[DEST_BOOTSTRAP]}" ] && echo "ok" || echo "none")" \
        "Bootstrap: ${CURRENT[DEST_BOOTSTRAP]:-${GRAY}(not set)${NC}}"
    print_status "$([ -n "${CURRENT[DEST_API_KEY]}" ] && echo "ok" || echo "none")" \
        "API Key:   $(mask_value "${CURRENT[DEST_API_KEY]}")"

    echo ""
    echo -e "   ${CYAN}Schema Registry${NC}"
    print_status "$([ -n "${CURRENT[SCHEMA_REGISTRY_URL]}" ] && echo "ok" || echo "none")" \
        "URL:       ${CURRENT[SCHEMA_REGISTRY_URL]:-${GRAY}(not set)${NC}}"

    echo ""
    echo -e "   ${CYAN}Monitoring${NC}"
    print_status "$([ -n "${CURRENT[GF_ADMIN_PASSWORD]}" ] && echo "ok" || echo "none")" \
        "Grafana:   $([ -n "${CURRENT[GF_ADMIN_PASSWORD]}" ] && echo "Password set" || echo "${GRAY}(not set)${NC}")"
    print_status "$([ -n "${CURRENT[SLACK_WEBHOOK_URL]}" ] && echo "ok" || echo "none")" \
        "Slack:     $([ -n "${CURRENT[SLACK_WEBHOOK_URL]}" ] && echo "Configured" || echo "${GRAY}(not set)${NC}")"

    echo ""
}

# Prompt with current value shown
prompt_with_current() {
    local prompt="$1"
    local var_name="$2"
    local current="${CURRENT[$var_name]}"
    local is_secret="$3"
    local value

    if [ -n "$current" ]; then
        if [ "$is_secret" = "true" ]; then
            echo -e -n "   ${CYAN}$prompt${NC} [$(mask_value "$current")]: "
        else
            echo -e -n "   ${CYAN}$prompt${NC} [${current}]: "
        fi
    else
        echo -e -n "   ${CYAN}$prompt${NC}: "
    fi

    if [ "$is_secret" = "true" ]; then
        read -s value
        echo ""
    else
        read value
    fi

    # Use current if empty
    if [ -z "$value" ]; then
        value="$current"
    fi

    NEW[$var_name]="$value"
}

# Test Kafka connectivity with spinner
test_kafka_connection() {
    local bootstrap="$1"
    local api_key="$2"
    local api_secret="$3"
    local name="$4"

    echo -e -n "   ${GRAY}Testing $name...${NC} "

    if [ -z "$bootstrap" ] || [ -z "$api_key" ] || [ -z "$api_secret" ]; then
        echo -e "${YELLOW}skipped (missing credentials)${NC}"
        return 1
    fi

    # Check if docker is available
    if ! command -v docker &> /dev/null; then
        echo -e "${YELLOW}skipped (Docker not available)${NC}"
        return 1
    fi

    # Create temp config
    local temp_config=$(mktemp)
    cat > "$temp_config" << EOF
security.protocol=SASL_SSL
sasl.mechanism=PLAIN
sasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required username='$api_key' password='$api_secret';
EOF

    # Test with timeout
    if timeout 20 docker run --rm --network host \
        -v "$temp_config:/tmp/client.properties:ro" \
        confluentinc/cp-kafka:7.5.0 \
        kafka-broker-api-versions \
        --bootstrap-server "$bootstrap" \
        --command-config /tmp/client.properties \
        > /dev/null 2>&1; then
        rm -f "$temp_config"
        echo -e "${GREEN}Connected ✓${NC}"
        return 0
    else
        rm -f "$temp_config"
        echo -e "${RED}Failed ✗${NC}"
        return 1
    fi
}

# Test Schema Registry connectivity
test_schema_registry() {
    local url="$1"
    local api_key="$2"
    local api_secret="$3"

    echo -e -n "   ${GRAY}Testing Schema Registry...${NC} "

    if [ -z "$url" ]; then
        echo -e "${YELLOW}skipped (not configured)${NC}"
        return 0
    fi

    if curl -s -u "$api_key:$api_secret" "$url/subjects" --connect-timeout 10 > /dev/null 2>&1; then
        echo -e "${GREEN}Connected ✓${NC}"
        return 0
    else
        echo -e "${RED}Failed ✗${NC}"
        return 1
    fi
}

# Main menu
show_main_menu() {
    echo ""
    echo -e "${BOLD}What would you like to do?${NC}"
    echo ""
    echo "   1) Configure everything (guided setup)"
    echo "   2) Edit Source cluster (Audit logs)"
    echo "   3) Edit Destination cluster"
    echo "   4) Edit Schema Registry"
    echo "   5) Edit Monitoring (Grafana/Slack)"
    echo "   6) Test all connections"
    echo "   7) Save and exit"
    echo "   8) Exit without saving"
    echo ""
    echo -e -n "   ${CYAN}Choose option [1-8]:${NC} "
    read choice
    echo "$choice"
}

# Configure source cluster
configure_source() {
    print_step "1/4: Source Cluster (Audit Logs)"
    echo ""
    print_info "This is the Confluent Cloud cluster containing audit logs."
    print_info "Find credentials in: Organization → Audit Log Settings"
    echo ""

    prompt_with_current "Bootstrap server" "AUDIT_BOOTSTRAP" false
    prompt_with_current "API Key" "AUDIT_API_KEY" false
    prompt_with_current "API Secret" "AUDIT_API_SECRET" true

    echo ""
    test_kafka_connection "${NEW[AUDIT_BOOTSTRAP]}" "${NEW[AUDIT_API_KEY]}" "${NEW[AUDIT_API_SECRET]}" "Source cluster"
}

# Configure destination cluster
configure_destination() {
    print_step "2/4: Destination Cluster"
    echo ""
    print_info "This is YOUR Kafka cluster for processed events."
    print_info "Find credentials in: Cluster → API Keys"
    echo ""

    prompt_with_current "Bootstrap server" "DEST_BOOTSTRAP" false
    prompt_with_current "API Key" "DEST_API_KEY" false
    prompt_with_current "API Secret" "DEST_API_SECRET" true

    echo ""
    test_kafka_connection "${NEW[DEST_BOOTSTRAP]}" "${NEW[DEST_API_KEY]}" "${NEW[DEST_API_SECRET]}" "Destination cluster"
}

# Configure schema registry
configure_schema_registry() {
    print_step "3/4: Schema Registry (Optional)"
    echo ""
    print_info "Enables Avro serialization for events."
    print_info "Find in: Environment → Stream Governance → API credentials"
    echo ""

    echo -e -n "   ${CYAN}Configure Schema Registry? [y/N]:${NC} "
    read answer

    if [[ "$answer" =~ ^[Yy] ]]; then
        prompt_with_current "Schema Registry URL" "SCHEMA_REGISTRY_URL" false
        prompt_with_current "API Key" "SCHEMA_REGISTRY_KEY" false
        prompt_with_current "API Secret" "SCHEMA_REGISTRY_SECRET" true

        echo ""
        test_schema_registry "${NEW[SCHEMA_REGISTRY_URL]}" "${NEW[SCHEMA_REGISTRY_KEY]}" "${NEW[SCHEMA_REGISTRY_SECRET]}"
    else
        NEW[SCHEMA_REGISTRY_URL]=""
        NEW[SCHEMA_REGISTRY_KEY]=""
        NEW[SCHEMA_REGISTRY_SECRET]=""
        print_info "Schema Registry skipped"
    fi
}

# Configure monitoring
configure_monitoring() {
    print_step "4/4: Monitoring & Alerts"
    echo ""

    # Grafana
    print_info "Grafana dashboard password (required)"
    prompt_with_current "Grafana admin password" "GF_ADMIN_PASSWORD" true

    echo ""

    # Slack
    echo -e -n "   ${CYAN}Configure Slack alerts? [y/N]:${NC} "
    read answer

    if [[ "$answer" =~ ^[Yy] ]]; then
        prompt_with_current "Slack Webhook URL" "SLACK_WEBHOOK_URL" false
    fi

    # Group ID
    echo ""
    print_info "Consumer group ID (change to reset offsets)"
    NEW[GROUP_ID]="${CURRENT[GROUP_ID]:-audit-fwd-$(date +%Y%m%d)}"
    prompt_with_current "Consumer Group ID" "GROUP_ID" false
}

# Test all connections
test_all_connections() {
    echo ""
    echo -e "${BOLD}Testing All Connections${NC}"
    echo ""

    local source_ok=false
    local dest_ok=false
    local sr_ok=true

    # Use NEW values if set, otherwise CURRENT
    local audit_bs="${NEW[AUDIT_BOOTSTRAP]:-${CURRENT[AUDIT_BOOTSTRAP]}}"
    local audit_key="${NEW[AUDIT_API_KEY]:-${CURRENT[AUDIT_API_KEY]}}"
    local audit_secret="${NEW[AUDIT_API_SECRET]:-${CURRENT[AUDIT_API_SECRET]}}"

    local dest_bs="${NEW[DEST_BOOTSTRAP]:-${CURRENT[DEST_BOOTSTRAP]}}"
    local dest_key="${NEW[DEST_API_KEY]:-${CURRENT[DEST_API_KEY]}}"
    local dest_secret="${NEW[DEST_API_SECRET]:-${CURRENT[DEST_API_SECRET]}}"

    local sr_url="${NEW[SCHEMA_REGISTRY_URL]:-${CURRENT[SCHEMA_REGISTRY_URL]}}"
    local sr_key="${NEW[SCHEMA_REGISTRY_KEY]:-${CURRENT[SCHEMA_REGISTRY_KEY]}}"
    local sr_secret="${NEW[SCHEMA_REGISTRY_SECRET]:-${CURRENT[SCHEMA_REGISTRY_SECRET]}}"

    test_kafka_connection "$audit_bs" "$audit_key" "$audit_secret" "Source (Audit)" && source_ok=true
    test_kafka_connection "$dest_bs" "$dest_key" "$dest_secret" "Destination" && dest_ok=true

    if [ -n "$sr_url" ]; then
        test_schema_registry "$sr_url" "$sr_key" "$sr_secret" || sr_ok=false
    fi

    echo ""
    echo -e "${BOLD}Summary:${NC}"
    $source_ok && print_status "ok" "Source cluster: Ready" || print_status "error" "Source cluster: Check credentials"
    $dest_ok && print_status "ok" "Destination cluster: Ready" || print_status "error" "Destination cluster: Check credentials"
    [ -n "$sr_url" ] && ($sr_ok && print_status "ok" "Schema Registry: Ready" || print_status "error" "Schema Registry: Check credentials")

    echo ""
    if $source_ok && $dest_ok; then
        print_success "All required connections working!"
        return 0
    else
        print_error "Some connections failed. Please check credentials."
        return 1
    fi
}

# Save configuration
save_configuration() {
    echo ""
    echo -e "${BOLD}Saving Configuration${NC}"
    echo ""

    # Merge NEW into CURRENT (NEW takes precedence)
    for key in "${!NEW[@]}"; do
        CURRENT[$key]="${NEW[$key]}"
    done

    # Write .secrets
    cat > "$SECRETS_FILE" << EOF
# AuditLens Secrets
# Generated: $(date)
# WARNING: Never commit this file to git!

# Source: Audit Log Cluster
AUDIT_BOOTSTRAP=${CURRENT[AUDIT_BOOTSTRAP]}
AUDIT_API_KEY=${CURRENT[AUDIT_API_KEY]}
AUDIT_API_SECRET=${CURRENT[AUDIT_API_SECRET]}

# Destination Cluster
DEST_BOOTSTRAP=${CURRENT[DEST_BOOTSTRAP]}
DEST_API_KEY=${CURRENT[DEST_API_KEY]}
DEST_API_SECRET=${CURRENT[DEST_API_SECRET]}

# Schema Registry
SCHEMA_REGISTRY_URL=${CURRENT[SCHEMA_REGISTRY_URL]}
SCHEMA_REGISTRY_KEY=${CURRENT[SCHEMA_REGISTRY_KEY]}
SCHEMA_REGISTRY_SECRET=${CURRENT[SCHEMA_REGISTRY_SECRET]}

# Grafana
GF_ADMIN_PASSWORD=${CURRENT[GF_ADMIN_PASSWORD]}

# Slack
SLACK_WEBHOOK_URL=${CURRENT[SLACK_WEBHOOK_URL]}
EOF

    chmod 600 "$SECRETS_FILE"
    print_success "Saved .secrets (mode 600)"

    # Write .env
    cat > "$ENV_FILE" << EOF
# AuditLens Configuration
# Generated: $(date)

# Topics
AUDIT_TOPIC_CRITICAL=audit_events_critical
AUDIT_TOPIC_HIGH=audit_events_high
AUDIT_TOPIC_MEDIUM=audit_events_medium
AUDIT_TOPIC_LOW=audit_events_low

# Forwarder
GROUP_ID=${CURRENT[GROUP_ID]:-audit-fwd-$(date +%Y%m%d)}
METRICS_PORT=8003
ENABLE_MULTI_TOPIC_ROUTING=true

# Anomaly Detection
ANOMALY_AUTH_FAILURE_THRESHOLD=10
ANOMALY_DELETION_THRESHOLD=5
EOF

    print_success "Saved .env"

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}                    ${BOLD}Configuration Saved!${NC}                         ${GREEN}║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "   Next steps:"
    echo ""
    echo -e "   ${CYAN}1.${NC} docker compose down && docker compose up -d"
    echo -e "   ${CYAN}2.${NC} docker logs -f audit-forwarder"
    echo -e "   ${CYAN}3.${NC} open http://localhost:8503"
    echo ""
}

# Full guided setup
full_setup() {
    configure_source
    configure_destination
    configure_schema_registry
    configure_monitoring

    echo ""
    echo -e -n "   ${CYAN}Save configuration? [Y/n]:${NC} "
    read answer
    if [[ ! "$answer" =~ ^[Nn] ]]; then
        save_configuration
    fi
}

# ============================================================================
# MAIN
# ============================================================================

print_banner
load_existing_config

# Check if config exists
if [ -f "$SECRETS_FILE" ] || [ -f "$ENV_FILE" ]; then
    show_current_settings

    while true; do
        choice=$(show_main_menu)

        case "$choice" in
            1) full_setup; break ;;
            2) configure_source ;;
            3) configure_destination ;;
            4) configure_schema_registry ;;
            5) configure_monitoring ;;
            6) test_all_connections ;;
            7) save_configuration; break ;;
            8) echo ""; echo "   Exiting without saving."; exit 0 ;;
            *) echo "   Invalid option" ;;
        esac
    done
else
    echo "   No existing configuration found. Starting guided setup..."
    full_setup
fi
