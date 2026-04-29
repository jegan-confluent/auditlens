# AuditLens Customer Use Cases

**Version 1.0** | Real-world scenarios for Security, Compliance, SRE, and Data Governance teams

---

## Table of Contents

1. [Use Cases by Persona](#use-cases-by-persona)
2. [Common Questions & Answers](#common-questions--answers)
3. [Dashboard Tab Reference](#dashboard-tab-reference)
4. [Example Queries](#example-queries)

---

## Use Cases by Persona

### Security Engineer

**Primary Goals:** Detect security incidents, investigate unauthorized access, prevent data breaches

#### Use Case 1: Investigating Repeated Authorization Failures

**Scenario:** You receive an alert about 47 authorization failures from service account `sa-prod-analytics` in 60 seconds.

**Question:** Is this a brute-force attack or a misconfigured application?

**AuditLens Answer:**
1. Navigate to **Security Alerts** tab
2. Find the aggregated denial alert for `sa-prod-analytics`
3. Examine:
   - **Operations attempted:** Read on topics `orders`, `payments`, `users`
   - **Source IPs:** `10.0.1.45` (single IP = likely misconfiguration)
   - **Time pattern:** All denials within 60s window
   - **Recommendation:** "Check service account permissions for Topic/Read"

**Resolution:** Misconfigured application - service account lacks ACLs for new topics. Grant Read permissions and verify denials stop.

**Value:** Reduced MTTD (Mean Time To Detect) from hours to seconds. Prevented false-positive PagerDuty escalation.

---

#### Use Case 2: Detecting After-Hours Production Access

**Scenario:** You want to ensure no one accesses production data outside business hours (9am-6pm).

**Question:** Who accessed production topics last night?

**AuditLens Answer:**
1. Navigate to **Time Insights** tab
2. View the activity heatmap (day × hour)
3. Identify bright cells in off-hours (columns 22:00-06:00)
4. Filter to those time ranges in **Audit Trail** tab
5. See events like:
   ```
   Time: 2025-02-18 02:47:32 UTC
   Principal: sa-emergency-runbook
   Method: kafka.Fetch
   Topic: prod-orders
   IP: 203.0.113.42
   ```

**Resolution:** Legitimate - on-call engineer used emergency service account to investigate production incident.

**Value:** Verified compliance with access policies. Created audit trail for SOC2 review.

---

#### Use Case 3: Tracking API Key Rotation Compliance

**Scenario:** Your security policy requires API keys to rotate every 90 days.

**Question:** Which service accounts have API keys older than 90 days?

**AuditLens Answer:**
1. Navigate to **API Keys** tab
2. Filter by `CreateApiKey` events in last 90 days
3. Export to CSV
4. Compare against inventory of service accounts
5. Identify missing entries (= keys created >90 days ago, never rotated)

**Example Results:**
```
Service Account           Last Key Created    Days Since
sa-prod-analytics         2024-08-15          187 days ⚠️
sa-staging-etl            2025-01-05          44 days ✓
sa-dev-testing            2024-11-20          90 days ⚠️
```

**Resolution:** Trigger key rotation workflow for `sa-prod-analytics` and `sa-dev-testing`.

**Value:** Automated compliance tracking. Reduced manual spreadsheet audits from quarterly to continuous.

---

### Compliance Officer

**Primary Goals:** Generate audit reports, prove controls, respond to auditor requests

#### Use Case 4: SOC2 Audit Report Generation

**Scenario:** External auditors request proof that you log and monitor all access to customer data.

**Question:** Show me all access to topic `customer-pii` in Q4 2024.

**AuditLens Answer:**
1. Navigate to **Export** tab
2. Configure report:
   - **Time Range:** 2024-10-01 to 2024-12-31
   - **Resource Filter:** `customer-pii`
   - **Include:** All criticality levels
   - **Format:** PDF
3. Click **Generate Report**
4. Receive PDF with:
   - **Executive Summary:** 1,247 access events, 3 failures
   - **Access by Principal:** Table of users/service accounts
   - **Failed Access Attempts:** 3 events with details
   - **Temporal Analysis:** Access pattern chart
   - **Attestation:** Report generated on [date] by AuditLens v11.0

**Resolution:** Submit PDF to auditors. Pass SOC2 AU-1 (Audit Logging) control.

**Value:** Reduced audit response time from 2 weeks to 10 minutes. No manual log aggregation needed.

---

#### Use Case 5: HIPAA Access Log Requirement

**Scenario:** HIPAA requires logging all access to PHI (Protected Health Information) and producing logs on request.

**Question:** Who accessed healthcare topics in January 2025?

**AuditLens Answer:**
1. Navigate to **Topic × Identity** tab
2. Filter by topics: `patient-records`, `lab-results`, `prescriptions`
3. View matrix showing:
   ```
   Identity                    patient-records    lab-results    prescriptions
   sa-ehr-integration          ✓ (8,547)          ✓ (3,291)      ✓ (1,845)
   user:jane@hospital.com      ✓ (12)             -              -
   sa-analytics-team           ✗ (denied: 5)      -              -
   ```
4. Export matrix to CSV
5. For detailed logs, switch to **Audit Trail** → Filter by topic → Export CSV

**Resolution:** Provide CSV logs to HIPAA auditor. Demonstrate role-based access controls (analytics team correctly denied).

**Value:** HIPAA-compliant access logging with minimal operational overhead.

---

#### Use Case 6: ISO27001 A.9.4.1 (Access Control Review)

**Scenario:** ISO27001 requires periodic review of access rights.

**Question:** Which identities have not accessed their authorized topics in 90+ days? (Stale ACLs)

**AuditLens Answer:**
1. Navigate to **Topic × Identity** tab
2. Configure **Stale ACL Detection:**
   - **Threshold:** 90 days
   - **Risk Level:** HIGH
3. View results:
   ```
   Identity               Topic              Last Access    Risk
   sa-legacy-connector    old-events-v1      147 days ago   HIGH
   user:bob@company.com   test-topic         92 days ago    HIGH
   ```
4. Click on identity → View **Identity Activity** timeline
5. Confirm no recent activity
6. Generate **Risk Report** showing stale permissions

**Resolution:** Revoke ACLs for `sa-legacy-connector` (deprecated). Keep `user:bob` (sabbatical, returning next month).

**Value:** Reduced attack surface by removing unused permissions. Demonstrated continuous access review for ISO27001 compliance.

---

### Site Reliability Engineer (SRE)

**Primary Goals:** Investigate incidents, detect anomalies, prevent outages

#### Use Case 7: Post-Mortem Analysis

**Scenario:** Production Kafka cluster had a brief outage at 14:37 UTC. You need to determine root cause.

**Question:** What operations happened around 14:37 that could have caused the outage?

**AuditLens Answer:**
1. Navigate to **Audit Trail** tab
2. Filter:
   - **Time:** 14:30 to 14:45 UTC
   - **Criticality:** CRITICAL + HIGH
3. View events in chronological order:
   ```
   14:36:12  UpdateKafkaClusterConfig  sa-platform-team
             Changed: min.insync.replicas = 1 → 3

   14:36:45  kafka.ProduceRequest      [multiple producers]
             Status: NOT_ENOUGH_REPLICAS (failures start)

   14:37:22  UpdateKafkaClusterConfig  sa-platform-team
             Changed: min.insync.replicas = 3 → 1 (rollback)

   14:38:01  kafka.ProduceRequest      [producers]
             Status: SUCCESS (recovery)
   ```

**Root Cause:** Platform team changed `min.insync.replicas` during peak traffic without considering replication factor (RF=2). With ISR=3, writes failed until rollback.

**Resolution:** Implement change control: config changes only during maintenance windows, require RF >= ISR.

**Value:** Reduced post-mortem investigation time from hours to 10 minutes. Clear audit trail prevents blame games.

---

#### Use Case 8: Detecting Unusual Deletion Activity

**Scenario:** Your monitoring alerts on spike in topic deletions (5 topics deleted in 5 minutes).

**Question:** Who is deleting topics and why?

**AuditLens Answer:**
1. Navigate to **Deletions** tab
2. Filter: Last 1 hour
3. See:
   ```
   Time       Principal           Topic           Cluster
   15:42:11   sa-terraform-ci     temp-test-123   lkc-staging
   15:42:15   sa-terraform-ci     temp-test-456   lkc-staging
   15:43:01   sa-terraform-ci     old-data-v1     lkc-staging ⚠️
   15:43:45   sa-terraform-ci     old-data-v2     lkc-staging ⚠️
   15:44:12   sa-terraform-ci     legacy-events   lkc-staging ⚠️
   ```
4. Click **Identity Activity** for `sa-terraform-ci`
5. View timeline showing Terraform run deleted test topics + production topics

**Root Cause:** Terraform state drift - staging state file accidentally pointed to production namespace.

**Resolution:** Kill Terraform job immediately. Restore production topics from backups. Fix Terraform state isolation.

**Value:** Detected mass deletion within 30 seconds. Prevented complete data loss via early intervention.

---

#### Use Case 9: Schema Registry Outage Investigation

**Scenario:** Schema Registry is returning 503 errors. Clients can't serialize messages.

**Question:** Did anyone recently change Schema Registry configuration?

**AuditLens Answer:**
1. Navigate to **Audit Trail** tab
2. Filter:
   - **Method contains:** `Schema` OR `Compatibility`
   - **Time:** Last 2 hours
   - **Criticality:** All
3. Find:
   ```
   13:15:22  UpdateCompatibility    user:alice@company.com
             Subject: customer-orders-value
             Changed: BACKWARD → NONE

   13:16:03  RegisterSchema         sa-orders-producer
             Status: INCOMPATIBLE_SCHEMA (failures start)
   ```

**Root Cause:** Alice changed compatibility mode to `NONE`, allowing incompatible schema registration. Producers began sending messages consumers couldn't deserialize.

**Resolution:** Rollback compatibility to `BACKWARD`. Re-deploy producer with compatible schema.

**Value:** Identified configuration change that caused incident. Prevented extended outage.

---

### Data Governance Lead

**Primary Goals:** Enforce data access policies, track data lineage, ensure privacy compliance

#### Use Case 10: Data Access Certification

**Scenario:** Quarterly, you must certify which teams have access to sensitive datasets.

**Question:** Which identities can read topic `customer-ssn` (contains Social Security Numbers)?

**AuditLens Answer:**
1. Navigate to **Topic × Identity** tab
2. Filter by topic: `customer-ssn`
3. View matrix:
   ```
   Identity                    Access    Last Used
   sa-compliance-exporter      Read      2025-02-18 (active)
   user:jane@legal.com         Read      2025-01-05 (stale 44d)
   sa-analytics-team           DENIED    2025-02-17 (blocked ✓)
   ```
4. Export to CSV
5. Send to data owners for quarterly access certification

**Resolution:** Jane confirms access still needed (annual audit prep). Analytics team correctly blocked (no business justification).

**Value:** Automated data access certification. Reduced manual tracking from spreadsheets to live dashboard.

---

#### Use Case 11: GDPR Article 30 (Record of Processing Activities)

**Scenario:** GDPR requires documenting who processes personal data and for what purpose.

**Question:** Which service accounts access PII topics and what operations do they perform?

**AuditLens Answer:**
1. Navigate to **Identity Activity** tab
2. Select service account: `sa-marketing-etl`
3. View activity timeline:
   ```
   Operations on PII Topics:
   - kafka.Fetch on customer-emails: 15,478 records (last 30 days)
   - kafka.Fetch on customer-profiles: 8,921 records

   Purpose: Marketing campaign segmentation (documented in SA description)
   Legal Basis: Legitimate Interest (GDPR Art. 6.1.f)
   Retention: 90 days (automatic topic retention)
   ```
4. Generate **Processing Activity Report** for DPO (Data Protection Officer)

**Resolution:** Document in Article 30 register. Demonstrate technical controls for data minimization.

**Value:** GDPR-compliant processing records with minimal manual documentation.

---

#### Use Case 12: Sensitive Data Exfiltration Detection

**Scenario:** You want to detect if anyone exports large volumes of sensitive data.

**Question:** Has anyone performed unusual high-volume reads on PII topics?

**AuditLens Answer:**
1. Navigate to **Analytics** tab
2. View **Event Volume by Method** chart
3. Identify spike in `kafka.Fetch` operations at 03:00 AM (off-hours)
4. Filter **Audit Trail:**
   - **Method:** kafka.Fetch
   - **Time:** 03:00-03:30 AM
   - **Topic contains:** `pii` OR `customer`
5. Find:
   ```
   03:12:45  kafka.Fetch  user:contractor@external.com
             Topic: customer-pii
             Records: ~500,000 (unusual volume)
             IP: 198.51.100.42 (external IP)
   ```

**Root Cause:** Contractor with temporary access performed bulk export for unauthorized purpose.

**Resolution:** Immediately revoke contractor's API key. Investigate data exposure. Implement rate limiting on sensitive topics.

**Value:** Detected data exfiltration within hours (before contractor left company). Prevented GDPR breach notification.

---

## Common Questions & Answers

### Security Questions

| Question | Dashboard Tab | Filter / Action |
|----------|---------------|-----------------|
| Who created this API key? | **API Keys** | Filter by `CreateApiKey`, search by key ID |
| Why is this service account getting denied? | **Failures** → **Identity Activity** | Filter by principal, view denial patterns |
| Were there any suspicious logins today? | **Audit Trail** | Filter by `Authentication`, result != SUCCESS |
| Show me all privilege escalations | **Security** | Filter by `CreateRoleBinding`, `GrantPermission` |
| Has anyone accessed this topic from outside our network? | **Audit Trail** | Filter by topic, check `clientIp` column |

### Compliance Questions

| Question | Dashboard Tab | Filter / Action |
|----------|---------------|-----------------|
| Generate a SOC2 audit report | **Export** | PDF report with time range filter |
| Who accessed customer data last quarter? | **Topic × Identity** | Filter by PII topics, export CSV |
| Prove we log all administrative actions | **Audit Trail** | Filter by HIGH + CRITICAL criticality |
| Show access logs for external auditor | **Export** | Generate PDF for specific time range |
| Which topics have no access in 90 days? | **Topic × Identity** | Enable Stale ACL detection |

### Operational Questions

| Question | Dashboard Tab | Filter / Action |
|----------|---------------|-----------------|
| What did this user do today? | **Identity Activity** | Search by principal or email |
| Who deleted this topic? | **Deletions** | Filter by topic name |
| When was this cluster last modified? | **Audit Trail** | Filter by cluster ID, method contains `Update` |
| Are there any active alerts? | **Security Alerts** | View aggregated denial alerts |
| What's happening right now? | **Audit Trail** | Sort by time descending, auto-refresh |

### Data Governance Questions

| Question | Dashboard Tab | Filter / Action |
|----------|---------------|-----------------|
| Which identities can read this sensitive topic? | **Topic × Identity** | Filter by topic, view access matrix |
| Who has unused permissions? | **Topic × Identity** | Stale ACL detection (90-day threshold) |
| Show me all cross-environment access | **Audit Trail** | Group by environment, filter by principal |
| Which service accounts are actively used? | **Identity Activity** | View timeline, check last activity |
| Generate data access certification report | **Topic × Identity** | Export matrix to CSV |

---

## Dashboard Tab Reference

### Tab-by-Tab Feature Guide

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         AUDITLENS DASHBOARD                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [Welcome] [Audit Trail] [Failures] [Deletions] [API Keys] [Security]  │
│  [Analytics] [Time Insights] [Security Alerts] [Topic×Identity]        │
│  [Identity Activity] [Export]                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 1. Welcome Tab

**Purpose:** System status, feature discovery, quick links

**When to use:**
- First-time user onboarding
- Check system health (Forwarder, Grafana, Prometheus)
- Find which tab to use for your question

**Key Features:**
- ✅ Live service health indicators
- ✅ Role-based navigation (Security, Compliance, SRE)
- ✅ Searchable feature list
- ✅ Common questions FAQ

---

#### 2. Audit Trail Tab

**Purpose:** Complete event log with filtering

**When to use:**
- Investigate specific incidents
- Answer "who did what when" questions
- General-purpose audit log browsing

**Key Features:**
- ✅ Full-text search across all fields
- ✅ Multi-column filtering (time, principal, method, resource)
- ✅ Sortable table
- ✅ Clickable principal → Identity Activity
- ✅ Export to CSV/JSON

**Example Filters:**
```
Time: Last 24 hours
Principal: sa-prod-*
Method: Delete
Criticality: CRITICAL + HIGH
```

---

#### 3. Failures Tab

**Purpose:** Authentication and authorization failures

**When to use:**
- Investigate denied access
- Detect brute-force attempts
- Troubleshoot permission issues

**Key Features:**
- ✅ Shows only `granted=false` or `resultStatus=FAILURE`
- ✅ Grouped by principal (see which users/SAs have most denials)
- ✅ Source IP tracking (detect distributed attacks)
- ✅ Time series chart (spot spikes)

**Security Value:**
- **Attack Detection:** 100+ failures from same IP = brute force
- **Misconfiguration Detection:** 10+ failures from SA in 1 minute = missing ACL

---

#### 4. Deletions Tab

**Purpose:** Track all delete operations

**When to use:**
- Audit destructive actions
- Investigate accidental deletions
- Compliance requirement (who deleted what)

**Key Features:**
- ✅ Shows `kafka.DeleteTopics`, `DeleteServiceAccount`, `DeleteApiKey`, etc.
- ✅ Filter by resource type (topics, ACLs, clusters)
- ✅ Time-based analysis (detect deletion spikes)
- ✅ Principal tracking (which users delete most often)

**Post-Mortem Value:**
- Quickly identify who deleted production topic
- Provide evidence for restore workflow

---

#### 5. API Keys Tab

**Purpose:** API key lifecycle tracking

**When to use:**
- Key rotation compliance
- Investigate compromised keys
- Track key creation/deletion patterns

**Key Features:**
- ✅ Shows `CreateApiKey`, `DeleteApiKey`, `UpdateApiKey`
- ✅ Key age calculation (days since creation)
- ✅ Rotation tracking (creation/deletion pairs)
- ✅ Service account mapping

**Compliance Value:**
- Generate "keys older than 90 days" report
- Prove key rotation policy enforcement

---

#### 6. Security Tab

**Purpose:** Security-focused event view

**When to use:**
- Security reviews
- Incident investigation
- Threat hunting

**Key Features:**
- ✅ CRITICAL + HIGH events only
- ✅ Security event types (failures, privilege changes, deletions)
- ✅ Risk scoring (LOW/MEDIUM/HIGH/CRITICAL)
- ✅ Alert context (why event is flagged)

**Security Team Value:**
- Pre-filtered view for daily security review
- No noise from routine operations

---

#### 7. Analytics Tab

**Purpose:** Charts and trends

**When to use:**
- Weekly/monthly reviews
- Capacity planning
- Trend analysis

**Key Features:**
- ✅ Event volume over time
- ✅ Top principals by activity
- ✅ Method distribution (what operations are most common)
- ✅ Criticality breakdown (% CRITICAL vs LOW)

**SRE Value:**
- Identify usage patterns
- Detect anomalies (sudden spike in operations)

---

#### 8. Time Insights Tab

**Purpose:** Temporal activity patterns

**When to use:**
- Identify peak usage times
- Detect after-hours activity
- Understand user behavior patterns

**Key Features:**
- ✅ Activity heatmap (day-of-week × hour-of-day)
- ✅ Interactive filtering (click cell → filter events)
- ✅ Color-coded intensity
- ✅ Timezone-aware (UTC default)

**Security Value:**
- Detect unusual after-hours access (bright cells at 2 AM)
- Establish baseline behavior (most activity Mon-Fri 9-5)

---

#### 9. Security Alerts Tab

**Purpose:** Aggregated denial alerts

**When to use:**
- Real-time security monitoring
- Investigate alert notifications
- Tune alert thresholds

**Key Features:**
- ✅ Shows aggregated denial alerts (20+ failures in 60s = HIGH)
- ✅ Summary view (principal, denial count, operations, IPs)
- ✅ Alert history
- ✅ Webhook integration status

**Alert Thresholds:**
- **HIGH:** 20+ denials in 60 seconds (possible attack)
- **MEDIUM:** 5-19 denials in 60 seconds (misconfiguration)
- **LOW:** <5 denials (normal RBAC checks)

---

#### 10. Topic × Identity Matrix

**Purpose:** Access rights visualization

**When to use:**
- Access certification
- Stale ACL detection
- Permission audits

**Key Features:**
- ✅ Matrix view (rows=identities, columns=topics)
- ✅ Access count per cell (e.g., `✓ 1,247` reads)
- ✅ Denied access indicator (`✗ denied: 5`)
- ✅ Stale ACL highlighting (90+ days since last access)
- ✅ Risk scoring

**Compliance Value:**
- Visual access review (who can read what)
- Identify unused permissions (blank cells for authorized users)

---

#### 11. Identity Activity Tab

**Purpose:** Deep dive into user/service account behavior

**When to use:**
- Investigate specific user
- Analyze service account usage
- Behavior profiling

**Key Features:**
- ✅ Timeline view (chronological activity)
- ✅ Operation breakdown (reads, writes, admin actions)
- ✅ Resource access list (which topics accessed)
- ✅ Failure analysis (denials, errors)
- ✅ Sankey diagram (identity → topics → operations flow)

**Investigation Value:**
- Full activity history for incident response
- Behavioral analysis (normal vs anomalous)

---

#### 12. Export Tab

**Purpose:** Generate compliance reports

**When to use:**
- Auditor requests
- SOC2/ISO27001 audits
- Management reporting

**Key Features:**
- ✅ PDF report generation
- ✅ Configurable time ranges
- ✅ Filter by criticality, principal, resource
- ✅ Executive summary section
- ✅ CSV export (raw data)

**Report Sections:**
1. **Executive Summary:** Event counts, failures, highlights
2. **Access by Principal:** Table of users and activity
3. **Failed Access Attempts:** Security events
4. **Temporal Analysis:** Activity over time chart
5. **Attestation:** Report metadata and signature

---

## Example Queries

### Real-World Query Examples

#### Query 1: Find All Actions by Specific User

**Business Question:** "What did jane@company.com do yesterday?"

**Dashboard Path:**
1. Navigate to **Identity Activity** tab
2. Search: `jane@company.com`
3. Time filter: Yesterday

**Expected Results:**
```
Time       Method                 Resource          Result
09:15:23   kafka.CreateTopics     dev-test-001      SUCCESS
09:18:45   kafka.Produce          dev-test-001      SUCCESS (12,547 messages)
14:22:11   kafka.DeleteTopics     dev-test-001      SUCCESS
16:45:32   CreateApiKey           api-key-dev-123   SUCCESS
```

**Insight:** Jane created a dev topic, used it for testing, cleaned up, and created API key for automation.

---

#### Query 2: Detect Mass Deletion Events

**Business Question:** "Alert me if >3 topics deleted in 5 minutes"

**Dashboard Path:**
1. Navigate to **Deletions** tab
2. Group by: Principal
3. Time window: 5 minutes

**Example Alert Trigger:**
```
Time Window: 14:30-14:35
Principal: sa-terraform-ci
Deletions: 8 topics
Topics: old-data-v1, old-data-v2, legacy-events, temp-*, ...
Risk: CRITICAL (verify if intentional)
```

**Action:** Immediately notify SRE team. Confirm if Terraform run was planned.

---

#### Query 3: Access Certification for Sensitive Topics

**Business Question:** "Who can read `customer-ssn` and when did they last access it?"

**Dashboard Path:**
1. Navigate to **Topic × Identity** tab
2. Filter: `customer-ssn`
3. Sort by: Last Access (ascending)

**Expected Results:**
```
Identity                  Access Type    Last Access    Days Ago
sa-compliance-exporter    Read           2025-02-18     0 (active)
user:jane@legal.com       Read           2025-01-05     44 (stale?)
sa-analytics-team         DENIED         2025-02-17     - (blocked ✓)
user:bob@finance.com      Read           2024-11-01     109 (STALE ⚠️)
```

**Action:** Review stale access (>90 days). Revoke bob's access if no longer needed.

---

#### Query 4: Investigate Failed Schema Registration

**Business Question:** "Producer can't register schema. Why?"

**Dashboard Path:**
1. Navigate to **Failures** tab
2. Filter by method: `RegisterSchema`
3. Filter by principal: `sa-orders-producer`

**Expected Results:**
```
Time       Method           Result              Reason
15:23:45   RegisterSchema   INCOMPATIBLE        Compatibility mode = BACKWARD,
                                                new schema breaks backward compat
```

**Root Cause:** Schema change removed required field `orderId`. Consumers would fail to deserialize.

**Resolution:** Fix schema to maintain backward compatibility (make field optional) or coordinate breaking change.

---

#### Query 5: Track Permission Changes

**Business Question:** "Show me all permission grants/revokes in last week"

**Dashboard Path:**
1. Navigate to **Audit Trail** tab
2. Filter by method: `CreateRoleBinding`, `DeleteRoleBinding`, `CreateAcl`, `DeleteAcl`
3. Time: Last 7 days

**Expected Results:**
```
Time       Principal            Method              Resource
2025-02-12 user:alice@ops.com  CreateRoleBinding   OrganizationAdmin → sa-platform
2025-02-15 user:bob@dev.com    CreateAcl           Topic:dev-* Read → user:contractor
2025-02-17 user:alice@ops.com  DeleteRoleBinding   OrganizationAdmin → sa-platform
```

**Insight:** Alice granted temporary OrganizationAdmin to platform SA for migration, then revoked. Bob granted contractor read access to dev topics.

**Compliance:** Demonstrates least-privilege principle (temporary elevated access).

---

#### Query 6: Detect Unusual API Key Creation

**Business Question:** "Alert if >5 API keys created by one user in 1 hour"

**Dashboard Path:**
1. Navigate to **API Keys** tab
2. Filter: `CreateApiKey`
3. Group by: Principal
4. Time window: 1 hour

**Example Alert:**
```
Time Window: 10:00-11:00
Principal: user:contractor@external.com
API Keys Created: 12
Risk: HIGH (unusual volume)
```

**Action:** Contact contractor. Verify legitimate use (e.g., testing automation) vs credential harvesting.

---

#### Query 7: Compliance - Prove No Production Access by Contractors

**Business Question:** "Show that contractors cannot access production"

**Dashboard Path:**
1. Navigate to **Audit Trail** tab
2. Filter by principal: `*contractor*` OR `*external*`
3. Filter by resource: `*prod*` OR cluster = `lkc-production`

**Expected Results:**
```
Time       Principal                  Method      Resource    Result
2025-02-15 user:contractor@ext.com   kafka.Fetch prod-orders DENIED ✓
2025-02-16 sa-external-vendor        kafka.Fetch prod-users  DENIED ✓
```

**Compliance Value:** Demonstrates technical control preventing contractor access to production. Include in SOC2 report.

---

#### Query 8: Post-Incident Timeline

**Business Question:** "Recreate 5-minute timeline before cluster outage"

**Dashboard Path:**
1. Navigate to **Audit Trail** tab
2. Filter: Outage time ± 5 minutes
3. Criticality: CRITICAL + HIGH
4. Sort: Time ascending

**Expected Timeline:**
```
14:32:15  kafka.CreateTopics         sa-app-team       orders-v2           SUCCESS
14:34:22  UpdateKafkaClusterConfig   sa-platform-team  retention.ms=86400  SUCCESS
14:35:47  kafka.DeleteTopics         sa-terraform-ci   orders-v1           SUCCESS
14:36:10  kafka.Produce              [all producers]   orders-v2           FAILURE ⚠️
                                                                            (Topic not ready)
14:37:00  CLUSTER OUTAGE - Consumer lag spike
```

**Root Cause:** App team created new topic `orders-v2`, Terraform immediately deleted old `orders-v1`, but producers weren't updated → wrote to non-existent topic → cascading failures.

**Resolution:** Implement topic migration runbook: 1) Create new, 2) Dual-write, 3) Migrate consumers, 4) Delete old.

