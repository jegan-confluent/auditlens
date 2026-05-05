#!/bin/bash
set -e

##############################################################################
# Audit Forwarder - Automated Testing Script
#
# This script automates testing steps 1-6:
# 1. Verify prerequisites
# 2. Build new secure image
# 3. Run security scan
# 4. Test forwarder in dry run mode
# 5. Test metrics endpoint
# 6. Test with full Docker Compose stack
#
# Usage:
#   ./scripts/test-setup.sh
##############################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="audit-forwarder"
VERSION="2.1.0"
TEST_DURATION=60  # seconds to run dry-run test
METRICS_CHECK_DELAY=10  # seconds to wait before checking metrics

# Track test results
TESTS_PASSED=0
TESTS_FAILED=0
TOTAL_TESTS=0

# Function to print status
print_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_step() {
    echo ""
    echo -e "${CYAN}>>> $1${NC}"
}

print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${MAGENTA}ℹ${NC} $1"
}

# Function to record test result
record_test() {
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    if [ $1 -eq 0 ]; then
        print_status "$2"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        print_error "$2"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

# Function to cleanup on exit
cleanup() {
    echo ""
    print_info "Cleaning up test resources..."
    docker stop audit-forwarder-test 2>/dev/null || true
    docker rm audit-forwarder-test 2>/dev/null || true
}

trap cleanup EXIT

# Start script
clear
print_header "🧪 Audit Forwarder - Automated Testing"
echo -e "${CYAN}Version: ${VERSION}${NC}"
echo -e "${CYAN}Started: $(date)${NC}"
echo ""

##############################################################################
# STEP 1: Verify Prerequisites
##############################################################################
print_header "Step 1/6: Verify Prerequisites"

print_step "Checking Docker..."
if command -v docker >/dev/null 2>&1; then
    DOCKER_VERSION=$(docker --version | awk '{print $3}' | tr -d ',')
    record_test 0 "Docker installed: ${DOCKER_VERSION}"
else
    record_test 1 "Docker not installed"
    print_error "Please install Docker Desktop: https://www.docker.com/products/docker-desktop"
    exit 1
fi

print_step "Checking Docker Compose..."
# Check for integrated Docker Compose (docker compose) or standalone (docker-compose)
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || docker compose version | awk '{print $NF}')
    record_test 0 "Docker Compose installed: ${COMPOSE_VERSION}"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
    COMPOSE_VERSION=$(docker-compose --version | awk '{print $4}' | tr -d ',')
    record_test 0 "Docker Compose installed: ${COMPOSE_VERSION}"
else
    record_test 1 "Docker Compose not installed"
    exit 1
fi

print_step "Checking Python..."
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    record_test 0 "Python installed: ${PYTHON_VERSION}"
else
    record_test 1 "Python not installed"
    exit 1
fi

print_step "Checking Docker daemon..."
if docker ps >/dev/null 2>&1; then
    record_test 0 "Docker daemon running"
else
    record_test 1 "Docker daemon not running"
    print_error "Please start Docker Desktop"
    exit 1
fi

print_step "Checking environment files..."
if [ -f ".env" ]; then
    record_test 0 "Found .env file"
else
    record_test 1 ".env file missing"
    print_error "Please create .env file (see .env.example)"
    exit 1
fi

if [ -f ".secrets" ]; then
    record_test 0 "Found .secrets file"
else
    record_test 1 ".secrets file missing"
    print_error "Please create .secrets file with API keys"
    exit 1
fi

print_step "Checking working directory..."
EXPECTED_DIR="audit-forwarder"
CURRENT_DIR=$(basename $(pwd))
if [[ "$CURRENT_DIR" == "$EXPECTED_DIR" ]]; then
    record_test 0 "Working directory correct: $(pwd)"
else
    record_test 1 "Working directory incorrect"
    print_warning "Expected to be in audit-forwarder directory"
fi

print_step "Checking Trivy (optional)..."
if command -v trivy >/dev/null 2>&1; then
    TRIVY_VERSION=$(trivy --version | head -1 | awk '{print $2}')
    record_test 0 "Trivy installed: ${TRIVY_VERSION}"
    TRIVY_AVAILABLE=true
else
    print_warning "Trivy not installed - security scan will be skipped"
    print_info "Install with: brew install trivy"
    TRIVY_AVAILABLE=false
fi

##############################################################################
# STEP 2: Build the New Secure Image
##############################################################################
print_header "Step 2/6: Build New Secure Image"

print_step "Enabling BuildKit for faster builds..."
export DOCKER_BUILDKIT=1
print_status "BuildKit enabled"

