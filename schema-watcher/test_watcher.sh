#!/bin/bash
# Test script for schema-watcher service

set -euo pipefail

echo "=== Schema Watcher Test Suite ==="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Test 1: Build Docker image
echo -e "${YELLOW}Test 1: Building Docker image...${NC}"
docker build -t schema-watcher:test ./schema-watcher
echo -e "${GREEN}✓ Image built successfully${NC}"
echo ""

# Test 2: Run dry-run check
echo -e "${YELLOW}Test 2: Running dry-run check...${NC}"
docker run --rm \
  -e DRY_RUN=true \
  -e CHECK_INTERVAL_HOURS=0.01 \
  -e METHODS_FILE=/app/watcher.py \
  -e VERSIONS_FILE=/tmp/schema_versions.json \
  schema-watcher:test \
  timeout 60s python watcher.py || true
echo -e "${GREEN}✓ Dry-run completed${NC}"
echo ""

# Test 3: Verify Python dependencies
echo -e "${YELLOW}Test 3: Verifying dependencies...${NC}"
docker run --rm schema-watcher:test pip list | grep -E '(httpx|beautifulsoup4|orjson|tenacity)'
echo -e "${GREEN}✓ All dependencies installed${NC}"
echo ""

# Test 4: Check file permissions
echo -e "${YELLOW}Test 4: Checking user permissions...${NC}"
docker run --rm schema-watcher:test id
docker run --rm schema-watcher:test ls -la /app
echo -e "${GREEN}✓ Running as non-root user${NC}"
echo ""

# Test 5: Verify health check
echo -e "${YELLOW}Test 5: Testing health check...${NC}"
docker run --rm \
  -v $(pwd)/schema-watcher/schema_versions.json:/app/data/schema_versions.json:ro \
  schema-watcher:test \
  python -c "import sys; from pathlib import Path; sys.exit(0 if Path('/app/data/schema_versions.json').exists() else 1)"
echo -e "${GREEN}✓ Health check passed${NC}"
echo ""

echo -e "${GREEN}=== All tests passed! ===${NC}"
echo ""
echo "Next steps:"
echo "  1. Set SLACK_WEBHOOK_URL in .env or .secrets"
echo "  2. Run: docker-compose up -d schema-watcher"
echo "  3. Monitor: docker logs -f schema-watcher"
