"""
Welcome & Guide Tab - First-time user onboarding and feature discovery
"""

import streamlit as st
import requests
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from config import (
    DASHBOARD_FORWARDER_URL,
    DASHBOARD_GRAFANA_URL,
    DASHBOARD_PROMETHEUS_URL,
)


def check_service_health(url: str, timeout: float = 2.0) -> Dict[str, Any]:
    """Check health of a service endpoint."""
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code == 200:
            return {
                "status": "healthy",
                "details": response.json() if response.headers.get("content-type", "").startswith("application/json") else None,
            }
        return {"status": "degraded", "details": f"HTTP {response.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"status": "offline", "details": "Connection refused"}
    except requests.exceptions.Timeout:
        return {"status": "timeout", "details": "Request timed out"}
    except Exception as e:
        return {"status": "error", "details": str(e)}


def _as_dict(value: Any) -> Dict[str, Any]:
    """Return a dict only when the payload section is actually object-shaped."""
    return value if isinstance(value, dict) else {}


def _first_dict_field(*sources: Dict[str, Any], field: str) -> Dict[str, Any]:
    """Return the first non-empty dict field found across normalized sources."""
    for source in sources:
        value = source.get(field)
        if isinstance(value, dict) and value:
            return value
    return {}


def _first_list_field(*sources: Dict[str, Any], field: str) -> list:
    """Return the first non-empty list field found across normalized sources."""
    for source in sources:
        value = source.get(field)
        if isinstance(value, list) and value:
            return value
    return []


def _first_value_field(*sources: Dict[str, Any], field: str) -> Any:
    """Return the first present scalar/object field across normalized sources."""
    for source in sources:
        value = source.get(field)
        if value is not None:
            return value
    return None


def normalize_forwarder_health(service_health: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize current and legacy forwarder health payloads for dashboard rendering.

    Current forwarder health exposes freshness, coverage, recovery, and components
    at the top level of the JSON response. Older dashboard code expected those
    fields below details. Degraded service checks may also store a string in
    details, so callers must never assume object shape.
    """
    service_payload = _as_dict(service_health)
    payload = _as_dict(service_payload.get("details"))
    nested_details = _as_dict(payload.get("details"))
    sources = (nested_details, payload, service_payload)

    freshness = _first_dict_field(*sources, field="freshness")
    coverage = _first_dict_field(*sources, field="coverage")
    recovery = _first_dict_field(*sources, field="recovery")
    offset_recovery = _first_dict_field(*sources, field="offset_recovery")
    observability = _first_dict_field(*sources, field="observability")
    components = _first_list_field(*sources, field="components")
    processed_total = _first_value_field(*sources, field="processed_total")
    consumer_lag = _first_value_field(*sources, field="consumer_lag")

    persistence_storage = observability.get("persistence_storage") if isinstance(observability.get("persistence_storage"), dict) else {}

    return {
        "freshness": freshness,
        "coverage": coverage,
        "recovery": recovery,
        "offset_recovery": offset_recovery,
        "observability": observability,
        "persistence_storage": persistence_storage,
        "components": components,
        "processed_total": processed_total,
        "consumer_lag": consumer_lag,
        "raw_payload_available": any(
            [
                freshness,
                coverage,
                recovery,
                offset_recovery,
                observability,
                components,
                processed_total is not None,
                consumer_lag is not None,
            ]
        ),
    }




def _format_bytes(value: Any) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return "unknown"


def storage_warning_summary(normalized_health: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    storage = normalized_health.get("persistence_storage") if isinstance(normalized_health.get("persistence_storage"), dict) else {}
    if not storage:
        return None

    status = str(storage.get("storage_status") or "ok")
    free_disk = int(storage.get("free_disk_bytes", 0) or 0)
    db_file = int(storage.get("db_file_bytes", 0) or 0)
    db_max = int(storage.get("db_max_bytes", 0) or 0)
    warn_free = int(storage.get("free_disk_warning_bytes", 0) or 0)
    reasons = storage.get("storage_reasons") if isinstance(storage.get("storage_reasons"), list) else []

    if status == "ok" and (warn_free <= 0 or free_disk > warn_free) and (db_max <= 0 or db_file <= db_max):
        return None

    return {
        "status": status,
        "free_disk": free_disk,
        "db_file": db_file,
        "db_max": db_max,
        "wal_file": int(storage.get("wal_file_bytes", 0) or 0),
        "cleanup_status": storage.get("cleanup_status", "unknown"),
        "reasons": reasons,
    }
def render_status_indicator(status: str) -> str:
    """Return colored status indicator."""
    indicators = {
        "healthy": "🟢",
        "degraded": "🟡",
        "offline": "🔴",
        "timeout": "🟠",
        "error": "🔴",
        "unknown": "⚪",
    }
    return indicators.get(status, "⚪")


def render(df=None, config: Optional[Dict] = None):
    """Render the Welcome & Guide tab."""

    st.markdown("## Welcome to AuditLens")
    st.markdown("*Confluent Audit Log Intelligence System*")

    # System Status Panel
    st.markdown("### System Status")

    col1, col2, col3, col4 = st.columns(4)

    # Check forwarder health
    forwarder_health = check_service_health(f"{DASHBOARD_FORWARDER_URL}/api/v1/health")
    with col1:
        status = render_status_indicator(forwarder_health["status"])
        st.metric(
            label="Forwarder",
            value=f"{status} {forwarder_health['status'].title()}",
        )

    # Dashboard is always healthy if we're seeing this
    with col2:
        st.metric(
            label="Dashboard",
            value="🟢 Healthy",
        )

    # Check Grafana
    grafana_health = check_service_health(f"{DASHBOARD_GRAFANA_URL}/api/health")
    with col3:
        status = render_status_indicator(grafana_health["status"])
        st.metric(
            label="Grafana",
            value=f"{status} {grafana_health['status'].title()}",
        )

    # Check Prometheus
    prometheus_health = check_service_health(f"{DASHBOARD_PROMETHEUS_URL}/-/healthy")
    with col4:
        status = render_status_indicator(prometheus_health["status"])
        st.metric(
            label="Prometheus",
            value=f"{status} {prometheus_health['status'].title()}",
        )

    st.divider()

    st.markdown("### Data Freshness")
    if df is not None and not df.empty and 'time' in df.columns:
        latest = df['time'].max()
        if latest is not None:
            try:
                latest_dt = latest.to_pydatetime()
                if latest_dt.tzinfo is None:
                    latest_dt = latest_dt.replace(tzinfo=timezone.utc)
                age_delta = datetime.now(timezone.utc) - latest_dt
                age_minutes = int(age_delta.total_seconds() // 60)
                st.info(f"Latest enriched event timestamp: `{latest}` | Age: `{age_minutes} minutes`")
            except Exception:
                st.info(f"Latest enriched event timestamp: `{latest}`")
    else:
        st.warning("No enriched events are currently visible. Health without recent data should not be treated as full audit coverage.")

    normalized_health = normalize_forwarder_health(forwarder_health)
    coverage = normalized_health["coverage"]
    storage_warning = storage_warning_summary(normalized_health)
    if storage_warning:
        detail_parts = [
            f"free disk `{_format_bytes(storage_warning['free_disk'])}`",
            f"db size `{_format_bytes(storage_warning['db_file'])}`",
            f"wal size `{_format_bytes(storage_warning['wal_file'])}`",
            f"cleanup `{storage_warning['cleanup_status']}`",
        ]
        if storage_warning["db_max"]:
            detail_parts.append(f"db max `{_format_bytes(storage_warning['db_max'])}`")
        if storage_warning["status"] == "critical":
            st.error("SQLite storage pressure is critical: " + " | ".join(detail_parts))
        else:
            st.warning("SQLite storage pressure detected: " + " | ".join(detail_parts))
        if storage_warning["reasons"]:
            st.caption("Storage reasons: " + ", ".join(storage_warning["reasons"]))

    if coverage:
        note = coverage.get("note")
        mode = coverage.get("mode")
        counts = coverage.get("api_window_counts") if isinstance(coverage.get("api_window_counts"), dict) else {}
        if note:
            st.caption(f"Coverage note: {note}")
        if mode or counts:
            summary_parts = []
            if mode:
                summary_parts.append(f"mode: `{mode}`")
            if counts:
                enriched_count = counts.get("enriched_events", 0)
                alert_count = counts.get("alerts", 0)
                summary_parts.append(f"recent enriched events: `{enriched_count}`")
                summary_parts.append(f"recent alerts: `{alert_count}`")
            st.caption("Coverage summary: " + " | ".join(summary_parts))

    # Quick Start Guide
    st.markdown("### Quick Start Guide")

    # Role-based guidance
    role_col1, role_col2, role_col3 = st.columns(3)

    with role_col1:
        st.markdown("#### Cluster Admins")
        st.markdown("""
        Focus on operational visibility:
        - **Audit Trail** - Who did what, when
        - **Deletions** - Track delete operations
        - **API Keys** - Key lifecycle events
        """)

    with role_col2:
        st.markdown("#### Security Teams")
        st.markdown("""
        Focus on security monitoring:
        - **Failures** - Auth/authz failures
        - **Security Alerts** - Aggregated alerts
        - **Topic x Identity** - Access patterns
        - **Export** - Compliance reports
        """)

    with role_col3:
        st.markdown("#### Platform Teams")
        st.markdown("""
        Focus on analytics:
        - **Analytics** - Trends & patterns
        - **Time Insights** - Activity heatmap
        - **Identity Activity** - User deep dives
        """)

    st.divider()

    # Feature Discovery
    st.markdown("### All Dashboard Tabs")

    features = [
        {
            "tab": "Audit Trail",
            "icon": "📋",
            "description": "Complete audit log viewer with filtering by principal, action, resource, and time range.",
            "use_case": "Answer: Who created topic X? What did user Y do today?",
        },
        {
            "tab": "Failures",
            "icon": "❌",
            "description": "Authentication and authorization failures across your organization.",
            "use_case": "Detect brute-force attempts, misconfigured clients, permission issues.",
        },
        {
            "tab": "Deletions",
            "icon": "🗑️",
            "description": "Track all delete operations - topics, ACLs, service accounts, clusters.",
            "use_case": "Audit who deleted resources, restore points, compliance.",
        },
        {
            "tab": "API Keys",
            "icon": "🔑",
            "description": "API key creation, deletion, and rotation events.",
            "use_case": "Key hygiene, rotation compliance, credential lifecycle.",
        },
        {
            "tab": "Security",
            "icon": "🔒",
            "description": "Security-focused view of critical events.",
            "use_case": "Security review, incident investigation, threat hunting.",
        },
        {
            "tab": "Analytics",
            "icon": "📊",
            "description": "Charts and trends showing activity patterns over time.",
            "use_case": "Capacity planning, trend analysis, anomaly detection.",
        },
        {
            "tab": "Time Insights",
            "icon": "🕐",
            "description": "Activity heatmap showing day-of-week vs hour-of-day patterns.",
            "use_case": "Identify peak usage times, after-hours activity, patterns.",
        },
        {
            "tab": "Security Alerts",
            "icon": "🔔",
            "description": "Aggregated security alerts from denial patterns and anomalies.",
            "use_case": "Real-time security monitoring, alert investigation.",
        },
        {
            "tab": "Topic x Identity",
            "icon": "🔗",
            "description": "Matrix showing which identities access which topics.",
            "use_case": "ACL review, stale permission detection, access audit.",
        },
        {
            "tab": "Identity Activity",
            "icon": "👤",
            "description": "Deep dive into any user or service account's activity.",
            "use_case": "User investigation, service account audit, behavior analysis.",
        },
        {
            "tab": "Export",
            "icon": "📄",
            "description": "Generate PDF compliance reports for auditors.",
            "use_case": "SOC2, compliance audits, management reporting.",
        },
    ]

    # Searchable feature list
    search = st.text_input("Search features...", key="feature_search", placeholder="Type to filter...")

    filtered_features = features
    if search:
        search_lower = search.lower()
        filtered_features = [
            f for f in features
            if search_lower in f["tab"].lower()
            or search_lower in f["description"].lower()
            or search_lower in f["use_case"].lower()
        ]

    # Display as cards
    for i in range(0, len(filtered_features), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            idx = i + j
            if idx < len(filtered_features):
                f = filtered_features[idx]
                with col:
                    st.markdown(f"**{f['icon']} {f['tab']}**")
                    st.markdown(f"{f['description']}")
                    st.caption(f"*{f['use_case']}*")
                    st.markdown("---")

    st.divider()

    # Common Questions / FAQ Navigation
    st.markdown("### Common Questions")

    questions = [
        ("Who accessed topic X?", "Use **Topic x Identity** tab and filter by topic name"),
        ("What did service account sa-xxxxx do?", "Use **Identity Activity** tab and search for the SA ID"),
        ("Why is user getting denied?", "Check **Failures** tab filtered by that principal"),
        ("Were any topics deleted today?", "Use **Deletions** tab with today's date filter"),
        ("Show me all API key rotations", "Use **API Keys** tab, filter for create/delete pairs"),
        ("Who has access to production?", "Use **Topic x Identity** tab, filter by prod topics"),
        ("Generate an audit report", "Use **Export** tab to create a PDF report"),
        ("Are there any security alerts?", "Check **Security Alerts** tab for aggregated alerts"),
    ]

    for question, answer in questions:
        with st.expander(f"**{question}**"):
            st.markdown(answer)

    st.divider()

    # Quick Links
    st.markdown("### Quick Links")

    link_col1, link_col2, link_col3 = st.columns(3)

    with link_col1:
        st.markdown(f"""
        **Monitoring**
        - [Grafana]({DASHBOARD_GRAFANA_URL})
        - [Prometheus]({DASHBOARD_PROMETHEUS_URL})
        - [Health API]({DASHBOARD_FORWARDER_URL}/health)
        """)

    with link_col2:
        st.markdown("""
        **Documentation**
        - Keyboard: Press **R** to refresh
        - Filter presets in sidebar
        - Theme toggle in sidebar
        """)

    with link_col3:
        st.markdown("""
        **Commands**
        ```
        ./status.sh      # System status
        ./setup.sh       # Re-run setup
        docker compose logs -f
        ```
        """)
