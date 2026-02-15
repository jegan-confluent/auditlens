# Cloud Deployment Scripts

Automated deployment scripts for deploying the Audit Forwarder to AWS, GCP, or Azure.

## 📋 Prerequisites

### Common Requirements (All Clouds)
- **Docker** installed
- **kubectl** installed
- **helm** installed
- **Confluent Cloud** account with:
  - Audit log cluster created
  - Destination Kafka cluster created
  - Schema Registry enabled
  - API keys generated

### Cloud-Specific CLIs

| Cloud | CLI | Installation |
|-------|-----|--------------|
| **AWS** | AWS CLI + eksctl | `brew install awscli eksctl` |
| **GCP** | gcloud CLI | `brew install --cask google-cloud-sdk` |
| **Azure** | Azure CLI | `brew install azure-cli` |

---

## 🚀 Quick Start

### **1. Make scripts executable**
```bash
chmod +x deploy/cloud/aws/setup-aws.sh
chmod +x deploy/cloud/gcp/setup-gcp.sh
chmod +x deploy/cloud/azure/setup-azure.sh
```

### **2. Choose your cloud provider**

#### AWS (EKS)
```bash
cd /Users/jegan/playground/audit-forwarder
./deploy/cloud/aws/setup-aws.sh
```

#### GCP (GKE)
```bash
cd /Users/jegan/playground/audit-forwarder
./deploy/cloud/gcp/setup-gcp.sh
```

#### Azure (AKS)
```bash
cd /Users/jegan/playground/audit-forwarder
./deploy/cloud/azure/setup-azure.sh
```

---

## 📊 What Each Script Does

### **Automated Steps:**

1. ✅ **Prerequisites Check** - Verifies all required tools installed
2. ✅ **Authentication** - Confirms cloud CLI authenticated
3. ✅ **Container Registry** - Creates registry (ECR/GCR/ACR)
4. ✅ **Docker Build** - Builds application image
5. ✅ **Image Push** - Pushes to cloud registry
6. ✅ **Cluster Creation** - Creates Kubernetes cluster (if needed)
7. ✅ **kubectl Configuration** - Sets up cluster access
8. ✅ **Namespace Creation** - Creates `audit-forwarder` namespace
9. ✅ **Secrets Management** - Creates Kubernetes secrets
10. ✅ **ConfigMap** - Creates application configuration
11. ✅ **Deployment** - Deploys forwarder pods (3 replicas)
12. ✅ **Service Creation** - Creates Kubernetes service
13. ✅ **Load Balancer** - (Optional) External access
14. ✅ **Monitoring** - (Optional) Prometheus + Grafana
15. ✅ **Verification** - Checks pods are running

### **Interactive Prompts:**

During execution, you'll be prompted for:
- Confluent Cloud bootstrap servers
- API keys and secrets
- Schema Registry URL and credentials
- Whether to create cluster (if not exists)
- Whether to install monitoring stack
- Whether to create external load balancer

---

## 🔧 Configuration Details

### **Cluster Defaults:**

| Setting | AWS (EKS) | GCP (GKE) | Azure (AKS) |
|---------|-----------|-----------|-------------|
| **Cluster Name** | audit-forwarder-cluster | audit-forwarder-cluster | audit-forwarder-cluster |
| **Region** | us-west-2 | us-west2 | westus2 |
| **Node Type** | t3.medium | e2-medium | Standard_D2s_v3 |
| **Node Count** | 3 (autoscale 2-4) | 3 (autoscale 2-4) | 3 (autoscale 2-4) |
| **Kubernetes Version** | 1.28 | Latest stable | Latest stable |

### **Storage Classes:**

| Cloud | Storage Class | Type |
|-------|--------------|------|
| AWS | `gp3` | EBS General Purpose SSD |
| GCP | `standard-rwo` | Persistent Disk |
| Azure | `managed-premium` | Managed Premium SSD |

---

## 💰 Cost Estimates

### **Monthly Costs (3-node cluster):**

| Cloud | Control Plane | Compute | Storage | LB | **Total** |
|-------|---------------|---------|---------|-----|-----------|
| **AWS** | $73 | $90 | $7 | $23 | **~$193** |
| **GCP** | $73 | $75 | $5 | $18 | **~$171** |
| **Azure** | Free | $180 | $7 | $20 | **~$207** |

**Note:** Costs exclude Confluent Cloud ($270/month for TableFlow + Flink alerts)

---

## 🎯 Deployment Time

| Cloud | Cluster Creation | Total Setup |
|-------|-----------------|-------------|
| **AWS** | ~20 minutes | ~25 minutes |
| **GCP** | ~10 minutes | ~15 minutes |
| **Azure** | ~15 minutes | ~20 minutes |

---

## ✅ Post-Deployment Verification

### **1. Check Pods**
```bash
kubectl get pods -n audit-forwarder

# Expected output:
# NAME                               READY   STATUS    RESTARTS   AGE
# audit-forwarder-7c9f8b6d4-abc12   1/1     Running   0          2m
# audit-forwarder-7c9f8b6d4-def34   1/1     Running   0          2m
# audit-forwarder-7c9f8b6d4-ghi56   1/1     Running   0          2m
```

### **2. Check Logs**
```bash
kubectl logs -f -n audit-forwarder -l app.kubernetes.io/name=audit-forwarder

# Expected output:
# INFO:audit_forwarder:Starting Confluent Audit Log Forwarder
# INFO:audit_forwarder:Metrics server running on port 8000
# INFO:audit_forwarder:Consumer assigned partitions: [0, 1, 2]
```

