# Makefile for Audit Forwarder
# Production-ready build, test, and deployment tasks

.PHONY: help build build-alpine build-distroless test scan clean deploy deploy-check migrate setup start stop restart status monitoring logs health ps sync backup backup-list backup-list-remote backup-restore update update-check repair

##############################################################################
# Quickstart Lifecycle (Phase 3 — single-command install + service control)
##############################################################################

setup: ## Run the guided setup wizard (./setup)
	@./setup

start: ## Start all services via docker compose
	docker compose up -d
	@echo ""
	@echo "✅  AuditLens started."
	@echo "    UI:     http://localhost:3000"
	@echo "    API:    http://localhost:8080"
	@echo "    Health: http://localhost:8003/health"
	@echo ""

stop: ## Stop all services
	docker compose down

restart: ## Restart all services
	docker compose down
	docker compose up -d

status: ## Show service health (compose ps + API + forwarder)
	@echo ""
	@docker compose ps
	@echo ""
	@curl -s --max-time 3 http://localhost:8080/health 2>/dev/null \
	  | python3 -c "import json,sys; d=json.load(sys.stdin); print('API:', d.get('status'), '|', d.get('database_mode'))" \
	  || echo "API: unreachable"
	@curl -s --max-time 3 http://localhost:8003/health 2>/dev/null \
	  | python3 -c "import json,sys; d=json.load(sys.stdin); print('Forwarder:', d.get('status'), '| rate:', round(d.get('processing_rate', 0), 1), 'msg/s | lag:', '{:,}'.format(d.get('consumer_lag', 0)))" \
	  || echo "Forwarder: unreachable"
	@echo ""

monitoring: ## Show monitoring URLs
	@echo ""
	@echo "Grafana:    http://localhost:3001 (admin/admin)"
	@echo "Prometheus: http://localhost:9090"
	@echo ""

##############################################################################
# Update flow for an already-running deployment
#   - `make update`        : git pull → docker compose pull → up -d --build → migrate
#   - `make update-check`  : does NOT modify anything; just compares HEAD ↔ origin/main
#
# Both are safe to run repeatedly. The migrate step is best-effort — the api
# container's own entrypoint also runs alembic upgrade on start, so a
# transient failure here doesn't leave the DB in a bad state.
##############################################################################

update: ## Pull latest + rebuild containers + run migrations
	@echo "⬆  Pulling latest AuditLens..."
	@git pull origin main
	@echo "ℹ  Rebuilding and restarting containers..."
	@docker compose -f docker-compose.prod.yml pull --quiet
	@docker compose -f docker-compose.prod.yml up -d --build
	@echo "ℹ  Running migrations..."
	@docker exec auditlens-api bash -c \
	  "cd /app/backend && python -m alembic upgrade head" 2>/dev/null || \
	  echo "⚠  Migration step failed — check manually"
	@echo "✅  AuditLens updated to $$(git rev-parse --short HEAD)"

update-check: ## Check if a remote update exists (no changes)
	@git fetch origin main --quiet 2>/dev/null || true
	@LOCAL=$$(git rev-parse HEAD); \
	 REMOTE=$$(git rev-parse origin/main 2>/dev/null); \
	 if [ "$$LOCAL" = "$$REMOTE" ]; then \
	   echo "✅  Already up to date ($$(git rev-parse --short HEAD))"; \
	 else \
	   echo "⬆  Update available: $$(git rev-parse --short HEAD) → $$(git rev-parse --short origin/main)"; \
	   echo "   Run: make update"; \
	 fi

