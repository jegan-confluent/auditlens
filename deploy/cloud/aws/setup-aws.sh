#!/bin/bash
set -e

##############################################################################
# AWS EKS Deployment Script for Audit Forwarder
#
# This script automates the complete deployment to AWS:
# - Creates EKS cluster
# - Sets up ECR repository
# - Builds and pushes Docker image
# - Deploys application to Kubernetes
# - Configures monitoring
#
# Prerequisites:
# - AWS CLI installed and configured
# - kubectl installed
# - eksctl installed
# - Docker installed
# - helm installed
#
# Usage:
#   ./setup-aws.sh
##############################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
CLUSTER_NAME="audit-forwarder-cluster"
REGION="us-west-2"
NODE_TYPE="t3.medium"
NODE_COUNT=3
ECR_REPO_NAME="audit-forwarder"
NAMESPACE="audit-forwarder"
IMAGE_TAG="2.0.0"

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}AWS EKS Audit Forwarder Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Cluster: ${CLUSTER_NAME}"
echo "Region: ${REGION}"
echo "AWS Account: ${AWS_ACCOUNT_ID}"
echo ""

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

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

command -v aws >/dev/null 2>&1 || { print_error "AWS CLI not installed. Install: brew install awscli"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { print_error "kubectl not installed. Install: brew install kubectl"; exit 1; }
command -v eksctl >/dev/null 2>&1 || { print_error "eksctl not installed. Install: brew install eksctl"; exit 1; }
command -v docker >/dev/null 2>&1 || { print_error "Docker not installed. Install: brew install --cask docker"; exit 1; }
command -v helm >/dev/null 2>&1 || { print_error "Helm not installed. Install: brew install helm"; exit 1; }

print_status "All prerequisites installed"

# Check AWS credentials
aws sts get-caller-identity >/dev/null 2>&1 || { print_error "AWS credentials not configured. Run: aws configure"; exit 1; }
print_status "AWS credentials configured"

# Prompt for Confluent Cloud credentials
echo ""
echo -e "${YELLOW}Enter Confluent Cloud Configuration:${NC}"
read -p "Audit Cluster Bootstrap (e.g., pkc-xxxxx.us-west-2.aws.confluent.cloud:9092): " AUDIT_BOOTSTRAP
read -p "Destination Cluster Bootstrap (e.g., pkc-yyyyy.us-west-2.aws.confluent.cloud:9092): " DEST_BOOTSTRAP
read -sp "Audit API Key: " AUDIT_API_KEY
echo ""
read -sp "Audit API Secret: " AUDIT_API_SECRET
echo ""
read -sp "Destination API Key: " DEST_API_KEY
echo ""
read -sp "Destination API Secret: " DEST_API_SECRET
echo ""
read -sp "Schema Registry Key: " SCHEMA_REGISTRY_KEY
echo ""
read -sp "Schema Registry Secret: " SCHEMA_REGISTRY_SECRET
echo ""
read -p "Schema Registry URL: " SCHEMA_REGISTRY_URL
echo ""

# Step 1: Create ECR repository
echo ""
echo -e "${YELLOW}Step 1: Creating ECR repository...${NC}"
if aws ecr describe-repositories --repository-names ${ECR_REPO_NAME} --region ${REGION} >/dev/null 2>&1; then
    print_status "ECR repository already exists"
else
    aws ecr create-repository \
        --repository-name ${ECR_REPO_NAME} \
        --region ${REGION} \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256
    print_status "ECR repository created"
fi

# Step 2: Build and push Docker image
echo ""
echo -e "${YELLOW}Step 2: Building and pushing Docker image...${NC}"

# Login to ECR
aws ecr get-login-password --region ${REGION} | \
    docker login --username AWS --password-stdin ${ECR_REGISTRY}
print_status "Logged in to ECR"

# Navigate to project root
cd "$(dirname "$0")/../../.."

# Build image
docker build -t ${ECR_REPO_NAME}:${IMAGE_TAG} .
print_status "Docker image built"

# Tag and push
docker tag ${ECR_REPO_NAME}:${IMAGE_TAG} ${ECR_REGISTRY}/${ECR_REPO_NAME}:${IMAGE_TAG}
docker push ${ECR_REGISTRY}/${ECR_REPO_NAME}:${IMAGE_TAG}
print_status "Docker image pushed to ECR"

# Step 3: Check if EKS cluster exists
echo ""
echo -e "${YELLOW}Step 3: Checking EKS cluster...${NC}"
if eksctl get cluster --name ${CLUSTER_NAME} --region ${REGION} >/dev/null 2>&1; then
    print_status "EKS cluster already exists"
    CLUSTER_EXISTS=true
else
    print_warning "EKS cluster does not exist"
    read -p "Create new EKS cluster? This will take ~20 minutes (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Creating EKS cluster (this will take ~20 minutes)...${NC}"
        eksctl create cluster \
            --name ${CLUSTER_NAME} \
            --region ${REGION} \
            --nodegroup-name audit-nodes \
            --node-type ${NODE_TYPE} \
            --nodes ${NODE_COUNT} \
            --nodes-min 2 \
            --nodes-max 4 \
            --managed \
            --version 1.28
        print_status "EKS cluster created"
        CLUSTER_EXISTS=true
    else
        print_error "Cannot proceed without cluster. Exiting."
        exit 1
    fi
fi

# Step 4: Configure kubectl
echo ""
echo -e "${YELLOW}Step 4: Configuring kubectl...${NC}"
aws eks update-kubeconfig --region ${REGION} --name ${CLUSTER_NAME}
print_status "kubectl configured"

# Verify connection
kubectl cluster-info >/dev/null 2>&1 || { print_error "Cannot connect to cluster"; exit 1; }
print_status "Connected to cluster"

# Step 5: Install EBS CSI driver
echo ""
echo -e "${YELLOW}Step 5: Installing EBS CSI driver...${NC}"

# Create IAM OIDC provider if not exists
if ! eksctl utils describe-iam-oidc-provider --cluster ${CLUSTER_NAME} --region ${REGION} >/dev/null 2>&1; then
    eksctl utils associate-iam-oidc-provider \
        --region ${REGION} \
        --cluster ${CLUSTER_NAME} \
        --approve
    print_status "IAM OIDC provider created"
else
    print_status "IAM OIDC provider already exists"
fi

# Install EBS CSI driver
if ! kubectl get pods -n kube-system | grep -q ebs-csi-controller; then
    kubectl apply -k "github.com/kubernetes-sigs/aws-ebs-csi-driver/deploy/kubernetes/overlays/stable/?ref=release-1.25"
    print_status "EBS CSI driver installed"
else
    print_status "EBS CSI driver already installed"
fi

# Step 6: Create namespace
echo ""
echo -e "${YELLOW}Step 6: Creating Kubernetes namespace...${NC}"
kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -
print_status "Namespace created"

# Step 7: Create secrets
echo ""
echo -e "${YELLOW}Step 7: Creating Kubernetes secrets...${NC}"
kubectl create secret generic audit-forwarder-secrets \
    --from-literal=AUDIT_API_KEY="${AUDIT_API_KEY}" \
    --from-literal=AUDIT_API_SECRET="${AUDIT_API_SECRET}" \
    --from-literal=DEST_API_KEY="${DEST_API_KEY}" \
    --from-literal=DEST_API_SECRET="${DEST_API_SECRET}" \
    --from-literal=SCHEMA_REGISTRY_KEY="${SCHEMA_REGISTRY_KEY}" \
    --from-literal=SCHEMA_REGISTRY_SECRET="${SCHEMA_REGISTRY_SECRET}" \
    --namespace ${NAMESPACE} \
    --dry-run=client -o yaml | kubectl apply -f -
print_status "Secrets created"

# Step 8: Create ConfigMap
echo ""
echo -e "${YELLOW}Step 8: Creating ConfigMap...${NC}"
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: audit-forwarder-config
  namespace: ${NAMESPACE}
data:
  AUDIT_BOOTSTRAP: "${AUDIT_BOOTSTRAP}"
  AUDIT_TOPIC: "confluent-audit-log-events"
  DEST_BOOTSTRAP: "${DEST_BOOTSTRAP}"
  DEST_TOPIC: "jegan_auditlog"
  SCHEMA_REGISTRY_URL: "${SCHEMA_REGISTRY_URL}"
  SCHEMA_SUBJECT_NAME: "jegan_auditlog-value"
  CONSUMER_GROUP_ID: "audit-forwarder-group"
  OFFSET_FILE: "/app/data/offsets.json"
  ENABLE_MULTI_TOPIC_ROUTING: "false"
  DROP_LOW_EVENTS: "false"
  METRICS_PORT: "8000"
  LOG_LEVEL: "INFO"
EOF
print_status "ConfigMap created"

# Step 9: Update and deploy Kubernetes manifests
echo ""
echo -e "${YELLOW}Step 9: Deploying application...${NC}"

# Create temporary deployment file with updated image
cat deploy/kubernetes/deployment.yaml | \
    sed "s|image:.*|image: ${ECR_REGISTRY}/${ECR_REPO_NAME}:${IMAGE_TAG}|" | \
    sed "s|storageClassName:.*|storageClassName: gp3|" | \
    kubectl apply -f -

print_status "Application deployed"

# Step 10: Create service
echo ""
echo -e "${YELLOW}Step 10: Creating service...${NC}"
kubectl apply -f deploy/kubernetes/service.yaml
print_status "Service created"

# Step 11: Install AWS Load Balancer Controller (optional)
echo ""
read -p "Install AWS Load Balancer Controller for external access? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Installing AWS Load Balancer Controller...${NC}"

    # Add helm repo
    helm repo add eks https://aws.github.io/eks-charts
    helm repo update

    # Install controller
    helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
        -n kube-system \
        --set clusterName=${CLUSTER_NAME} \
        --set serviceAccount.create=true

    print_status "AWS Load Balancer Controller installed"
fi

# Step 12: Verify deployment
echo ""
echo -e "${YELLOW}Step 12: Verifying deployment...${NC}"
sleep 10

# Wait for pods to be ready
echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=audit-forwarder \
    -n ${NAMESPACE} \
    --timeout=300s

print_status "All pods are ready"

# Get pod status
kubectl get pods -n ${NAMESPACE}

# Show logs from one pod
echo ""
echo -e "${YELLOW}Recent logs from forwarder:${NC}"
kubectl logs -n ${NAMESPACE} -l app.kubernetes.io/name=audit-forwarder --tail=20

# Step 13: Setup monitoring (optional)
echo ""
read -p "Install Prometheus & Grafana for monitoring? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Installing Prometheus & Grafana...${NC}"

    # Add helm repos
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update

    # Install Prometheus
    helm upgrade --install prometheus prometheus-community/prometheus \
        -n monitoring --create-namespace \
        --set server.persistentVolume.storageClass=gp3

    # Install Grafana
    helm upgrade --install grafana grafana/grafana \
        -n monitoring \
        --set persistence.enabled=true \
        --set persistence.storageClassName=gp3 \
        --set adminPassword=admin123

    print_status "Monitoring stack installed"

    echo ""
    echo "Get Grafana password:"
    echo "  kubectl get secret -n monitoring grafana -o jsonpath='{.data.admin-password}' | base64 --decode"
    echo ""
    echo "Access Grafana:"
    echo "  kubectl port-forward -n monitoring svc/grafana 3000:80"
fi

# Final summary
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Cluster: ${CLUSTER_NAME}"
echo "Region: ${REGION}"
echo "Namespace: ${NAMESPACE}"
echo "ECR Image: ${ECR_REGISTRY}/${ECR_REPO_NAME}:${IMAGE_TAG}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Check pod status:"
echo "   kubectl get pods -n ${NAMESPACE}"
echo ""
echo "2. View logs:"
echo "   kubectl logs -f -n ${NAMESPACE} -l app.kubernetes.io/name=audit-forwarder"
echo ""
echo "3. Access metrics:"
echo "   kubectl port-forward -n ${NAMESPACE} svc/audit-forwarder 8000:8000"
echo "   curl http://localhost:8000/metrics"
echo ""
echo "4. Check consumer lag:"
echo "   confluent kafka consumer group describe audit-forwarder-group --cluster <cluster-id>"
echo ""
echo "5. Cleanup (when done):"
echo "   eksctl delete cluster --name ${CLUSTER_NAME} --region ${REGION}"
echo ""
echo -e "${GREEN}Happy monitoring!${NC}"
