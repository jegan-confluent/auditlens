"""Simplified AuditLens dashboard entry point.

This app keeps the legacy dashboard intact and focuses on core audit workflows:
overview, audit trail, failures, deletions, and a placeholder for advanced
investigations.
"""

from __future__ import annotations

import html
import os as _os
from pathlib import Path
import re
from typing import Any, Dict, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

# ── Password gate ──────────────────────────────────────────────────────────────
# Set STREAMLIT_PASSWORD in the environment to require a password.
# If the variable is absent the gate is skipped (local dev / CI).
_STREAMLIT_PASSWORD = _os.getenv("STREAMLIT_PASSWORD", "")
if _STREAMLIT_PASSWORD:
    if not st.session_state.get("_authenticated"):
        _entered = st.text_input("Dashboard password", type="password", key="_pw_gate")
        if _entered == _STREAMLIT_PASSWORD:
            st.session_state["_authenticated"] = True
            st.rerun()
        elif _entered:
            st.error("Incorrect password")
        st.stop()
# ──────────────────────────────────────────────────────────────────────────────

import config
from config import APP_NAME, APP_TAGLINE, DATA_TABLE_CSS, LOGO_BASE64, THEME_CSS
from data.kafka_consumer import load_events_from_kafka


PRIMARY_TABS = ["Overview", "Audit Trail", "Failures", "Deletions", "Advanced", "Help"]
HELP_DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "AuditLens_Clean_Onboarding_Walkthrough.md"
HELP_GUIDED_DEMO_HEADING = "## 5. Guided Demo Flow"
HELP_GUIDED_DEMO_ANCHOR = "guided-demo-flow"
RESOURCE_TYPE_OPTIONS = [
    "All",
    "Topic",
    "Cluster",
    "Schema Registry",
    "KSQL",
    "Compute Pool",
    "Connector",
    "API Key",
    "ACL / RBAC",
    "Service Account",
    "Unknown",
]
ACTION_CATEGORY_OPTIONS = [
    "All",
    "Create",
    "Delete",
    "Data",
    "Security",
    "API Key",
    "Modify",
    "Other",
]
DEMO_FLOW_STEPS = [
    "Open Overview and check health, freshness, failures, deletions, and storage.",
    "Trigger a safe Confluent Cloud action, such as creating a temporary topic.",
    "Open Audit Trail and find the event by actor, resource, or action.",
    "Trigger a denied or failed operation with a restricted actor.",
    "Open Failures and inspect the human-readable summary.",
    "Use Row Details for raw method, request ID, environment, and evidence.",
    "Narrow the investigation with sidebar filters, then clear filters when done.",
]

CLEAN_DASHBOARD_CSS = """
<style>
.block-container {
    max-width: 100%;
    padding-left: 2rem;
    padding-right: 2rem;
}
[data-testid="stSidebar"] {
    min-width: 235px;
    max-width: 270px;
}
[data-testid="stSidebar"] > div:first-child {
    padding-left: 1rem;
    padding-right: 1rem;
}
.clean-hero {
    border: 1px solid #e7e8ee;
    border-radius: 8px;
    padding: 24px 28px;
    margin: 8px 0 18px 0;
    background: linear-gradient(135deg, #ffffff 0%, #f7f9fc 100%);
    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
}
.clean-hero-title {
    font-size: 2.15rem;
    font-weight: 760;
    line-height: 1.1;
    margin-bottom: 6px;
    color: #141820;
}
.clean-hero-subtitle {
    color: #5a6270;
    font-size: 1rem;
    margin-bottom: 18px;
}
.pill-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}
.focus-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    margin: 0 0 14px 0;
}
.focus-pill {
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 0.92rem;
    font-weight: 740;
    border: 1px solid transparent;
    white-space: nowrap;
}
.status-pill {
    display: inline-flex;
    align-items: center;
    border-radius: 999px;
    padding: 7px 12px;
    font-size: 0.83rem;
    font-weight: 650;
    border: 1px solid transparent;
}
.pill-ok {
    background: #ecfdf3;
    color: #067647;
    border-color: #abefc6;
}
.pill-warn {
    background: #fffaeb;
    color: #b54708;
    border-color: #fedf89;
}
.pill-bad {
    background: #fef3f2;
    color: #b42318;
    border-color: #fecdca;
}
.pill-neutral {
    background: #f2f4f7;
    color: #344054;
    border-color: #d0d5dd;
}
.signal-red {
    background: #fef3f2;
    color: #b42318;
    border-color: #fecdca;
}
.signal-orange {
    background: #fff4ed;
    color: #b93815;
    border-color: #f9dbaf;
}
.signal-yellow {
    background: #fffaeb;
    color: #b54708;
    border-color: #fedf89;
}
.signal-amber {
    background: #fff4ed;
    color: #b93815;
    border-color: #f9dbaf;
}
.signal-green {
    background: #ecfdf3;
    color: #067647;
    border-color: #abefc6;
}
.signal-blue {
    background: #eff8ff;
    color: #175cd3;
    border-color: #b2ddff;
}
.metric-card {
    border: 1px solid #e7e8ee;
    border-radius: 8px;
    padding: 18px;
    min-height: 132px;
    background: #ffffff;
    box-shadow: 0 8px 22px rgba(15, 23, 42, 0.045);
}
.metric-card.ok {
    border-top: 4px solid #12b76a;
}
.metric-card.warn {
    border-top: 4px solid #f79009;
}
.metric-card.orange {
    border-top: 4px solid #fb6514;
}
.metric-card.bad {
    border-top: 4px solid #f04438;
}
.metric-card.neutral {
    border-top: 4px solid #667085;
}
.metric-label {
    color: #667085;
    font-size: 0.82rem;
    font-weight: 650;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}
.metric-value {
    color: #101828;
    font-size: 2rem;
    font-weight: 760;
    margin-top: 8px;
}
.metric-help {
    color: #667085;
    font-size: 0.88rem;
    margin-top: 8px;
}
.metric-subtext {
    color: #475467;
    font-size: 0.82rem;
    font-weight: 650;
    margin-top: 10px;
}
.detail-card {
    border: 1px solid #e7e8ee;
    border-radius: 8px;
    padding: 14px 16px;
    background: #ffffff;
    min-height: 86px;
}
.detail-label {
    color: #667085;
    font-size: 0.78rem;
    font-weight: 650;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}
.detail-value {
    color: #101828;
    font-size: 1rem;
    font-weight: 700;
    margin-top: 8px;
    overflow-wrap: anywhere;
}
.shortcut-card {
    border: 1px solid #e7e8ee;
    border-radius: 8px;
    padding: 16px;
    min-height: 116px;
    background: #fbfcff;
}
.shortcut-title {
    font-weight: 720;
    color: #101828;
    margin-bottom: 6px;
}
.shortcut-body {
    color: #667085;
    font-size: 0.9rem;
}
.storage-panel {
    border: 1px solid #e7e8ee;
    border-radius: 8px;
    padding: 18px;
    background: #ffffff;
}
.failure-cta {
    border: 1px solid #fecdca;
    border-radius: 8px;
    padding: 10px 12px;
    margin: -4px 0 14px 0;
    background: #fef3f2;
    color: #b42318;
    font-weight: 750;
}
.onboarding-banner {
    border: 1px solid #b2ddff;
    border-radius: 8px;
    padding: 12px 14px;
    margin: 0 0 8px 0;
    background: #eff8ff;
    color: #175cd3;
    font-weight: 740;
}
div.stButton > button {
    white-space: nowrap;
    min-height: 2.35rem;
}
.context-help {
    border: 1px solid #e7e8ee;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 6px 0 12px 0;
    background: #fbfcff;
    color: #475467;
}
.help-card {
    border: 1px solid #e7e8ee;
    border-radius: 8px;
    padding: 14px 16px;
    background: #ffffff;
    margin: 8px 0 14px 0;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    margin-bottom: 0.35rem;
}
.audit-table-wrap {
    border: 1px solid #e7e8ee;
    border-radius: 8px;
    overflow-x: auto;
    overflow-y: hidden;
    margin-top: 8px;
    width: 100%;
}
.audit-table {
    width: 1370px;
    min-width: 1370px;
    border-collapse: collapse;
    table-layout: fixed;
    font-size: 0.86rem;
}
.audit-table th {
    background: #f8fafc;
    color: #667085;
    font-weight: 700;
    text-align: left;
    padding: 8px 9px;
    border-bottom: 1px solid #e7e8ee;
}
.audit-table td {
    padding: 7px 9px;
    border-bottom: 1px solid #eef0f4;
    vertical-align: top;
    line-height: 1.28;
    overflow: hidden;
}
.audit-table tr:nth-child(even) td {
    background: #fbfcff;
}
.audit-table .col-time { width: 130px; }
.audit-table .col-result { width: 100px; }
.audit-table .col-summary { width: 360px; font-weight: 700; color: #101828; white-space: normal; overflow-wrap: break-word; }
.audit-table .col-actor { width: 190px; font-weight: 650; color: #101828; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.audit-table .col-action { width: 140px; font-weight: 650; color: #101828; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.audit-table .col-resource { width: 220px; font-weight: 650; color: #101828; white-space: normal; overflow-wrap: break-word; }
.audit-table .col-cluster { width: 110px; color: #667085; font-size: 0.8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.audit-table .col-ip { width: 120px; color: #667085; font-size: 0.8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.audit-table .cell-wrap {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.audit-table .cell-nowrap {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.result-failure { color: #b42318; font-weight: 800; }
.result-denied { color: #b93815; font-weight: 800; }
.result-success { color: #067647; font-weight: 800; }
.result-neutral { color: #667085; font-weight: 700; }
@media (max-width: 900px) {
    .focus-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
@media (max-width: 560px) {
    .focus-strip {
        grid-template-columns: 1fr;
    }
}
</style>
"""

