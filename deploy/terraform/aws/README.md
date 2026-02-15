# AuditLens AWS Fargate Deployment

Deploy AuditLens (Confluent Audit Log Intelligence System) to AWS ECS Fargate using Terraform.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS VPC (10.0.0.0/16)                          │
│                                                                              │
│  ┌──────────────────────────────┐    ┌──────────────────────────────┐       │
│  │     Public Subnets           │    │     Private Subnets          │       │
│  │  ┌─────────────────────────┐ │    │  ┌─────────────────────────┐ │       │
│  │  │   Application Load      │ │    │  │   ECS Fargate           │ │       │
│  │  │   Balancer (ALB)        │─┼────┼──│   - Forwarder Service   │ │       │
│  │  │                         │ │    │  │   - Dashboard Service   │ │       │
│  │  └─────────────────────────┘ │    │  └───────────┬─────────────┘ │       │
│  │  ┌─────────────────────────┐ │    │              │               │       │
│  │  │   NAT Gateway           │◄┼────┼──────────────┘               │       │
│  │  └─────────────────────────┘ │    │                              │       │
│  └──────────────────────────────┘    └──────────────────────────────┘       │
│                                                                              │
└───────────────────────────────────────────────┬──────────────────────────────┘
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │   Confluent Cloud     │
                                    │   - Audit Log Cluster │
                                    │   - Dest Cluster      │
                                    └───────────────────────┘
```

## Prerequisites

- AWS CLI configured with appropriate permissions
- Terraform >= 1.5.0
- Docker (for building images)
- Confluent Cloud account with audit logs enabled

## Quick Start

### 1. Configure Variables

```bash
cd deploy/terraform/aws
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
```

### 2. Initialize and Apply

```bash
terraform init
terraform plan
terraform apply
```

### 3. Push Docker Images

After Terraform creates the ECR repositories, push your images:

```bash
# Get push commands from Terraform output
terraform output push_commands

# Or manually:
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-west-2.amazonaws.com

docker tag audit-forwarder:v2.2.0 <account-id>.dkr.ecr.us-west-2.amazonaws.com/auditlens/forwarder:v2.2.0
docker push <account-id>.dkr.ecr.us-west-2.amazonaws.com/auditlens/forwarder:v2.2.0

docker tag audit-dashboard:v10.19 <account-id>.dkr.ecr.us-west-2.amazonaws.com/auditlens/dashboard:v10.19
docker push <account-id>.dkr.ecr.us-west-2.amazonaws.com/auditlens/dashboard:v10.19
```

### 4. Access Dashboard

```bash
terraform output dashboard_url
# Open the URL in your browser
```

## Files

| File | Description |
|------|-------------|
| `versions.tf` | Terraform and provider versions |
| `variables.tf` | Input variables |
| `vpc.tf` | VPC, subnets, security groups |
| `ecr.tf` | ECR repositories |
| `secrets.tf` | AWS Secrets Manager |
| `iam.tf` | IAM roles and policies |
| `ecs.tf` | ECS cluster, task definitions, services |
| `alb.tf` | Application Load Balancer |
| `monitoring.tf` | CloudWatch logs, alarms, dashboard |
| `outputs.tf` | Output values |

## Cost Estimate

| Resource | Specification | Monthly Cost |
|----------|---------------|--------------|
| Forwarder (Fargate) | 0.5 vCPU, 1GB | ~$18 |
| Dashboard (Fargate) | 0.25 vCPU, 0.5GB × 2 | ~$18 |
| ALB | Basic usage | ~$16 |
| NAT Gateway | Single AZ | ~$32 |
| CloudWatch Logs | 5GB/month | ~$3 |
| Secrets Manager | 2 secrets | ~$1 |
| **Total** | | **~$88/month** |

### Cost Optimization

- Set `use_fargate_spot = true` for forwarder (~70% savings, can be interrupted)
- Reduce `dashboard_desired_count` to 1 (less HA)
- Use existing VPC instead of creating new one

## Monitoring

### CloudWatch Dashboard

```bash
terraform output cloudwatch_dashboard_url
```

### View Logs

```bash
# Forwarder logs
aws logs tail /ecs/auditlens-forwarder --follow

# Dashboard logs
aws logs tail /ecs/auditlens-dashboard --follow
```

### Alarms

- Forwarder CPU > 80%
- Forwarder Memory > 80%
- No running forwarder tasks
- No healthy dashboard hosts
- ALB 5xx errors > 10/min

## Updating

### Update Container Images

```bash
# Build new images
docker build -t audit-forwarder:v2.3.0 .
docker build -t audit-dashboard:v10.20 ./dashboard

# Push to ECR
docker tag audit-forwarder:v2.3.0 <ecr-url>/auditlens/forwarder:v2.3.0
docker push <ecr-url>/auditlens/forwarder:v2.3.0

# Update Terraform variables and apply
terraform apply -var="forwarder_image_tag=v2.3.0"
```

### Force New Deployment

```bash
aws ecs update-service --cluster auditlens-cluster --service auditlens-forwarder --force-new-deployment
aws ecs update-service --cluster auditlens-cluster --service auditlens-dashboard --force-new-deployment
```

## Cleanup

```bash
terraform destroy
```

**Note:** If deletion protection is enabled on ALB (production), disable it first:
```bash
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn <alb-arn> \
  --attributes Key=deletion_protection.enabled,Value=false
```
