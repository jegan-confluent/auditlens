# AuditLens Customer Documentation Index

**Complete Guide to Security, Compliance, and Operational Excellence with AuditLens**

---

## Quick Navigation

| I want to... | Read this document | Key sections |
|--------------|-------------------|--------------|
| **Understand what AuditLens can do for my role** | [Customer Use Cases](./CUSTOMER_USE_CASES.md) | Use Cases by Persona |
| **See real-world scenarios** | [Customer Use Cases](./CUSTOMER_USE_CASES.md) | 12 detailed scenarios with solutions |
| **Learn dashboard features** | [Customer Use Cases](./CUSTOMER_USE_CASES.md) | Dashboard Tab Reference |
| **Query audit logs with AI** | [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md) | Setup Instructions, Example Queries |
| **Set up Claude Code integration** | [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md) | Step-by-step configuration |
| **Understand metrics and alerts** | [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) | Prometheus Metrics, Alert Configuration |
| **Configure alert thresholds** | [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) | Alert Configuration |
| **Export audit logs** | [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) | Export Capabilities |
| **Prepare for SOC2 audit** | [Compliance Templates](./COMPLIANCE_TEMPLATES.md) | SOC2 Audit Report Template |
| **Prepare for ISO27001 audit** | [Compliance Templates](./COMPLIANCE_TEMPLATES.md) | ISO27001 Report Template |
| **Generate HIPAA access logs** | [Compliance Templates](./COMPLIANCE_TEMPLATES.md) | HIPAA Access Log Template |
| **Demonstrate PCI-DSS compliance** | [Compliance Templates](./COMPLIANCE_TEMPLATES.md) | PCI-DSS Audit Template |

---

## Documentation Overview

### 1. Customer Use Cases (35 KB, 15-20 min read)
**File:** [CUSTOMER_USE_CASES.md](./CUSTOMER_USE_CASES.md)

**Who should read this:** Everyone - Security Engineers, Compliance Officers, SREs, Data Governance teams

**What you'll learn:**
- ✅ 12 real-world scenarios with step-by-step solutions
- ✅ How each persona uses AuditLens (Security, Compliance, SRE, Governance)
- ✅ Complete dashboard tab reference with ASCII previews
- ✅ 50+ example queries for common questions
- ✅ Visual walkthroughs of investigations

**Key scenarios:**
- Investigating repeated authorization failures
- Detecting after-hours production access
- API key rotation compliance
- SOC2/ISO27001 report generation
- Post-mortem analysis
- Data exfiltration detection

---

### 2. MCP Integration Guide (27 KB, 10-15 min read)
**File:** [MCP_INTEGRATION_GUIDE.md](./MCP_INTEGRATION_GUIDE.md)

**Who should read this:** Security Engineers, SREs, Compliance Officers who want to query audit logs with natural language via Claude Code

**What you'll learn:**
- ✅ What is MCP and why it matters
- ✅ Step-by-step Claude Code configuration (5 minutes)
- ✅ 20+ example natural language queries
- ✅ Security configuration (Bearer token auth, IP allowlist)
- ✅ Troubleshooting common issues

**Example queries you can ask:**
- "Show me all failed authorization attempts in the last hour"
- "Who accessed production topics after 6 PM yesterday?"
- "Generate a SOC2 audit report for Q4 2024"
- "Which service accounts haven't accessed their topics in 90 days?"

**Key benefit:** Turn 30-minute manual investigations into 10-second AI-powered queries

---

### 3. Monitoring Capabilities (25 KB, 10 min read)
**File:** [MONITORING_CAPABILITIES.md](./MONITORING_CAPABILITIES.md)

**Who should read this:** SREs, Platform Engineers, Security Operations teams

**What you'll learn:**
- ✅ All 40+ Prometheus metrics exposed by AuditLens
- ✅ 6 pre-configured alert rules (consumer lag, high error rate, mass deletion, etc.)
- ✅ Retention policies by topic (CRITICAL: 90d, HIGH: 30d, MEDIUM: 14d, LOW: 7d)
- ✅ Export capabilities (S3, GCS, CSV, PDF, JSON)
- ✅ Grafana dashboards (Forwarder Health, Security Overview, Capacity Planning)
- ✅ Health check endpoints

**Key metrics:**
- `audit_forwarder_processed_messages_total` - Total events processed
- `audit_forwarder_consumer_lag_total` - How far behind real-time
- `audit_security_failures_total` - Auth/authz failures
- `audit_webhook_alerts_sent` - Alerts delivered to Slack/PagerDuty

