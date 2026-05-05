#!/bin/bash

# ============================================================================
# Confluent Audit Log Intelligence System - Quick Start Script v8.0
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Banner
echo -e "${CYAN}"
cat << "EOF"
============================================================================
  🔒 Confluent Audit Log Intelligence System v8.0
============================================================================
  Quick Start - Your audit monitoring in 60 seconds!
EOF
echo -e "${NC}"

# Step 1: Validate configuration
echo -e "\n${BLUE}>>> Step 1: Validating Configuration${NC}\n"

# Check .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found${NC}"
    echo "Run ./install.sh first to configure the system"
    exit 1
fi

# Check .secrets exists
if [ ! -f ".secrets" ]; then
    echo -e "${RED}❌ .secrets file not found${NC}"
    echo "Run ./install.sh first to configure the system"
    exit 1
fi

# Check .secrets has real credentials (not placeholders)
if grep -q "<TODO:" .secrets || grep -q "<your-" .secrets; then
    echo -e "${RED}❌ .secrets still has placeholders${NC}"
    echo "Please fill in your API keys in .secrets file:"
    echo "  nano .secrets"
    exit 1
fi

echo -e "${GREEN}✓${NC} Configuration files found"
echo -e "${GREEN}✓${NC} Credentials configured"

# Step 2: Check Docker is running
echo -e "\n${BLUE}>>> Step 2: Checking Docker${NC}\n"

if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running${NC}"
    echo "Please start Docker Desktop and try again"
    exit 1
fi

echo -e "${GREEN}✓${NC} Docker is running"

# Step 3: Stop existing containers (if any)
echo -e "\n${BLUE}>>> Step 3: Cleaning Up Old Containers${NC}\n"

if docker compose ps 2>/dev/null | grep -q "Up"; then
    echo "Stopping existing containers..."
    docker compose down
    echo -e "${GREEN}✓${NC} Old containers stopped"
else
    echo -e "${GREEN}✓${NC} No old containers to clean up"
fi

# Step 4: Start the system
echo -e "\n${BLUE}>>> Step 4: Starting Audit Log Intelligence System${NC}\n"

echo "Starting containers in detached mode..."
docker compose up -d

# Wait a few seconds for containers to initialize
echo "Waiting for containers to initialize..."
sleep 5

# Step 5: Check container status
echo -e "\n${BLUE}>>> Step 5: Checking Container Status${NC}\n"

# Check audit-forwarder
if docker ps | grep -q "audit-forwarder"; then
    echo -e "${GREEN}✓${NC} Forwarder: Running"
else
    echo -e "${RED}✗${NC} Forwarder: Not running"
    docker logs audit-forwarder --tail 20 2>&1
    exit 1
fi

# Check dashboard
if docker ps | grep -q "dashboard"; then
    echo -e "${GREEN}✓${NC} Dashboard: Running"
else
    echo -e "${RED}✗${NC} Dashboard: Not running"
    docker logs dashboard --tail 20 2>&1
    exit 1
fi

# Step 6: Show forwarder startup logs
echo -e "\n${BLUE}>>> Step 6: Forwarder Status${NC}\n"

echo "Last 10 lines of forwarder logs:"
docker logs audit-forwarder --tail 10 2>&1

# Step 7: Display URLs
echo -e "\n${GREEN}✅ SUCCESS! System is running!${NC}\n"

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}📊 Access Points${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${YELLOW}Dashboard:${NC}        http://localhost:8503"
echo -e "  ${YELLOW}Metrics:${NC}          http://localhost:8003/metrics"
echo -e "  ${YELLOW}Grafana:${NC}          http://localhost:3000 (if configured)"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Step 8: Wait for dashboard to be ready
echo -e "\n${BLUE}>>> Waiting for dashboard to be ready...${NC}"

MAX_WAIT=30
COUNTER=0
while [ $COUNTER -lt $MAX_WAIT ]; do
    if curl -s http://localhost:8503 > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Dashboard is ready!"
        break
    fi
    echo -n "."
    sleep 1
    COUNTER=$((COUNTER + 1))
done

if [ $COUNTER -eq $MAX_WAIT ]; then
    echo -e "\n${YELLOW}⚠${NC} Dashboard is taking longer than expected to start"
    echo "Check dashboard logs: docker logs dashboard"
fi

# Step 9: Open dashboard automatically
echo -e "\n${BLUE}>>> Opening Dashboard in Browser...${NC}\n"

# macOS
open http://localhost:8503 2>/dev/null || echo "Dashboard ready at: http://localhost:8503"

# Step 10: Helpful tips
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}💡 Helpful Commands${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${YELLOW}View forwarder logs:${NC}    docker logs -f audit-forwarder"
echo -e "  ${YELLOW}View dashboard logs:${NC}    docker logs -f dashboard"
echo -e "  ${YELLOW}Stop system:${NC}            docker compose down"
echo -e "  ${YELLOW}Restart system:${NC}         ./start.sh"
echo -e "  ${YELLOW}Check status:${NC}           docker compose ps"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Step 11: System info
echo -e "\n${BLUE}>>> System Information${NC}\n"

echo -e "  ${YELLOW}Version:${NC}              8.0 (Kafka Direct)"
echo -e "  ${YELLOW}Mode:${NC}                 Development"
echo -e "  ${YELLOW}Audit Cluster:${NC}        lkc-qzk87 (us-west-2)"
echo -e "  ${YELLOW}Destination Cluster:${NC}  lkc-3q9omo (ap-south-1)"
echo -e "  ${YELLOW}Monthly Cost:${NC}         ~$770"
echo -e "  ${YELLOW}Savings vs Flink:${NC}     $401/month"
echo ""

# Step 12: First-time tips
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}🎯 What to Do Next${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  1. ${GREEN}Dashboard should auto-open${NC} at http://localhost:8503"
echo -e "  2. ${GREEN}Wait 1-2 minutes${NC} for first audit events to appear"
echo -e "  3. ${GREEN}Generate test events:${NC} Create/delete a topic in Confluent Cloud"
echo -e "  4. ${GREEN}Watch live events${NC} flow into the dashboard!"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "\n${GREEN}🚀 System is ready! Happy auditing!${NC}\n"

exit 0