---

## Visual Dashboard Previews

### Audit Trail Tab
```
┌─────────────────────────────────────────────────────────────────────────┐
│ AUDIT TRAIL                                               [Export] [R]  │
├─────────────────────────────────────────────────────────────────────────┤
│ Filters: [Time: Last 24h ▼] [Criticality: All ▼] [Principal: _______]  │
│          [Method: _______] [Resource: _______]                          │
├─────────────────────────────────────────────────────────────────────────┤
│ Time       Principal          Method              Resource       Status │
├─────────────────────────────────────────────────────────────────────────┤
│ 15:23:45   sa-prod-analytics  kafka.Fetch         orders         ✓      │
│ 15:22:11   user:jane@co.com   kafka.CreateTopics  dev-test       ✓      │
│ 15:20:33   sa-terraform-ci    kafka.DeleteTopics  old-data       ✓      │
│ 15:18:07   sa-external-app    kafka.Fetch         prod-payments  ✗      │
│ ...                                                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Topic × Identity Matrix
```
┌─────────────────────────────────────────────────────────────────────────┐
│ TOPIC × IDENTITY MATRIX                        [Stale ACL: 90 days ▼]  │
├─────────────────────────────────────────────────────────────────────────┤
│ Identity              orders    payments   users     prod-*   Risk      │
├─────────────────────────────────────────────────────────────────────────┤
│ sa-prod-analytics     ✓ 8.5K    ✓ 3.2K     ✓ 1.8K   ✗ denied  LOW      │
│ sa-legacy-connector   ⚠️ 147d    -          -         -         HIGH     │
│ user:jane@legal.com   -         -          ✓ 12      -         LOW      │
│ sa-external-vendor    ✗ denied  ✗ denied   ✗ denied  ✗ denied  LOW ✓    │
│ ...                                                                      │
└─────────────────────────────────────────────────────────────────────────┘

