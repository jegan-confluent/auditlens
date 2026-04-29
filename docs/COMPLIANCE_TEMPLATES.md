# AuditLens Compliance Templates

**Ready-to-Use Templates for SOC2, ISO27001, HIPAA, PCI-DSS**

---

## Table of Contents

1. [SOC2 Audit Report Template](#soc2-audit-report-template)
2. [ISO27001 Report Template](#iso27001-report-template)
3. [HIPAA Access Log Template](#hipaa-access-log-template)
4. [PCI-DSS Audit Template](#pci-dss-audit-template)
5. [Example Compliance Queries](#example-compliance-queries)
6. [Evidence Collection Guide](#evidence-collection-guide)

---

## SOC2 Audit Report Template

### Trust Service Criteria Coverage

AuditLens addresses these SOC2 Trust Service Criteria:

| Criteria | Description | AuditLens Evidence |
|----------|-------------|-------------------|
| **CC6.1** | Logical and physical access controls | Authorization failure logs, ACL changes |
| **CC6.2** | Prior to issuing system credentials | API key creation logs, service account provisioning |
| **CC6.3** | Removes access when no longer required | Stale ACL detection, permission revocations |
| **CC6.6** | Removes access that is no longer needed | DeleteApiKey, DeleteServiceAccount logs |
| **CC7.2** | Detects and responds to security incidents | CRITICAL event alerts, denial aggregation |
| **CC7.3** | Evaluates security events | Security Alerts tab, failure analysis |

---

### Report Template

```markdown
# SOC2 Type II Audit Report
## Audit Log Evidence: [Topic/Service Name]

**Report Period:** [Start Date] to [End Date]
**Generated:** [Date] by AuditLens v11.0
**Auditor:** [Auditor Name/Firm]

---

## 1. Executive Summary

### Scope
This report covers access logs for [describe resources: topics, clusters, services]
within Confluent Cloud environment for the period [dates].

### Key Findings
- **Total Access Events:** [count]
- **Unique Principals:** [count] users, [count] service accounts
- **Failed Access Attempts:** [count]
- **Security Incidents:** [count] (all investigated and resolved)
- **Compliance Status:** ✅ PASS / ⚠️ FINDINGS

### Control Effectiveness
All Trust Service Criteria (CC6.1, CC6.2, CC6.3, CC6.6, CC7.2, CC7.3) are
operating effectively with no material exceptions.

---

## 2. Access Summary by Principal

### Human Users
| Email | Role | Access Events | Last Access | Status |
|-------|------|---------------|-------------|--------|
| alice@company.com | Platform Admin | 1,247 | 2025-02-19 | Active |
| bob@company.com | Developer | 523 | 2025-02-15 | Active |
| jane@company.com | Security Lead | 89 | 2025-02-10 | Active |

### Service Accounts
| Service Account | Purpose | Access Events | Last Access | Status |
|-----------------|---------|---------------|-------------|--------|
| sa-prod-analytics | Production data processing | 125,478 | 2025-02-19 | Active |
| sa-compliance-exporter | Compliance reporting | 8,921 | 2025-02-18 | Active |
| sa-legacy-connector | Deprecated ETL pipeline | 0 | 2024-11-01 | ⚠️ Stale (revoked) |

**Control Point:** Service account `sa-legacy-connector` was identified as stale
(no access for 109 days) and access was revoked on [date], demonstrating
effective implementation of CC6.3 (timely removal of access).

---

## 3. Access Control Evidence (CC6.1)

### Authorization Denials
| Date | Principal | Resource | Reason | Resolution |
|------|-----------|----------|--------|------------|
| 2025-02-05 | sa-analytics-team | customer-pii | No ACL | Verified denial is correct |
| 2025-02-12 | user:contractor@ext.com | prod-orders | No ACL | Verified denial is correct |
| 2025-02-17 | sa-external-vendor | prod-* | No ACL | Verified denial is correct |

**Control Effectiveness:** All unauthorized access attempts were successfully
denied. Least-privilege principle is enforced via role-based access control (RBAC).

### Approved Access Grants
| Date | Grantor | Grantee | Resource | Justification |
|------|---------|---------|----------|---------------|
| 2025-02-01 | alice@company.com | sa-new-pipeline | staging-data | New staging pipeline deployment |
| 2025-02-10 | alice@company.com | bob@company.com | dev-test-* | Developer onboarding |

**Control Point:** All access grants were approved by authorized personnel
(alice@company.com holds OrganizationAdmin role).

---

## 4. Credential Management (CC6.2, CC6.6)

### API Key Creation Events
| Date | Created By | Service Account | Purpose | Status |
|------|------------|-----------------|---------|--------|
| 2025-02-01 | alice@company.com | sa-new-pipeline | Production deployment | Active |
| 2025-02-15 | bob@company.com | sa-dev-testing | Development testing | Active |

### API Key Deletion Events (Rotation)
| Date | Deleted By | Service Account | Key Age | Reason |
|------|------------|-----------------|---------|--------|
| 2025-02-08 | alice@company.com | sa-prod-analytics | 87 days | Scheduled rotation (90-day policy) |
| 2025-02-14 | alice@company.com | sa-contractor-temp | 45 days | Contractor offboarding |

**Control Effectiveness:** API key rotation policy (90 days) is enforced.
Contractor keys are revoked upon offboarding.

---

## 5. Incident Detection and Response (CC7.2, CC7.3)

### Security Incidents Detected
| Date | Incident | Principal | Detection Method | Resolution |
|------|----------|-----------|------------------|------------|
| 2025-02-05 | 47 auth failures in 60s | sa-prod-analytics | AuditLens aggregated denial alert | Misconfigured ACLs - fixed within 10 min |
| 2025-02-12 | After-hours prod access | user:contractor@ext.com | Time Insights heatmap | Investigated - attempted unauthorized access, credentials revoked |

**Mean Time to Detect (MTTD):** <5 minutes (via AuditLens real-time alerts)
**Mean Time to Respond (MTTR):** <30 minutes (via Slack webhook integration)

**Control Effectiveness:** Security monitoring is continuous. All incidents were
detected, investigated, and resolved within SLA.

---

## 6. Access Review Process (CC6.3)

### Stale Access Detection
AuditLens performs automated stale ACL detection (90-day threshold).

| Principal | Resource | Last Access | Days Stale | Action Taken |
|-----------|----------|-------------|------------|--------------|
| sa-legacy-connector | old-events-v1 | 2024-11-01 | 109 | ACLs revoked on 2025-02-18 |
| user:bob@company.com | customer-ssn | 2024-12-05 | 75 | Under review (sabbatical, returning March) |

**Control Point:** Quarterly access reviews are conducted. Unused permissions
are revoked within 120 days of inactivity.

---

## 7. Segregation of Duties

### Production Access
| Principal | Environment | Access Type | Justification |
|-----------|-------------|-------------|---------------|
| sa-prod-analytics | Production | Read-only | Data processing (approved business need) |
| sa-platform-team | Production | Admin | Platform operations (approved role) |
| sa-dev-testing | Production | DENIED ✓ | Development SA correctly blocked from prod |

**Control Effectiveness:** Developers do not have production write access.
Segregation of duties is enforced via RBAC.

---

## 8. Temporal Analysis

### Access Pattern by Hour
```
Hour    00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23
Events  12 8  5  3  2  4  15 45 98 142 156 138 145 152 147 139 121 95 52 31 22 18 14 10
```

**Observation:**
- Peak activity: 09:00-17:00 (business hours) ✅
- Off-hours activity: Minimal (automated jobs only) ✅
- No unusual after-hours access by human users ✅

---

## 9. Attestation

This report was generated from Confluent Audit Logs using AuditLens v11.0,
a tamper-evident audit log intelligence system. All events are cryptographically
signed and stored in immutable Kafka topics with 90-day retention.

**Report Hash (SHA-256):** [hash-value]
**Generated By:** [Your Name], [Your Title]
**Date:** [Date]
**Signature:** ______________________

---

## 10. Appendices

### Appendix A: Control Descriptions
- **CC6.1:** System access is restricted to authorized users
- **CC6.2:** New access requests are approved before granting
- **CC6.3:** Access is removed when no longer needed
- **CC6.6:** Credentials are revoked upon termination/role change
- **CC7.2:** Security incidents are detected and investigated
- **CC7.3:** Security events are continuously evaluated

### Appendix B: Evidence Files
- `audit-trail-export.csv` - Full audit trail for review period
- `topic-identity-matrix.csv` - Access permissions matrix
- `security-alerts.csv` - All security alerts generated

### Appendix C: Deviations and Remediation
| Finding | Severity | Remediation | Completion Date |
|---------|----------|-------------|-----------------|
| sa-legacy-connector stale access | Low | ACLs revoked | 2025-02-18 |
| (None) | - | - | - |

---

## 11. Auditor Notes

_[Space for auditor to add comments and findings]_

---

**End of Report**
```

---

## ISO27001 Report Template

### Annex A Controls Coverage

| Control | Description | AuditLens Evidence |
|---------|-------------|-------------------|
| **A.9.2.1** | User registration and de-registration | CreateServiceAccount, DeleteServiceAccount logs |
| **A.9.2.2** | User access provisioning | CreateApiKey, CreateRoleBinding logs |
| **A.9.2.5** | Review of user access rights | Stale ACL detection, access certification |
| **A.9.2.6** | Removal or adjustment of access rights | DeleteApiKey, DeleteRoleBinding logs |
| **A.9.4.1** | Information access restriction | Authorization denials, ACL enforcement |
| **A.9.4.5** | Access to program source code | (N/A for Kafka, applicable for Schema Registry) |
| **A.12.4.1** | Event logging | All audit events captured |
| **A.12.4.3** | Administrator and operator logs | Platform admin actions logged |

---

### Report Template

```markdown
# ISO27001:2013 Annex A.9/A.12 Evidence
## Information Access Control and Logging

**Audit Period:** [Start Date] to [End Date]
**Scope:** Confluent Cloud Kafka Clusters, Schema Registry, ksqlDB
**Generated:** [Date] by AuditLens v11.0

---

## A.9.2.1 - User Registration and De-registration

### Service Account Lifecycle Events

#### Registrations (New Service Accounts)
| Date | Created By | Service Account | Purpose | Approval Reference |
|------|------------|-----------------|---------|-------------------|
| 2025-02-01 | alice@company.com | sa-new-pipeline | Production ETL | Ticket #SVC-1234 |
| 2025-02-10 | bob@company.com | sa-dev-testing | Development testing | Ticket #DEV-5678 |

#### De-registrations (Deleted Service Accounts)
| Date | Deleted By | Service Account | Reason | Retention Period |
|------|------------|-----------------|--------|------------------|
| 2025-02-14 | alice@company.com | sa-contractor-temp | Contractor offboarded | 45 days (within policy) |
| 2025-02-18 | alice@company.com | sa-legacy-connector | Deprecated system | 109 days (cleanup) |

**Control Assessment:** ✅ EFFECTIVE
- All service accounts have documented business justification
- Deprovisioning occurs within policy timelines (60 days post-offboarding)

---

## A.9.2.2 - User Access Provisioning

### Access Grants
| Date | Grantor | Grantee | Resource | Operation | Approval |
|------|---------|---------|----------|-----------|----------|
| 2025-02-01 | alice@company.com | sa-new-pipeline | topic:staging-data | Read/Write | Approved |
| 2025-02-10 | alice@company.com | bob@company.com | topic:dev-test-* | Read/Write | Approved |

### Access Denials (Unauthorized Requests)
| Date | Requester | Resource | Reason | Action Taken |
|------|-----------|----------|--------|--------------|
| 2025-02-05 | sa-analytics-team | customer-pii | No business justification | Denial upheld ✓ |
| 2025-02-12 | user:contractor@ext.com | prod-* | External user | Denial upheld ✓ |

**Control Assessment:** ✅ EFFECTIVE
- All access grants approved by authorized administrators
- Least-privilege principle enforced (denials for unauthorized requests)

---

## A.9.2.5 - Review of User Access Rights

### Quarterly Access Review (Q1 2025)

#### Access Certification Results
| Principal | Resource | Last Access | Certification | Reviewer | Date |
|-----------|----------|-------------|---------------|----------|------|
| sa-prod-analytics | customer-pii | 2025-02-19 | ✅ Approved | jane@company.com | 2025-02-20 |
| user:bob@company.com | customer-ssn | 2024-12-05 | ⚠️ Pending | jane@company.com | 2025-02-20 |
| sa-legacy-connector | old-events-v1 | 2024-11-01 | ❌ Revoked | jane@company.com | 2025-02-18 |

#### Stale Access Detection (90-day threshold)
AuditLens automatically identifies access rights not used in 90+ days.

**Stale Access Found:** 2 identities
**Action Taken:** 1 revoked, 1 under review (sabbatical exception)

**Control Assessment:** ✅ EFFECTIVE
- Quarterly access reviews conducted on schedule
- Automated stale access detection supplements manual reviews

---

## A.9.4.1 - Information Access Restriction

### Access Control Effectiveness

#### Successful Access (Authorized)
| Principal | Resource | Access Count | Last Access |
|-----------|----------|--------------|-------------|
| sa-prod-analytics | prod-orders | 125,478 | 2025-02-19 |
| sa-compliance-exporter | customer-pii | 8,921 | 2025-02-18 |

#### Denied Access (Unauthorized)
| Date | Principal | Resource | Reason |
|------|-----------|----------|--------|
| 2025-02-05 | sa-analytics-team | customer-pii | No ACL |
| 2025-02-12 | user:contractor@ext.com | prod-orders | No ACL |
| 2025-02-17 | sa-external-vendor | prod-* | No ACL |

**Access Control Metrics:**
- **Total Access Attempts:** 125,893
- **Authorized (granted):** 125,890 (99.998%)
- **Denied (unauthorized):** 3 (0.002%)
- **False Negatives:** 0 (no unauthorized access granted)
- **False Positives:** 0 (no legitimate access denied)

**Control Assessment:** ✅ EFFECTIVE
- Role-based access control (RBAC) operating correctly
- All unauthorized access attempts blocked

---

## A.12.4.1 - Event Logging

### Audit Log Completeness

#### Events Captured
| Event Type | Count | Examples |
|------------|-------|----------|
| Authentication | 45,892 | kafka.Authentication, Login |
| Authorization | 78,945 | kafka.Fetch, kafka.Produce, mds.Authorize |
| Administrative | 1,056 | kafka.CreateTopics, UpdateKafkaClusterConfig |
| Security | 3 | Authorization denials |

**Log Fields Captured:**
- ✅ Event ID (unique identifier)
- ✅ Timestamp (UTC, millisecond precision)
- ✅ User/Service Account (principal)
- ✅ Event type (authentication, authorization, administrative)
- ✅ Outcome (success, failure, denied)
- ✅ Source IP address
- ✅ Resource accessed (topic, cluster, subject)

**Control Assessment:** ✅ EFFECTIVE
- All required event types logged
- Logs are tamper-evident (Kafka immutable log)
- Retention: 90 days (exceeds ISO27001 minimum)

---

## A.12.4.3 - Administrator and Operator Logs

### Privileged User Activity

| Date | Administrator | Action | Resource | Result |
|------|---------------|--------|----------|--------|
| 2025-02-01 | alice@company.com | CreateServiceAccount | sa-new-pipeline | SUCCESS |
| 2025-02-05 | alice@company.com | UpdateKafkaClusterConfig | lkc-production | SUCCESS |
| 2025-02-14 | alice@company.com | DeleteServiceAccount | sa-contractor-temp | SUCCESS |
| 2025-02-18 | alice@company.com | DeleteAcl | sa-legacy-connector | SUCCESS |

**Privileged Operations Monitored:**
- Service account creation/deletion
- API key creation/deletion
- ACL creation/deletion
- Cluster configuration changes
- Role binding changes

**Control Assessment:** ✅ EFFECTIVE
- All privileged actions logged and attributed to specific users
- No unauthorized administrative actions detected

---

## Evidence Files

1. **Full Audit Trail:** `audit-trail-q1-2025.csv` (125,893 events)
2. **Access Matrix:** `topic-identity-matrix.csv` (access rights per principal)
3. **Security Alerts:** `security-alerts-q1-2025.csv` (3 alerts)
4. **Stale Access Report:** `stale-acl-detection.csv` (2 findings)

---

## Non-Conformities and Corrective Actions

| Finding | Control | Severity | Corrective Action | Completion |
|---------|---------|----------|-------------------|------------|
| Stale access (sa-legacy-connector) | A.9.2.5 | Low | ACLs revoked | 2025-02-18 |
| (None) | - | - | - | - |

---

## Attestation

I hereby certify that this report accurately represents the access control
and logging evidence for the audit period [dates].

**Information Security Officer:** ______________________
**Date:** [Date]
```

---

## HIPAA Access Log Template

### 45 CFR § 164.308(a)(1)(ii)(D) - Information System Activity Review

**Required by HIPAA:** Implement procedures to regularly review records of
information system activity, such as audit logs, access reports, and security
incident tracking reports.

---

### Report Template

```markdown
# HIPAA Access Log Review
## Protected Health Information (PHI) Access Audit

**Covered Entity:** [Your Organization]
**Review Period:** [Start Date] to [End Date]
**Generated:** [Date] by AuditLens v11.0
**Reviewed By:** [Privacy Officer Name]

---

## 1. Scope

This report documents all access to Kafka topics containing Protected Health
Information (PHI) as defined by 45 CFR § 160.103.

**PHI Topics:**
- `patient-records` - Patient demographics, medical records
- `lab-results` - Laboratory test results
- `prescriptions` - Prescription and medication data
- `appointments` - Appointment scheduling data

---

## 2. Access Summary

| Topic | Access Events | Unique Principals | Failed Access | Last Access |
|-------|---------------|-------------------|---------------|-------------|
| patient-records | 15,478 | 3 | 5 | 2025-02-19 |
| lab-results | 8,921 | 2 | 1 | 2025-02-18 |
| prescriptions | 3,456 | 2 | 0 | 2025-02-19 |
| appointments | 2,134 | 4 | 2 | 2025-02-17 |

**Total PHI Access Events:** 30,989
**Unauthorized Access Attempts:** 8 (all denied ✓)

---

## 3. Authorized Access

### Human Users
| User | Role | Access Count | Topics Accessed | Last Access | Minimum Necessary |
|------|------|--------------|-----------------|-------------|-------------------|
| jane@hospital.com | Physician | 547 | patient-records, prescriptions | 2025-02-19 | ✅ Yes |
| bob@hospital.com | Lab Technician | 234 | lab-results | 2025-02-18 | ✅ Yes |
| alice@hospital.com | Front Desk | 89 | appointments | 2025-02-17 | ✅ Yes |

**Minimum Necessary Principle:** Each user has access only to PHI topics
required for their job function.

### System Access (Service Accounts)
| Service Account | Purpose | Access Count | Topics Accessed | Last Access |
|-----------------|---------|--------------|-----------------|-------------|
| sa-ehr-integration | Electronic Health Record system | 28,547 | patient-records, lab-results, prescriptions | 2025-02-19 |
| sa-billing-system | Medical billing | 1,234 | patient-records, appointments | 2025-02-18 |
| sa-analytics-hipaa | De-identified analytics | 238 | (aggregated data only, no direct PHI) | 2025-02-15 |

---

## 4. Unauthorized Access Attempts (Denied)

| Date | User/System | Topic | Reason | Follow-up Action |
|------|-------------|-------|--------|------------------|
| 2025-02-05 | sa-analytics-team | patient-records | No ACL (not authorized for PHI) | Denial upheld ✓ |
| 2025-02-12 | user:contractor@ext.com | lab-results | External user | Denial upheld ✓ |
| 2025-02-17 | sa-marketing-system | prescriptions | No business justification | Denial upheld ✓ |

**HIPAA Compliance:** All unauthorized access attempts were successfully denied.
No PHI was disclosed to unauthorized parties.

---

## 5. Access by Date and Time

### Temporal Pattern
```
Date       Total Access  Business Hours (8am-6pm)  After-Hours
2025-02-13  1,234        1,198 (97%)               36 (3%, automated jobs)
2025-02-14  1,456        1,423 (98%)               33 (2%, automated jobs)
2025-02-15  987          965 (98%)                 22 (2%, automated jobs)
2025-02-16  1,123        1,098 (98%)               25 (2%, automated jobs)
2025-02-17  1,089        1,067 (98%)               22 (2%, automated jobs)
```

**After-Hours Access:** All after-hours access is from authorized automated
systems (EHR integration, billing system). No human user access outside
business hours detected. ✅

---

## 6. Minimum Necessary Review

HIPAA requires that access to PHI be limited to the minimum necessary to
accomplish the intended purpose.

| User | Topics Accessed | Purpose | Minimum Necessary Assessment |
|------|-----------------|---------|------------------------------|
| jane@hospital.com | patient-records, prescriptions | Physician - patient care | ✅ Appropriate |
| bob@hospital.com | lab-results | Lab technician - test results | ✅ Appropriate |
| alice@hospital.com | appointments | Front desk - scheduling | ✅ Appropriate |
| sa-analytics-team | (DENIED - patient-records) | Analytics - no PHI needed | ✅ Correctly blocked |

**Finding:** All access is consistent with minimum necessary principle.

---

## 7. Business Associate Access

HIPAA requires tracking access by Business Associates (third-party vendors).

| Business Associate | Service Account | Purpose | Access Count | BAA in Place |
|--------------------|-----------------|---------|--------------|--------------|
| HealthTech Inc. | sa-ehr-integration | EHR system integration | 28,547 | ✅ Yes (signed 2024-01-15) |
| BillMed Corp. | sa-billing-system | Medical billing services | 1,234 | ✅ Yes (signed 2023-06-01) |

**HIPAA Compliance:** All Business Associates have signed Business Associate
Agreements (BAAs) on file.

---

## 8. Incident Review

### Security Incidents Detected
| Date | Incident | Resolution | Breach Determination |
|------|----------|------------|----------------------|
| 2025-02-12 | Contractor attempted to access lab-results | Access denied, credentials revoked | ✅ No breach (access denied) |

**Breach Notification:** No reportable breaches occurred during review period.

---

## 9. Access Log Retention

**HIPAA Requirement:** Maintain audit logs for 6 years from creation or last use.

**AuditLens Configuration:**
- Kafka topic retention: 90 days (hot storage)
- S3 Glacier archival: 7 years (cold storage)
- Total retention: 7 years ✅

---

## 10. Attestation

This access log review was conducted in accordance with 45 CFR § 164.308(a)(1)(ii)(D).

**Privacy Officer:** ______________________
**Date:** [Date]

**Next Review Due:** [Date + 30 days] (monthly reviews required)

---

## Appendices

### Appendix A: Full Access Log
`phi-access-log-[dates].csv` - Complete access log for review period

### Appendix B: Denial Log
`phi-denial-log-[dates].csv` - All denied access attempts

### Appendix C: Business Associate Agreements
- HealthTech Inc. BAA (signed 2024-01-15)
- BillMed Corp. BAA (signed 2023-06-01)

```

---

## PCI-DSS Audit Template

### PCI-DSS Requirements Coverage

| Requirement | Description | AuditLens Evidence |
|-------------|-------------|-------------------|
| **10.2** | Implement automated audit trails | All events logged automatically |
| **10.2.2** | All actions by privileged users | Admin actions logged (CreateApiKey, DeleteServiceAccount) |
| **10.2.5** | Unauthorized access attempts | Authorization denials logged |
| **10.3** | Record audit trail entries | Time, user, event type, outcome, resource |
| **10.5.1** | Limit viewing of audit trails | RBAC on dashboard, metrics auth required |
| **10.6** | Review logs and security events | Security Alerts tab, daily review workflow |
| **10.7** | Retain audit trail history | 90 days Kafka + 365 days S3 archive |

---

### Report Template

```markdown
# PCI-DSS Requirement 10 Evidence
## Audit Logging and Monitoring

**Merchant/Service Provider:** [Your Organization]
**Audit Period:** [Start Date] to [End Date]
**Assessor:** [QSA Firm]
**Generated:** [Date] by AuditLens v11.0

---

## Requirement 10.2 - Implement Automated Audit Trails

### 10.2.1 - All Individual User Accesses to Cardholder Data
| Date | User | Topic (CHD) | Operation | Result |
|------|------|-------------|-----------|--------|
| 2025-02-15 | jane@company.com | payment-card-tokens | kafka.Fetch (Read) | SUCCESS |
| 2025-02-17 | sa-payment-processor | payment-transactions | kafka.Produce (Write) | SUCCESS |

**Evidence:** All access to cardholder data environments (CDE) is logged with
user, timestamp, and operation.

---

### 10.2.2 - All Actions by Privileged Users
| Date | Admin User | Action | Resource | Result |
|------|------------|--------|----------|--------|
| 2025-02-01 | alice@company.com | CreateServiceAccount | sa-payment-processor | SUCCESS |
| 2025-02-05 | alice@company.com | CreateApiKey | sa-payment-processor | SUCCESS |
| 2025-02-14 | alice@company.com | DeleteApiKey | sa-old-payment-key | SUCCESS |

**Evidence:** All administrative actions are logged and attributed to specific users.

---

### 10.2.5 - Unauthorized Access Attempts
| Date | User/System | Topic (CHD) | Reason | Action Taken |
|------|-------------|-------------|--------|--------------|
| 2025-02-10 | sa-analytics-team | payment-card-tokens | No ACL | Denial upheld ✓ |
| 2025-02-15 | user:contractor@ext.com | payment-transactions | No ACL | Denial upheld ✓ |

**Evidence:** All unauthorized access attempts are logged and investigated.

---

## Requirement 10.3 - Record Audit Trail Entries

AuditLens captures all required audit trail fields:

| Field | Example | Captured |
|-------|---------|----------|
| User identification | `jane@company.com` | ✅ Yes |
| Type of event | `kafka.Fetch`, `CreateApiKey` | ✅ Yes |
| Date and time | `2025-02-19T15:23:45Z` | ✅ Yes |
| Success or failure | `SUCCESS`, `DENIED` | ✅ Yes |
| Origination of event | Source IP: `203.0.113.42` | ✅ Yes |
| Identity or name of data | Topic: `payment-card-tokens` | ✅ Yes |

**Evidence:** All required fields are captured for every audit event.

---

## Requirement 10.5.1 - Limit Viewing of Audit Trails

**Access Control for Audit Logs:**
- Dashboard access: Requires authentication (Okta SSO)
- Metrics endpoint: Requires Bearer token authentication
- Role-based access: Only Security and Compliance teams can view CHD audit logs

**Evidence:**
```bash
# Metrics endpoint requires authentication
curl http://localhost:8003/metrics
# → 401 Unauthorized (without token)

curl -H "Authorization: Bearer TOKEN" http://localhost:8003/metrics
# → 200 OK (with valid token)
```

---

## Requirement 10.6 - Review Logs and Security Events

### Daily Log Review Process
**Responsible Party:** Security Operations Center (SOC)
**Review Frequency:** Daily (automated alerts) + Weekly manual review

**Review Checklist:**
- [ ] Authorization failures (AuditLens Security Alerts tab)
- [ ] Privileged user actions (filter by admin users)
- [ ] Access to CHD topics (payment-card-tokens, payment-transactions)
- [ ] Unusual access patterns (Time Insights heatmap)

**Evidence:**
```
Review Log - Week of 2025-02-13

Reviewed By: jane@security.com
Date: 2025-02-20
Findings:
  - 2 unauthorized access attempts (both denied) ✓
  - No unusual after-hours access ✓
  - API key rotated for sa-payment-processor (scheduled) ✓
Action Items: None
```

---

## Requirement 10.7 - Retain Audit Trail History

**Retention Policy:**
- **Hot Storage (Kafka):** 90 days
- **Cold Storage (S3 Glacier):** 365 days
- **Total Retention:** 365 days (exceeds PCI-DSS minimum of 90 days) ✅

**Evidence:**
```bash
# Kafka topic configuration
kafka-configs --describe --entity-type topics --entity-name audit_events_critical
# Configs:
#   retention.ms=7776000000 (90 days)

# S3 lifecycle policy
{
  "Rules": [{
    "Transitions": [{"Days": 90, "StorageClass": "GLACIER"}],
    "Expiration": {"Days": 365}
  }]
}
```

---

## Compliance Summary

| Requirement | Status | Evidence Location |
|-------------|--------|-------------------|
| 10.2 - Automated audit trails | ✅ PASS | All events logged automatically |
| 10.2.1 - CHD access | ✅ PASS | Section 10.2.1 |
| 10.2.2 - Privileged users | ✅ PASS | Section 10.2.2 |
| 10.2.5 - Unauthorized access | ✅ PASS | Section 10.2.5 |
| 10.3 - Audit trail fields | ✅ PASS | Section 10.3 |
| 10.5.1 - Limit audit log viewing | ✅ PASS | Section 10.5.1 |
| 10.6 - Log review | ✅ PASS | Section 10.6 |
| 10.7 - Retention | ✅ PASS | Section 10.7 |

**Overall Compliance Status:** ✅ COMPLIANT (no findings)

---

## Assessor Notes

_[Space for QSA to add findings]_

---

**Qualified Security Assessor (QSA):** ______________________
**Date:** [Date]
```

---

## Example Compliance Queries

### Query 1: SOC2 - Show All Access to Sensitive Topics

**Dashboard:**
1. Navigate to **Topic × Identity** tab
2. Filter topics: `customer-pii`, `customer-ssn`, `patient-records`
3. Export to CSV

**MCP (Claude Code):**
```
Show me all access to topics containing PII in the last 30 days
```

**Expected Output:**
```csv
date,principal,topic,access_count,last_access
2025-02-19,sa-compliance-exporter,customer-pii,8921,2025-02-19T15:23:45Z
2025-02-19,user:jane@legal.com,customer-pii,92,2025-02-15T10:45:22Z
```

---

### Query 2: ISO27001 - Identify Stale Access

**Dashboard:**
1. Navigate to **Topic × Identity** tab
2. Enable **Stale ACL Detection** (90-day threshold)
3. Review highlighted rows

**MCP (Claude Code):**
```
Which service accounts have not accessed their authorized topics in 90+ days?
```

**Expected Output:**
```
Stale Access Detected:

1. sa-legacy-connector
   Topics: old-events-v1
   Last Access: 147 days ago
   Recommendation: Revoke ACLs

2. user:bob@company.com
   Topics: customer-ssn
   Last Access: 92 days ago
   Recommendation: Review with data owner
```

---

### Query 3: HIPAA - PHI Access Audit

**Dashboard:**
1. Navigate to **Audit Trail** tab
2. Filter topics: `patient-records`, `lab-results`, `prescriptions`
3. Time range: Last 30 days
4. Export to CSV for privacy officer review

**MCP (Claude Code):**
```
Generate HIPAA access log for patient-records topic in January 2025
```

---

### Query 4: PCI-DSS - Cardholder Data Access

**Dashboard:**
1. Navigate to **Audit Trail** tab
2. Filter topics: `payment-card-tokens`, `payment-transactions`
3. Export to CSV

**MCP (Claude Code):**
```
Show all access to payment-card-tokens topic, including denied attempts
```

---

## Evidence Collection Guide

### For Auditors

#### Step 1: Access AuditLens Dashboard
```
URL: http://localhost:8503
Authentication: [Okta SSO / local credentials]
```

#### Step 2: Generate Compliance Report
1. Navigate to **Export** tab
2. Select report type: SOC2 / ISO27001 / HIPAA / PCI-DSS
3. Configure time range
4. Click **Generate PDF Report**

#### Step 3: Export Raw Data
1. Navigate to **Audit Trail** tab
2. Apply filters per compliance requirement
3. Click **Export to CSV**
4. Provide CSV file to auditor

#### Step 4: Verify Retention Policy
```bash
# Check Kafka retention
kafka-configs --describe --entity-type topics --entity-name audit_events_critical

# Check S3 archival
aws s3api get-bucket-lifecycle-configuration --bucket company-audit-logs
```

---

### Self-Service Evidence Package

**For Compliance Officers:**

AuditLens can generate a complete evidence package with one click.

**Contents:**
1. `executive-summary.pdf` - High-level overview
2. `audit-trail-full.csv` - Complete audit trail
3. `topic-identity-matrix.csv` - Access permissions
4. `security-alerts.csv` - All security incidents
5. `stale-acl-report.csv` - Unused permissions
6. `retention-policy.txt` - Retention configuration
7. `attestation.pdf` - Signed attestation by Security Officer

**Generate:**
```bash
./scripts/generate-compliance-package.sh --framework soc2 --period q1-2025
```

---

## Best Practices

### 1. Proactive Compliance

**Do:**
- ✅ Generate compliance reports quarterly (even if not audited)
- ✅ Review stale access monthly
- ✅ Document all security incidents immediately
- ✅ Maintain evidence files in version control

**Don't:**
- ❌ Wait until audit to generate first report
- ❌ Delete audit logs before retention period ends
- ❌ Grant access without documented justification

---

### 2. Auditor Collaboration

**Do:**
- ✅ Provide auditor read-only dashboard access
- ✅ Offer both PDF reports (executive summary) and CSV (raw data)
- ✅ Document how AuditLens satisfies each control
- ✅ Maintain audit trail of auditor's own access

**Don't:**
- ❌ Give auditor production admin access
- ❌ Provide only screenshots (auditors want exportable data)
- ❌ Wait for auditor requests - proactively provide evidence

---

### 3. Continuous Compliance

**Setup:**
- Weekly automated compliance checks
- Real-time alerts for security events
- Monthly access certification reviews
- Quarterly evidence package generation

**Example Workflow:**
```
Weekly (Automated):
  - AuditLens generates compliance summary
  - Email to Security Officer
  - Review Security Alerts tab

Monthly (Manual):
  - Access certification review (Topic × Identity tab)
  - Revoke stale access
  - Document findings

Quarterly (For Auditors):
  - Generate full compliance package
  - Archive evidence files
  - Update CLAUDE.md with any policy changes
```

---

## Next Steps

- **Getting Started:** [Quick Start Guide](./QUICK_START.md)
- **Use Cases:** [Customer Use Cases](./CUSTOMER_USE_CASES.md)
- **AI-Assisted Compliance:** [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md)
- **Monitoring:** [Monitoring Capabilities](./MONITORING_CAPABILITIES.md)

---

**Version:** 1.0
**Last Updated:** 2025-02-19
**Frameworks Covered:** SOC2 Type II, ISO27001:2013, HIPAA, PCI-DSS v3.2.1
