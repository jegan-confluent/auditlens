# Deployment Guide - Audit Forwarder v2

This guide covers deploying the Audit Forwarder using Terraform to AWS, GCP, or directly to Confluent Cloud.

## Prerequisites

- Terraform >= 1.0
- Confluent Cloud account with audit logging enabled
- AWS CLI configured (for AWS deployment)
- gcloud CLI configured (for GCP deployment)
- Docker (for building images)

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              DEPLOYMENT OPTIONS                                   │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  Option 1: AWS (ECS Fargate)           Option 2: GCP (Cloud Run)                 │
│  ┌─────────────────────────┐           ┌─────────────────────────┐               │
│  │  ECS Fargate Cluster    │           │  Cloud Run Service      │               │
│  │  ├── Audit Forwarder    │           │  ├── Audit Forwarder    │               │
│  │  └── Auto Scaling       │           │  └── Auto Scaling       │               │
│  ├─────────────────────────┤           ├─────────────────────────┤               │
│  │  S3 Bucket (Parquet)    │           │  GCS Bucket (Parquet)   │               │
│  ├─────────────────────────┤           ├─────────────────────────┤               │
│  │  Secrets Manager        │           │  Secret Manager         │               │
│  │  KMS Encryption         │           │  Cloud KMS              │               │
│  │  CloudWatch Monitoring  │           │  Cloud Monitoring       │               │
│  └─────────────────────────┘           └─────────────────────────┘               │
│                                                                                   │
│                        ┌───────────────────────────┐                             │
│                        │   Confluent Cloud         │                             │
│                        │   ├── Audit Log Cluster   │                             │
│                        │   ├── Destination Cluster │                             │
│                        │   └── Schema Registry     │                             │
│                        └───────────────────────────┘                             │
│                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Step 1: Set Up Confluent Cloud Resources

First, create the necessary Confluent Cloud resources:

```bash
cd deploy/terraform/confluent-cloud

# Copy and edit variables
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your Confluent Cloud details

# Initialize and apply
terraform init
terraform plan
terraform apply

# Save the output for next steps
terraform output -json > ../confluent-outputs.json
```

### Step 2: Deploy to Your Cloud Provider

#### Option A: AWS Deployment

```bash
cd deploy/terraform/aws

# Copy and edit variables
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your AWS and Confluent details

# Initialize and apply
terraform init
terraform plan
terraform apply
```

#### Option B: GCP Deployment

```bash
cd deploy/terraform/gcp

# Copy and edit variables
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your GCP and Confluent details

# Initialize and apply
terraform init
terraform plan
terraform apply
```

### Step 3: Build and Push Docker Image

#### For AWS (ECR):

```bash
# Get ECR repository URL
ECR_REPO=$(cd deploy/terraform/aws && terraform output -raw ecr_repository_url)

# Login to ECR
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin $ECR_REPO

# Build and push
docker build -t $ECR_REPO:latest -f deploy/docker/Dockerfile .
docker push $ECR_REPO:latest

# Force new deployment
aws ecs update-service --cluster audit-forwarder-cluster --service audit-forwarder --force-new-deployment
```

#### For GCP (Artifact Registry):

```bash
# Get Artifact Registry URL
AR_REPO=$(cd deploy/terraform/gcp && terraform output -raw artifact_registry_repository)

# Configure Docker for Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build and push
docker build -t $AR_REPO/audit-forwarder:latest -f deploy/docker/Dockerfile .
docker push $AR_REPO/audit-forwarder:latest

# Deploy new revision
gcloud run deploy audit-forwarder --image $AR_REPO/audit-forwarder:latest --region us-central1
```

## Detailed Configuration

### AWS Terraform Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `aws_region` | AWS region | Yes | `us-west-2` |
| `environment` | Environment name | Yes | `dev` |
| `audit_bootstrap` | Confluent audit cluster bootstrap | Yes | - |
| `audit_api_key` | API key for audit cluster | Yes | - |
| `dest_bootstrap` | Destination cluster bootstrap | Yes | - |
| `dest_api_key` | API key for destination | Yes | - |
| `ecs_cpu` | CPU units for ECS task | No | `512` |
| `ecs_memory` | Memory (MB) for ECS task | No | `1024` |
| `desired_count` | Number of ECS tasks | No | `2` |

