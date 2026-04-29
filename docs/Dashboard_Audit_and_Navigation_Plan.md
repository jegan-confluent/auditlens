# Dashboard Audit and Navigation Plan

## Executive Summary

The dashboard is functionally rich but product-heavy: it exposes 13 primary tabs, 5 sidebar search fields, 10 quick-filter buttons, 3 clickable KPI filters, tab-specific filters, and filter presets at the same time. The result is not a lack of capability; it is an unclear information architecture.

The core user questions are investigation-oriented: what happened, who did it, what failed, what was deleted, and what should I report. The current UI splits those questions across overlapping tabs such as Audit Trail, All Failures, Security, Security Alerts, Details, Topic x Identity, Identity Activity, Analytics, and Time Insights. Several advanced views depend on optional identity/ACL enrichment and should not be first-level navigation.

Recommendation: keep the existing data model and tab code for now, but collapse the visible primary navigation to four tabs plus an Advanced section. Before any visual redesign, simplify filter semantics: one global filter bar, one active filter state, and tab-specific filters only inside advanced investigation views.

## Current Dashboard Map

| Tab / Area | File / Function | Purpose | User Value | Recommendation |
|---|---|---|---|---|
| App shell | `dashboard/app.py` top-level Streamlit script | Header, sidebar filters, data loading, quick filters, KPI filters, and tab registration | Central control surface | **FIX BEFORE SHOWING**: too many global controls, debug info visible, tabs overloaded |
| Welcome | `dashboard/tabs/welcome.py::render` | Onboarding, service health, feature catalog, common questions | Useful first-run orientation | **MERGE** into Overview; keep health/coverage, remove searchable feature catalog from primary flow |
| Audit Trail | `dashboard/tabs/audit_trail.py::render_tab` | Complete event table | Core investigation view for who/what/when/resource/result | **KEEP CORE** |
| All Failures | `dashboard/tabs/failures.py::render_tab` | Failure-only event table with summary charts | Answers denied/failed operation questions | **KEEP CORE**, rename to Failures |
| Deletions | `dashboard/tabs/deletions.py::render_tab` | Deletion-only event table with summary charts | Answers destructive action questions | **KEEP CORE** |
| API Keys | `dashboard/tabs/api_keys.py::render_tab` | API key create/delete/update/rotate events | Useful for security reviews | **MOVE TO ADVANCED**; also reachable via Audit Trail preset |
| Security | `dashboard/tabs/security.py::render_tab` | RBAC/ACL fields and authorization events | Potentially useful, but often sparse because fields may be missing | **FIX BEFORE SHOWING** or move to Advanced as Authorization Details |
| Details | `dashboard/tabs/details.py::render_tab` | Select one event and inspect fields/JSON | Valuable drill-down, but not a top-level destination | **MERGE** into Audit Trail row selection/expander or Advanced |
| Analytics | `dashboard/tabs/analytics.py::render_tab` | Criticality, methods, timeline, top users charts | Useful summary, duplicates Overview and Time Insights | **MERGE** into Overview |
| Time Insights | `dashboard/tabs/time_insights.py::render_tab` | Heatmaps and time-bucket charts | Advanced pattern analysis | **MOVE TO ADVANCED**, possibly merge with Analytics |
| Export | `dashboard/tabs/export.py::render_tab` | CSV, JSON, PDF downloads from current dataframe | Compliance/reporting workflow | **MOVE TO ADVANCED**, but expose as button from Audit Trail/Overview |
| Security Alerts | `dashboard/tabs/security_alerts.py::render_tab` | Aggregated denial summaries from signals topic | Useful if aggregation is running | **MERGE** into Overview alert panel and Failures tab |
| Topic x Identity | `dashboard/tabs/topic_identity.py::render_topic_identity_tab` | Topic-principal activity, optional ACL data, stale ACLs, Sankey | High-value advanced investigation | **MOVE TO ADVANCED**; needs clearer dependency warnings |
| Identity Activity | `dashboard/tabs/identity_activity.py::render_identity_activity_tab` | Per-principal profile, risk score, timeline, table | Answers “what did this identity do?” | **MOVE TO ADVANCED**, but link from Audit Trail principal |
| Alert banner | `dashboard/components/filters.py::render_alert_banner` | Inline anomaly banner from current dataframe | Useful if trustworthy | **MERGE** into Overview; avoid duplicating Security Alerts |
| Quick filters | `dashboard/components/filters.py::render_quick_filters`, `apply_quick_filter` | Button filters for common slices | Fast but conflicts with sidebar/KPI/tabs | **FIX BEFORE SHOWING**: one active filter model |
| Pagination | `dashboard/components/filters.py::render_paginated_dataframe` | Shared paginated tables | Useful and reusable | **KEEP CORE** |
| KPI cards | `dashboard/components/metrics.py::render_metric_card`; clickable buttons in `app.py` | Counts and metric-filter actions | Useful summary, but filter side effects unclear | **MERGE** with Overview; make clicks explicit chips |
| Kafka events loader | `dashboard/data/kafka_consumer.py::load_events_from_kafka` | Reads latest enriched events from Kafka | Main data source | **KEEP CORE**, but consider backend/API path later |
| Security alerts loader | `dashboard/data/kafka_consumer.py::load_security_alerts` | Reads denial signal topic | Powers Security Alerts | **MOVE TO ADVANCED / Overview alert panel** |
| Transformations | `dashboard/data/transformations.py` helpers | Deep field extraction, display fields, classification, anomalies | Required for dashboard semantics | **KEEP CORE**, but centralize with backend semantics later |
| Email cache | `dashboard/data/email_cache.py` helpers | Maps principals to emails/user names | Useful but optional | **MOVE TO ADVANCED config/status**; failure should not distract |
| Export helpers | `dashboard/data/export.py` | CSV/JSON/PDF serialization | Needed for compliance reports | **KEEP**, expose in Advanced/Report workflow |
| Chart helpers | `dashboard/components/charts.py` | Reusable chart constructors | Mostly not wired from current tabs | **REMOVE / HIDE FOR NOW** unless reused in redesign |
| Metrics parser | `dashboard/metrics_parser.py` | Prometheus parsing and forwarder status helpers | Not wired into current dashboard app | **REMOVE / HIDE FOR NOW** or move to Overview if used |
| Legacy consumer | `dashboard/data/kafka_consumer_old.py` | Old Kafka loader | Legacy copy | **REMOVE / HIDE FOR NOW** after confirming not imported |
| Refactor scripts | `dashboard/create_tabs.py`, `dashboard/refactor_script.py` | One-off migration scripts reading backups | Not runtime dashboard | **REMOVE / HIDE FOR NOW** from product package |
| Backups | `dashboard/app.py.backup`, `dashboard/app.py.backup-simple` | Historical app copies | Not runtime dashboard | **REMOVE / HIDE FOR NOW** after repo cleanup approval |

