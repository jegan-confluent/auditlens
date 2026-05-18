# AuditLens — Deployment Guide

> Read-only ground truth: every step here is derived from actual scripts,
> Makefile targets, and compose files in this repo. Anything not yet
> implemented is marked **🚧 Coming soon** rather than invented.

---

## Choose Your Deployment Type

| I want to...                              | Go to       |
|-------------------------------------------|-------------|
| Run locally on Mac or Linux               | Section 1   |
| Run locally on Windows                    | Section 2   |
| Deploy to a single EC2 / VM              | Section 3   |
| Deploy to AWS EKS (Kubernetes)            | Section 4   |
| Deploy to AWS ECS / Fargate (Terraform)   | Section 5   |
| Deploy to GCP GKE                         | Section 6   |
| Deploy to Azure AKS                       | Section 7   |
| Deploy with raw Kubernetes manifests      | Section 8   |
| Deploy with Helm                          | Section 9   |

---

## Section 1 — Local (Mac / Linux)

**Status: ✅ Fully scripted**

### Prerequisites

- Docker Desktop ≥ 24 (or Docker Engine + Compose plugin on Linux)
- Python 3.9+ (for the setup wizard)
- npm ≥ 9 (frontend build, handled automatically by Docker)
- A Confluent Cloud account with an audit log cluster

### First-time setup

```bash
# Clone the repo
git clone <repo-url> AuditLens && cd AuditLens

# Run the guided setup wizard — creates .env and .secrets
./setup
```

The wizard (`scripts/bootstrap_auditlens.py`) asks for:
- Confluent Cloud bootstrap server + API key/secret (audit log cluster)
- Destination Kafka cluster + API key/secret
- Postgres password (auto-generated if left blank)
- Optional: Confluent Cloud API key for IAM identity enrichment
- Optional: Slack/Teams webhook URL for notifications

### Start / stop

```bash
make start          # docker compose up -d (default services)
make stop           # docker compose down
make restart        # down then up
```

Or directly:
```bash
docker compose up -d
docker compose down
```

### What you get (default profile)