**Alert examples:**
- Consumer lag >10,000 messages → Warning
- No messages processed in 5 minutes → Critical
- >5 topic deletions in 5 minutes → Critical (mass deletion)
- ≥20 authorization denials in 60 seconds → High (aggregated alert)

---

### 4. Compliance Templates (33 KB, 15 min read)
**File:** [COMPLIANCE_TEMPLATES.md](./COMPLIANCE_TEMPLATES.md)

**Who should read this:** Compliance Officers, Auditors, Legal teams, InfoSec teams

**What you'll learn:**
- ✅ Ready-to-use SOC2 Type II audit report template
- ✅ ISO27001 Annex A.9/A.12 evidence template
- ✅ HIPAA 45 CFR § 164.308 access log template
- ✅ PCI-DSS Requirement 10 evidence template
- ✅ Example compliance queries
- ✅ Evidence collection guide for auditors

**SOC2 Coverage:**
- CC6.1 - Logical access controls
- CC6.2 - Credential issuance
- CC6.3 - Access removal when no longer required
- CC6.6 - Removes access no longer needed
- CC7.2 - Security incident detection
- CC7.3 - Security event evaluation

**ISO27001 Coverage:**
- A.9.2.1 - User registration/de-registration
- A.9.2.2 - User access provisioning
- A.9.2.5 - Review of access rights
- A.9.4.1 - Information access restriction
- A.12.4.1 - Event logging
- A.12.4.3 - Administrator logs

**HIPAA Coverage:**
- 45 CFR § 164.308(a)(1)(ii)(D) - Information system activity review
- PHI access tracking
- Minimum necessary principle enforcement
- Business Associate access monitoring

**PCI-DSS Coverage:**
- Requirement 10.2 - Automated audit trails
- Requirement 10.3 - Audit trail fields
- Requirement 10.5.1 - Limit audit log viewing
- Requirement 10.6 - Log review
- Requirement 10.7 - Retention (365 days)

---

## Documentation Statistics

| Document | Size | Read Time | Sections | Examples | Templates |
|----------|------|-----------|----------|----------|-----------|
| Customer Use Cases | 35 KB | 15-20 min | 4 | 12 scenarios | 8 query examples |
| MCP Integration | 27 KB | 10-15 min | 7 | 20+ queries | 3 config examples |
| Monitoring Capabilities | 25 KB | 10 min | 7 | 40+ metrics | 6 alert rules |
| Compliance Templates | 33 KB | 15 min | 6 | 8 queries | 4 full reports |
| **Total** | **120 KB** | **50-60 min** | **24** | **80+** | **21** |

---

## Suggested Reading Order

### For First-Time Users
1. Start with [Customer Use Cases](./CUSTOMER_USE_CASES.md) - **Dashboard Tab Reference** section
2. Read your persona-specific use cases (Security, Compliance, SRE, or Governance)
3. Try example queries in the dashboard
4. If interested in AI queries, proceed to [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md)

---

### For Security Engineers
1. [Customer Use Cases](./CUSTOMER_USE_CASES.md) - **Security Engineer** section
2. [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) - **Alert Configuration** section
3. [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md) - **Security Queries** section
4. Set up Slack webhook for real-time alerts

---

### For Compliance Officers
1. [Compliance Templates](./COMPLIANCE_TEMPLATES.md) - Your framework (SOC2, ISO27001, HIPAA, or PCI-DSS)
2. [Customer Use Cases](./CUSTOMER_USE_CASES.md) - **Compliance Officer** section
3. [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md) - **Compliance Queries** section
4. Generate sample PDF report from **Export** tab

---

### For SREs / Platform Engineers
1. [Customer Use Cases](./CUSTOMER_USE_CASES.md) - **SRE** section
2. [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) - Full document
3. Set up Prometheus alerts and Grafana dashboards
4. Configure S3/GCS export for long-term retention

---

### For Data Governance Leads
1. [Customer Use Cases](./CUSTOMER_USE_CASES.md) - **Data Governance** section
2. [Customer Use Cases](./CUSTOMER_USE_CASES.md) - **Topic × Identity Matrix** tab reference
3. Enable Stale ACL detection (90-day threshold)
4. Schedule weekly access certification reviews

---

## Quick Start Checklist

### Day 1: Get AuditLens Running
- [ ] Run `./scripts/setup.sh` (5 minutes)
- [ ] Verify services: `./scripts/verify.sh`
- [ ] Open dashboard: http://localhost:8503
- [ ] Read **Welcome** tab feature guide