## Dashboard-Related Functions and Classes

| File | Function/Class | Purpose | Powers |
|---|---|---|---|
| `dashboard/app.py` | top-level Streamlit script | App shell, global filters, data load, KPI filters, tab routing | Entire dashboard |
| `dashboard/config.py` | `get_logo_base64` | Load logo | Header |
| `dashboard/config.py` | `QUICK_FILTERS` | Quick filter definitions | Quick filter buttons |
| `dashboard/components/filters.py` | `render_alert_banner` | Render anomaly banners | Global banner |
| `dashboard/components/filters.py` | `render_quick_filters` | Render two rows of quick-filter buttons | Global quick filters |
| `dashboard/components/filters.py` | `apply_quick_filter` | Apply quick filter predicates | Global dataframe |
| `dashboard/components/filters.py` | `render_paginated_dataframe` | Paginated Streamlit dataframe | Audit Trail, Failures, Deletions, API Keys, Security |
| `dashboard/components/metrics.py` | `render_metric_card` | Static HTML metric card | KPI row |
| `dashboard/components/charts.py` | `create_*_chart` helpers | Chart factory functions | Not visibly wired by current app |
| `dashboard/data/kafka_consumer.py` | `load_events_from_kafka` | Load latest enriched events from Kafka | Main dataframe |
| `dashboard/data/kafka_consumer.py` | `load_security_alerts` | Load denial summaries | Security Alerts |
| `dashboard/data/transformations.py` | `extract_deep_fields` | Flatten nested audit event fields | Data load |
| `dashboard/data/transformations.py` | `extract_user_display` | Normalize principal display | Tables |
| `dashboard/data/transformations.py` | `format_resource_for_display` | Resource label formatting | Tables |
| `dashboard/data/transformations.py` | `is_failure_event` | Failure classification | Failures/metrics/filters |
| `dashboard/data/transformations.py` | `classify_event` | Dashboard-side criticality fallback | Metrics/filters |
| `dashboard/data/transformations.py` | `enhance_events_dataframe` | Adds display and flag columns | All tabs |
| `dashboard/data/transformations.py` | `detect_anomalies` | Dashboard-side simple anomaly detection | Alert banner |
| `dashboard/data/email_cache.py` | `load_email_cache`, `save_email_cache`, `fetch_users_from_confluent_api`, `refresh_email_cache`, `extract_user_id`, `enrich_email_from_cache`, `build_cache_from_dataframe`, `load_user_mapping`, `initialize_email_cache` | Identity/email enrichment | Sidebar refresh, display names |
| `dashboard/data/export.py` | `export_to_csv`, `export_to_json`, `export_to_pdf` | Report/download generation | Export tab |
| `dashboard/tabs/welcome.py` | `check_service_health`, normalization helpers, `storage_warning_summary`, `render_status_indicator`, `render` | Health/onboarding | Welcome tab |
| `dashboard/tabs/audit_trail.py` | `render_tab` | Complete event table | Audit Trail |
| `dashboard/tabs/failures.py` | `render_tab` | Failure-only table/charts | All Failures |
| `dashboard/tabs/deletions.py` | `render_tab` | Deletion-only table/charts | Deletions |
| `dashboard/tabs/api_keys.py` | `render_tab` | API key events | API Keys |
| `dashboard/tabs/security.py` | `render_tab` | RBAC/ACL/security table | Security |
| `dashboard/tabs/details.py` | `render_tab` | Single-event inspection | Details |
| `dashboard/tabs/analytics.py` | `render_tab` | General charts | Analytics |
| `dashboard/tabs/time_insights.py` | `render_tab` | Time heatmaps and trends | Time Insights |
| `dashboard/tabs/export.py` | `render_tab` | Downloads and preview | Export |
| `dashboard/tabs/security_alerts.py` | `render_tab` | Aggregated denial alert table | Security Alerts |
| `dashboard/tabs/topic_identity.py` | `aggregate_topic_activity`, `enrich_with_identity_names`, `get_acl_data`, `find_stale_acls`, render helpers | Topic/identity and ACL analysis | Topic x Identity |
| `dashboard/tabs/identity_activity.py` | `calculate_risk_score`, `get_identity_profile`, render helpers | Per-identity analysis | Identity Activity |
| `dashboard/metrics_parser.py` | `MetricValue`, `parse_prometheus_text`, `fetch_metrics`, `get_metrics_dict`, `get_forwarder_status`, distribution helpers | Metrics parsing | Not currently wired into app |

