#!/bin/bash
# ============================================================================
# Confluent Cloud Audit Log Analyzer - Deploy Script
# ============================================================================
# This script delegates to setup.sh for the proper two-cluster flow.
#
# ARCHITECTURE:
#   - Audit Log Cluster (Source): Managed by Confluent, READ-ONLY
#   - Customer Cluster (Destination): Your cluster where output is written
#
# ============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "=============================================="
echo "  Confluent Cloud Audit Log Analyzer"
echo "=============================================="
echo -e "${NC}"
echo ""
echo "This tool deploys a Flink-based audit log analyzer that:"
echo "  1. Reads from the Confluent-managed audit log cluster"
echo "  2. Flattens the nested JSON schema"
echo "  3. Creates pre-computed aggregation tables"
echo "  4. Writes to YOUR cluster for querying"
echo ""

# Check if setup.sh exists
if [ -f "setup.sh" ]; then
    echo -e "${YELLOW}Starting setup wizard...${NC}"
    echo ""
    exec ./setup.sh
else
    echo -e "${RED}ERROR: setup.sh not found${NC}"
    echo "Please ensure you're running from the audit-forwarder directory."
    exit 1
fi
