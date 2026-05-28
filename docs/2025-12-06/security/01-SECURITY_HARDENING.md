# Security Hardening & Best Practices

**Document Version:** 1.0
**Last Updated:** December 6, 2025
**Classification:** Internal Use Only

---

## Security Architecture

### **Defense in Depth**

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Network Security                                   │
│  ✓ TLS 1.2+ for all Kafka connections (SASL_SSL)           │
│  ✓ HTTPS for Schema Registry                               │
│  ✓ VPC/Private Link for Confluent Cloud (optional)         │
│  ✓ Network policies in Kubernetes                          │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Authentication & Authorization                     │
│  ✓ Confluent Cloud API keys (separate for each cluster)    │
│  ✓ Schema Registry API keys (separate credentials)         │
│  ✓ RBAC for Confluent Cloud resources                      │
│  ✓ Kubernetes RBAC for pod/secret access                   │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Secrets Management                                 │
│  ✓ Kubernetes Secrets (encrypted at rest)                  │
│  ✓ Never commit secrets to Git                             │
│  ✓ Rotate API keys quarterly                               │
│  ✓ Least privilege principle                               │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 4: Application Security                               │
│  ✓ No direct credential exposure in logs                   │
│  ✓ Input validation on all external data                   │
│  ✓ Schema validation before producing events               │
│  ✓ Read-only dashboard access to Iceberg                   │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 5: Audit & Compliance                                 │
│  ✓ All events logged and immutable                         │
│  ✓ Access logs for dashboard                               │
│  ✓ Metric exposition only on internal network              │
│  ✓ Regular security audits                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Credentials Management

### **API Keys & Secrets**

#### **Separate API Keys for Each Purpose**

| Component | API Key Purpose | Permissions Required |
|-----------|----------------|---------------------|
| Audit Consumer | Read audit log events | `kafka_read` on `confluent-audit-log-events` topic |
| Destination Producer | Write enriched events | `kafka_write` on destination topic |
| Schema Registry | Read/write schemas | Schema Registry access |
| TableFlow Read | Dashboard queries | Read-only on Iceberg table |

#### **API Key Rotation Schedule**

```
Quarterly Rotation (Every 90 days):
1. Generate new API key in Confluent Cloud
2. Update Kubernetes Secret OR .secrets file
3. Rolling restart of forwarder/dashboard
4. Verify new keys working
5. Delete old API keys
6. Document rotation in security log
```

#### **Secret Storage Options**

**Option A: Kubernetes Secrets (Recommended for Production)**
```bash
# Create secret for forwarder
kubectl create secret generic audit-forwarder-secrets \
  --from-literal=AUDIT_API_KEY='xxx' \
  --from-literal=AUDIT_API_SECRET='yyy' \
  --from-literal=DEST_API_KEY='aaa' \
  --from-literal=DEST_API_SECRET='bbb' \
  --from-literal=SCHEMA_REGISTRY_KEY='ccc' \
  --from-literal=SCHEMA_REGISTRY_SECRET='ddd' \
  --namespace=audit-system

# Enable encryption at rest
# (Enabled by default in most Kubernetes providers)
```

**Option B: Hashicorp Vault (Enterprise)**
```bash
# Store secrets in Vault
vault kv put secret/audit-forwarder \
  AUDIT_API_KEY='xxx' \
  AUDIT_API_SECRET='yyy'

# Use Vault Agent for injection
# See: https://www.vaultproject.io/docs/platform/k8s/injector
```

**Option C: .secrets File (Development ONLY)**
```bash
# Create .secrets file (NEVER commit to Git)
cat > .secrets << 'EOF'
AUDIT_API_KEY=xxx
AUDIT_API_SECRET=yyy
DEST_API_KEY=aaa
DEST_API_SECRET=bbb
EOF

# Add to .gitignore
echo ".secrets" >> .gitignore
```

---

## Access Control

### **Confluent Cloud RBAC**

#### **Forwarder Service Account**

Minimum required permissions:
```
Resource: Cluster (audit log cluster)
  → Role: DeveloperRead

Resource: Topic (confluent-audit-log-events)
  → Role: DeveloperRead

Resource: Consumer Group (audit-forwarder-group)
  → Role: DeveloperManage

Resource: Cluster (destination cluster)
  → Role: DeveloperWrite

Resource: Topic (jegan_auditlog)
  → Role: DeveloperWrite

Resource: Schema Registry
  → Role: ResourceOwner (or DeveloperWrite if schema pre-created)
```

**Why minimal permissions?**
- ✅ Prevents accidental topic deletion
- ✅ Limits blast radius of compromised credentials
- ✅ Audit trail shows only necessary operations

#### **Dashboard Service Account**