print_step "Building ${IMAGE_NAME}:${VERSION}..."
BUILD_START=$(date +%s)

if docker build -t ${IMAGE_NAME}:${VERSION} -t ${IMAGE_NAME}:latest . > /tmp/docker-build.log 2>&1; then
    BUILD_END=$(date +%s)
    BUILD_TIME=$((BUILD_END - BUILD_START))
    record_test 0 "Image built successfully in ${BUILD_TIME}s"
else
    record_test 1 "Image build failed"
    print_error "Build logs:"
    cat /tmp/docker-build.log
    exit 1
fi

print_step "Verifying image..."
if docker images ${IMAGE_NAME}:${VERSION} --format "{{.Repository}}:{{.Tag}}" | grep -q "${IMAGE_NAME}:${VERSION}"; then
    IMAGE_SIZE=$(docker images ${IMAGE_NAME}:${VERSION} --format "{{.Size}}")
    record_test 0 "Image verified: ${IMAGE_SIZE}"
else
    record_test 1 "Image verification failed"
    exit 1
fi

##############################################################################
# STEP 3: Run Security Scan
##############################################################################
print_header "Step 3/6: Run Security Scan"

if [ "$TRIVY_AVAILABLE" = true ]; then
    print_step "Updating Trivy database..."
    trivy image --download-db-only > /dev/null 2>&1
    print_status "Database updated"

    print_step "Scanning ${IMAGE_NAME}:${VERSION} for vulnerabilities..."
    mkdir -p security-reports
    SCAN_FILE="security-reports/test-scan-$(date +%Y%m%d_%H%M%S).txt"

    if trivy image --severity CRITICAL,HIGH,MEDIUM --format table --output ${SCAN_FILE} ${IMAGE_NAME}:${VERSION}; then
        # Count vulnerabilities
        CRITICAL=$(grep -c "CRITICAL" ${SCAN_FILE} || echo "0")
        HIGH=$(grep -c "HIGH" ${SCAN_FILE} || echo "0")
        MEDIUM=$(grep -c "MEDIUM" ${SCAN_FILE} || echo "0")

        print_info "Vulnerabilities found:"
        echo "  🔴 CRITICAL: ${CRITICAL}"
        echo "  🟠 HIGH: ${HIGH}"
        echo "  🟡 MEDIUM: ${MEDIUM}"

        if [ "$CRITICAL" -eq 0 ] && [ "$HIGH" -eq 0 ]; then
            record_test 0 "No critical or high vulnerabilities found"
        else
            record_test 1 "Found ${CRITICAL} critical and ${HIGH} high vulnerabilities"
            print_warning "Review scan report: ${SCAN_FILE}"
        fi
    else
        record_test 1 "Security scan failed"
    fi
else
    print_warning "Skipping security scan (Trivy not installed)"
fi

##############################################################################
# STEP 4: Test Forwarder in Dry Run Mode
##############################################################################
print_header "Step 4/6: Test Forwarder (Dry Run Mode)"

print_step "Stopping any existing containers and compose services..."
# Stop any running compose services to free up port 8003
${COMPOSE_CMD} down > /dev/null 2>&1 || true
# Stop any standalone test containers
docker stop audit-forwarder-test 2>/dev/null || true
docker rm audit-forwarder-test 2>/dev/null || true
print_status "Cleaned up existing containers"

print_step "Starting forwarder in dry run mode..."
print_info "Container will run for ${TEST_DURATION} seconds..."

# Start container in background
docker run -d \
    --name audit-forwarder-test \
    --env-file .env \
    --env-file .secrets \
    -e AUDIT_ROUTER_DRY_RUN=true \
    -e DROP_LOW_EVENTS=true \
    -e METRICS_PORT=8003 \
    -p 8003:8003 \
    -v $(pwd)/data:/app/data \
    ${IMAGE_NAME}:${VERSION} > /dev/null 2>&1

if [ $? -eq 0 ]; then
    record_test 0 "Container started successfully"
else
    record_test 1 "Failed to start container"
    docker logs audit-forwarder-test
    exit 1
fi

print_step "Waiting for startup (10 seconds)..."
sleep 10

print_step "Checking container status..."
if docker ps | grep -q audit-forwarder-test; then
    record_test 0 "Container is running"
else
    record_test 1 "Container exited unexpectedly"
    print_error "Container logs:"
    docker logs audit-forwarder-test
    exit 1
fi

print_step "Checking logs for errors..."
LOGS=$(docker logs audit-forwarder-test 2>&1)
if echo "$LOGS" | grep -E "\bERROR\b|\bEXCEPTION\b|Traceback|Failed to|failed to start"; then
    record_test 1 "Found errors in logs"
    print_error "Recent logs:"
    docker logs --tail 20 audit-forwarder-test