## Filter System Analysis

### Global Data Load Filters

| Filter | Location | Applied Where | Scope | Notes |
|---|---|---|---|---|
| Criticality Level | `dashboard/app.py` sidebar | Passed into `load_events_from_kafka` | Global, pre-transform | Overlaps with quick filter `all_failures`, KPI Critical, and tab-specific Security/Failures/Deletions |
| Time Window | `dashboard/app.py` sidebar and `load_events_from_kafka` | Kafka-loaded dataframe filtered after read | Global | Also duplicated by Identity Activity's own time range |
| Max Events | `dashboard/app.py` sidebar | Controls Kafka read volume | Global | Operator setting, not really a user filter |
| Hide internal/system operations | `dashboard/app.py` | Filters `is_internal` after transform | Global | Useful default, but hidden semantics are vague |
| Hide successful authz noise | `dashboard/app.py` | Filters `is_successful_authz_noise` | Global | Useful, but can make Security tab look empty or misleading |

### Sidebar Search Filters

| Filter | Location | Applied Where | Scope | Notes |
|---|---|---|---|---|
| Cluster | `dashboard/app.py` | `cluster_id.str.contains` | Global | Overlaps with Topic x Identity cluster filter |
| Environment | `dashboard/app.py` | `environment_id.str.contains` | Global | Reasonable |
| Principal/User | `dashboard/app.py` | `principal`, `principal_normalized`, `email` | Global | Overlaps with Identity Activity search/select |
| Method | `dashboard/app.py` | `methodName.str.contains` | Global | Overlaps with quick filters and tabs |
| Resource | `dashboard/app.py` | `resourceName.str.contains` only | Global | Risk: ignores `resource_display`, `authzResourceName`, and `topic_name`, so users may not find visible resources |