Minimum required permissions:
```
Resource: Iceberg Table (TableFlow)
  → Role: Read-only

Resource: Confluent Cloud IAM (for user/SA lookup)
  → Role: OrganizationAdmin (read-only) OR custom role
```

**Note:** Dashboard uses Confluent CLI which requires organization-level permissions for `confluent iam user list` and `confluent iam service-account list`. Consider creating a dedicated read-only admin role.

---

## Network Security

### **Production Deployment: Private Link**

For highly sensitive environments, use Confluent Cloud Private Link:

```bash
# 1. Enable Private Link in Confluent Cloud
confluent network private-link create \
  --cloud aws \
  --region us-west-2 \
  --connection-type privatelink

# 2. Configure VPC Endpoint in AWS
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxxx \
  --service-name com.amazonaws.vpce.us-west-2.vpce-svc-xxxxx \
  --subnet-ids subnet-yyyyy

# 3. Update forwarder to use Private Link DNS
export AUDIT_BOOTSTRAP="pkc-xxxxx.us-west-2.aws.private.confluent.cloud:9092"
export DEST_BOOTSTRAP="pkc-yyyyy.us-west-2.aws.private.confluent.cloud:9092"
```

**Benefits:**
- ✅ Traffic never leaves cloud provider network
- ✅ Reduced exposure to internet threats
- ✅ Lower latency
- ✅ Compliance (e.g., HIPAA, PCI-DSS)

---

## Kubernetes Security

### **Pod Security Standards**

```yaml
# deploy/kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: audit-forwarder
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault

      containers:
      - name: forwarder
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true  # ⚠️ Requires writable /tmp volume
          capabilities:
            drop:
              - ALL

        resources:
          limits:
            memory: "2Gi"
            cpu: "1000m"
          requests:
            memory: "512Mi"
            cpu: "250m"
```

### **Network Policies**

```yaml
# Restrict forwarder to only access Kafka and Schema Registry
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: audit-forwarder-netpol
spec:
  podSelector:
    matchLabels:
      app: audit-forwarder
  policyTypes:
    - Egress
  egress:
    # Allow DNS
    - to:
      - namespaceSelector:
          matchLabels:
            name: kube-system
      ports:
      - protocol: UDP
        port: 53

    # Allow Confluent Cloud (9092, 9093)
    - to:
      - ipBlock:
          cidr: 0.0.0.0/0  # Replace with specific Confluent Cloud IP ranges
      ports:
      - protocol: TCP
        port: 9092
      - protocol: TCP
        port: 9093

    # Allow Schema Registry (443)
    - to:
      - ipBlock:
          cidr: 0.0.0.0/0  # Replace with specific Schema Registry IP
      ports:
      - protocol: TCP
        port: 443
```

---

## Dashboard Security

### **Authentication Options**

#### **Option A: Kubernetes Ingress + OAuth2 Proxy**

```yaml
# Use OAuth2 Proxy for Google/GitHub/Okta SSO
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dashboard-ingress
  annotations:
    nginx.ingress.kubernetes.io/auth-url: "https://$host/oauth2/auth"
    nginx.ingress.kubernetes.io/auth-signin: "https://$host/oauth2/start?rd=$escaped_request_uri"
spec:
  rules:
  - host: audit-dashboard.company.com
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

#### **Option B: Streamlit Basic Auth (Simple)**

```python
# Add to dashboard/app.py
import streamlit as st
import hashlib

def check_password():
    """Returns True if user entered correct password."""
    def password_entered():
        if hashlib.sha256(st.session_state["password"].encode()).hexdigest() == \
           os.getenv("DASHBOARD_PASSWORD_HASH"):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

if not check_password():
    st.stop()

# Rest of dashboard code
```

#### **Option C: VPN-Only Access**

```bash
# Deploy dashboard only on internal network
# Configure Kubernetes Service as ClusterIP (not LoadBalancer)
kubectl patch service audit-dashboard -p '{"spec":{"type":"ClusterIP"}}'

# Access via kubectl port-forward over VPN
kubectl port-forward svc/audit-dashboard 8504:8504
```

---

## Data Security

### **Encryption**

| Data State | Encryption Method | Key Management |
|------------|------------------|----------------|
| **In Transit** | TLS 1.2+ (SASL_SSL) | Confluent Cloud managed |
| **At Rest (Kafka)** | AES-256 | Confluent Cloud managed |
| **At Rest (Iceberg)** | S3/GCS encryption | Cloud provider (AWS KMS/Google KMS) |
| **At Rest (Offsets)** | Kubernetes Secret encryption | Kubernetes etcd encryption |

### **Data Retention**

```bash
# Kafka topic retention (default: 7 days)
confluent kafka topic update confluent-audit-log-events \
  --cluster lkc-xxxxx \
  --config retention.ms=604800000  # 7 days