CLEAN_AUDIT_COLUMNS = {
    "time": "Time",
    "result_display": "Result",
    "summary": "Summary",
    "user_display": "Actor",
    "action": "Action",
    "resource": "Resource",
    "cluster_id": "Cluster",
    "clientIp": "Source IP",
}

DETAIL_FIELDS = {
    "methodName": "Raw Method",
    "environment_id": "Environment",
    "clientId": "Client ID",
    "request_id": "Request ID",
    "requestId": "Request ID",
    "resultStatus": "Failure/Error Reason",
    "error_message": "Failure/Error Reason",
    "resourceName": "Raw Resource",
    "resource_display": "Raw Resource Display",
    "raw_json": "Raw JSON",
}

FILTER_COUNTER_LABELS = {
    "loaded_rows": "Rows loaded",
    "after_enrichment": "After enrichment",
    "after_resource_type": "After Resource Type",
    "after_resource_text": "After Resource text",
    "after_action_category": "After Action Category",
    "after_action_text": "After Action text",
    "after_actor": "After Actor",
    "after_routine_hiding": "After routine hiding",
}


def _first_present(row: pd.Series, names: Iterable[str], default: str = "-") -> Any:
    for name in names:
        if name in row and pd.notna(row[name]) and row[name] != "":
            return row[name]
    return default