### Quick Filters

Defined in `dashboard/config.py::QUICK_FILTERS`, rendered by `components.filters.render_quick_filters`, applied by `apply_quick_filter`.

| Quick Filter | Predicate | Overlap / Risk |
|---|---|---|
| All Failures | `is_failure == True` | Duplicates Failures tab and KPI Failures |
| Deletions | `methodName contains Delete` | Duplicates Deletions tab and KPI Deletions |
| Creations | `methodName contains Create` | Useful but no dedicated destination |
| API Keys | `methodName contains ApiKey` | Duplicates API Keys tab and preset |
| Topics | `methodName contains Topic` | Partial; misses many topic authz events where resource contains topic but method does not |
| Users/SA | `methodName contains User/ServiceAccount/SignIn` | Misleading: does not search actual principal identity |
| Connectors | `methodName contains Connector` | Advanced |
| Flink | `Statement/ComputePool/Flink` | Advanced/premature for core |
| RBAC | `Role/Acl/Bind` | Duplicates Security tab |
| Denied | `granted == False` | Duplicates Failures subset and Security Alerts concept |

### KPI Click Filters

In `dashboard/app.py`, KPI buttons set `st.session_state.metric_filter` for critical, failures, and deletions. They clear quick filters but not sidebar filters. This is confusing because users can have active sidebar filters plus a KPI filter plus a tab that applies another filter.

### Tab-Specific Filters

| Tab | Filters | Scope | Risk |
|---|---|---|---|
| Topic x Identity | Cluster, stale ACL threshold, search, view mode | Tab-only | Duplicates global cluster/search but only after global filters already altered data |
| Identity Activity | Search identity, select identity, time range | Tab-only | Duplicates global principal and time filters; operates on already-filtered global dataframe |
| Details | Event selector | Tab-only | Limited to first 100 after global filters, so important event may be hidden |
| Export | None | Current global dataframe | Export result can silently reflect hidden quick/KPI/sidebar filters |
| Security Alerts | Uses global time window, then separate Kafka load | Semi-global | Does not use current dataframe; semantics differ from other tabs |

### Presets

Presets are stored in `st.session_state.filter_presets` and can be saved, but loading a preset only displays its values with `st.info`; it does not actually apply them back to Streamlit widget state. This is a major UX bug: it looks like a feature, but it is not an effective navigation/filter mechanism.

## Keep / Move / Merge / Remove

