#!/bin/bash
set -e

##############################################################################
# GCP GKE Deployment Script for Audit Forwarder
#
# This script automates the complete deployment to GCP:
# - Creates GKE cluster
# - Sets up GCR repository
# - Builds and pushes Docker image
# - Deploys application to Kubernetes
# - Configures monitoring
#
# Prerequisites:
# - gcloud CLI installed and configured
# - kubectl installed
# - Docker installed
# - helm installed
#
# Usage:
#   ./setup-gcp.sh
##############################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
CLUSTER_NAME="audit-forwarder-cluster"
REGION="us-west2"
ZONES="us-west2-a,us-west2-b,us-west2-c"
MACHINE_TYPE="e2-medium"
MIN_NODES=2
MAX_NODES=4
IMAGE_NAME="audit-forwarder"
IMAGE_TAG="2.0.0"
NAMESPACE="audit-forwarder"

# Get GCP project ID
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}No GCP project configured.${NC}"
    read -p "Enter GCP Project ID: " PROJECT_ID
    gcloud config set project $PROJECT_ID
fi

GCR_REGISTRY="gcr.io/${PROJECT_ID}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}GCP GKE Audit Forwarder Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Project: ${PROJECT_ID}"
echo "Cluster: ${CLUSTER_NAME}"
echo "Region: ${REGION}"
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