else
    record_test 0 "No errors in startup logs"
fi

print_step "Checking for expected log patterns..."
if echo "$LOGS" | grep -q "Starting Confluent Audit Log"; then
    record_test 0 "Forwarder started successfully"
else
    record_test 1 "Missing startup message"
fi

if echo "$LOGS" | grep -q "Metrics server started"; then
    record_test 0 "Metrics server started"
else
    record_test 1 "Metrics server not running"
fi

if echo "$LOGS" | grep -q "Connected to source"; then
    record_test 0 "Consumer connected to Kafka"
else
    record_test 1 "Consumer not connected"
    print_warning "Check Kafka connection settings in .env"
fi

print_step "Letting forwarder process events for ${TEST_DURATION}s..."
for i in $(seq 1 $TEST_DURATION); do
    printf "\r  Processing events... %02ds/%02ds" $i $TEST_DURATION
    sleep 1
done
printf "\n"

print_step "Checking for runtime errors..."
RUNTIME_LOGS=$(docker logs audit-forwarder-test 2>&1 | tail -50)
if echo "$RUNTIME_LOGS" | grep -E "\bERROR\b|\bEXCEPTION\b|Traceback|Failed to|failed to start"; then
    record_test 1 "Runtime errors detected"
    print_error "Recent logs:"
    echo "$RUNTIME_LOGS"
else
    record_test 0 "No runtime errors detected"
fi

##############################################################################
# STEP 5: Test Metrics Endpoint
##############################################################################
print_header "Step 5/6: Test Metrics Endpoint"

print_step "Waiting for metrics to be available (${METRICS_CHECK_DELAY}s)..."
sleep ${METRICS_CHECK_DELAY}