### **3. Access Metrics**
```bash
# Port-forward
kubectl port-forward -n audit-forwarder svc/audit-forwarder 8000:8000

# Check metrics (in another terminal)
curl http://localhost:8000/metrics | grep audit_events_processed_total
```

### **4. Check Consumer Lag**
```bash
confluent kafka consumer group describe audit-forwarder-group \
  --cluster <your-cluster-id>
```

---

## 🔄 Update Application

### **Build New Image**
```bash
# Update version in script (IMAGE_TAG="2.1.0")
# Or manually:

# AWS
docker build -t audit-forwarder:2.1.0 .
docker tag audit-forwarder:2.1.0 ${AWS_ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/audit-forwarder:2.1.0
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/audit-forwarder:2.1.0

# GCP
docker build -t audit-forwarder:2.1.0 .
docker tag audit-forwarder:2.1.0 gcr.io/${PROJECT_ID}/audit-forwarder:2.1.0
docker push gcr.io/${PROJECT_ID}/audit-forwarder:2.1.0

# Azure
docker build -t audit-forwarder:2.1.0 .
docker tag audit-forwarder:2.1.0 ${ACR_NAME}.azurecr.io/audit-forwarder:2.1.0
docker push ${ACR_NAME}.azurecr.io/audit-forwarder:2.1.0
```

### **Rolling Update**
```bash
# Update deployment with new image
kubectl set image deployment/audit-forwarder \
  forwarder=${REGISTRY}/audit-forwarder:2.1.0 \
  -n audit-forwarder

# Watch rollout
kubectl rollout status deployment/audit-forwarder -n audit-forwarder

# Rollback if needed
kubectl rollout undo deployment/audit-forwarder -n audit-forwarder
```

---

## 🧹 Cleanup

### **Delete Application Only (Keep Cluster)**
```bash
kubectl delete namespace audit-forwarder
```

### **Delete Everything (Including Cluster)**

#### AWS
```bash
# Delete cluster
eksctl delete cluster --name audit-forwarder-cluster --region us-west-2

# Delete ECR repository
aws ecr delete-repository --repository-name audit-forwarder --region us-west-2 --force
```

#### GCP
```bash
# Delete cluster
gcloud container clusters delete audit-forwarder-cluster --region us-west2 --quiet

# Delete images
gcloud container images delete gcr.io/${PROJECT_ID}/audit-forwarder:2.0.0 --quiet
```

#### Azure
```bash
# Delete entire resource group (cluster + ACR)
az group delete --name audit-forwarder-rg --yes --no-wait
```

---

## 🐛 Troubleshooting

### **Issue: Script fails at Docker build**
```bash
# Check Docker is running
docker ps

# If not running:
open -a Docker
```

### **Issue: Cannot connect to cluster**
```bash
# Verify kubectl context
kubectl config current-context

# List all contexts
kubectl config get-contexts

# Switch context
kubectl config use-context <context-name>
```

### **Issue: Pods stuck in Pending**
```bash
# Check pod events
kubectl describe pod <pod-name> -n audit-forwarder

# Common causes:
# 1. Insufficient resources (scale up nodes)
# 2. PVC not bound (check storage class)
# 3. Image pull error (check ACR/ECR/GCR permissions)
```

### **Issue: Pods crash with "Permission denied"**
```bash
# Check security context in deployment
kubectl get deployment audit-forwarder -n audit-forwarder -o yaml | grep -A10 securityContext

# Ensure runAsUser: 1000 and fsGroup: 1000 are set
```

### **Issue: Cannot pull image from registry**

**AWS:**
```bash
# Check ECR permissions
aws ecr get-login-password --region us-west-2
```

**GCP:**
```bash
# Configure docker auth
gcloud auth configure-docker
```

**Azure:**
```bash
# Verify ACR is attached to AKS
az aks check-acr --name audit-forwarder-cluster --resource-group audit-forwarder-rg --acr auditforwarderacr
```

---

## 📚 Additional Resources

### **Cloud Documentation:**
- **AWS EKS:** https://docs.aws.amazon.com/eks/
- **GCP GKE:** https://cloud.google.com/kubernetes-engine/docs
- **Azure AKS:** https://docs.microsoft.com/en-us/azure/aks/

### **Kubernetes:**
- **kubectl Cheat Sheet:** https://kubernetes.io/docs/reference/kubectl/cheatsheet/
- **Troubleshooting:** https://kubernetes.io/docs/tasks/debug/

### **Confluent Cloud:**
- **Audit Logs:** https://docs.confluent.io/cloud/current/monitoring/audit-logging.html
- **API Keys:** https://docs.confluent.io/cloud/current/access-management/authenticate/api-keys/

---

## 🆘 Support

**Issues with scripts:** Open GitHub issue or contact devops@company.com
**Confluent Cloud:** https://support.confluent.io
**Cloud-specific:** Contact your cloud support team

---

## 📝 Customization

### **Modify Cluster Size**

Edit the script before running:

```bash
# In setup-aws.sh, setup-gcp.sh, or setup-azure.sh
NODE_COUNT=5        # Increase from 3 to 5
NODE_TYPE="..."     # Change instance type
```

### **Change Region**

```bash
# AWS
REGION="us-east-1"

# GCP
REGION="us-central1"
ZONES="us-central1-a,us-central1-b,us-central1-c"

# Azure
LOCATION="eastus"
```

### **Custom Namespace**

```bash
NAMESPACE="my-custom-namespace"
```

---

**Last Updated:** December 6, 2025
**Version:** 1.0
