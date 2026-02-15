#!/bin/bash
set -e

##############################################################################
# Security Scanning Script using Trivy
#
# This script runs comprehensive security scans on Docker images,
# filesystem, and Kubernetes manifests using Trivy scanner.
#
# Prerequisites:
# - Trivy installed (brew install trivy)
# - Docker running (for image scans)
#
# Usage:
#   ./scripts/security-scan.sh [image|fs|k8s|all]
##############################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="${IMAGE_NAME:-audit-forwarder:2.1.0}"
TRIVY_CONFIG="trivy.yaml"
REPORTS_DIR="security-reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Function to print status
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
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check if Trivy is installed
if ! command -v trivy >/dev/null 2>&1; then
    print_error "Trivy not installed. Install with: brew install trivy"
    exit 1
fi

print_status "Trivy installed: $(trivy version | head -1)"

# Create reports directory
mkdir -p ${REPORTS_DIR}

# Update vulnerability database
print_info "Updating Trivy vulnerability database..."
trivy image --download-db-only
print_status "Database updated"

# Function to scan Docker image
scan_image() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Scanning Docker Image${NC}"
    echo -e "${BLUE}========================================${NC}"

    local image=$1
    local report="${REPORTS_DIR}/image-scan-${TIMESTAMP}.txt"
    local json_report="${REPORTS_DIR}/image-scan-${TIMESTAMP}.json"
    local sarif_report="${REPORTS_DIR}/image-scan-${TIMESTAMP}.sarif"

    print_info "Image: ${image}"

    # Table format for console
    trivy image \
        --config ${TRIVY_CONFIG} \
        --severity CRITICAL,HIGH,MEDIUM \
        --format table \
        --output ${report} \
        ${image}

    # JSON format for automation
    trivy image \
        --config ${TRIVY_CONFIG} \
        --severity CRITICAL,HIGH,MEDIUM,LOW \
        --format json \
        --output ${json_report} \
        ${image}

    # SARIF format for GitHub integration
    trivy image \
        --config ${TRIVY_CONFIG} \
        --severity CRITICAL,HIGH,MEDIUM \
        --format sarif \
        --output ${sarif_report} \
        ${image}

    print_status "Image scan complete"
    print_info "Reports saved to: ${REPORTS_DIR}/"

    # Display summary
    echo ""
    cat ${report}
}

# Function to scan filesystem
scan_filesystem() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Scanning Filesystem${NC}"
    echo -e "${BLUE}========================================${NC}"

    local report="${REPORTS_DIR}/fs-scan-${TIMESTAMP}.txt"
    local json_report="${REPORTS_DIR}/fs-scan-${TIMESTAMP}.json"

    print_info "Scanning current directory for vulnerabilities..."

    # Scan for vulnerabilities in dependencies
    trivy fs \
        --config ${TRIVY_CONFIG} \
        --severity CRITICAL,HIGH,MEDIUM \
        --format table \
        --output ${report} \
        .

    # JSON format
    trivy fs \
        --config ${TRIVY_CONFIG} \
        --severity CRITICAL,HIGH,MEDIUM,LOW \
        --format json \
        --output ${json_report} \
        .

    print_status "Filesystem scan complete"
    print_info "Reports saved to: ${REPORTS_DIR}/"

    # Display summary
    echo ""
    cat ${report}
}

# Function to scan Kubernetes manifests
scan_kubernetes() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Scanning Kubernetes Manifests${NC}"
    echo -e "${BLUE}========================================${NC}"

    local report="${REPORTS_DIR}/k8s-scan-${TIMESTAMP}.txt"
    local json_report="${REPORTS_DIR}/k8s-scan-${TIMESTAMP}.json"

    print_info "Scanning Kubernetes manifests for misconfigurations..."

    # Scan deployment manifest
    trivy config \
        --severity CRITICAL,HIGH,MEDIUM \
        --format table \
        --output ${report} \
        deploy/kubernetes/

    # JSON format
    trivy config \
        --severity CRITICAL,HIGH,MEDIUM,LOW \
        --format json \
        --output ${json_report} \
        deploy/kubernetes/

    print_status "Kubernetes scan complete"
    print_info "Reports saved to: ${REPORTS_DIR}/"

    # Display summary
    echo ""
    cat ${report}
}

# Function to scan for secrets
scan_secrets() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Scanning for Exposed Secrets${NC}"
    echo -e "${BLUE}========================================${NC}"

    local report="${REPORTS_DIR}/secrets-scan-${TIMESTAMP}.txt"

    print_info "Scanning for hardcoded secrets..."

    trivy fs \
        --scanners secret \
        --format table \
        --output ${report} \
        .

    print_status "Secret scan complete"
    print_info "Report saved to: ${report}"

    # Display summary
    echo ""
    cat ${report}
}

# Main execution
SCAN_TYPE="${1:-all}"

case ${SCAN_TYPE} in
    image)
        scan_image ${IMAGE_NAME}
        ;;
    fs|filesystem)
        scan_filesystem
        ;;
    k8s|kubernetes)
        scan_kubernetes
        ;;
    secrets)
        scan_secrets
        ;;
    all)
        scan_image ${IMAGE_NAME}
        scan_filesystem
        scan_kubernetes
        scan_secrets
        ;;
    *)
        print_error "Invalid scan type: ${SCAN_TYPE}"
        echo "Usage: $0 [image|fs|k8s|secrets|all]"
        exit 1
        ;;
esac

# Final summary
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Security Scan Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
print_info "All reports saved to: ${REPORTS_DIR}/"
echo ""
echo "Next steps:"
echo "1. Review scan results in ${REPORTS_DIR}/"
echo "2. Fix CRITICAL and HIGH severity issues"
echo "3. Document accepted risks in .trivyignore"
echo "4. Re-run scan to verify fixes"
echo ""