repair: ## Heal a broken install — pull, patch .env, rebuild, migrate (no credential re-entry)
	@echo "🔧  Repairing AuditLens install..."
	@echo "ℹ  Step 1/4 — Pulling latest code..."
	@git pull origin main --quiet
	@echo "ℹ  Step 2/4 — Patching .env with any missing config..."
	@AUDITLENS_NO_UPDATE=1 AUDITLENS_REPAIR_ONLY=1 ./setup --migrate-env-only
	@echo "ℹ  Step 3/4 — Rebuilding containers..."
	@docker compose -f docker-compose.prod.yml pull --quiet 2>/dev/null || true
	@docker compose -f docker-compose.prod.yml up -d --build --quiet-pull
	@echo "ℹ  Step 4/4 — Running migrations..."
	@docker exec auditlens-api bash -c \
	  "cd /app/backend && python -m alembic upgrade head" 2>/dev/null || \
	  echo "⚠  Migration step skipped"
	@echo ""
	@echo "✅  Repair complete. Open your browser:"
	@if [ "$$(uname -s)" = "Darwin" ]; then \
	  echo "   http://localhost:8088"; \
	else \
	  echo "   http://$$(curl -s --max-time 1 \
	    http://169.254.169.254/latest/meta-data/public-ipv4 \
	    2>/dev/null || hostname -I | awk '{print $$1}')"; \
	fi

##############################################################################
# Postgres backup / restore
#   - `make backup` writes a gzipped pg_dump to backups/auditlens-<ts>.sql.gz
#   - `make backup-list` shows the most recent backups (newest first)
#   - `make backup-restore FILE=backups/auditlens-…sql.gz` pipes the dump
#     back into the running postgres container. NEVER runs without an
#     explicit FILE= to avoid an accidental restore from the wrong dump.
#
# The backup target reuses the running auditlens-postgres container so it
# works against the live deployment without needing direct DB credentials
# on the host — Postgres credentials stay inside the container.
##############################################################################

backup: ## Snapshot the AuditLens Postgres database to backups/
	@echo "Backing up AuditLens Postgres database..."
	@mkdir -p backups
	@ts=$$(date +%Y%m%d-%H%M%S); \
	  out="backups/auditlens-$${ts}.sql.gz"; \
	  docker exec auditlens-postgres pg_dump \
	    -U $${POSTGRES_USER:-auditlens} \
	    -d $${POSTGRES_DB:-auditlens} \
	    --no-owner --no-acl \
	  | gzip > "$$out" \
	  && echo "✅  Backup saved to $$out"