def load_onboarding_markdown(path: Path = HELP_DOC_PATH) -> str | None:
    """Load the bundled AuditLens Clean onboarding guide."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def help_markdown_with_anchor(markdown: str) -> str:
    """Inject a stable anchor before the Guided Demo Flow heading."""
    anchor = f'<a id="{HELP_GUIDED_DEMO_ANCHOR}"></a>'
    if anchor in markdown:
        return markdown
    return markdown.replace(HELP_GUIDED_DEMO_HEADING, f"{anchor}\n\n{HELP_GUIDED_DEMO_HEADING}", 1)


def set_active_tab(tab_name: str, *, anchor: str | None = None) -> None:
    if tab_name not in PRIMARY_TABS:
        tab_name = "Overview"
    st.session_state["active_tab"] = tab_name
    if anchor:
        st.session_state["help_anchor"] = anchor


def next_demo_step(current_step: int, total_steps: int = len(DEMO_FLOW_STEPS)) -> int:
    if total_steps <= 0:
        return 0
    return min(current_step + 1, total_steps - 1)


def previous_demo_step(current_step: int) -> int:
    return max(current_step - 1, 0)


def format_event_time(value: Any, timezone: str = "UTC") -> str:
    """Format event timestamps for dashboard display."""
    if value is None or value == "":
        return "-"
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(timestamp):
        return "-"

    try:
        tzinfo = ZoneInfo(timezone)
    except Exception:
        tzinfo = ZoneInfo("UTC")

    localized = timestamp.to_pydatetime().astimezone(tzinfo)
    zone_label = "UTC" if timezone.upper() == "UTC" else localized.tzname() or timezone
    return f"{localized.strftime('%b')} {localized.day}, {localized.year} {localized:%H:%M} {zone_label}"


def _extract_crn_value(value: str, marker: str) -> str:
    tail = value.split(marker, 1)[1]
    return tail.split("/", 1)[0].strip()


def _extract_quoted_topic(value: str) -> str:
    match = re.search(r"\btopic\s+['\"]([^'\"]+)['\"]", value, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def summarize_resource(value: Any) -> str:
    """Summarize long CRNs for the default table while keeping raw values in details."""
    if value is None or value == "":
        return "-"
    if not isinstance(value, (dict, list, tuple, set)) and pd.isna(value):
        return "-"
    text = str(value).strip()
    crn_markers = (
        ("/topic=", "Topic"),
        ("/cloud-cluster=", "Cluster"),
        ("/schema-registry=", "Schema Registry"),
        ("/ksql=", "KSQL"),
        ("/compute-pool=", "Compute Pool"),
    )
    for marker, label in crn_markers:
        if marker in text:
            extracted = _extract_crn_value(text, marker)
            return f"{label}: {extracted}" if extracted else label
    if "crn://" in text:
        for segment in reversed(text.split("/")):
            if "=" not in segment:
                continue
            key, extracted = segment.split("=", 1)
            if key in {"organization"}:
                continue
            label = key.replace("-", " ").replace("_", " ").title()
            return f"{label}: {extracted}" if extracted else label
        return "CRN resource"
    return text


def derive_resource_info(row: pd.Series) -> Dict[str, str]:
    """Derive normalized resource fields while preserving the raw audit resource."""
    resource_fields = (
        "resourceName",
        "authzResourceName",
        "resource_display",
        "summary",
        "message",
        "request",
        "requestData",
        "request_data",
        "topic_name",
        "cluster_id",
    )
    raw_resource = str(_first_present(
        row,
        resource_fields,
        "",
    ))
    method = str(row.get("methodName", "") or "")
    resource_type_hint = str(row.get("resourceType", "") or row.get("resource_type", "") or "")
    search_text = " ".join(
        str(row.get(col, "") or "")
        for col in (
            "resourceName",
            "authzResourceName",
            "resource_display",
            "summary",
            "message",
            "request",
            "requestData",
            "request_data",
            "topic_name",
            "cluster_id",
            "methodName",
            "resourceType",
            "resource_type",
            "action",
        )
    )
    lowered = search_text.lower()

    marker_types = (
        ("/topic=", "Topic"),
        ("/cloud-cluster=", "Cluster"),
        ("/schema-registry=", "Schema Registry"),
        ("/ksql=", "KSQL"),
        ("/compute-pool=", "Compute Pool"),
    )
    resource_type = "Unknown"
    resource_name = "-"

    for marker, label in marker_types:
        marker_source = next(
            (
                str(row.get(field))
                for field in resource_fields
                if row.get(field) not in (None, "") and pd.notna(row.get(field)) and marker in str(row.get(field))
            ),
            "",
        )
        if marker_source:
            resource_type = label
            resource_name = _extract_crn_value(marker_source, marker)
            break

    if resource_type == "Unknown":
        if row.get("topic_name") not in (None, "") and pd.notna(row.get("topic_name")):
            resource_type = "Topic"
            resource_name = str(row.get("topic_name"))
        elif "topic" in lowered:
            quoted_topic = _extract_quoted_topic(search_text)
            resource_type = "Topic"
            resource_name = quoted_topic if quoted_topic else resource_name
        elif "connector" in lowered:
            resource_type = "Connector"
        elif "apikey" in lowered or "api key" in lowered:
            resource_type = "API Key"
        elif any(marker in lowered for marker in ("createacl", "deleteacl", "acl:", "/acl=", " rbac", "rolebinding", "role binding")):
            resource_type = "ACL / RBAC"
        elif "serviceaccount" in lowered or "service account" in lowered or "service-account" in lowered:
            resource_type = "Service Account"
        elif "cluster" in lowered or resource_type_hint.upper() in {"CLUSTER", "KAFKA_CLUSTER"}:
            resource_type = "Cluster"

    if resource_name == "-":
        quoted_topic = _extract_quoted_topic(search_text)
        if resource_type == "Topic" and quoted_topic:
            resource_name = quoted_topic
        elif raw_resource:
            resource_name = summarize_resource(raw_resource)
            if ":" in resource_name:
                resource_name = resource_name.split(":", 1)[1].strip()
        elif row.get("cluster_id") not in (None, "") and pd.notna(row.get("cluster_id")):
            resource_name = str(row.get("cluster_id"))

    if resource_type == "Connector" and resource_name == "-":
        resource_name = summarize_resource(raw_resource) if raw_resource else "Connector"
    if resource_type == "API Key" and resource_name == "-":
        resource_name = summarize_resource(raw_resource) if raw_resource else "API key"
    if resource_type == "ACL / RBAC" and resource_name == "-":
        resource_name = summarize_resource(raw_resource) if raw_resource else "ACL / RBAC"

    resource_display = f"{resource_type}: {resource_name}" if resource_type != "Unknown" and resource_name != "-" else summarize_resource(raw_resource)
    if not resource_display or resource_display == "-":
        resource_display = "Unknown"

    return {
        "resource_type": resource_type,
        "resource_name": resource_name if resource_name else "-",
        "resource_display": resource_display,
        "raw_resource": raw_resource or "-",
    }


def infer_resource_type(row: pd.Series) -> str:
    """Infer a compact resource type for clean dashboard tables."""
    for field in ("resourceType", "resource_type", "type"):
        value = row.get(field)
        if pd.notna(value) and str(value).strip():
            return str(value)

    method = str(row.get("methodName", "") or "").lower()
    resource = str(row.get("resourceName", "") or row.get("resource_display", "") or "").lower()
    combined = f"{method} {resource}"
    if "topic" in combined:
        return "Topic"
    if "acl" in combined:
        return "ACL"
    if "apikey" in combined or "api key" in combined:
        return "API Key"
    if "connector" in combined:
        return "Connector"
    if "cluster" in combined:
        return "Cluster"
    if "rbac" in combined or "rolebinding" in combined:
        return "RBAC"
    return "Other"


def infer_resource_name(row: pd.Series) -> str:
    """Infer the best human-readable resource name available."""
    return str(
        _first_present(
            row,
            (
                "topic_name",
                "resourceName",
                "resource_name",
                "resource_display",
                "cluster_id",
            ),
        )
    )


def summarize_event_resource(row: pd.Series) -> str:
    return derive_resource_info(row)["resource_display"]


def summarize_actor(value: Any) -> str:
    if value is None or value == "":
        return "Unknown actor"
    text = str(value).strip()
    if not text:
        return "Unknown actor"
    if " (" in text:
        text = text.split(" (", 1)[0]
    if text.startswith("User:"):
        text = text.replace("User:", "", 1)
    return text


def humanize_action(row: pd.Series) -> str:
    """Convert raw audit methods into operator-readable labels."""
    method = str(row.get("methodName", "") or "")
    action = str(row.get("action", "") or "")
    combined = f"{method} {action}"
    lowered = combined.lower()
    resource_text = " ".join(str(row.get(col, "") or "") for col in ("resourceType", "resource_type", "resourceName", "resource_display"))
    resource_lower = resource_text.lower()

    if "io.confluent.kafka.server/authentication" in lowered:
        return "Kafka authentication"
    if "io.confluent.sg.server/authentication" in lowered:
        return "Schema Registry authentication"
    if ("authentication" in lowered or "authenticate" in lowered) and "schema-registry" in resource_lower:
        return "Schema Registry authentication"
    if "authentication" in lowered or "authenticate" in lowered:
        return "Kafka authentication"
    if "authorize" in lowered and ("compute_pool" in resource_lower or "compute-pool" in resource_lower):
        return "Authorize compute pool"
    if "createacl" in lowered or "createacls" in lowered or "create_acl" in lowered:
        return "Create ACL"
    if "deleteacl" in lowered or "deleteacls" in lowered or "delete_acl" in lowered:
        return "Delete ACL"
    if "createtopic" in lowered or "createtopics" in lowered:
        return "Create topic"
    if "deletetopic" in lowered or "deletetopics" in lowered:
        return "Delete topic"
    if "getkafkaclusters" in lowered:
        return "Fetch cluster metadata"
    if "listcomputepools" in lowered:
        return "List compute pools"
    if "getconnectors" in lowered:
        return "Fetch connectors"
    if "listconnectors" in lowered:
        return "List connectors"
    if "getstatement" in lowered:
        return "Fetch statement"
    if "metadata" in lowered:
        return "Fetch metadata"

    fallback = action or method
    if not fallback:
        return "-"
    return fallback.replace("_", " ").strip()


def normalized_result(row: pd.Series) -> str:
    """Convert raw result fields into fast-scannable status labels."""
    if bool(row.get("is_failure", False)):
        raw = str(row.get("resultStatus", "") or row.get("result_display", "") or "").lower()
        if "denied" in raw or row.get("granted") is False:
            return "⚠️ Denied"
        return "❌ Failure"

    raw_value = row.get("resultStatus")
    display_value = row.get("result_display")
    if raw_value is None and display_value is None:
        return "Unknown"

    raw = str(raw_value if raw_value is not None else display_value).strip().lower()
    if "denied" in raw or row.get("granted") is False:
        return "⚠️ Denied"
    if "success" in raw or "allowed" in raw or row.get("granted") is True:
        return "✅ Success"
    if raw in {"-", "—", "neutral", "none", "nan", ""}:
        return "Neutral" if raw in {"-", "—", "neutral"} else "Unknown"
    return "Neutral"


def _object_name(resource: str) -> str:
    if ":" in resource:
        return resource.split(":", 1)[1].strip()
    return resource


def _resource_type_and_name(resource: str) -> tuple[str, str]:
    if ":" in resource:
        label, name = resource.split(":", 1)
        return label.strip().lower(), name.strip()
    return "", resource


def _environment_id(row: pd.Series) -> str:
    env = _first_present(row, ("environment_id", "environmentId"), "")
    if env:
        return str(env)
    resource = str(_first_present(row, ("resourceName", "resource_display"), ""))
    for marker in ("/environment=", "/env="):
        if marker in resource:
            return _extract_crn_value(resource, marker)
    return "-"


def _action_phrase(action: str) -> str:
    mapping = {
        "Create topic": "created topic",
        "Delete topic": "deleted topic",
        "Create ACL": "created ACL",
        "Delete ACL": "deleted ACL",
        "Kafka authentication": "authenticated with Kafka",
        "Schema Registry authentication": "authenticated with Schema Registry",
        "Authorize compute pool": "authorized compute pool",
        "Fetch cluster metadata": "fetched cluster metadata",
        "List compute pools": "listed compute pools",
        "Fetch connectors": "fetched connectors",
        "List connectors": "listed connectors",
        "Fetch statement": "fetched statement",
        "Fetch metadata": "fetched metadata",
    }
    if action in mapping:
        return mapping[action]
    if action == "-" or not action:
        return "performed an audit operation"
    return action[:1].lower() + action[1:]


def _failure_action_phrase(action: str) -> str:
    mapping = {
        "Create topic": "create topic",
        "Delete topic": "delete topic",
        "Create ACL": "create ACL",
        "Delete ACL": "delete ACL",
        "Kafka authentication": "authenticate with Kafka",
        "Schema Registry authentication": "authenticate with Schema Registry",
        "Authorize compute pool": "authorize compute pool",
        "Fetch cluster metadata": "fetch cluster metadata",
        "List compute pools": "list compute pools",
        "Fetch connectors": "fetch connectors",
        "List connectors": "list connectors",
        "Fetch statement": "fetch statement",
        "Fetch metadata": "fetch metadata",
    }
    if action in mapping:
        return mapping[action]
    if action == "-" or not action:
        return "complete operation"
    return action[:1].lower() + action[1:]


def human_summary(row: pd.Series) -> str:
    actor = summarize_actor(_first_present(row, ("user_display", "user", "principal"), "Unknown actor"))
    action = humanize_action(row)
    resource = summarize_event_resource(row)
    result = normalized_result(row)
    object_name = _object_name(resource)
    resource_type, typed_name = _resource_type_and_name(resource)
    phrase = _action_phrase(action)

    if result == "⚠️ Denied" and "authorize" in action.lower():
        target_type = resource_type or "resource"
        return f"{actor} was denied access to {target_type} '{typed_name}'"
    if result == "❌ Failure" or result == "⚠️ Denied":
        return f"{actor} failed to {_failure_action_phrase(action)} '{object_name}'"
    if action in {"Kafka authentication", "Schema Registry authentication"}:
        return f"{actor} {phrase}"
    if action == "Fetch cluster metadata":
        return f"{actor} fetched cluster metadata for {_environment_id(row)}"
    if action == "List compute pools":
        return f"{actor} listed compute pools in {_environment_id(row)}"
    if object_name and object_name != "-":
        return f"{actor} {phrase} '{object_name}'"
    return f"{actor} {phrase}"


def is_api_key_event(row: pd.Series) -> bool:
    text = " ".join(str(row.get(col, "") or "") for col in ("methodName", "action", "resourceName", "resource_display"))
    return "apikey" in text.lower() or "api key" in text.lower()


def is_acl_rbac_event(row: pd.Series) -> bool:
    text = " ".join(str(row.get(col, "") or "") for col in ("methodName", "action", "resourceName", "resource_display", "resourceType", "resource_type"))
    lowered = text.lower()
    acl_markers = (
        "createacl",
        "createacls",
        "deleteacl",
        "deleteacls",
        "alteracl",
        "alteracls",
        "acl:",
        "/acl=",
        " acl ",
        "acls",
    )
    return any(marker in lowered for marker in acl_markers) or "rbac" in lowered or "rolebinding" in lowered


def is_success_neutral_or_unknown_result(row: pd.Series) -> bool:
    result = str(row.get("resultStatus", "") or row.get("result_display", "") or "").strip().lower()
    return (
        result in {"", "success", "none", "nan", "-", "—", "ok", "neutral", "unknown"}
        or "success" in result
        or "allowed" in result
    )


def is_denied_result(row: pd.Series) -> bool:
    result = str(row.get("resultStatus", "") or row.get("result_display", "") or "").lower()
    return "denied" in result or row.get("granted") is False


def derive_is_failure(row: pd.Series) -> bool:
    result = str(row.get("resultStatus", "") or row.get("result_display", "") or "").strip().lower()
    return (
        is_true_flag(row.get("is_failure", False))
        or is_denied_result(row)
        or any(marker in result for marker in ("error", "fail", "denied", "unauthorized", "forbidden"))
    )


def is_true_flag(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    return str(value).strip().lower() in {"true", "1", "yes"}


def is_protected_investigation_signal(row: pd.Series) -> bool:
    category = str(row.get("action_category") or derive_action_category(row.get("methodName", ""), row.get("action", "")))
    return (
        category in {"Create", "Delete", "Modify", "API Key"}
        or is_true_flag(row.get("is_failure", False))
        or is_denied_result(row)
        or is_true_flag(row.get("is_deletion", False))
        or is_true_flag(row.get("is_creation", False))
        or is_api_key_event(row)
        or is_acl_rbac_event(row)
    )


def is_routine_auth_noise(row: pd.Series) -> bool:
    method = str(row.get("methodName", "") or "").lower()
    action = str(row.get("action", "") or "").lower()
    auth_event = (
        "authentication" in method
        or "authentication" in action
        or "authenticate" in method
        or "authenticate" in action
        or "authorize" in method
        or "authorize" in action
    )
    return auth_event and is_success_neutral_or_unknown_result(row) and not is_protected_investigation_signal(row)


def is_routine_metadata_noise(row: pd.Series) -> bool:
    method = str(row.get("methodName", "") or "").lower()
    action = str(row.get("action", "") or "").lower()
    combined = f"{method} {action}"
    routine_read = any(
        marker in combined
        for marker in (
            "getkafkaclusters",
            "listcomputepools",
            "getconnectors",
            "listconnectors",
            "fetch",
            "metadata",
        )
    )
    return routine_read and is_success_neutral_or_unknown_result(row) and not is_protected_investigation_signal(row)


def derive_action_category(method_name: str, action: str) -> str:
    """Group raw audit methods into high-level investigation intent."""
    method = str(method_name or "")
    action_text = str(action or "")
    combined = f"{method} {action_text}"
    lowered = re.sub(r"[_./-]+", " ", combined).lower()
    compact = re.sub(r"[^a-z0-9]+", "", lowered)

    if "apikey" in compact or "api key" in lowered:
        return "API Key"
    if any(marker in compact for marker in ("createacl", "createacls", "deleteacl", "deleteacls", "rolebinding", "rbac")) or re.search(r"\bacl\b", lowered):
        return "Security"
    if "createtopic" in compact or "createtopics" in compact:
        return "Create"
    if "deletetopic" in compact or "deletetopics" in compact:
        return "Delete"
    if any(marker in compact for marker in ("tableflowgettable", "produce", "fetch", "consume", "read")):
        return "Data"
    if any(marker in compact for marker in ("authorize", "authorization", "authentication", "authenticate")):
        return "Security"
    if "delete" in compact:
        return "Delete"
    if any(marker in compact for marker in ("alter", "update", "modify", "config")):
        return "Modify"
    if "create" in compact:
        return "Create"
    return "Other"


def enrich_clean_events(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with normalized clean-dashboard fields attached."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    enriched = df.copy()
    resource_info = enriched.apply(derive_resource_info, axis=1)
    enriched["normalized_action"] = enriched.apply(humanize_action, axis=1)
    enriched["action_category"] = enriched.apply(
        lambda row: derive_action_category(
            str(row.get("methodName", "") or ""),
            str(row.get("action", "") or ""),
        ),
        axis=1,
    )
    enriched["resource_type"] = resource_info.apply(lambda item: item["resource_type"])
    enriched["resource_name"] = resource_info.apply(lambda item: item["resource_name"])
    enriched["resource_display"] = resource_info.apply(lambda item: item["resource_display"])
    enriched["raw_resource"] = resource_info.apply(lambda item: item["raw_resource"])
    enriched["is_failure"] = enriched.apply(derive_is_failure, axis=1)
    enriched["is_denied"] = enriched.apply(is_denied_result, axis=1)
    enriched["is_routine_noise"] = enriched.apply(
        lambda row: is_routine_auth_noise(row) or is_routine_metadata_noise(row),
        axis=1,
    )
    return enriched


def attach_action_category(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with the clean dashboard action_category column attached."""
    return enrich_clean_events(df)


