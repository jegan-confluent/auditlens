#!/bin/bash
set -e

##############################################################################
# Azure AKS Deployment Script for Audit Forwarder
#
# This script automates the complete deployment to Azure:
# - Creates AKS cluster
# - Sets up ACR repository
# - Builds and pushes Docker image
# - Deploys application to Kubernetes
# - Configures monitoring
#
# Prerequisites:
# - Azure CLI (az) installed and configured
# - kubectl installed
# - Docker installed
# - helm installed
#
# Usage:
#   ./setup-azure.sh
##############################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
RESOURCE_GROUP="audit-forwarder-rg"
CLUSTER_NAME="audit-forwarder-cluster"
LOCATION="westus2"
NODE_SIZE="Standard_D2s_v3"
NODE_COUNT=3
ACR_NAME="auditforwarderacr"
IMAGE_NAME="audit-forwarder"
IMAGE_TAG="2.0.0"
NAMESPACE="audit-forwarder"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Azure AKS Audit Forwarder Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Resource Group: ${RESOURCE_GROUP}"
echo "Cluster: ${CLUSTER_NAME}"
echo "Location: ${LOCATION}"
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

command -v az >/dev/null 2>&1 || { print_error "Azure CLI not installed. Install: brew install azure-cli"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { print_error "kubectl not installed. Install: brew install kubectl"; exit 1; }
command -v docker >/dev/null 2>&1 || { print_error "Docker not installed. Install: brew install --cask docker"; exit 1; }
command -v helm >/dev/null 2>&1 || { print_error "Helm not installed. Install: brew install helm"; exit 1; }

print_status "All prerequisites installed"

# Check Azure login
az account show >/dev/null 2>&1 || { print_error "Not logged in to Azure. Run: az login"; exit 1; }
print_status "Authenticated with Azure"

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "Subscription: ${SUBSCRIPTION_ID}"

# Prompt for Confluent Cloud credentials
echo ""
echo -e "${YELLOW}Enter Confluent Cloud Configuration:${NC}"
read -p "Audit Cluster Bootstrap: " AUDIT_BOOTSTRAP
read -p "Destination Cluster Bootstrap: " DEST_BOOTSTRAP
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

# Step 1: Create resource group
echo ""
echo -e "${YELLOW}Step 1: Creating resource group...${NC}"
if az group show --name ${RESOURCE_GROUP} >/dev/null 2>&1; then
    print_status "Resource group already exists"
else
    az group create --name ${RESOURCE_GROUP} --location ${LOCATION}
    print_status "Resource group created"
fi

# Step 2: Create Azure Container Registry
echo ""
echo -e "${YELLOW}Step 2: Creating Azure Container Registry...${NC}"
if az acr show --name ${ACR_NAME} --resource-group ${RESOURCE_GROUP} >/dev/null 2>&1; then
    print_status "ACR already exists"
else
    az acr create \
        --resource-group ${RESOURCE_GROUP} \
        --name ${ACR_NAME} \
        --sku Basic
    print_status "ACR created"
fi

# Get ACR login server
ACR_LOGIN_SERVER=$(az acr show --name ${ACR_NAME} --resource-group ${RESOURCE_GROUP} --query loginServer -o tsv)
print_status "ACR login server: ${ACR_LOGIN_SERVER}"

# Step 3: Build and push Docker image to ACR
echo ""
echo -e "${YELLOW}Step 3: Building and pushing Docker image to ACR...${NC}"

# Navigate to project root
cd "$(dirname "$0")/../../.."

# Option 1: Build locally
echo "Building Docker image locally..."
docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
print_status "Docker image built"

# Login to ACR
az acr login --name ${ACR_NAME}
print_status "Logged in to ACR"

# Tag and push
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}
docker push ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}
print_status "Docker image pushed to ACR"

# Option 2: Build in ACR (uncomment to use ACR Tasks)
# echo "Building Docker image using ACR Tasks..."
# az acr build \
#     --registry ${ACR_NAME} \
#     --image ${IMAGE_NAME}:${IMAGE_TAG} \
#     --file Dockerfile \
#     .
# print_status "Docker image built and pushed via ACR Tasks"

# Step 4: Check if AKS cluster exists
echo ""
echo -e "${YELLOW}Step 4: Checking AKS cluster...${NC}"
if az aks show --name ${CLUSTER_NAME} --resource-group ${RESOURCE_GROUP} >/dev/null 2>&1; then
    print_status "AKS cluster already exists"
    CLUSTER_EXISTS=true