| Feature | Classification | Reason |
|---|---|---|
| Audit Trail table | KEEP CORE | Primary investigation surface |
| Failures table | KEEP CORE | Directly answers failure/denial questions |
| Deletions table | KEEP CORE | High-value destructive action view |
| Overview health + high-level metrics | KEEP CORE | Needed first screen |
| Export/report generation | MOVE TO ADVANCED | Important, but not a first tab |
| API Keys | MOVE TO ADVANCED | Useful security workflow; too specific for primary nav |
| Security RBAC/ACL tab | FIX BEFORE SHOWING | Often sparse and affected by hidden authz noise |
| Security Alerts | MERGE | Should surface in Overview and Failures, not separate primary tab |
| Details tab | MERGE | Should be a drill-down from Audit Trail, not a tab |
| Analytics | MERGE | Useful charts belong in Overview |
| Time Insights | MOVE TO ADVANCED | Useful but not first-time core |
| Topic x Identity | MOVE TO ADVANCED | Powerful but optional API/ACL dependencies |
| Identity Activity | MOVE TO ADVANCED | Powerful investigation view, linked from principals |
| Quick filters | FIX BEFORE SHOWING | Useful but currently duplicates tabs/KPI/sidebar |
| Clickable KPI filters | MERGE | Keep as explicit filter chips or Overview links |
| Presets | FIX BEFORE SHOWING | Current load behavior does not apply values |
| Keyboard shortcuts | REMOVE / HIDE FOR NOW | JavaScript shortcut promise is fragile in Streamlit and not core |
| `dashboard/components/charts.py` | REMOVE / HIDE FOR NOW | Appears unused by current app |
| `dashboard/metrics_parser.py` | REMOVE / HIDE FOR NOW | Not wired into app despite potential value |
| `dashboard/data/kafka_consumer_old.py` | REMOVE / HIDE FOR NOW | Legacy duplicate |
| `dashboard/create_tabs.py`, `dashboard/refactor_script.py` | REMOVE / HIDE FOR NOW | One-off migration scripts |
| `dashboard/app.py.backup*` | REMOVE / HIDE FOR NOW | Historical copies should not ship |

## Proposed Navigation

Keep primary navigation to four first-level tabs plus one Advanced menu/section.

### 1. Overview

Purpose: “Is AuditLens healthy, what happened recently, and what needs attention?”

Contains:
- Service health and persistence/hot-cache status from Welcome.
- Key metrics: total events, failures, deletions, critical/high, unique principals.
- Recent Security Alerts summary.
- Top methods/users charts from Analytics.
- Clear active filter chips.

Move from:
- Welcome
- Analytics
- Security Alerts summary
- KPI row

### 2. Audit Trail

Purpose: “Show me the events.”

Contains:
- Main event table.
- Global search/filter bar.
- Row expand/detail drawer replacing Details tab.
- Direct links/actions: filter by this principal, filter by this resource, export current result.

Move from:
- Audit Trail
- Details
- parts of Export

### 3. Failures

Purpose: “What failed and why?”

Contains:
- Failure-only table.
- Denial summaries/security alerts.
- Failure reason/status breakdown.
- Principal/resource investigation links.

Move from:
- All Failures
- Security Alerts
- Denied quick filter

### 4. Deletions

Purpose: “What destructive actions happened?”

Contains:
- Deletion-only table.
- Deleted resource/user summaries.
- Topic/resource filters.

Move from:
- Deletions
- deletion KPI filter

### 5. Advanced

Use as a grouped section, not equal-weight primary tabs.

Under Advanced:
- API Keys
- Identity Activity
- Topic x Identity
- Authorization / RBAC / ACL
- Time Insights
- Export / Compliance Report
- Raw Analytics

Rationale: these are valuable but specialized. They require context, optional enrichment, or a specific reporting workflow.

## User Journey Mapping

| Question | Ideal Path | Filters | Expected Output |
|---|---|---|---|
| Who created topic X? | Audit Trail | Resource = topic X, Method = Create or action Creation | Table rows showing creator principal, time, cluster, result; row detail for raw event |
| Who deleted topic X? | Deletions | Resource/topic = topic X | Deletion event with principal, timestamp, cluster/environment, result, source IP |
| Why did topic creation fail? | Failures | Resource = topic X, Method = Create/Topic | Failure row with result status, granted flag, auth/resource fields, raw details |
| What did service account `sa-xxxxx` do? | Audit Trail, then Advanced → Identity Activity | Principal = `sa-xxxxx` | Timeline/table of actions, clusters, resources, failures, risk indicators |
| Are there auth failures? | Failures | Failure type Denied/Auth or no filter | Denied/auth failures, top principals, status breakdown, alert summaries |
| Are there suspicious activities? | Overview first, Advanced if needed | No initial filter; then principal/resource drill-down | Anomaly banner, critical/high/deletion/API key summaries, links into Audit Trail |
| Generate compliance report | Advanced → Export / Compliance Report | Time range + optional principal/resource filters | CSV/JSON/PDF export with clear note that it reflects current filters and hot-cache window |