backup-list: ## List existing Postgres backups (newest first)
	@ls -lth backups/*.sql.gz 2>/dev/null || echo "No backups found."

backup-restore: ## Restore a Postgres backup: make backup-restore FILE=backups/<file>.sql.gz
	@test -n "$${FILE}" || (echo "❌  FILE is required, e.g. make backup-restore FILE=backups/auditlens-YYYYMMDD-HHMMSS.sql.gz" && exit 1)
	@test -f "$${FILE}" || (echo "❌  $${FILE} does not exist" && exit 1)
	@echo "Restoring $${FILE} into auditlens-postgres..."
	@gunzip -c $${FILE} | docker exec -i auditlens-postgres psql \
	  -U $${POSTGRES_USER:-auditlens} \
	  -d $${POSTGRES_DB:-auditlens}
	@echo "✅  Restore complete."

# Default target
.DEFAULT_GOAL := help

# Configuration
IMAGE_NAME := audit-forwarder
VERSION := 2.1.0
REGISTRY ?= localhost
DOCKER_BUILDKIT := 1
export DOCKER_BUILDKIT

# EC2 deployment config — update before running make deploy
EC2_IP    ?= 98.95.144.160
EC2_USER  ?= ec2-user
PEM       ?= ~/.ssh/auditlens.pem
REMOTE     = $(EC2_USER)@$(EC2_IP):~/AuditLens/

# Colors for output
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
NC     := \033[0m# No Color

help: ## Show this help message
	@echo "$(GREEN)Audit Forwarder - Available Commands:$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

##############################################################################
# Build Targets
##############################################################################

build: ## Build standard Debian-based Docker image
	@echo "$(GREEN)Building standard image...$(NC)"
	docker build -t $(IMAGE_NAME):$(VERSION) .
	docker tag $(IMAGE_NAME):$(VERSION) $(IMAGE_NAME):latest
	@echo "$(GREEN)✓ Build complete$(NC)"

build-alpine: ## Build Alpine-based Docker image (smallest)
	@echo "$(GREEN)Building Alpine image...$(NC)"
	docker build -f Dockerfile.alpine -t $(IMAGE_NAME):$(VERSION)-alpine .
	docker tag $(IMAGE_NAME):$(VERSION)-alpine $(IMAGE_NAME):alpine
	@echo "$(GREEN)✓ Alpine build complete$(NC)"

build-distroless: ## Build distroless Docker image (most secure)
	@echo "$(GREEN)Building distroless image...$(NC)"
	docker build -f Dockerfile.distroless -t $(IMAGE_NAME):$(VERSION)-distroless .
	docker tag $(IMAGE_NAME):$(VERSION)-distroless $(IMAGE_NAME):distroless
	@echo "$(GREEN)✓ Distroless build complete$(NC)"

build-all: build build-alpine build-distroless ## Build all image variants

##############################################################################
# Testing & Quality
##############################################################################

test: ## Run unit tests
	@echo "$(GREEN)Running tests...$(NC)"
	python -m pytest tests/ -v
	@echo "$(GREEN)✓ Tests passed$(NC)"

migrate: ## Apply Alembic migrations to the configured DATABASE_URL (Postgres production path)
	@echo "$(GREEN)Applying Alembic migrations...$(NC)"
	cd backend && alembic upgrade head
	@echo "$(GREEN)✓ Migrations applied$(NC)"

lint: ## Run code linting
	@echo "$(GREEN)Running linters...$(NC)"
	flake8 audit_forwarder.py src/
	pylint audit_forwarder.py src/
	black --check audit_forwarder.py src/
	@echo "$(GREEN)✓ Linting passed$(NC)"

format: ## Format code with black
	@echo "$(GREEN)Formatting code...$(NC)"
	black audit_forwarder.py src/
	@echo "$(GREEN)✓ Code formatted$(NC)"

##############################################################################
# Security Scanning
##############################################################################

scan: ## Run all security scans
	@echo "$(GREEN)Running security scans...$(NC)"
	./scripts/security-scan.sh all
	@echo "$(GREEN)✓ Security scans complete$(NC)"

scan-image: build ## Scan Docker image for vulnerabilities
	@echo "$(GREEN)Scanning Docker image...$(NC)"
	./scripts/security-scan.sh image
	@echo "$(GREEN)✓ Image scan complete$(NC)"

scan-fs: ## Scan filesystem for vulnerabilities
	@echo "$(GREEN)Scanning filesystem...$(NC)"
	./scripts/security-scan.sh fs
	@echo "$(GREEN)✓ Filesystem scan complete$(NC)"

scan-k8s: ## Scan Kubernetes manifests
	@echo "$(GREEN)Scanning Kubernetes manifests...$(NC)"
	./scripts/security-scan.sh k8s
	@echo "$(GREEN)✓ Kubernetes scan complete$(NC)"

scan-secrets: ## Scan for exposed secrets
	@echo "$(GREEN)Scanning for secrets...$(NC)"
	./scripts/security-scan.sh secrets
	@echo "$(GREEN)✓ Secret scan complete$(NC)"

##############################################################################
# Docker Operations
##############################################################################

push: ## Push image to registry
	@echo "$(GREEN)Pushing image to $(REGISTRY)...$(NC)"
	docker tag $(IMAGE_NAME):$(VERSION) $(REGISTRY)/$(IMAGE_NAME):$(VERSION)
	docker tag $(IMAGE_NAME):$(VERSION) $(REGISTRY)/$(IMAGE_NAME):latest
	docker push $(REGISTRY)/$(IMAGE_NAME):$(VERSION)
	docker push $(REGISTRY)/$(IMAGE_NAME):latest
	@echo "$(GREEN)✓ Push complete$(NC)"

run: ## Run container locally
	@echo "$(GREEN)Starting container...$(NC)"
	docker run --rm -it \
		--name audit-forwarder \
		--env-file .env \
		--env-file .secrets \
		-p 8003:8003 \
		-v $(PWD)/data:/app/data \
		$(IMAGE_NAME):$(VERSION)

run-compose: ## Run with docker-compose
	@echo "$(GREEN)Starting services with docker-compose...$(NC)"
	docker-compose up -d
	@echo "$(GREEN)✓ Services started$(NC)"

stop-compose: ## Stop docker-compose services
	@echo "$(GREEN)Stopping services...$(NC)"
	docker-compose down
	@echo "$(GREEN)✓ Services stopped$(NC)"

logs: ## Tail EC2 prod logs
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"cd ~/AuditLens && \
		docker compose -f docker-compose.prod.yml logs -f --tail=50"

##############################################################################
# EC2 Deployment
##############################################################################

deploy: ## Rsync to EC2 + rebuild containers
	@echo "→ Syncing to EC2 $(EC2_IP)..."
	rsync -avz -e "ssh -i $(PEM)" --progress \
		--exclude='.venv' \
		--exclude='node_modules' \
		--exclude='frontend/.next' \
		--exclude='__pycache__' \
		--exclude='**/*.pyc' \
		--exclude='.git' \
		--exclude='logs' \
		--exclude='data' \
		--exclude='*.log' \
		--exclude='.env' \
		--exclude='.secrets' \
		./ $(REMOTE)
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"sudo chown -R 1000:1000 ~/AuditLens/src ~/AuditLens/prometheus && \
		 sudo chmod -R 755 ~/AuditLens/prometheus/alerts/"
	@echo "→ Rebuilding and restarting on EC2..."
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"cd ~/AuditLens && \
		docker compose -f docker-compose.prod.yml up -d --build --force-recreate --remove-orphans 2>&1 | tail -5 && \
		echo '→ Waiting for API to be ready...' && \
		sleep 10 && \
		echo '→ Running database migrations...' && \
		docker exec auditlens-postgres psql -U auditlens -d auditlens -c 'SELECT version_num FROM alembic_version;' \
		&& echo '✅  Migrations applied.' \
		|| echo '⚠️  Migration step failed — check manually with: docker exec auditlens-api bash -c \"cd /app/backend && python -m alembic upgrade head\"'"
	@echo "✅  Deploy complete — code + migrations."