---

### Day 2: Explore Your Use Case
- [ ] Read persona-specific section in [Customer Use Cases](./CUSTOMER_USE_CASES.md)
- [ ] Try 3-5 example queries from your role
- [ ] Bookmark relevant dashboard tabs
- [ ] Export sample CSV/PDF report

---

### Week 1: Set Up Monitoring
- [ ] Read [Monitoring Capabilities](./MONITORING_CAPABILITIES.md)
- [ ] Configure Slack webhook for alerts
- [ ] Set up Prometheus scraping
- [ ] Review Grafana dashboards (http://localhost:3000)
- [ ] Test alert rules (simulate high consumer lag)

---

### Week 2: AI Integration (Optional)
- [ ] Read [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md)
- [ ] Install Claude Code
- [ ] Configure MCP server (5 minutes)
- [ ] Test 5 natural language queries
- [ ] Share with team (show value)

---

### Month 1: Compliance Preparation
- [ ] Read relevant framework in [Compliance Templates](./COMPLIANCE_TEMPLATES.md)
- [ ] Generate sample compliance report
- [ ] Schedule quarterly access reviews
- [ ] Configure long-term archival (S3/GCS)
- [ ] Document evidence collection process

---

## Support Resources

### Documentation
- [Quick Start](./QUICK_START.md) - Get started in 5 minutes
- [End-to-End Flow](./END_TO_END_FLOW.md) - Technical architecture deep dive
- [Audit Queries](./AUDIT_QUERIES.md) - Advanced query examples
- [README](./README.md) - Project overview

---

### Live Support
- **Dashboard:** http://localhost:8503 (Welcome tab has system status)
- **Metrics:** http://localhost:8003/metrics (Prometheus metrics)
- **Health:** http://localhost:8003/health (Health check API)
- **Grafana:** http://localhost:3000 (admin/admin)

---

### Common Questions

#### Q: Which document should I read first?
**A:** Start with [Customer Use Cases](./CUSTOMER_USE_CASES.md). It's written for all audiences and covers practical scenarios.

---

#### Q: I'm preparing for a SOC2 audit next month. What should I do?
**A:**
1. Read [Compliance Templates](./COMPLIANCE_TEMPLATES.md) - SOC2 section
2. Generate a sample report in **Export** tab
3. Review [Customer Use Cases](./CUSTOMER_USE_CASES.md) - Use Case 4 (SOC2 Report Generation)
4. Export CSV evidence files for auditor
5. Optionally set up [MCP Integration](./MCP_INTEGRATION_GUIDE.md) to answer auditor questions in real-time

---

#### Q: How do I query audit logs with natural language?
**A:** Read [MCP Integration Guide](./MCP_INTEGRATION_GUIDE.md). Setup takes 5 minutes, then you can ask questions like "Show me all failed authorization attempts in the last hour" directly in Claude Code.

---

#### Q: What metrics should I monitor?
**A:** Read [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) - Section 2 (Prometheus Metrics). Key metrics:
- `audit_forwarder_consumer_lag_total` - How far behind
- `audit_forwarder_processing_rate_per_second` - Throughput
- `audit_security_failures_total` - Auth failures

---

#### Q: How long does AuditLens retain audit logs?
**A:**
- **Kafka (hot storage):** 90 days for CRITICAL, 30 days for HIGH, 14 days for MEDIUM, 7 days for LOW
- **S3/GCS (cold storage):** Configurable (recommend 365 days for compliance)
- See [Monitoring Capabilities](./MONITORING_CAPABILITIES.md) - Section 4 (Retention Policies)

---

## Feedback & Contributions

These documents are living resources. If you find:
- ✅ Missing use cases for your role
- ✅ Unclear sections
- ✅ Additional compliance frameworks needed
- ✅ Example queries that would help others

Please open a GitHub issue or submit a pull request.

---

## Document Versions

| Document | Version | Last Updated | Status |
|----------|---------|--------------|--------|
| Customer Use Cases | 1.0 | 2025-02-19 | ✅ Current |
| MCP Integration Guide | 1.0 | 2025-02-19 | ✅ Current |
| Monitoring Capabilities | 1.0 | 2025-02-19 | ✅ Current |
| Compliance Templates | 1.0 | 2025-02-19 | ✅ Current |

**Supported AuditLens Version:** v11.0+

---

**Happy auditing!**