## Risks and Fixes Before Redesign

1. **Preset loading is misleading**
   - Risk: user selects a preset and sees an info message, but filters are not applied.
   - Fix: either implement widget state application or hide presets until redesign.

2. **Too many active filter systems**
   - Risk: sidebar + quick filter + KPI filter + tab filter can stack invisibly.
   - Fix: one global filter state shown as chips. Quick filters and KPI clicks should set the same state.

3. **Resource search does not match what users see**
   - Risk: sidebar Resource searches only `resourceName`, while tables show `resource_display`; topic info can live in `authzResourceName` or `topic_name`.
   - Fix: resource filter should search `resourceName`, `authzResourceName`, `resource_display`, and `topic_name`.

4. **Security tab can be empty or misleading**
   - Risk: global “Hide successful authz noise” can remove most authorization evidence before the Security tab sees it.
   - Fix: Security/Authorization view should either override that filter or explicitly say authz noise is hidden.

5. **Topic x Identity uses columns before aggregation**
   - Risk: tab-level search references `topic_resource` before `aggregate_topic_activity` creates it. This can fail or silently not work depending on dataframe columns.
   - Fix: compute topic_resource before search, or search `resourceName/authzResourceName`.

6. **Optional enrichment warnings are implementation-oriented**
   - Risk: users see “install src/identity and src/confluent_api modules,” which is not product language.
   - Fix: say “Identity/ACL enrichment is not configured” and show what still works.

7. **Dashboard duplicates backend semantics**
   - Risk: `dashboard/data/transformations.py::classify_event`, `is_failure_event`, and `detect_anomalies` may diverge from forwarder classification.
   - Fix: prefer forwarder-enriched fields and clearly mark dashboard-derived heuristics.

8. **Security Alerts reads a separate Kafka topic**
   - Risk: unlike most tabs, it ignores the current dataframe except time config; users may expect all filters to apply.
   - Fix: label it as “aggregated signals” and explain filter scope.

9. **Details tab is capped to first 100 current rows**
   - Risk: users cannot inspect an event outside the first 100 filtered rows.
   - Fix: row-level expansion in Audit Trail or event-id search.

10. **Performance risk in dashboard Kafka reads**
    - Risk: each refresh scans recent offsets per partition from Kafka and then transforms/enriches locally.
    - Fix: later redesign should use the forwarder API/SQLite hot cache for UI reads, with Kafka as backend pipeline, not direct dashboard polling.

11. **Dead/legacy files increase maintenance risk**
    - Risk: backups, old consumer, migration scripts, and unused chart/metrics helpers obscure the true runtime surface.
    - Fix: after this audit is accepted, remove or archive them in a cleanup-only change.

12. **Export semantics are unclear**
    - Risk: export reflects current in-memory dataframe, hidden filters, max event cap, and hot-cache window, but does not state that clearly.
    - Fix: every export should include filter summary, time window, max rows, and “bounded hot cache” notice.

## Final Recommendation

Do not start with visual redesign. First simplify navigation and filter semantics.

Recommended sequence:

1. Hide or group Advanced tabs so first-level navigation is Overview, Audit Trail, Failures, Deletions, Advanced.
2. Replace quick/KPI/sidebar conflicts with one global filter state and visible active filter chips.
3. Merge Details into Audit Trail as row drill-down.
4. Merge Security Alerts into Overview and Failures.
5. Move API Keys, Topic x Identity, Identity Activity, Time Insights, Security/RBAC, and Export under Advanced.
6. Fix preset loading or remove it from the visible UI.
7. Add explicit copy anywhere data/export appears: “Showing recent hot-cache data only.”
8. Remove dead/legacy files only after the navigation plan is accepted.

The current dashboard has enough useful capability to keep. The problem is exposure and priority: too many specialized tools are presented as equal choices. The next UI pass should make the common investigation paths obvious and move expert workflows behind an Advanced boundary.