| Service | Port | Purpose |
|---|---|---|
| auditlens-caddy | 80, 443 | Reverse proxy: /api/* → backend, /* → frontend |
| auditlens-frontend | (via Caddy) | Next.js dashboard |
| auditlens-api | (via Caddy) | FastAPI backend |
| auditlens-forwarder | 8003 | Kafka consumer + enrichment engine |
| auditlens-postgres | 5432 (internal) | Event store |

### Optional profiles

Add via `--profile <name>` or set `COMPOSE_PROFILES` in `.env`:

| Profile | What it adds |
|---|---|
| `observability` | Prometheus (:9090), Grafana (:3001), Loki, Promtail |
| `streamlit` | Legacy Streamlit dashboard (:8503) |
| `postgres` | Postgres Exporter for Prometheus scraping (:9187) |
| `dev` | All of the above + landing page |

```bash
# Start with observability stack
docker compose --profile observability up -d
```

### Verify

```bash
curl http://localhost/api/health   # → {"status":"ok"}
curl http://localhost:8003/health  # → {"status":"healthy"}
open http://localhost              # Dashboard in browser
```

---

## Section 2 — Local (Windows)

**Status: ❌ No Windows-specific scripts exist**

AuditLens does not include a Windows setup script. The Docker Compose stack
is cross-platform but the `./setup` wizard is a Python/bash script not tested
on Windows.

**Workaround:** Use WSL2 (Windows Subsystem for Linux) with Ubuntu 22.04,
install Docker Desktop with WSL2 backend, then follow Section 1 inside WSL2.

🚧 Coming soon: native Windows bootstrap.

---

## Section 3 — Single EC2 / VM

**Status: ✅ Fully scripted via Makefile**

### Prerequisites

- EC2 instance: **Amazon Linux 2023** or **Ubuntu 22.04**
  - Minimum: **t3.large** (2 vCPU, 8 GB RAM), **50 GB** EBS storage
  - Security group: inbound TCP 22 (SSH), 80 (HTTP), 443 (HTTPS)
- Docker + Compose plugin installed on the instance
- SSH key at `~/.ssh/auditlens.pem`

Makefile defaults (override on command line or in shell):

```makefile
EC2_IP   = YOUR_EC2_IP   # change this
EC2_USER = ec2-user
PEM      = ~/.ssh/auditlens.pem
```

Override: `make deploy EC2_IP=1.2.3.4`

### First-time EC2 setup

SSH onto the instance and install Docker:

```bash
# Amazon Linux 2023
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
newgrp docker   # or log out and back in

# Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
```

From your Mac, copy credentials (rsync deliberately excludes `.env` and `.secrets`):

```bash
scp -i ~/.ssh/auditlens.pem .env     ec2-user@<ip>:~/AuditLens/.env
scp -i ~/.ssh/auditlens.pem .secrets ec2-user@<ip>:~/AuditLens/.secrets
```

Then deploy:

```bash
make deploy-check   # dry-run: shows what rsync would change
make deploy         # full deploy
```

### What `make deploy` does (step by step)

1. **rsync** code to `~/AuditLens/` on EC2
   (excludes `.git`, `.env`, `.secrets`, `.venv`, `node_modules`, `data`, `logs`)
2. **chown/chmod** — fixes `src/` and `prometheus/alerts/` ownership
3. **docker compose up --build --force-recreate** — rebuilds images, restarts containers
4. **sleep 10** — waits for API container to become healthy
5. **alembic upgrade head** — applies any pending DB migrations automatically
6. Reports `✅ Migrations applied.` or warns if migration failed (deploy continues)

### Ongoing operations

```bash
make deploy          # Full deploy: sync + rebuild + migrate
make sync            # Sync code only, no container restart
make deploy-check    # Dry-run rsync — shows what would change
make ps              # Container status on EC2
make logs            # Tail prod logs (all services)
make health          # Check forwarder + API health endpoints
```

### Backup

```bash
make backup-install  # Install daily 2am UTC cron on EC2
make backup-now      # Run backup immediately
make backup-list     # List existing backups + tail log
```

Backups are stored at `~/backups/postgres/auditlens_<timestamp>.sql.gz`
with 7-day retention. Script: `infra/backup/run_backup.sh`.

---

## Section 4 — AWS EKS (Kubernetes)

**Status: ⚠️ Script exists — not CI-tested**

Entry point: `deploy/cloud/aws/setup-aws.sh`

The script creates an EKS cluster, ECR repository, builds and pushes the
Docker image, and deploys to Kubernetes.

Default config inside the script:
- Cluster: `audit-forwarder-cluster`, region `us-west-2`
- Nodes: `t3.medium` × 3
- Namespace: `audit-forwarder`

### Prerequisites

```bash
brew install awscli eksctl kubectl helm
aws configure   # AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + region
```

### Deploy

```bash
chmod +x deploy/cloud/aws/setup-aws.sh
make deploy-aws
```

🚧 This script deploys the **forwarder only**, not the full 4-service stack
(API, frontend, Caddy, Postgres). Treat as a starting point.

---

## Section 5 — AWS ECS / Fargate (Terraform)

**Status: ⚠️ Full Terraform config exists — not applied in production**

`deploy/terraform/aws/` provisions:

| File | Resources |
|---|---|
| `vpc.tf` | VPC, subnets, NAT gateway |
| `ecr.tf` | ECR repository |
| `ecs.tf` | ECS cluster + Fargate task + service |
| `alb.tf` | Application Load Balancer |
| `iam.tf` | Task execution role + policies |
| `secrets.tf` | AWS Secrets Manager entries |
| `monitoring.tf` | CloudWatch log groups + alarms |

Estimated cost: ~$88/month (Fargate + ALB + transfer).

### Deploy

```bash
cd deploy/terraform/aws
cp terraform.tfvars.example terraform.tfvars
# Edit: aws_region, project_name, environment, container image, etc.
terraform init
terraform plan
terraform apply
```

A `.terraform.lock.hcl` is checked in — `init` is fast.

🚧 The Terraform config provisions the forwarder service only. API, frontend,
and Postgres are not yet in the ECS task definitions.

---

## Section 6 — GCP GKE

**Status: ⚠️ Script + Terraform exist — not tested end-to-end**

### Script deploy

```bash
brew install --cask google-cloud-sdk kubectl helm
gcloud auth login
chmod +x deploy/cloud/gcp/setup-gcp.sh
make deploy-gcp
```

### Terraform

```bash
cd deploy/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
terraform init && terraform apply
```

🚧 GCP path has not been validated against a live account.

---

## Section 7 — Azure AKS

**Status: ⚠️ Script exists — no Terraform, not tested end-to-end**

```bash
brew install azure-cli kubectl helm
az login
chmod +x deploy/cloud/azure/setup-azure.sh
make deploy-azure
```

🚧 No Terraform configuration for Azure. Script has not been validated
against a live account.

---

## Section 8 — Raw Kubernetes Manifests

**Status: ⚠️ Manifests exist — cover forwarder only, not full stack**

`deploy/kubernetes/` contains security-hardened manifests (NetworkPolicy
default-deny, non-root container, read-only root filesystem):

```bash
# See deploy/kubernetes/README.md for secrets handling guidance
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/networkpolicy.yaml
kubectl apply -f deploy/kubernetes/configmap.yaml
# Populate secret.yaml with real values via sealed-secrets or external-secrets
kubectl apply -f deploy/kubernetes/pvc.yaml
kubectl apply -f deploy/kubernetes/service.yaml
kubectl apply -f deploy/kubernetes/deployment.yaml
```

**Operations:**

```bash
make k8s-status   # kubectl get pods/svc -n audit-forwarder
make k8s-logs     # kubectl logs -f
make scan-k8s     # Trivy manifest security scan
```

🚧 Manifests deploy the **forwarder container only**. API, frontend, Caddy,
and Postgres are not yet represented as Kubernetes resources.

---

## Section 9 — Helm

**Status: ❌ No Helm chart exists**

`helm` is listed as a prerequisite in the cloud scripts, but this repo
contains no `Chart.yaml` or `values.yaml`. No AuditLens Helm chart has
been created.

🚧 Coming soon.

---

## Common Operations (all deployment types)

### Running migrations manually

```bash
# Inside the running API container
docker exec auditlens-api bash -c "cd /app/backend && python -m alembic upgrade head"

# Local dev against DATABASE_URL
make migrate
```

### Checking service health

```bash
# Via Caddy reverse proxy (standard path)
curl http://<host>/api/health
# → {"status":"ok","service":"auditlens-backend","database_mode":"postgres"}

# Forwarder direct (port 8003 must be accessible)
curl http://<host>:8003/health

# EC2 shortcut (uses SSH + curl internally)
make health
```

### Viewing logs

```bash
# EC2 — all services via SSH
make logs

# Direct Compose
docker compose -f docker-compose.prod.yml logs -f auditlens-forwarder
docker compose -f docker-compose.prod.yml logs -f auditlens-api
docker compose -f docker-compose.prod.yml logs -f auditlens-postgres

# Local dev
docker compose logs -f
```

### Backup (EC2 / any Docker host)

```bash
make backup-install   # Set up nightly 2am UTC cron on EC2
make backup-now       # Run immediately
make backup-list      # List backups + tail backup.log

# Manual (SSH onto host, or adapt for any environment)
bash ~/AuditLens/infra/backup/run_backup.sh
# Output: ~/backups/postgres/auditlens_<timestamp>.sql.gz
# Retention: 7 days (older files deleted automatically)
```

### Security scan

```bash
make scan-image   # Trivy scan of Docker image
make scan-k8s     # Trivy scan of K8s manifests
```

---

## Deployment Options Summary

| Option | Status | Entry point |
|---|---|---|
| Local (Mac / Linux) | ✅ Scripted + documented | `./setup` → `make start` |
| Local (Windows) | ❌ Not implemented | WSL2 workaround → Section 1 |
| EC2 / single VM | ✅ Scripted + documented | `make deploy` |
| AWS EKS | ⚠️ Script exists, untested | `make deploy-aws` |
| AWS ECS / Fargate | ⚠️ Terraform exists, untested | `cd deploy/terraform/aws && terraform apply` |
| GCP GKE | ⚠️ Script + Terraform exists, untested | `make deploy-gcp` |
| Azure AKS | ⚠️ Script exists, no Terraform, untested | `make deploy-azure` |
| Raw K8s manifests | ⚠️ Forwarder-only | `kubectl apply -f deploy/kubernetes/` |
| Helm | ❌ No chart exists | — |
| Confluent Cloud (Terraform) | ⚠️ Kafka resources only | `cd deploy/terraform/confluent-cloud && terraform apply` |