command -v gcloud >/dev/null 2>&1 || { print_error "gcloud CLI not installed. Install: brew install --cask google-cloud-sdk"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { print_error "kubectl not installed. Install: brew install kubectl"; exit 1; }
command -v docker >/dev/null 2>&1 || { print_error "Docker not installed. Install: brew install --cask docker"; exit 1; }
command -v helm >/dev/null 2>&1 || { print_error "Helm not installed. Install: brew install helm"; exit 1; }

print_status "All prerequisites installed"

# Check gcloud auth
gcloud auth list >/dev/null 2>&1 || { print_error "Not logged in to gcloud. Run: gcloud auth login"; exit 1; }
print_status "Authenticated with gcloud"

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

# Step 1: Enable required APIs
echo ""
echo -e "${YELLOW}Step 1: Enabling required GCP APIs...${NC}"
gcloud services enable container.googleapis.com
gcloud services enable containerregistry.googleapis.com
gcloud services enable cloudresourcemanager.googleapis.com
print_status "APIs enabled"

# Step 2: Build and push Docker image to GCR
echo ""
echo -e "${YELLOW}Step 2: Building and pushing Docker image to GCR...${NC}"

# Configure Docker for GCR
gcloud auth configure-docker --quiet
print_status "Docker configured for GCR"

# Navigate to project root
cd "$(dirname "$0")/../../.."

# Option 1: Build locally and push
echo "Building Docker image locally..."
docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${GCR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
docker push ${GCR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
print_status "Docker image pushed to GCR"

# Option 2: Build in GCP (uncomment to use Cloud Build instead)
# echo "Building Docker image using Cloud Build..."
# gcloud builds submit --tag ${GCR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} .
# print_status "Docker image built and pushed via Cloud Build"

# Step 3: Check if GKE cluster exists
echo ""
echo -e "${YELLOW}Step 3: Checking GKE cluster...${NC}"
if gcloud container clusters describe ${CLUSTER_NAME} --region ${REGION} >/dev/null 2>&1; then
    print_status "GKE cluster already exists"
    CLUSTER_EXISTS=true
else
    print_warning "GKE cluster does not exist"
    read -p "Create new GKE cluster? This will take ~10 minutes (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Creating GKE cluster (this will take ~10 minutes)...${NC}"
        gcloud container clusters create ${CLUSTER_NAME} \
            --region ${REGION} \
            --node-locations ${ZONES} \
            --machine-type ${MACHINE_TYPE} \
            --num-nodes 1 \
            --enable-autoscaling \
            --min-nodes ${MIN_NODES} \
            --max-nodes ${MAX_NODES} \
            --enable-autorepair \
            --enable-autoupgrade \
            --enable-stackdriver-kubernetes \
            --addons HorizontalPodAutoscaling,HttpLoadBalancing,GcePersistentDiskCsiDriver \
            --workload-pool=${PROJECT_ID}.svc.id.goog \
            --release-channel regular
        print_status "GKE cluster created"
        CLUSTER_EXISTS=true
    else
        print_error "Cannot proceed without cluster. Exiting."
        exit 1
    fi
fi

# Step 4: Configure kubectl
echo ""
echo -e "${YELLOW}Step 4: Configuring kubectl...${NC}"
gcloud container clusters get-credentials ${CLUSTER_NAME} --region ${REGION}
print_status "kubectl configured"

# Verify connection
kubectl cluster-info >/dev/null 2>&1 || { print_error "Cannot connect to cluster"; exit 1; }
print_status "Connected to cluster"

# Step 5: Create GCP service account for Workload Identity
echo ""
echo -e "${YELLOW}Step 5: Setting up Workload Identity...${NC}"

GSA_NAME="audit-forwarder-sa"
GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Create GCP service account if not exists
if ! gcloud iam service-accounts describe ${GSA_EMAIL} >/dev/null 2>&1; then
    gcloud iam service-accounts create ${GSA_NAME} \
        --display-name="Audit Forwarder Service Account"
    print_status "GCP service account created"
else
    print_status "GCP service account already exists"
fi

# Grant permissions (if using GCS sinks)
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="roles/storage.objectCreator" \
    --condition=None >/dev/null 2>&1 || true

print_status "Workload Identity configured"

# Step 6: Create namespace
echo ""
echo -e "${YELLOW}Step 6: Creating Kubernetes namespace...${NC}"
kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -
print_status "Namespace created"

# Step 7: Create Kubernetes service account and bind to GCP SA
echo ""
echo -e "${YELLOW}Step 7: Creating Kubernetes service account...${NC}"
kubectl create serviceaccount audit-forwarder -n ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

# Bind Kubernetes SA to GCP SA
gcloud iam service-accounts add-iam-policy-binding ${GSA_EMAIL} \
    --role roles/iam.workloadIdentityUser \
    --member "serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/audit-forwarder]"

# Annotate K8s service account
kubectl annotate serviceaccount audit-forwarder \
    -n ${NAMESPACE} \
    iam.gke.io/gcp-service-account=${GSA_EMAIL} \
    --overwrite

print_status "Service account configured"

# Step 8: Create secrets
echo ""
echo -e "${YELLOW}Step 8: Creating Kubernetes secrets...${NC}"
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

# Step 9: Create ConfigMap
echo ""
echo -e "${YELLOW}Step 9: Creating ConfigMap...${NC}"
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

# Step 10: Update and deploy Kubernetes manifests
echo ""
echo -e "${YELLOW}Step 10: Deploying application...${NC}"

# Create temporary deployment file with updated image
cat deploy/kubernetes/deployment.yaml | \
    sed "s|image:.*|image: ${GCR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}|" | \
    sed "s|storageClassName:.*|storageClassName: standard-rwo|" | \
    kubectl apply -f -

print_status "Application deployed"

# Step 11: Create service
echo ""
echo -e "${YELLOW}Step 11: Creating service...${NC}"
kubectl apply -f deploy/kubernetes/service.yaml
print_status "Service created"

# Step 12: Create LoadBalancer (optional)
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

# Step 13: Verify deployment
echo ""
echo -e "${YELLOW}Step 13: Verifying deployment...${NC}"
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

# Step 14: Setup monitoring (optional)
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
        --set server.persistentVolume.storageClass=standard-rwo

    # Install Grafana
    helm upgrade --install grafana grafana/grafana \
        -n monitoring \
        --set persistence.enabled=true \
        --set persistence.storageClassName=standard-rwo \
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
echo "Project: ${PROJECT_ID}"
echo "Cluster: ${CLUSTER_NAME}"
echo "Region: ${REGION}"
echo "Namespace: ${NAMESPACE}"
echo "GCR Image: ${GCR_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
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
echo "5. View in GCP Console:"
echo "   https://console.cloud.google.com/kubernetes/workload?project=${PROJECT_ID}"
echo ""
echo "6. Cleanup (when done):"
echo "   gcloud container clusters delete ${CLUSTER_NAME} --region ${REGION}"
echo ""
echo -e "${GREEN}Happy monitoring!${NC}"