deploy-check: ## Dry-run rsync (shows what would change)
	rsync -avzn --progress \
		--exclude='.venv' \
		--exclude='node_modules' \
		--exclude='frontend/.next' \
		--exclude='__pycache__' \
		--exclude='**/*.pyc' \
		--exclude='.git' \
		--exclude='logs' \
		--exclude='data' \
		--exclude='*.log' \
		--exclude='.env' \
		--exclude='.secrets' \
		./ $(REMOTE)

deploy-aws: ## Deploy to AWS EKS
	@echo "$(GREEN)Deploying to AWS EKS...$(NC)"
	./deploy/cloud/aws/setup-aws.sh

deploy-gcp: ## Deploy to GCP GKE
	@echo "$(GREEN)Deploying to GCP GKE...$(NC)"
	./deploy/cloud/gcp/setup-gcp.sh

deploy-azure: ## Deploy to Azure AKS
	@echo "$(GREEN)Deploying to Azure AKS...$(NC)"
	./deploy/cloud/azure/setup-azure.sh

ps: ## Show EC2 container status
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"cd ~/AuditLens && \
		docker compose -f docker-compose.prod.yml ps"

backup-install: ## Install pg_dump cron on EC2 (runs daily at 2am)
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"mkdir -p ~/backups/postgres && \
		chmod +x ~/AuditLens/infra/backup/run_backup.sh && \
		(crontab -l 2>/dev/null | grep -v run_backup; \
		echo '0 2 * * * /home/ec2-user/AuditLens/infra/backup/run_backup.sh') | crontab -"
	@echo "✅ Backup cron installed — runs daily at 2am UTC"

backup-now: ## Run backup immediately on EC2
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"bash ~/AuditLens/infra/backup/run_backup.sh"
	@echo "✅ Backup complete"

backup-list-remote: ## List backups on EC2 (remote ~/backups/postgres/)
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"ls -lh ~/backups/postgres/ && echo '---' && tail -5 ~/backups/backup.log"

