#!/bin/bash
# ============================================================================
# Auto-Restart Forwarder Script for Local Development
# ============================================================================
# This script runs the audit forwarder with automatic restart on crash.
# Designed for local development and testing.
#
# Features:
# - Auto-restart with 5 second delay
# - Loads environment variables from .env and .secrets
# - Configurable multi-topic routing
# - Logs each start attempt
# - Clean shutdown with Ctrl+C
# ============================================================================

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}============================================================================${NC}"
echo -e "${GREEN} Audit Log Forwarder - Auto-Restart Mode${NC}"
echo -e "${GREEN}============================================================================${NC}"
echo ""

# Load environment variables
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo -e "${GREEN}✓ Loaded .env file${NC}"
else
    echo -e "${RED}✗ .env file not found${NC}"
    exit 1
fi

if [ -f .secrets ]; then
    set -a
    source .secrets
    set +a
    echo -e "${GREEN}✓ Loaded .secrets file${NC}"
else
    echo -e "${RED}✗ .secrets file not found${NC}"
    exit 1
fi

# Set optimal configuration for production
export ENABLE_MULTI_TOPIC_ROUTING=true
export DROP_LOW_EVENTS=true
export METRICS_PORT=${METRICS_PORT:-8003}

echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Multi-Topic Routing: ${ENABLE_MULTI_TOPIC_ROUTING}"
echo "  Drop LOW Events: ${DROP_LOW_EVENTS}"
echo "  Metrics Port: ${METRICS_PORT}"
echo ""

# Trap SIGINT and SIGTERM for clean shutdown
trap 'echo -e "\n${YELLOW}Shutting down forwarder...${NC}"; exit 0' SIGINT SIGTERM

# Auto-restart loop
attempt=1
while true; do
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] Starting forwarder (Attempt #${attempt})${NC}"
    
    # Run the forwarder
    python3 audit_forwarder.py
    
    exit_code=$?
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] Forwarder exited with code ${exit_code}${NC}"
    
    # If exit code is 0, it was a clean shutdown, so exit
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}Clean shutdown detected, exiting${NC}"
        break
    fi
    
    # Otherwise, wait and restart
    echo -e "${YELLOW}Waiting 5 seconds before restart...${NC}"
    sleep 5
    
    attempt=$((attempt + 1))
done