def build_clean_audit_table(df: pd.DataFrame) -> pd.DataFrame:
    """Map transformed audit events to the clean dashboard's default columns."""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(CLEAN_AUDIT_COLUMNS.values()))

    table = pd.DataFrame(index=df.index)
    for source, label in CLEAN_AUDIT_COLUMNS.items():
        if source == "time":
            table[label] = df[source].apply(format_event_time) if source in df.columns else "-"
        elif source == "result_display":
            table[label] = df.apply(normalized_result, axis=1)
        elif source == "summary":
            table[label] = df.apply(human_summary, axis=1)
        elif source == "user_display":
            table[label] = df[source].apply(summarize_actor) if source in df.columns else "-"
        elif source == "action":
            table[label] = df.apply(humanize_action, axis=1)
        elif source == "resource":
            table[label] = df.apply(summarize_event_resource, axis=1)
        elif source in df.columns:
            table[label] = df[source].fillna("-").astype(str)
        else:
            table[label] = "-"
    return table


def _init_filter_counters(df: pd.DataFrame | None) -> Dict[str, int]:
    loaded = 0 if df is None else len(df)
    return {key: loaded if key == "loaded_rows" else 0 for key in FILTER_COUNTER_LABELS}


def _record_filter_count(counters: Dict[str, int], key: str, df: pd.DataFrame) -> None:
    counters[key] = len(df)