Legend: ✓ = Access granted  ✗ = Denied  ⚠️ = Stale (90+ days)  Number = Event count
```

### Time Insights Heatmap
```
┌─────────────────────────────────────────────────────────────────────────┐
│ TIME INSIGHTS - Activity Heatmap                                        │
├─────────────────────────────────────────────────────────────────────────┤
│ Day \ Hour  00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 ...     │
├─────────────────────────────────────────────────────────────────────────┤
│ Monday      ░░ ░░ ░░ ░░ ░░ ░░ ░░ ▓▓ ██ ██ ██ ██ ██ ██ ██ ██ ██ ...     │
│ Tuesday     ░░ ░░ ░░ ░░ ░░ ░░ ░░ ▓▓ ██ ██ ██ ██ ██ ██ ██ ██ ██ ...     │
│ Wednesday   ░░ ░░ ██ ░░ ░░ ░░ ░░ ▓▓ ██ ██ ██ ██ ██ ██ ██ ██ ██ ... ⚠️  │
│ Thursday    ░░ ░░ ░░ ░░ ░░ ░░ ░░ ▓▓ ██ ██ ██ ██ ██ ██ ██ ██ ██ ...     │
│ Friday      ░░ ░░ ░░ ░░ ░░ ░░ ░░ ▓▓ ██ ██ ██ ██ ██ ██ ██ ▓▓ ▓▓ ...     │
│ Saturday    ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ...     │
│ Sunday      ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ░░ ...     │
└─────────────────────────────────────────────────────────────────────────┘

