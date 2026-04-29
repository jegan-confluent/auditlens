"""
Confluent AuditLens
Real-time Kafka Audit Intelligence Dashboard
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# Configuration and themes
import config
from config import APP_NAME, APP_VERSION, APP_TAGLINE, LOGO_BASE64, THEME_CSS, DATA_TABLE_CSS, THEME, TIMEZONES

# Data layer
from data.kafka_consumer import load_events_from_kafka
from data.transformations import detect_anomalies
from data.email_cache import GLOBAL_EMAIL_CACHE, refresh_email_cache

# Components
from components.metrics import render_metric_card
from components.filters import render_alert_banner, render_quick_filters, apply_quick_filter

# Tabs
import tabs.welcome as welcome
import tabs.audit_trail as audit_trail
import tabs.failures as failures
import tabs.deletions as deletions
import tabs.api_keys as api_keys
import tabs.security as security
import tabs.details as details
import tabs.analytics as analytics
import tabs.time_insights as time_insights
import tabs.export as export_tab
import tabs.security_alerts as security_alerts
import tabs.topic_identity as topic_identity
import tabs.identity_activity as identity_activity


RAW_PAYLOAD_CACHE_MAX = 200


def dataframe_memory_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"rows": 0, "columns": 0, "memory_bytes": 0, "memory_mib": 0.0}
    memory_bytes = int(df.memory_usage(deep=True).sum())
    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "memory_bytes": memory_bytes,
        "memory_mib": round(memory_bytes / (1024 * 1024), 2),
    }


def stash_raw_payloads_and_trim(df: pd.DataFrame) -> pd.DataFrame:
    """Keep bulky raw JSON out of table DataFrames while preserving details lookup."""
    if df is None or df.empty or "data_json" not in df.columns:
        return df

    cache = st.session_state.setdefault("auditlens_raw_payloads", {})
    id_columns = [column for column in ("id", "event_id", "requestId", "correlationId") if column in df.columns]
    if id_columns:
        for _, row in df[["data_json", *id_columns]].head(RAW_PAYLOAD_CACHE_MAX).iterrows():
            payload = row.get("data_json")
            if pd.isna(payload):
                continue
            cache_key = next((str(row.get(column)) for column in id_columns if pd.notna(row.get(column)) and row.get(column)), None)
            if cache_key:
                cache[cache_key] = payload
        while len(cache) > RAW_PAYLOAD_CACHE_MAX:
            cache.pop(next(iter(cache)))

    return df.drop(columns=["data_json"])

# =============================================================================
# STREAMLIT PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title=APP_NAME,
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize theme in session state
if 'theme' not in st.session_state:
    st.session_state.theme = THEME

# Apply theme CSS (from session state)
st.markdown(THEME_CSS[st.session_state.theme], unsafe_allow_html=True)
st.markdown(DATA_TABLE_CSS, unsafe_allow_html=True)

# =============================================================================
# HEADER
# =============================================================================
col_logo, col_title = st.columns([1, 4])

with col_logo:
    if LOGO_BASE64:
        st.markdown(
            f'<img src="data:image/png;base64,{LOGO_BASE64}" width="120" style="margin-top: 10px;">',
            unsafe_allow_html=True
        )

with col_title:
    st.title(APP_NAME)
    st.markdown(f"**{APP_TAGLINE}**")

# =============================================================================
# SIDEBAR CONTROLS
# =============================================================================
with st.sidebar:
    st.header("⚙️ Query Settings")

    # Quick Help toggle
    if 'show_help' not in st.session_state:
        st.session_state.show_help = False

    if st.button("❓ Quick Help", use_container_width=True):
        st.session_state.show_help = not st.session_state.show_help

    if st.session_state.show_help:
        st.info("""