def _resource_text_matches(row: pd.Series, query: str) -> bool:
    needle = str(query or "").strip().lower()
    if not needle:
        return True

    values = [
        row.get("resource_name", ""),
        row.get("resource_display", ""),
        row.get("raw_resource", ""),
        row.get("summary", ""),
        row.get("message", ""),
        row.get("resourceName", ""),
        row.get("authzResourceName", ""),
        row.get("topic_name", ""),
        row.get("cluster_id", ""),
        row.get("request", ""),
        row.get("requestData", ""),
        row.get("request_data", ""),
        row.get("methodName", ""),
        row.get("action", ""),
    ]
    try:
        values.append(human_summary(row))
    except Exception:
        pass

    haystack = " ".join(str(value or "") for value in values).lower()
    return needle in haystack


def render_filter_counters(counters: Dict[str, int] | None) -> None:
    if not counters:
        return
    with st.expander("Filter counters", expanded=False):
        for key, label in FILTER_COUNTER_LABELS.items():
            st.caption(f"{label}: {counters.get(key, 0):,}")


def dataframe_memory_summary(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {"rows": 0, "columns": 0, "memory_bytes": 0, "memory_mib": 0.0}
    memory_bytes = int(df.memory_usage(deep=True).sum())
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "memory_bytes": memory_bytes,
        "memory_mib": round(memory_bytes / (1024 * 1024), 2),
    }


def render_empty_filter_counters(counters: Dict[str, int] | None) -> None:
    if not counters:
        return
    for key in (
        "loaded_rows",
        "after_resource_type",
        "after_resource_text",
        "after_action_category",
        "after_routine_hiding",
    ):
        st.caption(f"{FILTER_COUNTER_LABELS[key]}: {counters.get(key, 0):,}")


def filter_core_events(
    df: pd.DataFrame,
    *,
    hide_internal: bool,
    hide_authz_noise: bool,
    show_routine_auth: bool = False,
    actor_query: str = "",
    resource_query: str = "",
    action_query: str = "",
    resource_type_filter: str = "All",
    action_category_filter: str = "All",
    return_counters: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, Dict[str, int]]:
    """Apply only the simple global filters used by the clean dashboard."""
    counters = _init_filter_counters(df)
    if df is None or df.empty:
        empty = pd.DataFrame()
        return (empty, counters) if return_counters else empty

    filtered = enrich_clean_events(df)
    _record_filter_count(counters, "after_enrichment", filtered)
    if hide_internal and "is_internal" in filtered.columns:
        filtered = filtered[~filtered["is_internal"].apply(is_true_flag)]
    if hide_authz_noise and "is_successful_authz_noise" in filtered.columns:
        filtered = filtered[~filtered["is_successful_authz_noise"].apply(is_true_flag)]
    if resource_type_filter and resource_type_filter != "All":
        type_mask = filtered["resource_type"] == resource_type_filter
        filtered = filtered[type_mask]
    _record_filter_count(counters, "after_resource_type", filtered)
    if resource_query:
        trimmed_query = str(resource_query).strip()
        resource_mask = filtered.apply(lambda row: _resource_text_matches(row, trimmed_query), axis=1)
        filtered = filtered[resource_mask]
    _record_filter_count(counters, "after_resource_text", filtered)
    if action_category_filter and action_category_filter != "All":
        filtered = filtered[filtered["action_category"] == action_category_filter]
    _record_filter_count(counters, "after_action_category", filtered)
    if action_query and "methodName" in filtered.columns:
        trimmed_action = str(action_query).strip()
        action_mask = filtered["methodName"].astype(str).str.contains(trimmed_action, case=False, na=False, regex=False)
        if "action" in filtered.columns:
            action_mask = action_mask | filtered["action"].astype(str).str.contains(trimmed_action, case=False, na=False, regex=False)
        if "normalized_action" in filtered.columns:
            action_mask = action_mask | filtered["normalized_action"].astype(str).str.contains(trimmed_action, case=False, na=False, regex=False)
        filtered = filtered[action_mask]
    _record_filter_count(counters, "after_action_text", filtered)
    if actor_query:
        trimmed_actor = str(actor_query).strip()
        actor_mask = pd.Series(False, index=filtered.index)
        for column in ("principal", "principal_normalized", "user", "user_display", "email"):
            if column in filtered.columns:
                actor_mask = actor_mask | filtered[column].astype(str).str.contains(trimmed_actor, case=False, na=False, regex=False)
        filtered = filtered[actor_mask]
    _record_filter_count(counters, "after_actor", filtered)
    if not show_routine_auth:
        routine_mask = filtered["is_routine_noise"] if "is_routine_noise" in filtered.columns else filtered.apply(
            lambda row: is_routine_auth_noise(row) or is_routine_metadata_noise(row),
            axis=1,
        )
        routine_mask = routine_mask.apply(is_true_flag)
        filtered = filtered[~routine_mask]
    _record_filter_count(counters, "after_routine_hiding", filtered)
    return (filtered, counters) if return_counters else filtered


def fetch_forwarder_health(timeout: float = 2.0) -> Dict[str, Any]:
    """Fetch forwarder health without making dashboard startup depend on it."""
    base_urls = [
        config.DASHBOARD_FORWARDER_URL.rstrip("/"),
        "http://localhost:8003",
    ]
    seen = set()
    for base_url in base_urls:
        if base_url in seen:
            continue
        seen.add(base_url)
        try:
            response = requests.get(f"{base_url}/health", timeout=timeout)
            if response.ok:
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
        except Exception:
            continue
    return {}


def extract_storage_summary(health: Dict[str, Any]) -> Dict[str, Any]:
    """Extract bounded hot-cache storage fields from /health."""
    observability = health.get("observability") if isinstance(health.get("observability"), dict) else {}
    storage = observability.get("persistence_storage") if isinstance(observability.get("persistence_storage"), dict) else {}

    return {
        "status": health.get("status"),
        "current_db_size": storage.get("current_db_size"),
        "max_db_size": storage.get("max_db_size"),
        "storage_mode": storage.get("storage_mode"),
        "hot_cache_retention_hours": storage.get("hot_cache_retention_hours"),
        "last_rotation_time": storage.get("last_rotation_time"),
        "archive_enabled": storage.get("archive_enabled"),
    }


def latest_event_time(df: pd.DataFrame) -> str:
    if df is None or df.empty or "time" not in df.columns:
        return "-"
    latest = pd.to_datetime(df["time"], errors="coerce").max()
    if pd.isna(latest):
        return "-"
    return format_event_time(latest)