### GCP Terraform Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `project_id` | GCP project ID | Yes | - |
| `region` | GCP region | Yes | `us-central1` |
| `environment` | Environment name | Yes | `dev` |
| `audit_bootstrap` | Confluent audit cluster bootstrap | Yes | - |
| `audit_api_key` | API key for audit cluster | Yes | - |
| `dest_bootstrap` | Destination cluster bootstrap | Yes | - |
| `dest_api_key` | API key for destination | Yes | - |
| `cpu` | CPU allocation | No | `1` |
| `memory` | Memory allocation | No | `1Gi` |
| `min_instances` | Minimum instances | No | `1` |

### Confluent Cloud Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `confluent_cloud_api_key` | Cloud API key | Yes |
| `confluent_cloud_api_secret` | Cloud API secret | Yes |
| `environment_id` | Environment ID | Yes |
| `audit_cluster_id` | Audit log cluster ID | Yes |
| `dest_cluster_id` | Destination cluster ID | Yes |

## Production Recommendations

### High Availability

**AWS:**
```hcl
# terraform.tfvars
desired_count = 3
min_count     = 2
max_count     = 10

# Use multiple AZs
availability_zones = ["us-west-2a", "us-west-2b", "us-west-2c"]
```

**GCP:**
```hcl
# terraform.tfvars
min_instances = 2
max_instances = 10
```

### Security

1. **Use Secrets Manager** (enabled by default)
2. **Enable encryption at rest** (KMS/Cloud KMS)
3. **VPC isolation** (private subnets, no public IP)
4. **Least privilege IAM** (minimal permissions)

### Monitoring

**AWS CloudWatch Alarms (included):**
- High CPU utilization
- ECS service health

**GCP Cloud Monitoring (included):**
- High error rate alert
- Dashboard for CPU, memory, requests

### Cost Optimization

**AWS:**
- Use FARGATE_SPOT for non-production
- Right-size ECS tasks based on actual usage
- Enable S3 lifecycle policies (Glacier after 90 days)

**GCP:**
- Use min_instances = 0 for dev (scale to zero)
- Enable GCS lifecycle policies

## Multi-Region Deployment

For disaster recovery, deploy to multiple regions:

```bash
# AWS Multi-Region
cd deploy/terraform/aws
terraform workspace new us-west-2
terraform apply -var="aws_region=us-west-2"

terraform workspace new us-east-1
terraform apply -var="aws_region=us-east-1"
```

## Upgrading

### Rolling Update (Zero Downtime)

```bash
# AWS
aws ecs update-service \
  --cluster audit-forwarder-cluster \
  --service audit-forwarder \
  --force-new-deployment

# GCP
gcloud run deploy audit-forwarder \
  --image $AR_REPO/audit-forwarder:v2.1.0 \
  --region us-central1 \
  --no-traffic

# Verify, then shift traffic
gcloud run services update-traffic audit-forwarder \
  --to-latest --region us-central1
```

### Terraform Updates

```bash
# Review changes
terraform plan

# Apply with auto-approve (use cautiously)
terraform apply -auto-approve
```

## Troubleshooting

### Check Logs

**AWS:**
```bash
aws logs tail /ecs/audit-forwarder --follow
```

**GCP:**
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=audit-forwarder" --limit=100
```

### Check Health

```bash
# AWS (via VPN/bastion)
curl http://<task-private-ip>:8001/health

# GCP
curl $(terraform output -raw cloud_run_service_url)/health
```

### Common Issues

1. **Consumer lag increasing**: Scale up instances
2. **S3/GCS write failures**: Check IAM permissions
3. **Authentication errors**: Verify API keys in Secrets Manager

## Cleanup

```bash
# Destroy resources (USE WITH CAUTION!)
cd deploy/terraform/aws  # or gcp
terraform destroy

# Clean up Confluent Cloud resources
cd deploy/terraform/confluent-cloud
terraform destroy
```

## File Structure

```
deploy/terraform/
├── aws/
│   ├── main.tf              # AWS resources (VPC, ECS, S3, etc.)
│   ├── variables.tf         # Input variables
│   ├── outputs.tf           # Output values
│   └── terraform.tfvars.example
├── gcp/
│   ├── main.tf              # GCP resources (Cloud Run, GCS, etc.)
│   ├── variables.tf         # Input variables
│   ├── outputs.tf           # Output values
│   └── terraform.tfvars.example
└── confluent-cloud/
    ├── main.tf              # Confluent resources (topics, ACLs, etc.)
    ├── variables.tf         # Input variables
    ├── outputs.tf           # Output values (including env vars)
    └── terraform.tfvars.example
```
