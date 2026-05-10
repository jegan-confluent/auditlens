# Makefile for Audit Forwarder
# Production-ready build, test, and deployment tasks

.PHONY: help build build-alpine build-distroless test scan clean deploy migrate setup start stop restart status

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

# Default target
.DEFAULT_GOAL := help

# Configuration
IMAGE_NAME := audit-forwarder
VERSION := 2.1.0
REGISTRY ?= localhost
DOCKER_BUILDKIT := 1
export DOCKER_BUILDKIT

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

logs: ## View container logs
	docker logs -f audit-forwarder

##############################################################################
# Kubernetes Deployment
##############################################################################

deploy: ## Deploy to Kubernetes
	@echo "$(GREEN)Deploying to Kubernetes...$(NC)"
	kubectl apply -f deploy/kubernetes/deployment.yaml
	kubectl apply -f deploy/kubernetes/service.yaml
	@echo "$(GREEN)✓ Deployment complete$(NC)"

deploy-aws: ## Deploy to AWS EKS
	@echo "$(GREEN)Deploying to AWS EKS...$(NC)"
	./deploy/cloud/aws/setup-aws.sh

deploy-gcp: ## Deploy to GCP GKE
	@echo "$(GREEN)Deploying to GCP GKE...$(NC)"
	./deploy/cloud/gcp/setup-gcp.sh

deploy-azure: ## Deploy to Azure AKS
	@echo "$(GREEN)Deploying to Azure AKS...$(NC)"
	./deploy/cloud/azure/setup-azure.sh

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

health: ## Check health endpoint
	@echo "$(GREEN)Checking health...$(NC)"
	curl -s http://localhost:8003/health | jq

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

.PHONY: help build build-alpine build-distroless test scan clean deploy migrate