Legend: ░░ Low  ▓▓ Medium  ██ High
⚠️ Anomaly: Wednesday 02:00 has unusual activity (click to investigate)
```

---

## Getting Started

### For Security Engineers
1. Start at **Welcome** tab → Review service health
2. Check **Security Alerts** tab for active alerts
3. Review **Failures** tab for auth issues
4. Set up Slack webhook for real-time alerts

### For Compliance Officers
1. Navigate to **Export** tab
2. Generate sample PDF report
3. Review **Topic × Identity** for access matrix
4. Bookmark quarterly report configuration

### For SREs
1. Check **Audit Trail** for recent activity
2. Use **Analytics** tab to establish baseline
3. Monitor **Deletions** tab for destructive actions
4. Integrate with PagerDuty for CRITICAL events

### For Data Governance
1. Start with **Topic × Identity** matrix
2. Enable Stale ACL detection (90-day threshold)
3. Review **Identity Activity** for service accounts
4. Schedule weekly access certification review

---

**Next Steps:**
- [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md) - Query AuditLens from Claude Code
- [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) - All metrics and alerts
- [Compliance Templates](./COMPLIANCE_TEMPLATES.md) - SOC2, ISO27001, HIPAA templates

---

**Version:** 1.0
**Last Updated:** 2025-02-19
**Supported AuditLens Version:** v11.0+