else
    print_warning "AKS cluster does not exist"
    read -p "Create new AKS cluster? This will take ~15 minutes (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Creating AKS cluster (this will take ~15 minutes)...${NC}"
        az aks create \
            --resource-group ${RESOURCE_GROUP} \
            --name ${CLUSTER_NAME} \
            --node-count ${NODE_COUNT} \
            --node-vm-size ${NODE_SIZE} \
            --enable-managed-identity \
            --enable-cluster-autoscaler \
            --min-count 2 \
            --max-count 4 \
            --network-plugin azure \
            --enable-addons monitoring \
            --generate-ssh-keys \
            --attach-acr ${ACR_NAME}
        print_status "AKS cluster created"
        CLUSTER_EXISTS=true
    else
        print_error "Cannot proceed without cluster. Exiting."
        exit 1
    fi
fi

# If cluster exists but ACR not attached, attach it
if [ "$CLUSTER_EXISTS" = true ]; then
    echo ""
    echo -e "${YELLOW}Ensuring ACR is attached to AKS...${NC}"
    az aks update \
        --resource-group ${RESOURCE_GROUP} \
        --name ${CLUSTER_NAME} \
        --attach-acr ${ACR_NAME} || true
    print_status "ACR attached to AKS"
fi

# Step 5: Configure kubectl
echo ""
echo -e "${YELLOW}Step 5: Configuring kubectl...${NC}"
az aks get-credentials \
    --resource-group ${RESOURCE_GROUP} \
    --name ${CLUSTER_NAME} \
    --overwrite-existing
print_status "kubectl configured"

# Verify connection
kubectl cluster-info >/dev/null 2>&1 || { print_error "Cannot connect to cluster"; exit 1; }
print_status "Connected to cluster"

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
    sed "s|image:.*|image: ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}|" | \
    sed "s|storageClassName:.*|storageClassName: managed-premium|" | \
    kubectl apply -f -

print_status "Application deployed"

# Step 10: Create service
echo ""
echo -e "${YELLOW}Step 10: Creating service...${NC}"
kubectl apply -f deploy/kubernetes/service.yaml
print_status "Service created"

# Step 11: Create LoadBalancer (optional)
echo ""
read -p "Create external LoadBalancer for metrics access? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Creating LoadBalancer...${NC}"
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: audit-forwarder-lb
  namespace: ${NAMESPACE}
spec:
  type: LoadBalancer
  selector:
    app.kubernetes.io/name: audit-forwarder
  ports:
  - port: 80
    targetPort: 8000
    name: metrics
EOF
    print_status "LoadBalancer created"

    echo "Waiting for external IP..."
    sleep 30
    EXTERNAL_IP=$(kubectl get svc audit-forwarder-lb -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
    echo "External IP: ${EXTERNAL_IP}"
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
        --set server.persistentVolume.storageClass=managed-premium

    # Install Grafana
    helm upgrade --install grafana grafana/grafana \
        -n monitoring \
        --set persistence.enabled=true \
        --set persistence.storageClassName=managed-premium \
        --set adminPassword=admin123

    print_status "Monitoring stack installed"

    echo ""
    echo "Get Grafana password:"
    echo "  kubectl get secret -n monitoring grafana -o jsonpath='{.data.admin-password}' | base64 --decode"
    echo ""
    echo "Access Grafana:"
    echo "  kubectl port-forward -n monitoring svc/grafana 3000:80"
fi

# Step 14: Enable Azure Monitor insights (optional)
echo ""
read -p "Enable Azure Monitor Container Insights? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Enabling Azure Monitor...${NC}"
    az aks enable-addons \
        --resource-group ${RESOURCE_GROUP} \
        --name ${CLUSTER_NAME} \
        --addons monitoring
    print_status "Azure Monitor enabled"

    echo ""
    echo "View in Azure Portal:"
    echo "  https://portal.azure.com/#@/resource/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ContainerService/managedClusters/${CLUSTER_NAME}/containerInsights"
fi

# Final summary
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Resource Group: ${RESOURCE_GROUP}"
echo "Cluster: ${CLUSTER_NAME}"
echo "Location: ${LOCATION}"
echo "Namespace: ${NAMESPACE}"
echo "ACR Image: ${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
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
echo "5. View in Azure Portal:"
echo "   https://portal.azure.com/#@/resource/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/overview"
echo ""
echo "6. Cleanup (when done):"
echo "   az group delete --name ${RESOURCE_GROUP} --yes --no-wait"
echo ""
echo -e "${GREEN}Happy monitoring!${NC}"