k8s-status: ## Check Kubernetes deployment status
	@echo "$(GREEN)Checking deployment status...$(NC)"
	kubectl get pods -n audit-forwarder
	kubectl get svc -n audit-forwarder

k8s-logs: ## View Kubernetes pod logs
	kubectl logs -f -n audit-forwarder -l app.kubernetes.io/name=audit-forwarder

##############################################################################
# Cleanup
##############################################################################

clean: ## Clean build artifacts and cache
	@echo "$(GREEN)Cleaning build artifacts...$(NC)"
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -delete
	find . -type d -name '.pytest_cache' -delete
	find . -type d -name '.trivycache' -delete
	rm -rf build/ dist/ *.egg-info
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

clean-docker: ## Remove Docker images
	@echo "$(GREEN)Removing Docker images...$(NC)"
	docker rmi $(IMAGE_NAME):$(VERSION) || true
	docker rmi $(IMAGE_NAME):latest || true
	docker rmi $(IMAGE_NAME):$(VERSION)-alpine || true
	docker rmi $(IMAGE_NAME):$(VERSION)-distroless || true
	@echo "$(GREEN)✓ Docker cleanup complete$(NC)"

clean-all: clean clean-docker ## Clean everything
	@echo "$(GREEN)✓ Full cleanup complete$(NC)"

##############################################################################
# Development
##############################################################################

dev-setup: ## Set up development environment
	@echo "$(GREEN)Setting up development environment...$(NC)"
	pip install -r requirements.txt
	pip install -r requirements-dev.txt
	@echo "$(GREEN)✓ Development environment ready$(NC)"

dev-run: ## Run forwarder in development mode
	@echo "$(GREEN)Starting forwarder in dev mode...$(NC)"
	source .env && source .secrets && python audit_forwarder.py

##############################################################################
# CI/CD
##############################################################################

ci: lint test scan-image ## Run CI pipeline (lint, test, scan)
	@echo "$(GREEN)✓ CI pipeline complete$(NC)"

release: ci build push ## Create release (CI + build + push)
	@echo "$(GREEN)✓ Release $(VERSION) complete$(NC)"

##############################################################################
# Monitoring
##############################################################################

metrics: ## View Prometheus metrics
	@echo "$(GREEN)Fetching metrics...$(NC)"
	curl -s http://localhost:8003/metrics | grep audit_

health: ## Check EC2 forwarder + API health
	@echo "=== Forwarder ==="
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"curl -s http://localhost:8003/health | \
		python3 -c \"import json,sys; d=json.load(sys.stdin); \
		print('Status:', d.get('status')); \
		print('Processed:', d.get('processed_total', 0)); \
		print('Lag:', f\\\"{d.get('consumer_lag', 0):,}\\\"); \
		print('DB Writer:', d.get('db_writer_status', 'n/a'))\""
	@echo ""
	@echo "=== API ==="
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) \
		"curl -s http://localhost:8080/health | \
		python3 -c \"import json,sys; d=json.load(sys.stdin); \
		print('Status:', d.get('status'))\""

##############################################################################
# Utilities
##############################################################################

shell: ## Open shell in running container
	docker exec -it audit-forwarder /bin/bash

size: ## Show image sizes
	@echo "$(GREEN)Image sizes:$(NC)"
	@docker images $(IMAGE_NAME) --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

version: ## Show version information
	@echo "$(GREEN)Audit Forwarder $(VERSION)$(NC)"
	@echo "Docker: $$(docker --version)"
	@echo "Trivy: $$(trivy --version | head -1)"

sync: ## Sync files to EC2 without restart
	rsync -avz -e "ssh -i $(PEM)" \
	  --exclude='.git' \
	  --exclude='.env' \
	  --exclude='.secrets' \
	  --exclude='.venv' \
	  --exclude='__pycache__' \
	  --exclude='*.pyc' \
	  --exclude='node_modules' \
	  --exclude='.next' \
	  ./ $(REMOTE)

health-check-full: ## Run full 7-section health check on EC2
	ssh -i $(PEM) $(EC2_USER)@$(EC2_IP) "bash ~/AuditLens/scripts/health_check_full.sh"