print_step "Testing health endpoint..."
HEALTH_RESPONSE=$(curl -s http://localhost:8003/health || echo "")
if [ -n "$HEALTH_RESPONSE" ]; then
    if echo "$HEALTH_RESPONSE" | grep -q "status"; then
        record_test 0 "Health endpoint responding"
        print_info "Response: ${HEALTH_RESPONSE}"
    else
        record_test 1 "Health endpoint returned unexpected response"
    fi
else
    record_test 1 "Health endpoint not accessible"
    print_error "Cannot reach http://localhost:8003/health"
fi

print_step "Testing metrics endpoint..."
METRICS_RESPONSE=$(curl -s http://localhost:8003/metrics || echo "")
if [ -n "$METRICS_RESPONSE" ]; then
    if echo "$METRICS_RESPONSE" | grep -q "audit_forwarder_processed_messages_total"; then
        record_test 0 "Metrics endpoint responding"

        # Extract key metrics
        print_info "Key metrics:"
        echo "$METRICS_RESPONSE" | grep "audit_forwarder_processed_messages_total" | head -5
        echo "$METRICS_RESPONSE" | grep "audit_forwarder_processing_rate" | head -3
    else
        record_test 1 "Metrics endpoint has no audit metrics"
    fi
else
    record_test 1 "Metrics endpoint not accessible"
fi

print_step "Checking Prometheus format..."
if echo "$METRICS_RESPONSE" | grep -q "^# HELP\|^# TYPE"; then
    record_test 0 "Metrics in valid Prometheus format"
else
    record_test 1 "Invalid Prometheus format"
fi

print_step "Stopping dry-run container..."
docker stop audit-forwarder-test > /dev/null 2>&1
docker rm audit-forwarder-test > /dev/null 2>&1
print_status "Container stopped and removed"

##############################################################################
# STEP 6: Test with Full Docker Compose Stack
##############################################################################
print_header "Step 6/6: Test Full Docker Compose Stack"

print_step "Stopping any running compose services..."
${COMPOSE_CMD} down > /dev/null 2>&1
print_status "Existing services stopped"

print_step "Starting full monitoring stack..."
if ${COMPOSE_CMD} up -d > /tmp/compose-up.log 2>&1; then
    record_test 0 "Docker Compose services started"
else
    record_test 1 "Failed to start Docker Compose services"
    cat /tmp/compose-up.log
    exit 1
fi

print_step "Waiting for services to initialize (30 seconds)..."
for i in $(seq 1 30); do
    printf "\r  Initializing services... %02ds/30s" $i
    sleep 1
done
printf "\n"

print_step "Checking service status..."
COMPOSE_PS=$(${COMPOSE_CMD} ps)
echo "$COMPOSE_PS"

# Check each service
SERVICES=("audit-forwarder" "prometheus" "grafana" "loki" "promtail")
for service in "${SERVICES[@]}"; do
    if echo "$COMPOSE_PS" | grep "$service" | grep -q "Up"; then
        record_test 0 "${service} is running"
    else
        record_test 1 "${service} is not running"
    fi
done

print_step "Checking service health..."
# Check audit-forwarder
if curl -s http://localhost:8003/health > /dev/null 2>&1; then
    record_test 0 "Audit forwarder health check passed"
else
    record_test 1 "Audit forwarder health check failed"
fi

# Check Prometheus
if curl -s http://localhost:9090/-/healthy > /dev/null 2>&1; then
    record_test 0 "Prometheus health check passed"
else
    record_test 1 "Prometheus health check failed"
fi

# Check Grafana
if curl -s http://localhost:3000/api/health > /dev/null 2>&1; then
    record_test 0 "Grafana health check passed"
else
    record_test 1 "Grafana health check failed"
fi

# Check Loki
if curl -s http://localhost:3100/ready > /dev/null 2>&1; then
    record_test 0 "Loki health check passed"
else
    record_test 1 "Loki health check failed"
fi

print_step "Checking Prometheus targets..."
sleep 5  # Give Prometheus time to scrape
TARGETS=$(curl -s http://localhost:9090/api/v1/targets | grep -o '"health":"[^"]*"' | head -1)
if echo "$TARGETS" | grep -q "up"; then
    record_test 0 "Prometheus scraping targets"
else
    record_test 1 "Prometheus not scraping targets"
fi

print_step "Checking forwarder logs for errors..."
COMPOSE_LOGS=$(${COMPOSE_CMD} logs audit-forwarder 2>&1 | tail -50)
if echo "$COMPOSE_LOGS" | grep -E "\bERROR\b|\bEXCEPTION\b|Traceback|Failed to|failed to start"; then
    record_test 1 "Errors found in compose logs"
    print_warning "Recent logs:"
    ${COMPOSE_CMD} logs --tail 20 audit-forwarder
else
    record_test 0 "No errors in compose logs"
fi

##############################################################################
# Final Summary
##############################################################################
print_header "📊 Test Results Summary"

echo ""
echo -e "${CYAN}Total Tests: ${TOTAL_TESTS}${NC}"
echo -e "${GREEN}✓ Passed: ${TESTS_PASSED}${NC}"
echo -e "${RED}✗ Failed: ${TESTS_FAILED}${NC}"
echo ""

# Calculate success rate
if [ $TOTAL_TESTS -gt 0 ]; then
    SUCCESS_RATE=$((TESTS_PASSED * 100 / TOTAL_TESTS))
    echo -e "${CYAN}Success Rate: ${SUCCESS_RATE}%${NC}"
fi

echo ""
print_header "🎯 What's Running Now"
echo ""
echo -e "${CYAN}Services:${NC}"
echo "  • Audit Forwarder:  http://localhost:8003/metrics"
echo "  • Prometheus:       http://localhost:9090"
echo "  • Grafana:          http://localhost:3000 (admin/changeme)"
echo "  • Loki:             http://localhost:3100"
echo ""
echo -e "${CYAN}Useful Commands:${NC}"
echo "  • View logs:        ${COMPOSE_CMD} logs -f audit-forwarder"
echo "  • Stop services:    ${COMPOSE_CMD} down"
echo "  • Restart:          ${COMPOSE_CMD} restart audit-forwarder"
echo "  • Check status:     ${COMPOSE_CMD} ps"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    print_header "✅ All Tests Passed!"
    echo ""
    echo -e "${GREEN}The audit forwarder is ready for team testing!${NC}"
    echo ""
    echo -e "${CYAN}Next Steps:${NC}"
    echo "  1. Open Grafana (http://localhost:3000)"
    echo "  2. Monitor metrics for 30 minutes"
    echo "  3. Share testing guide with team"
    echo "  4. Collect feedback"
    echo ""
    exit 0
else
    print_header "⚠️  Some Tests Failed"
    echo ""
    echo -e "${YELLOW}Please review the failures above and fix before proceeding.${NC}"
    echo ""
    echo -e "${CYAN}Troubleshooting:${NC}"
    echo "  • Check logs:       ${COMPOSE_CMD} logs audit-forwarder"
    echo "  • Verify .env:      cat .env | grep -v SECRET"
    echo "  • Check Kafka:      Test connection to Confluent Cloud"
    echo "  • Review docs:      docs/2025-12-06/troubleshooting/"
    echo ""
    exit 1
fi