**Filters:** Time Window, Criticality, Search boxes
**Tabs:** Audit Trail | Failures | Deletions | API Keys | Security
**Tips:** "Hide internal" filters system ops • Quick Filter buttons for common views
        """)

    st.divider()

    # Criticality filter
    criticality_filter = st.selectbox(
        "Criticality Level",
        options=['All', 'CRITICAL', 'HIGH', 'MEDIUM'],
        index=0,
        help="Filter events by importance level"
    )

    # Time window selector
    time_options = {
        '15 minutes': 15,
        '30 minutes': 30,
        '1 hour': 60,
        '2 hours': 120,
        '4 hours': 240,
        '8 hours': 480,
        '12 hours': 720,
        '24 hours': 1440,
        '48 hours': 2880,
        '72 hours': 4320
    }
    selected_time = st.selectbox(
        "Time Window",
        list(time_options.keys()),
        index=2,  # Default to 1 hour (index 2)
        help="Time window for events"
    )
    time_minutes = time_options[selected_time]

    # Timezone selector
    selected_tz = st.selectbox(
        "Display Timezone",
        list(TIMEZONES.keys()),
        index=0,
        help="Convert timestamps to selected timezone"
    )

    # Theme selector
    theme_options = {'🌸 Pastel': 'B', '⚪ Clean': 'A', '🔵 Professional': 'C'}
    theme_labels = list(theme_options.keys())
    current_theme_idx = list(theme_options.values()).index(st.session_state.theme)
    selected_theme_label = st.selectbox(
        "Theme",
        theme_labels,
        index=current_theme_idx,
        help="Change dashboard appearance"
    )
    new_theme = theme_options[selected_theme_label]
    if new_theme != st.session_state.theme:
        st.session_state.theme = new_theme
        st.rerun()

    # Max events slider
    max_events = st.slider(
        "Max Events",
        min_value=500,
        max_value=10000,
        value=5000,
        step=500,
        help="Maximum number of events to fetch"
    )

    # Auto-refresh (non-blocking)
    auto_refresh = st.checkbox(
        "Auto-refresh (60s)",
        value=False,
        help="Automatically reload data every 60 seconds"
    )

    if auto_refresh:
        # Non-blocking auto-refresh using streamlit-autorefresh
        refresh_count = st_autorefresh(interval=60000, limit=None, key="data_autorefresh")
        # Clear cache on each auto-refresh to get fresh data
        if refresh_count > 0:
            st.cache_data.clear()
        st.markdown(
            f"""<p style="color: green; font-size: 12px;">⏱️ Auto-refresh active (count: {refresh_count})</p>""",
            unsafe_allow_html=True
        )

    st.divider()

    # Search filters section
    st.header("🔍 Search Filters")

    # Hide internal operations filter
    hide_internal = st.checkbox(
        "Hide internal/system operations",
        value=True,  # Default True - hide internal proxy operations users don't care about
        help="Hide operations on UUID-named resources (internal Confluent Cloud operations)"
    )

    hide_authz_noise = st.checkbox(
        "Hide successful authz noise",
        value=True,
        help="Hide successful Authorize checks from the default operator views"
    )

    # Cluster filter (populated after data load)
    filter_cluster = st.text_input(
        "Filter by Cluster",
        placeholder="lkc-xxxxx",
        help="Filter by Kafka cluster ID"
    )

    # Environment filter
    filter_environment = st.text_input(
        "Filter by Environment",
        placeholder="env-xxxxx",
        help="Filter by environment ID"
    )

    filter_principal = st.text_input(
        "Filter by Principal/User",
        placeholder="sa-12345 or email...",
        help="Search for specific user or service account"
    )

    filter_method = st.text_input(
        "Filter by Method",
        placeholder="DeleteTopic, CreateApiKey...",
        help="Search for specific method"
    )

    filter_resource = st.text_input(
        "Filter by Resource",
        placeholder="topic name, cluster id...",
        help="Search for specific resource"
    )

    # Filter Presets
    st.markdown("##### 💾 Filter Presets")
    if 'filter_presets' not in st.session_state:
        st.session_state.filter_presets = {
            'Security Review': {'criticality': 'CRITICAL', 'method': 'Delete', 'hide_internal': True},
            'API Key Audit': {'method': 'ApiKey', 'hide_internal': True},
            'All Activity': {'criticality': 'All', 'hide_internal': False},
        }

    preset_names = ['-- Select Preset --'] + list(st.session_state.filter_presets.keys())
    selected_preset = st.selectbox("Load Preset", preset_names, key="preset_selector")

    if selected_preset != '-- Select Preset --':
        preset = st.session_state.filter_presets[selected_preset]
        st.info(f"Preset: {', '.join([f'{k}={v}' for k,v in preset.items()])}")

    # Save current as preset
    with st.expander("Save Current Filters"):
        new_preset_name = st.text_input("Preset Name", placeholder="My Custom Filter")
        if st.button("💾 Save Preset", use_container_width=True) and new_preset_name:
            st.session_state.filter_presets[new_preset_name] = {
                'criticality': criticality_filter,
                'cluster': filter_cluster,
                'environment': filter_environment,
                'principal': filter_principal,
                'method': filter_method,
                'resource': filter_resource,
                'hide_internal': hide_internal
            }
            st.success(f"Saved preset: {new_preset_name}")
            st.rerun()

    st.divider()

    # Action buttons
    if st.button("🔄 Refresh Data", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    # Auto-clear cache on filter changes
    current_filter_hash = f"{criticality_filter}_{time_minutes}_{max_events}_{hide_internal}"
    if 'last_filter_hash' not in st.session_state:
        st.session_state.last_filter_hash = current_filter_hash
    elif st.session_state.last_filter_hash != current_filter_hash:
        st.cache_data.clear()
        st.session_state.last_filter_hash = current_filter_hash

    if st.button("👥 Refresh User Cache", use_container_width=True):
        with st.spinner("Fetching users from Confluent Cloud IAM API..."):
            refresh_email_cache()
            st.success("Email cache refreshed!")

    st.divider()
    st.caption(f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# =============================================================================
# LOAD DATA
# =============================================================================
# Data is cached for 15s - no spinner needed for cache hits
df = load_events_from_kafka(
    criticality_filter=criticality_filter,
    time_minutes=time_minutes,
    max_events=max_events
)
df = stash_raw_payloads_and_trim(df)
runtime_memory_summary = dataframe_memory_summary(df)

# Debug: Show raw data count
raw_count = len(df)

# Apply filters
if hide_internal and 'is_internal' in df.columns:
    internal_count = df['is_internal'].sum()
    df = df[~df['is_internal']]
else:
    internal_count = 0

# Apply search filters from sidebar
if filter_cluster and 'cluster_id' in df.columns:
    df = df[df['cluster_id'].str.contains(filter_cluster, case=False, na=False)]

if filter_environment and 'environment_id' in df.columns:
    df = df[df['environment_id'].str.contains(filter_environment, case=False, na=False)]

if filter_principal and 'principal' in df.columns:
    principal_mask = df['principal'].str.contains(filter_principal, case=False, na=False)
    if 'principal_normalized' in df.columns:
        principal_mask = principal_mask | df['principal_normalized'].astype(str).str.contains(filter_principal, case=False, na=False)
    if 'email' in df.columns:
        principal_mask = principal_mask | df['email'].astype(str).str.contains(filter_principal, case=False, na=False)
    df = df[principal_mask]

if filter_method and 'methodName' in df.columns:
    df = df[df['methodName'].str.contains(filter_method, case=False, na=False)]

if filter_resource and 'resourceName' in df.columns:
    df = df[df['resourceName'].str.contains(filter_resource, case=False, na=False)]

if hide_authz_noise and 'is_successful_authz_noise' in df.columns:
    df = df[~df['is_successful_authz_noise']]

# Detect anomalies
anomalies = detect_anomalies(df) if not df.empty else []

# =============================================================================
# QUICK FILTERS & ALERTS
# =============================================================================
# Alert banner
if anomalies:
    render_alert_banner(anomalies)

# Initialize quick filter session state
if 'quick_filter' not in st.session_state:
    st.session_state.quick_filter = None

# Quick filters
st.markdown("### ⚡ Quick Filters")
clicked_filter = render_quick_filters(st.session_state.quick_filter)

# Handle filter click
if clicked_filter is not None:
    if clicked_filter == "__CLEAR__":
        # User clicked active filter to deactivate
        st.session_state.quick_filter = None
    else:
        # User clicked a new filter
        st.session_state.quick_filter = clicked_filter
    st.rerun()

# Store original count before filtering
total_loaded = len(df)

# Apply the filter from session state (persists across reruns)
df = apply_quick_filter(df, st.session_state.quick_filter)

# Show active filter indicator with debug info
active_filter = st.session_state.quick_filter
from config import QUICK_FILTERS
filter_label = QUICK_FILTERS.get(active_filter, {}).get('label', 'None') if active_filter else 'None'
internal_status = 'hidden' if hide_internal else 'shown'
# Debug: Show data flow
st.info(f"📊 Raw: {raw_count} → After hide_internal: {total_loaded} → After Quick Filter: {len(df)} | Quick: {filter_label} | Internal: {internal_status}")

# =============================================================================
# KEY METRICS (Clickable)
# =============================================================================
st.markdown("### 📊 Key Metrics")
st.caption("Click a metric to filter")

col1, col2, col3, col4, col5 = st.columns(5)

total_events = len(df)
failure_count = int(df['is_failure'].sum()) if 'is_failure' in df.columns else 0
deletion_count = int(df['is_deletion'].sum()) if 'is_deletion' in df.columns else 0
critical_count = len(df[df['criticality'] == 'CRITICAL']) if 'criticality' in df.columns else 0
unique_users = df['user'].nunique() if 'user' in df.columns else 0

with col1:
    st.markdown(render_metric_card("📊 SHOWING / LOADED", f"{len(df)} / {total_loaded}", "purple"), unsafe_allow_html=True)

with col2:
    if st.button(f"🔴 CRITICAL\n\n**{critical_count}**", key="metric_critical", use_container_width=True):
        st.session_state.quick_filter = None  # Clear quick filter
        st.session_state.metric_filter = 'critical'
        st.rerun()

with col3:
    if st.button(f"❌ FAILURES\n\n**{failure_count}**", key="metric_failures", use_container_width=True):
        st.session_state.quick_filter = None
        st.session_state.metric_filter = 'failures'
        st.rerun()

with col4:
    if st.button(f"🗑️ DELETIONS\n\n**{deletion_count}**", key="metric_deletions", use_container_width=True):
        st.session_state.quick_filter = None
        st.session_state.metric_filter = 'deletions'
        st.rerun()

with col5:
    if st.button(f"👥 USERS\n\n**{unique_users}**", key="metric_users", use_container_width=True):
        st.session_state.quick_filter = None
        st.session_state.metric_filter = None  # Just info, no filter
        st.rerun()

# Apply metric filter if set
if 'metric_filter' in st.session_state and st.session_state.metric_filter:
    mf = st.session_state.metric_filter
    if mf == 'critical' and 'criticality' in df.columns:
        df = df[df['criticality'] == 'CRITICAL']
        st.info(f"🔴 Filtered to CRITICAL events: {len(df)} events")
    elif mf == 'failures' and 'is_failure' in df.columns:
        df = df[df['is_failure'] == True]
        st.info(f"❌ Filtered to FAILURES: {len(df)} events")
    elif mf == 'deletions' and 'is_deletion' in df.columns:
        df = df[df['is_deletion'] == True]
        st.info(f"🗑️ Filtered to DELETIONS: {len(df)} events")

# Clear metric filter button
if 'metric_filter' in st.session_state and st.session_state.metric_filter:
    if st.button("🔄 Clear Metric Filter", key="clear_metric"):
        st.session_state.metric_filter = None
        st.rerun()

# =============================================================================
# TABS
# =============================================================================
st.markdown("---")

tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12 = st.tabs([
    "🏠 Welcome",
    "🔍 Audit Trail",
    "🚨 All Failures",
    "🗑️ Deletions",
    "🔑 API Keys",
    "🛡️ Security",
    "📊 Details",
    "📈 Analytics",
    "⏰ Time Insights",
    "💾 Export",
    "🔔 Security Alerts",
    "🔗 Topic × Identity",
    "👤 Identity Activity"
])

# Pass configuration object to tabs
tab_config = {
    'time_minutes': time_minutes,
    'timezone': selected_tz,
    'hide_internal': hide_internal,
    'hide_authz_noise': hide_authz_noise,
}

with tab0:
    welcome.render(df, tab_config)

with tab1:
    audit_trail.render_tab(df, tab_config)

with tab2:
    failures.render_tab(df, tab_config)

with tab3:
    deletions.render_tab(df, tab_config)

with tab4:
    api_keys.render_tab(df, tab_config)

with tab5:
    security.render_tab(df, tab_config)

with tab6:
    details.render_tab(df, tab_config)

with tab7:
    analytics.render_tab(df, tab_config)

with tab8:
    time_insights.render_tab(df, tab_config)

with tab9:
    export_tab.render_tab(df, tab_config)

with tab10:
    security_alerts.render_tab(df, tab_config)

with tab11:
    topic_identity.render_topic_identity_tab(df)

with tab12:
    identity_activity.render_identity_activity_tab(df)

# =============================================================================
# FOOTER
# =============================================================================
st.markdown("---")

# Keyboard shortcuts help
with st.expander("⌨️ Keyboard Shortcuts"):
    st.markdown("""
    | Key | Action |
    |-----|--------|
    | `R` | Refresh data |
    | `H` | Toggle help |
    | `?` | Show shortcuts |
    """)

st.caption("Confluent AuditLens | Powered by Streamlit & Confluent Kafka")

with st.expander("Runtime Memory"):
    st.json({
        "dataframe": runtime_memory_summary,
        "raw_payload_cache_entries": len(st.session_state.get("auditlens_raw_payloads", {})),
        "raw_payload_cache_max": RAW_PAYLOAD_CACHE_MAX,
        "streamlit_cache": "load_events_from_kafka ttl=15s max_entries=2",
    })

# Keyboard shortcuts JavaScript
st.markdown("""
<script>
document.addEventListener('keydown', function(e) {
    // Only trigger if not typing in an input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if (e.key === 'r' || e.key === 'R') {
        // Find and click refresh button
        const buttons = document.querySelectorAll('button');
        buttons.forEach(btn => {
            if (btn.innerText.includes('Refresh')) btn.click();
        });
    }
});
</script>
""", unsafe_allow_html=True)