# Iceberg table retention (configurable)
# Via TableFlow connector configuration:
{
  "tasks.max": "1",
  "iceberg.table.retention.days": "90",
  "iceberg.partition.spec": "daily"
}
```

### **Data Anonymization (Optional)**

For compliance (GDPR, CCPA), consider anonymizing PII:

```python
# Add to audit_forwarder.py processing pipeline
import hashlib

def anonymize_pii(event):
    """Hash email addresses and user IDs."""
    if 'principal' in event and '@' in str(event['principal']):
        # Hash email while keeping domain
        email = event['principal']
        local, domain = email.split('@')
        hashed_local = hashlib.sha256(local.encode()).hexdigest()[:16]
        event['principal'] = f"{hashed_local}@{domain}"

    if 'clientIp' in event:
        # Anonymize last octet of IP
        parts = event['clientIp'].split('.')
        event['clientIp'] = f"{parts[0]}.{parts[1]}.{parts[2]}.XXX"

    return event
```

---

## Audit & Compliance

### **Security Audit Trail**

The system itself provides a complete audit trail:

1. **All Confluent Cloud operations logged** → confluent-audit-log-events
2. **All dashboard accesses logged** → Streamlit access logs
3. **All forwarder operations logged** → stdout (captured by log aggregator)
4. **All metrics exposed** → Prometheus (retention configurable)

### **Compliance Mapping**

| Requirement | Implementation |
|------------|----------------|
| **SOC 2** | Immutable audit logs, access controls, encryption |
| **GDPR** | Data anonymization option, right to erasure (schema evolution) |
| **HIPAA** | Encryption in transit/rest, access logs, Private Link |
| **PCI-DSS** | Network segmentation, key rotation, audit logs |

---

## Security Checklist

### **Pre-Production Security Review**

- [ ] All API keys rotated and stored in Kubernetes Secrets
- [ ] Separate service accounts for forwarder and dashboard
- [ ] Least privilege RBAC configured in Confluent Cloud
- [ ] Network policies configured in Kubernetes
- [ ] Pod security context enforced (runAsNonRoot, read-only filesystem)
- [ ] TLS 1.2+ enforced for all connections
- [ ] Dashboard authentication enabled (OAuth2 or VPN)
- [ ] Secrets never committed to Git (verify with `git log -p | grep -i "api.*key"`)
- [ ] Prometheus `/metrics` endpoint not exposed to internet
- [ ] Log aggregation configured (stdout → ELK/Splunk)
- [ ] Security alerts configured (high anomaly rate, auth failures)
- [ ] Incident response plan documented
- [ ] Quarterly key rotation scheduled
- [ ] Backup strategy for offsets.json
- [ ] DLQ review process established

---

## Incident Response

### **Compromised API Key**

```bash
# IMMEDIATE ACTIONS (within 15 minutes):
# 1. Revoke compromised key in Confluent Cloud
confluent api-key delete <key-id> --force

# 2. Generate new API key
confluent api-key create --resource lkc-xxxxx --description "Audit Forwarder (rotated)"

# 3. Update Kubernetes Secret
kubectl create secret generic audit-forwarder-secrets \
  --from-literal=AUDIT_API_KEY='new-key' \
  --from-literal=AUDIT_API_SECRET='new-secret' \
  --dry-run=client -o yaml | kubectl apply -f -

# 4. Rolling restart forwarder
kubectl rollout restart deployment audit-forwarder

# 5. Verify new key working
kubectl logs -f deployment/audit-forwarder | grep "Successfully connected"

# 6. Audit access logs for unauthorized activity
confluent audit-log describe --start-time "2025-12-06T00:00:00Z"
```

### **Unauthorized Dashboard Access**

```bash
# 1. Review Streamlit access logs
kubectl logs deployment/audit-dashboard | grep "GET /" | awk '{print $1}' | sort | uniq -c

# 2. Block suspicious IPs in Ingress
kubectl edit ingress dashboard-ingress
# Add annotation: nginx.ingress.kubernetes.io/whitelist-source-range: "10.0.0.0/8"

# 3. Force re-authentication (if using OAuth2)
# Delete user sessions

# 4. Investigate accessed data
# Check Prometheus metrics for query patterns
```

---

## Security Monitoring Metrics

```promql
# Failed authentication attempts
rate(kafka_consumer_authentication_failure_total[5m]) > 0

# Unusual access patterns to dashboard
rate(streamlit_http_requests_total{status="403"}[5m]) > 1

# High anomaly detection rate
rate(anomaly_detected_total[5m]) > 10

# Unauthorized topic access attempts
rate(kafka_authorization_error_total[5m]) > 0
```

---

## Contact Information

**Security Team:** security@company.com
**Incident Hotline:** [Your 24/7 Hotline]
**Confluent Support:** https://support.confluent.io
