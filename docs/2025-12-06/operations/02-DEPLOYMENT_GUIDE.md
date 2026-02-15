# Deployment & Operations Guide

**Document Version:** 1.0
**Last Updated:** December 6, 2025
**Audience:** DevOps, SRE, Platform Engineering

---

## Overview

This guide covers deployment of the Confluent Audit Log Intelligence System across different environments: local development, Docker Compose, and Kubernetes (production). It includes configuration management, upgrade procedures, backup strategies, and operational runbooks.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development Setup](#local-development-setup)
3. [Docker Compose Deployment](#docker-compose-deployment)
4. [Kubernetes Deployment](#kubernetes-deployment)
5. [Configuration Management](#configuration-management)
6. [Upgrade Procedures](#upgrade-procedures)
7. [Backup & Restore](#backup--restore)
8. [Operational Runbooks](#operational-runbooks)

---

## Prerequisites

### **Required Services**

| Service | Purpose | How to Obtain |
|---------|---------|---------------|
| **Confluent Cloud Account** | Kafka cluster hosting | https://confluent.cloud/signup |
| **Audit Log Cluster** | Source of audit events | Auto-created with Confluent Cloud |
| **Destination Kafka Cluster** | Enriched event storage | Create in Confluent Cloud |
| **Schema Registry** | JSON Schema validation | Enable in Confluent Cloud environment |
| **TableFlow Connector** | Kafka → Iceberg sync | Create in Confluent Cloud UI |
| **Kubernetes Cluster** (production) | Container orchestration | AWS EKS, GCP GKE, or Azure AKS |

### **Required Credentials**

You'll need to generate the following API keys in Confluent Cloud:

1. **Audit Log Consumer API Key:**
   ```bash
   confluent api-key create --resource lkc-xxxxx --description "Audit Log Consumer"
   ```

2. **Destination Producer API Key:**
   ```bash
   confluent api-key create --resource lkc-yyyyy --description "Destination Producer"
   ```

3. **Schema Registry API Key:**
   ```bash
   confluent api-key create --resource lsrc-zzzzz --description "Schema Registry"
   ```

4. **Confluent Cloud User Credentials:**
   - Email/password for Confluent CLI (used by dashboard for identity resolution)

---

## Local Development Setup

### **1. Install Dependencies**

**Python 3.9+ Required:**
```bash
# Verify Python version
python3 --version  # Should be 3.9 or higher

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

**Requirements:**
```txt
confluent-kafka==2.3.0
pyiceberg==0.5.1
streamlit==1.28.0
prometheus-client==0.19.0
pandas==2.1.3
plotly==5.18.0
python-dotenv==1.0.0
```

---

### **2. Configure Environment Variables**

**Create `.env` file:**
```bash
cat > .env << 'EOF'
# Audit Log Cluster (Source)
AUDIT_BOOTSTRAP=pkc-xxxxx.us-west-2.aws.confluent.cloud:9092
AUDIT_TOPIC=confluent-audit-log-events

# Destination Kafka Cluster
DEST_BOOTSTRAP=pkc-yyyyy.us-west-2.aws.confluent.cloud:9092
DEST_TOPIC=jegan_auditlog

# Schema Registry
SCHEMA_REGISTRY_URL=https://psrc-zzzzz.us-west-2.aws.confluent.cloud
SCHEMA_SUBJECT_NAME=jegan_auditlog-value

# Consumer Configuration
CONSUMER_GROUP_ID=audit-forwarder-group
OFFSET_FILE=offsets.json

# Processing Options
ENABLE_MULTI_TOPIC_ROUTING=false
DROP_LOW_EVENTS=false
AUDIT_ROUTER_DRY_RUN=false

# Metrics
METRICS_PORT=8000

# Dashboard (PyIceberg)
ICEBERG_CATALOG_URI=https://api.confluent.cloud/tableflow/v1
ICEBERG_WAREHOUSE=confluent-cloud
ICEBERG_TABLE=audit_events

# Dashboard (Confluent CLI for identity resolution)
CONFLUENT_CLOUD_EMAIL=your-email@company.com

# Logging
LOG_LEVEL=INFO
EOF
```

**Create `.secrets` file (NEVER commit to Git):**
```bash
cat > .secrets << 'EOF'
# Audit Log Cluster API Keys
AUDIT_API_KEY=YOUR_AUDIT_API_KEY
AUDIT_API_SECRET=YOUR_AUDIT_API_SECRET

# Destination Cluster API Keys
DEST_API_KEY=YOUR_DEST_API_KEY
DEST_API_SECRET=YOUR_DEST_API_SECRET

# Schema Registry API Keys
SCHEMA_REGISTRY_KEY=YOUR_SR_KEY
SCHEMA_REGISTRY_SECRET=YOUR_SR_SECRET

# Confluent Cloud Password (for CLI)
CONFLUENT_CLOUD_PASSWORD=YOUR_PASSWORD
EOF

# Add to .gitignore
echo ".secrets" >> .gitignore
```

---

### **3. Run Locally**

**Terminal 1: Start Forwarder**
```bash
source .env
source .secrets

python3 audit_forwarder.py
```

**Expected Output:**
```
INFO:audit_forwarder:Starting Confluent Audit Log Forwarder
INFO:audit_forwarder:Metrics server running on port 8000
INFO:audit_forwarder:Consumer assigned partitions: [0, 1, 2]
INFO:audit_forwarder:Resuming confluent-audit-log-events_0 from offset 123456
INFO:audit_forwarder:Processing events...
```

**Terminal 2: Start Dashboard**
```bash
source .env
source .secrets

streamlit run dashboard/app.py --server.port 8504
```

**Access Dashboard:**
- Open browser: http://localhost:8504

---

### **4. Verify Setup**

```bash
# Check forwarder metrics
curl http://localhost:8000/metrics

# Expected output:
# audit_events_processed_total{criticality="CRITICAL"} 123
# audit_events_processed_total{criticality="HIGH"} 456
# ...

# Check offset file
cat offsets.json
# Expected: {"confluent-audit-log-events_0": 123456, ...}

# Check consumer lag
confluent kafka consumer group describe audit-forwarder-group \
  --cluster lkc-xxxxx
```

---

## Docker Compose Deployment

**Best for:** Staging environments, testing, or small-scale production

### **1. Create Docker Compose File**

**File:** `docker-compose.yml`
```yaml
version: '3.8'

services:
  audit-forwarder:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: audit-forwarder
    restart: unless-stopped
    env_file:
      - .env
      - .secrets
    ports:
      - "8000:8000"  # Prometheus metrics
    volumes:
      - ./offsets.json:/app/offsets.json
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - audit-network

  audit-dashboard:
    build:
      context: ./dashboard
      dockerfile: Dockerfile
    container_name: audit-dashboard
    restart: unless-stopped
    env_file:
      - .env
      - .secrets
    ports:
      - "8504:8504"  # Streamlit UI
    depends_on:
      - audit-forwarder
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8504/_stcore/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - audit-network

  prometheus:
    image: prom/prometheus:v2.48.0
    container_name: prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./deploy/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=7d'
    networks:
      - audit-network

  grafana:
    image: grafana/grafana:10.2.0
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=changeme
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana-data:/var/lib/grafana
      - ./deploy/grafana/dashboards:/etc/grafana/provisioning/dashboards
    depends_on:
      - prometheus
    networks:
      - audit-network

networks:
  audit-network:
    driver: bridge

volumes:
  prometheus-data:
  grafana-data:
```

---

### **2. Create Dockerfiles**

**Forwarder Dockerfile:**
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY audit_forwarder.py .
COPY src/ ./src/

# Create offsets directory
RUN mkdir -p /app/offsets

# Expose metrics port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run forwarder
CMD ["python3", "audit_forwarder.py"]
```

**Dashboard Dockerfile:**
```dockerfile
# dashboard/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Confluent CLI (for identity resolution)
RUN curl -sL --http1.1 https://cnfl.io/cli | sh -s -- latest

# Copy dashboard code
COPY app.py .

# Expose Streamlit port
EXPOSE 8504

# Run dashboard
CMD ["streamlit", "run", "app.py", "--server.port=8504", "--server.headless=true"]
```

---

### **3. Deploy with Docker Compose**

```bash
# Build images
docker-compose build

# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f audit-forwarder
docker-compose logs -f audit-dashboard

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

---

### **4. Access Services**

- **Forwarder Metrics:** http://localhost:8000/metrics
- **Dashboard:** http://localhost:8504
- **Prometheus:** http://localhost:9090
- **Grafana:** http://localhost:3000 (admin/changeme)

---

## Kubernetes Deployment

**Best for:** Production environments requiring high availability and scalability

### **1. Create Namespace**

```bash
kubectl create namespace audit-system
```

---

### **2. Create Secrets**

```bash
# Create secret from .secrets file
kubectl create secret generic audit-forwarder-secrets \
  --from-literal=AUDIT_API_KEY='YOUR_AUDIT_API_KEY' \
  --from-literal=AUDIT_API_SECRET='YOUR_AUDIT_API_SECRET' \
  --from-literal=DEST_API_KEY='YOUR_DEST_API_KEY' \
  --from-literal=DEST_API_SECRET='YOUR_DEST_API_SECRET' \
  --from-literal=SCHEMA_REGISTRY_KEY='YOUR_SR_KEY' \
  --from-literal=SCHEMA_REGISTRY_SECRET='YOUR_SR_SECRET' \
  --from-literal=CONFLUENT_CLOUD_EMAIL='your-email@company.com' \
  --from-literal=CONFLUENT_CLOUD_PASSWORD='YOUR_PASSWORD' \
  --namespace=audit-system
```

---

### **3. Create ConfigMap**

```yaml
# deploy/kubernetes/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: audit-forwarder-config
  namespace: audit-system
data:
  AUDIT_BOOTSTRAP: "pkc-xxxxx.us-west-2.aws.confluent.cloud:9092"
  AUDIT_TOPIC: "confluent-audit-log-events"
  DEST_BOOTSTRAP: "pkc-yyyyy.us-west-2.aws.confluent.cloud:9092"
  DEST_TOPIC: "jegan_auditlog"
  SCHEMA_REGISTRY_URL: "https://psrc-zzzzz.us-west-2.aws.confluent.cloud"
  SCHEMA_SUBJECT_NAME: "jegan_auditlog-value"
  CONSUMER_GROUP_ID: "audit-forwarder-group"
  OFFSET_FILE: "/data/offsets.json"
  ENABLE_MULTI_TOPIC_ROUTING: "false"
  DROP_LOW_EVENTS: "false"
  METRICS_PORT: "8000"
  LOG_LEVEL: "INFO"
  ICEBERG_CATALOG_URI: "https://api.confluent.cloud/tableflow/v1"
  ICEBERG_WAREHOUSE: "confluent-cloud"
  ICEBERG_TABLE: "audit_events"
```

```bash
kubectl apply -f deploy/kubernetes/configmap.yaml
```

---

### **4. Create Persistent Volume Claim (for offsets)**

```yaml
# deploy/kubernetes/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: forwarder-offsets-pvc
  namespace: audit-system
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: gp3  # AWS EBS gp3, adjust for your cloud provider
```

```bash
kubectl apply -f deploy/kubernetes/pvc.yaml
```

---

### **5. Deploy Forwarder**

```yaml
# deploy/kubernetes/forwarder-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: audit-forwarder
  namespace: audit-system
  labels:
    app: audit-forwarder
spec:
  replicas: 3  # High availability
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: audit-forwarder
  template:
    metadata:
      labels:
        app: audit-forwarder
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000

      containers:
      - name: forwarder
        image: your-registry/audit-forwarder:latest
        imagePullPolicy: Always

        envFrom:
        - configMapRef:
            name: audit-forwarder-config
        - secretRef:
            name: audit-forwarder-secrets

        ports:
        - containerPort: 8000
          name: metrics
          protocol: TCP

        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2000m
            memory: 4Gi

        volumeMounts:
        - name: offsets
          mountPath: /data

        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          failureThreshold: 3

        readinessProbe:
          httpGet:
            path: /metrics
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5

        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: false  # Need to write offset file
          capabilities:
            drop:
              - ALL

      volumes:
      - name: offsets
        persistentVolumeClaim:
          claimName: forwarder-offsets-pvc

      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - audit-forwarder
              topologyKey: kubernetes.io/hostname
---
apiVersion: v1
kind: Service
metadata:
  name: audit-forwarder
  namespace: audit-system
spec:
  selector:
    app: audit-forwarder
  ports:
  - name: metrics
    port: 8000
    targetPort: 8000
  type: ClusterIP
```

```bash
kubectl apply -f deploy/kubernetes/forwarder-deployment.yaml
```

---

### **6. Deploy Dashboard**

```yaml
# deploy/kubernetes/dashboard-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: audit-dashboard
  namespace: audit-system
  labels:
    app: audit-dashboard
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: audit-dashboard
  template:
    metadata:
      labels:
        app: audit-dashboard
    spec:
      containers:
      - name: dashboard
        image: your-registry/audit-dashboard:latest
        imagePullPolicy: Always

        envFrom:
        - configMapRef:
            name: audit-forwarder-config
        - secretRef:
            name: audit-forwarder-secrets

        ports:
        - containerPort: 8504
          name: http
          protocol: TCP

        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 2Gi

        livenessProbe:
          httpGet:
            path: /_stcore/health
            port: 8504
          initialDelaySeconds: 30
          periodSeconds: 10

        readinessProbe:
          httpGet:
            path: /_stcore/health
            port: 8504
          initialDelaySeconds: 10
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: audit-dashboard
  namespace: audit-system
spec:
  selector:
    app: audit-dashboard
  ports:
  - name: http
    port: 8504
    targetPort: 8504
  type: LoadBalancer  # Or ClusterIP if using Ingress
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: audit-dashboard-ingress
  namespace: audit-system
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
  - hosts:
    - audit.company.com
    secretName: audit-dashboard-tls
  rules:
  - host: audit.company.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: audit-dashboard
            port:
              number: 8504
```

```bash
kubectl apply -f deploy/kubernetes/dashboard-deployment.yaml
```

---

### **7. Verify Deployment**

```bash
# Check pods
kubectl get pods -n audit-system

# Expected output:
# NAME                               READY   STATUS    RESTARTS   AGE
# audit-forwarder-7c9f8b6d4-abc12   1/1     Running   0          5m
# audit-forwarder-7c9f8b6d4-def34   1/1     Running   0          5m
# audit-forwarder-7c9f8b6d4-ghi56   1/1     Running   0          5m
# audit-dashboard-5d8c7a9b2-xyz78   1/1     Running   0          3m

# Check logs
kubectl logs -n audit-system deployment/audit-forwarder --tail=100

# Check metrics endpoint
kubectl port-forward -n audit-system svc/audit-forwarder 8000:8000
curl http://localhost:8000/metrics

# Access dashboard
kubectl port-forward -n audit-system svc/audit-dashboard 8504:8504
# Open browser: http://localhost:8504
```

---

## Configuration Management

### **Environment-Specific Configuration**

**Development:**
```yaml
# config/dev.yaml
replicas: 1
resources:
  requests:
    cpu: 250m
    memory: 512Mi
retention:
  kafka: 3d
  iceberg: 7d
logging:
  level: DEBUG
```

**Staging:**
```yaml
# config/staging.yaml
replicas: 2
resources:
  requests:
    cpu: 500m
    memory: 1Gi
retention:
  kafka: 7d
  iceberg: 30d
logging:
  level: INFO
```

**Production:**
```yaml
# config/production.yaml
replicas: 3
resources:
  requests:
    cpu: 1000m
    memory: 2Gi
  limits:
    cpu: 2000m
    memory: 4Gi
retention:
  kafka: 7d
  iceberg: 90d
logging:
  level: WARNING
highAvailability:
  enabled: true
  antiAffinity: true
```

### **Using Kustomize**

```bash
# Directory structure:
# deploy/kubernetes/
#   base/
#     deployment.yaml
#     service.yaml
#     kustomization.yaml
#   overlays/
#     dev/
#       kustomization.yaml
#     staging/
#       kustomization.yaml
#     production/
#       kustomization.yaml

# Deploy to production
kubectl apply -k deploy/kubernetes/overlays/production
```

---

## Upgrade Procedures

### **Rolling Update (Zero Downtime)**

**1. Build New Image:**
```bash
docker build -t your-registry/audit-forwarder:v2.0.0 .
docker push your-registry/audit-forwarder:v2.0.0
```

**2. Update Deployment:**
```bash
kubectl set image deployment/audit-forwarder \
  forwarder=your-registry/audit-forwarder:v2.0.0 \
  -n audit-system

# Watch rollout status
kubectl rollout status deployment/audit-forwarder -n audit-system
```

**3. Verify:**
```bash
# Check new pods running
kubectl get pods -n audit-system

# Check logs for errors
kubectl logs -n audit-system deployment/audit-forwarder --tail=100

# Verify metrics
kubectl port-forward -n audit-system svc/audit-forwarder 8000:8000
curl http://localhost:8000/metrics | grep audit_events_total
```

**4. Rollback if Needed:**
```bash
kubectl rollout undo deployment/audit-forwarder -n audit-system

# Rollback to specific revision
kubectl rollout history deployment/audit-forwarder -n audit-system
kubectl rollout undo deployment/audit-forwarder --to-revision=3 -n audit-system
```

---

### **Blue-Green Deployment**

```bash
# 1. Deploy new version (green)
kubectl apply -f deploy/kubernetes/forwarder-deployment-green.yaml

# 2. Test green deployment
kubectl port-forward svc/audit-forwarder-green 8000:8000
curl http://localhost:8000/metrics

# 3. Switch traffic to green
kubectl patch service audit-forwarder -n audit-system \
  -p '{"spec":{"selector":{"version":"green"}}}'

# 4. Decommission blue after verification
kubectl delete deployment audit-forwarder-blue -n audit-system
```

---

## Backup & Restore

### **1. Backup Offset File**

**Manual Backup:**
```bash
# Kubernetes
kubectl exec -n audit-system deployment/audit-forwarder -- \
  cat /data/offsets.json > offsets-backup-$(date +%Y%m%d).json

# Docker Compose
docker cp audit-forwarder:/app/offsets.json offsets-backup-$(date +%Y%m%d).json
```

**Automated Backup (CronJob):**
```yaml
# deploy/kubernetes/backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: offset-backup
  namespace: audit-system
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: busybox
            command:
            - /bin/sh
            - -c
            - cp /data/offsets.json /backups/offsets-$(date +\%Y\%m\%d-\%H\%M).json
            volumeMounts:
            - name: offsets
              mountPath: /data
            - name: backups
              mountPath: /backups
          restartPolicy: OnFailure
          volumes:
          - name: offsets
            persistentVolumeClaim:
              claimName: forwarder-offsets-pvc
          - name: backups
            persistentVolumeClaim:
              claimName: offset-backups-pvc
```

---

### **2. Restore Offset File**

```bash
# Kubernetes
kubectl cp offsets-backup-20251206.json \
  audit-system/audit-forwarder-7c9f8b6d4-abc12:/data/offsets.json

# Restart forwarder to pick up restored offset
kubectl rollout restart deployment/audit-forwarder -n audit-system

# Docker Compose
docker cp offsets-backup-20251206.json audit-forwarder:/app/offsets.json
docker-compose restart audit-forwarder
```

---

### **3. Backup Prometheus Data**

```bash
# Kubernetes (using VolumeSnapshot)
kubectl apply -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: prometheus-snapshot-$(date +%Y%m%d)
  namespace: audit-system
spec:
  volumeSnapshotClassName: ebs-csi-snapshot-class
  source:
    persistentVolumeClaimName: prometheus-storage
EOF
```

---

## Operational Runbooks

### **Runbook 1: Scale Forwarder for High Load**

**Symptom:** Consumer lag increasing, processing latency high

**Solution:**
```bash
# Horizontal scaling
kubectl scale deployment audit-forwarder --replicas=5 -n audit-system

# Verify scaling
kubectl get pods -n audit-system | grep forwarder

# Check consumer lag after 5 minutes
kubectl exec -n audit-system deployment/audit-forwarder -- \
  curl -s localhost:8000/metrics | grep consumer_lag
```

---

### **Runbook 2: Emergency Stop**

**Scenario:** Critical bug detected, need to stop processing immediately

**Procedure:**
```bash
# Stop forwarder (preserves offsets)
kubectl scale deployment audit-forwarder --replicas=0 -n audit-system

# Verify stopped
kubectl get pods -n audit-system | grep forwarder
# Should show no pods

# Resume when ready
kubectl scale deployment audit-forwarder --replicas=3 -n audit-system
```

---

### **Runbook 3: Disaster Recovery**

**Scenario:** Complete cluster failure, need to rebuild from scratch

**Recovery Steps:**
```bash
# 1. Restore configuration
kubectl apply -f deploy/kubernetes/configmap.yaml
kubectl apply -f deploy/kubernetes/secrets.yaml

# 2. Restore offset file from backup
kubectl cp offsets-backup.json audit-system/audit-forwarder:/data/offsets.json

# 3. Deploy forwarder
kubectl apply -f deploy/kubernetes/forwarder-deployment.yaml

# 4. Verify recovery
kubectl logs -f deployment/audit-forwarder -n audit-system

# 5. Check consumer lag
confluent kafka consumer group describe audit-forwarder-group --cluster lkc-xxxxx
```

---

## Deployment Checklist

**Pre-Deployment:**
- [ ] Verify all API keys are valid and not expired
- [ ] Check Confluent Cloud cluster health
- [ ] Review and update `.env` configuration
- [ ] Test configuration in dev environment
- [ ] Back up current offset file
- [ ] Review recent changes in Git

**Deployment:**
- [ ] Build and push Docker images
- [ ] Apply Kubernetes manifests (or docker-compose up)
- [ ] Verify pods/containers started successfully
- [ ] Check logs for errors
- [ ] Verify metrics endpoint responding
- [ ] Test dashboard accessibility

**Post-Deployment:**
- [ ] Monitor consumer lag for 30 minutes
- [ ] Check DLQ for any failed events
- [ ] Verify anomaly detection working
- [ ] Test dashboard queries
- [ ] Update deployment documentation
- [ ] Notify team in Slack

---

## Contact Information

**DevOps Team:** devops@company.com
**On-Call:** PagerDuty rotation
**Confluent Support:** https://support.confluent.io