def latest_event_age(df: pd.DataFrame) -> str:
    if df is None or df.empty or "time" not in df.columns:
        return "No recent events"
    latest = pd.to_datetime(df["time"], errors="coerce", utc=True).max()
    if pd.isna(latest):
        return "No recent events"
    now = pd.Timestamp.now(tz="UTC")
    minutes = max(0, int((now - latest).total_seconds() // 60))
    if minutes < 1:
        return "Latest event just now"
    if minutes == 1:
        return "Latest event 1 minute ago"
    if minutes < 60:
        return f"Latest event {minutes} minutes ago"
    hours = minutes // 60
    return f"Latest event {hours} hour{'s' if hours != 1 else ''} ago"


def compact_event_age(df: pd.DataFrame) -> str:
    if df is None or df.empty or "time" not in df.columns:
        return "no events"
    latest = pd.to_datetime(df["time"], errors="coerce", utc=True).max()
    if pd.isna(latest):
        return "no events"
    minutes = max(0, int((pd.Timestamp.now(tz="UTC") - latest).total_seconds() // 60))
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago"


def _format_bytes(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        size = float(value)
    except (TypeError, ValueError):
        return str(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _storage_usage(storage: Dict[str, Any]) -> float:
    try:
        current = float(storage.get("current_db_size") or 0)
        maximum = float(storage.get("max_db_size") or 0)
    except (TypeError, ValueError):
        return 0.0
    if maximum <= 0:
        return 0.0
    return max(0.0, min(current / maximum, 1.0))


def signal_class(kind: str, value: float) -> str:
    """Return focus-strip severity classes for counts and storage percentage."""
    if kind == "storage":
        if value >= 90:
            return "signal-red"
        if value >= 80:
            return "signal-amber"
        if value >= 60:
            return "signal-yellow"
        return "signal-green"
    if kind == "failures" and value > 0:
        return "signal-red"
    if kind == "deletions" and value > 0:
        return "signal-orange"
    return "signal-green"


def _severity_class(value: str) -> str:
    lowered = str(value or "").lower()
    if lowered in {"healthy", "normal", "ok"}:
        return "pill-ok"
    if lowered in {"warning", "degraded"}:
        return "pill-warn"
    if lowered in {"critical", "emergency", "unhealthy", "unavailable"}:
        return "pill-bad"
    return "pill-neutral"


def _card_severity(value: str) -> str:
    lowered = str(value or "").lower()
    if lowered in {"warning", "degraded"}:
        return "warn"
    if lowered in {"critical", "emergency", "unhealthy", "unavailable"}:
        return "bad"
    if lowered in {"healthy", "normal", "ok"}:
        return "ok"
    return "neutral"


def storage_card_severity(storage_pct: float) -> str:
    if storage_pct >= 90:
        return "bad"
    if storage_pct >= 80:
        return "orange"
    if storage_pct >= 60:
        return "warn"
    return "ok"


def _recent_count(df: pd.DataFrame, column: str, hours: int = 24) -> int:
    if df is None or df.empty or column not in df.columns:
        return 0
    scoped = df
    if "time" in df.columns:
        times = pd.to_datetime(df["time"], errors="coerce", utc=True)
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
        scoped = df[times >= cutoff]
        if scoped.empty and times.notna().any():
            scoped = df
    return int(scoped[column].sum()) if column in scoped.columns else 0


def render_focus_strip(df: pd.DataFrame, storage: Dict[str, Any]) -> None:
    failures = _recent_count(df, "is_failure")
    deletions = _recent_count(df, "is_deletion")
    storage_pct = _storage_usage(storage) * 100
    updated = compact_event_age(df)
    st.markdown(
        f"""
        <div class="focus-strip">
            <div class="focus-pill {signal_class('failures', failures)}">Failures: {failures:,}</div>
            <div class="focus-pill {signal_class('deletions', deletions)}">Deletions: {deletions:,}</div>
            <div class="focus-pill {signal_class('storage', storage_pct)}">Storage {storage_pct:.0f}%</div>
            <div class="focus-pill signal-blue">Updated {updated}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_failure_cta(df: pd.DataFrame) -> None:
    failures = _recent_count(df, "is_failure")
    if failures <= 0:
        return
    st.markdown(
        '<div class="failure-cta">Investigate failures in the Failures tab.</div>',
        unsafe_allow_html=True,
    )


def render_top_help_button() -> None:
    _, help_col = st.columns([10, 1])
    with help_col:
        if st.button("?", key="top_help_button", help="Open AuditLens Clean help"):
            set_active_tab("Help", anchor=HELP_GUIDED_DEMO_ANCHOR)
            st.rerun()


def render_first_time_onboarding_banner() -> None:
    if st.session_state.get("onboarding_banner_dismissed"):
        return
    if "onboarding_banner_seen" not in st.session_state:
        st.session_state.onboarding_banner_seen = True

    st.markdown(
        '<div class="onboarding-banner">New to AuditLens? Start the 10-minute guided demo</div>',
        unsafe_allow_html=True,
    )
    start_col, dismiss_col, _ = st.columns([2, 1.4, 5.6], vertical_alignment="center")
    with start_col:
        if st.button("Start guided demo", key="start_guided_demo", use_container_width=False):
            set_active_tab("Help", anchor=HELP_GUIDED_DEMO_ANCHOR)
            st.session_state.demo_flow_step = 0
            st.rerun()
    with dismiss_col:
        if st.button("Dismiss", key="dismiss_onboarding", use_container_width=False):
            st.session_state.onboarding_banner_dismissed = True
            st.rerun()


def render_context_hint(key: str, message: str, *, help_anchor: str | None = None) -> None:
    dismiss_key = f"context_hint_dismissed_{key}"
    if st.session_state.get(dismiss_key):
        return
    st.markdown(f'<div class="context-help">{html.escape(message)}</div>', unsafe_allow_html=True)
    cols = st.columns([1, 1, 6])
    if help_anchor:
        with cols[0]:
            if st.button("Open guide", key=f"open_guide_{key}"):
                set_active_tab("Help", anchor=help_anchor)
                st.rerun()
    with cols[1]:
        if st.button("Dismiss", key=f"dismiss_hint_{key}"):
            st.session_state[dismiss_key] = True
            st.rerun()


def _render_header(df: pd.DataFrame, health: Dict[str, Any], storage: Dict[str, Any]) -> None:
    health_label = str(storage.get("status") or "unavailable").title() if health else "Unavailable"
    storage_mode = str(storage.get("storage_mode") or "unknown").lower()
    logo = ""
    if LOGO_BASE64:
        logo = f'<img src="data:image/png;base64,{LOGO_BASE64}" width="76" style="margin-bottom: 12px;">'

    st.markdown(
        f"""
        <div class="clean-hero">
            {logo}
            <div class="clean-hero-title">{APP_NAME} Clean</div>
            <div class="clean-hero-subtitle">Real-time audit intelligence for Confluent Cloud</div>
            <div class="pill-row">
                <span class="status-pill {_severity_class(health_label)}">{health_label}</span>
                <span class="status-pill pill-neutral">{latest_event_age(df)}</span>
                <span class="status-pill {_severity_class(storage_mode)}">Hot cache {storage_mode}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_metric_card(label: str, value: str, helper: str, severity: str = "neutral") -> None:
    subtext_by_label = {
        "Failures": "Investigate in Failures",
        "Deletions": "Review in Deletions",
        "Storage Used": "Hot cache usage",
        "Loaded Events": "Current audit window",
    }
    subtext = subtext_by_label.get(label, "")
    st.markdown(
        f"""
        <div class="metric-card {severity}">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-help">{helper}</div>
            <div class="metric-subtext">{subtext}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_shortcut_card(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="shortcut-card">
            <div class="shortcut-title">{title}</div>
            <div class="shortcut-body">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_detail_card(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="detail-card">
            <div class="detail-label">{label}</div>
            <div class="detail-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def style_clean_table(table: pd.DataFrame):
    """Apply lightweight emphasis to investigation table columns."""
    def style_cell(value: Any, column: str) -> str:
        text = str(value)
        if column == "Result":
            if "Failure" in text:
                return "color: #b42318; font-weight: 750;"
            if "Denied" in text:
                return "color: #b93815; font-weight: 750;"
            if "Success" in text:
                return "color: #067647; font-weight: 750;"
            return "color: #667085;"
        if column in {"Action", "Resource", "Actor"}:
            return "font-weight: 650; color: #101828;"
        if column in {"Cluster", "Source IP"}:
            return "color: #667085; font-size: 0.88rem;"
        if column == "Summary":
            return "color: #344054; font-weight: 600;"
        return ""

    return table.style.apply(lambda row: [style_cell(row[col], col) for col in row.index], axis=1)


def _result_class(value: str) -> str:
    if "Failure" in value:
        return "result-failure"
    if "Denied" in value:
        return "result-denied"
    if "Success" in value:
        return "result-success"
    return "result-neutral"


def render_audit_html_table(table: pd.DataFrame, max_rows: int = 75) -> str:
    columns = ["Time", "Result", "Summary", "Actor", "Action", "Resource", "Cluster", "Source IP"]
    class_by_column = {
        "Time": "col-time",
        "Result": "col-result",
        "Summary": "col-summary",
        "Actor": "col-actor",
        "Action": "col-action",
        "Resource": "col-resource",
        "Cluster": "col-cluster",
        "Source IP": "col-ip",
    }
    header = "".join(f'<th class="{class_by_column[col]}">{html.escape(col)}</th>' for col in columns)
    rows = []
    for _, row in table.head(max_rows).iterrows():
        cells = []
        for col in columns:
            value = html.escape(str(row.get(col, "")))
            classes = class_by_column[col]
            content_class = "cell-wrap" if col in {"Summary", "Resource"} else "cell-nowrap"
            if col == "Result":
                classes = f"{classes} {_result_class(str(row.get(col, '')))}"
            cells.append(f'<td class="{classes}"><div class="{content_class}">{value}</div></td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        '<div class="audit-table-wrap">'
        '<table class="audit-table">'
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


def row_detail_sections(row: pd.Series) -> tuple[Dict[str, Any], Dict[str, Any]]:
    resource_info = derive_resource_info(row)
    normalized = {
        "Time": format_event_time(_first_present(row, ("time", "time_display"), "")),
        "Actor": summarize_actor(_first_present(row, ("user_display", "user", "principal"), "Unknown actor")),
        "Actor email/name": str(_first_present(row, ("actor_email", "user_email", "email", "actor_name", "user_name", "name"), "-")),
        "Action": humanize_action(row),
        "Result": normalized_result(row),
        "Resource Type": resource_info["resource_type"],
        "Resource Name": resource_info["resource_name"],
        "Resource Display": resource_info["resource_display"],
        "Cluster": str(_first_present(row, ("cluster_id", "clusterId"), "-")),
        "Environment": str(_first_present(row, ("environment_id", "environmentId"), _environment_id(row))),
        "Source IP": str(_first_present(row, ("clientIp", "sourceIp", "source_ip"), "-")),
        "Client ID": str(_first_present(row, ("clientId", "client_id"), "-")),
    }

    raw_json = "-"
    if "raw" in row and pd.notna(row["raw"]):
        raw_json = row["raw"]
    elif "event" in row and pd.notna(row["event"]):
        raw_json = row["event"]

    request_or_client_id = _first_present(
        row,
        ("request_id", "requestId", "clientId", "client_id", "correlation_id", "correlationId"),
        "-",
    )
    raw = {
        "methodName": str(_first_present(row, ("methodName",), "-")),
        "resourceName": str(_first_present(row, ("resourceName",), "-")),
        "authzResourceName": str(_first_present(row, ("authzResourceName",), "-")),
        "principal": str(_first_present(row, ("principal", "principal_raw", "principal_normalized"), "-")),
        "resultStatus": str(_first_present(row, ("resultStatus",), "-")),
        "granted": str(_first_present(row, ("granted",), "-")),
        "request/client ID": str(request_or_client_id),
        "full raw JSON": raw_json,
    }
    return normalized, raw


def _render_overview(df: pd.DataFrame, health: Dict[str, Any], storage: Dict[str, Any]) -> None:
    render_context_hint(
        "overview",
        "Start here: check failures, deletions, data freshness, and storage state before drilling into events.",
    )
    failures = int(df["is_failure"].sum()) if "is_failure" in df.columns and not df.empty else 0
    deletions = int(df["is_deletion"].sum()) if "is_deletion" in df.columns and not df.empty else 0
    health_available = bool(health)
    status = str(storage.get("status") or "unknown").title() if health_available else "Unavailable"
    storage_mode = str(storage.get("storage_mode") or "-")
    usage = _storage_usage(storage)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        _render_metric_card("Loaded Events", f"{len(df):,}", "Events currently in the investigation window.", "neutral")
    with col2:
        _render_metric_card("Failures", f"{failures:,}", "Denied, failed, or errored operations.", "bad" if failures else "ok")
    with col3:
        _render_metric_card("Deletions", f"{deletions:,}", "Irreversible delete activity in scope.", "orange" if deletions else "ok")
    with col4:
        _render_metric_card("Storage Used", f"{usage * 100:.0f}%", "SQLite bounded hot-cache usage.", storage_card_severity(usage * 100))

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        _render_detail_card("System Health", status)
    with col6:
        _render_detail_card("Latest Event", latest_event_time(df))
    with col7:
        _render_detail_card("Data Freshness", latest_event_age(df))
    with col8:
        _render_detail_card("Storage Mode", storage_mode)

    if not health_available:
        st.error("Forwarder health unavailable")

    st.markdown("#### Investigation Shortcuts")
    shortcuts = st.columns(4)
    with shortcuts[0]:
        _render_shortcut_card("Find failed operations", "Open the Failures tab to isolate denied, failed, or errored requests.")
    with shortcuts[1]:
        _render_shortcut_card("Review deletions", "Open the Deletions tab to inspect irreversible activity.")
    with shortcuts[2]:
        _render_shortcut_card("Search actor/resource", "Use the Audit Trail filters for a service account, topic, cluster, or method.")
    with shortcuts[3]:
        _render_shortcut_card("Check storage state", "Review the hot-cache storage section below for bounded retention status.")

    st.markdown("#### Storage Summary")
    storage_cols = st.columns(4)
    storage_cols[0].metric("Current DB", _format_bytes(storage.get("current_db_size")))
    storage_cols[1].metric("Max DB", _format_bytes(storage.get("max_db_size")))
    storage_cols[2].metric("Hot Cache Retention", f"{storage.get('hot_cache_retention_hours') or '-'} hours")
    archive = storage.get("archive_enabled")
    storage_cols[3].metric("Archive", "enabled" if archive is True else "not enabled" if archive is False else "-")
    st.progress(usage, text=f"DB usage: {usage * 100:.1f}%")
    st.caption(f"Last rotation: {storage.get('last_rotation_time') or '-'}")

    st.info(
        "SQLite is a bounded hot cache, not long-term archive. "
        "This clean dashboard shows recent audit intelligence only."
    )


def _render_clean_table(df: pd.DataFrame, key: str, counters: Dict[str, int] | None = None) -> None:
    st.info("Routine authentication and authorization events are hidden by default. Enable in sidebar to view all events.")

    if df.empty:
        st.info("No matching audit events found.")
        render_empty_filter_counters(counters)
        return

    table = build_clean_audit_table(df)
    st.markdown(render_audit_html_table(table), unsafe_allow_html=True)
    if len(table) > 75:
        st.caption(f"Showing first 75 of {len(table):,} matching events. Use filters to narrow the investigation.")

    st.markdown("#### Row Details")
    sorted_df = df.sort_values("time", ascending=False) if "time" in df.columns else df
    choices = []
    for idx, row in sorted_df.head(200).iterrows():
        actor = _first_present(row, ("user_display", "user", "principal"), "unknown actor")
        action = humanize_action(row)
        resource = summarize_event_resource(row)
        when = format_event_time(_first_present(row, ("time", "time_display"), ""))
        choices.append((idx, f"{when} | {actor} | {action} | {resource}"))

    selected_label = st.selectbox("Select an event", [label for _, label in choices], key=f"{key}_row_detail")
    selected_idx = next(idx for idx, label in choices if label == selected_label)
    row = sorted_df.loc[selected_idx]
    normalized_detail, raw_detail = row_detail_sections(row)

    st.markdown("##### Normalized")
    st.json(normalized_detail)
    st.markdown("##### Raw")
    st.json(raw_detail)


def _render_audit_trail(df: pd.DataFrame, counters: Dict[str, int] | None = None) -> None:
    st.subheader("Audit Trail")
    st.caption("To find who created or deleted a topic, set Resource Type = Topic and search the topic name.")
    display_df = df.sort_values("time", ascending=False) if "time" in df.columns and not df.empty else df
    _render_clean_table(display_df, "audit_trail", counters)


def _render_failures(df: pd.DataFrame, counters: Dict[str, int] | None = None) -> None:
    failure_df = df[df["is_failure"] == True].copy() if "is_failure" in df.columns else pd.DataFrame()
    st.subheader(f"Failures ({len(failure_df):,})")
    st.caption("Denied access, authentication failures, authorization failures, and operation errors.")
    render_context_hint(
        "failures",
        "Debug failures by reading Summary, then open Row Details for raw method, request ID, and error evidence.",
        help_anchor=HELP_GUIDED_DEMO_ANCHOR,
    )
    _render_clean_table(failure_df, "failures", counters)


def _render_deletions(df: pd.DataFrame, counters: Dict[str, int] | None = None) -> None:
    deletion_df = df[df["is_deletion"] == True].copy() if "is_deletion" in df.columns else pd.DataFrame()
    st.subheader(f"Deletions ({len(deletion_df):,})")
    st.caption("Deletion operations for topics, clusters, connectors, API keys, RBAC, ACLs, and related resources.")
    st.caption("Use Resource Type = Topic to find topic deletions.")
    _render_clean_table(deletion_df, "deletions", counters)


def _render_advanced_placeholder(counters: Dict[str, int] | None = None, df: pd.DataFrame | None = None) -> None:
    st.subheader("Advanced")
    st.markdown(
        """
Advanced investigations are available in the legacy dashboard. This clean dashboard keeps first-line audit workflows focused.

Advanced tools currently available in the legacy dashboard:

- API Keys
- Topic x Identity
- Identity Activity
- Analytics
- Export

Run the legacy dashboard with:

```bash
streamlit run dashboard/app.py --server.port 8503
```
        """
    )
    render_filter_counters(counters)
    st.markdown("### Runtime Memory")
    st.json({
        "dataframe": dataframe_memory_summary(pd.DataFrame() if df is None else df),
        "streamlit_cache": "load_events_from_kafka ttl=15s max_entries=2",
    })


def _render_demo_flow_runner() -> None:
    st.markdown("### Run Demo Flow")
    st.caption("Use this as a lightweight checklist while walking through a real Confluent Cloud demo.")
    if "demo_flow_step" not in st.session_state:
        st.session_state.demo_flow_step = 0

    step = int(st.session_state.demo_flow_step)
    total = len(DEMO_FLOW_STEPS)
    st.markdown(
        f"""
        <div class="help-card">
            <strong>Step {step + 1} of {total}</strong><br>
            {html.escape(DEMO_FLOW_STEPS[step])}
        </div>
        """,
        unsafe_allow_html=True,
    )

    prev_col, next_col, reset_col, _ = st.columns([1, 1, 1, 6])
    with prev_col:
        if st.button("Previous", key="demo_previous", disabled=step == 0):
            st.session_state.demo_flow_step = previous_demo_step(step)
            st.rerun()
    with next_col:
        if st.button("Next", key="demo_next", disabled=step >= total - 1):
            st.session_state.demo_flow_step = next_demo_step(step, total)
            st.rerun()
    with reset_col:
        if st.button("Reset", key="demo_reset"):
            st.session_state.demo_flow_step = 0
            st.rerun()


def _render_help_tab() -> None:
    st.subheader("Help")
    _render_demo_flow_runner()
    markdown = load_onboarding_markdown()
    if markdown is None:
        st.warning(
            "AuditLens Clean onboarding walkthrough is not available. "
            "Expected docs/AuditLens_Clean_Onboarding_Walkthrough.md."
        )
        return

    if st.session_state.pop("help_anchor", None) == HELP_GUIDED_DEMO_ANCHOR:
        st.markdown(f'<a id="{HELP_GUIDED_DEMO_ANCHOR}"></a>', unsafe_allow_html=True)
        st.info("Jump to: Guided Demo Flow")

    st.markdown(help_markdown_with_anchor(markdown), unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title=f"{APP_NAME} Clean", page_icon="AL", layout="wide")
    st.markdown(CLEAN_DASHBOARD_CSS, unsafe_allow_html=True)
    st.markdown(THEME_CSS.get("A", ""), unsafe_allow_html=True)
    st.markdown(DATA_TABLE_CSS, unsafe_allow_html=True)
    if "active_tab" not in st.session_state or st.session_state.active_tab not in PRIMARY_TABS:
        st.session_state.active_tab = "Overview"

    with st.sidebar:
        st.header("Query")
        st.markdown("### Controls")
        time_options = {
            "15 minutes": 15,
            "30 minutes": 30,
            "1 hour": 60,
            "4 hours": 240,
            "12 hours": 720,
            "24 hours": 1440,
            "72 hours": 4320,
        }
        selected_time = st.selectbox("Time Window", list(time_options.keys()), index=2)
        max_events = st.slider("Max Events", min_value=500, max_value=10000, value=3000, step=500)
        show_routine_auth = st.checkbox("Show routine auth/authz events", value=False)
        st.markdown("### Filters")
        actor_query = st.text_input("Actor", placeholder="sa-xxxxx or user")
        resource_type_filter = st.selectbox("Resource Type", RESOURCE_TYPE_OPTIONS, index=0)
        resource_query = st.text_input("Resource", placeholder="topic, cluster, API key")
        action_category_filter = st.selectbox("Action Category", ACTION_CATEGORY_OPTIONS, index=0)
        st.caption("Groups operations by intent (Create, Delete, Data access, Security, etc.)")
        action_query = st.text_input("Action", placeholder="CreateTopic, DeleteTopic")
        if st.button("Refresh Data", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    df = load_events_from_kafka(
        criticality_filter="All",
        time_minutes=time_options[selected_time],
        max_events=max_events,
    )
    df, filter_counters = filter_core_events(
        df,
        hide_internal=False,
        hide_authz_noise=False,
        show_routine_auth=show_routine_auth,
        actor_query=actor_query,
        resource_query=resource_query,
        action_query=action_query,
        resource_type_filter=resource_type_filter,
        action_category_filter=action_category_filter,
        return_counters=True,
    )

    health = fetch_forwarder_health()
    storage = extract_storage_summary(health)
    render_top_help_button()
    _render_header(df, health, storage)

    selected_tab = st.radio(
        "Navigation",
        PRIMARY_TABS,
        key="active_tab",
        horizontal=True,
        label_visibility="collapsed",
    )

    if selected_tab == "Overview":
        render_first_time_onboarding_banner()
        render_focus_strip(df, storage)
        render_failure_cta(df)
        _render_overview(df, health, storage)
    elif selected_tab == "Audit Trail":
        _render_audit_trail(df, filter_counters)
    elif selected_tab == "Failures":
        _render_failures(df, filter_counters)
    elif selected_tab == "Deletions":
        _render_deletions(df, filter_counters)
    elif selected_tab == "Advanced":
        _render_advanced_placeholder(filter_counters, df)
    elif selected_tab == "Help":
        _render_help_tab()

    st.caption("Legacy dashboard remains available separately with the full investigation surface.")


if __name__ == "__main__":
    main()
