#!/usr/bin/env python3
"""
Audit Log Dashboard v2
=======================
Enhanced dashboard with severity-based color coding, interactive charts,
and filtering by criticality, operation type, and computed fields.

Run: streamlit run dashboard_v2.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import os
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv
from confluent_kafka import Consumer, TopicPartition

# Load environment
load_dotenv('.env')
load_dotenv('.secrets')

# Config
BOOTSTRAP = os.getenv('DEST_BOOTSTRAP')
API_KEY = os.getenv('DEST_API_KEY')
API_SECRET = os.getenv('DEST_API_SECRET')
TOPIC = os.getenv('DEST_TOPIC', 'audit_events_flattened')

# Severity color scheme
SEVERITY_COLORS = {
    'CRITICAL': '#dc3545',  # Red
    'HIGH': '#fd7e14',      # Orange
    'MEDIUM': '#ffc107',    # Yellow
    'LOW': '#28a745',       # Green
}

SEVERITY_BG_COLORS = {
    'CRITICAL': 'rgba(220, 53, 69, 0.2)',
    'HIGH': 'rgba(253, 126, 20, 0.2)',
    'MEDIUM': 'rgba(255, 193, 7, 0.2)',
    'LOW': 'rgba(40, 167, 69, 0.2)',
}

@st.cache_data(ttl=3600)
def load_identity_lookup():
    """Load user and service account mappings from Confluent CLI."""
    lookup = {}

    # Load service accounts
    try:
        result = subprocess.run(
            ['confluent', 'iam', 'service-account', 'list', '-o', 'json'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            for sa in json.loads(result.stdout):
                sa_id = sa.get('id', '')
                name = sa.get('name', '')
                lookup[sa_id] = name
                lookup[f"User:{sa_id}"] = name
    except Exception as e:
        st.sidebar.warning(f"Could not load service accounts: {e}")

    # Load users
    try:
        result = subprocess.run(
            ['confluent', 'iam', 'user', 'list', '-o', 'json'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            for user in json.loads(result.stdout):
                user_id = user.get('id', '')
                name = user.get('name', '') or user.get('email', '')
                email = user.get('email', '')
                display = f"{name} ({email})" if name and email else (name or email or user_id)
                lookup[user_id] = display
                lookup[f"User:{user_id}"] = display
    except Exception as e:
        st.sidebar.warning(f"Could not load users: {e}")

    return lookup

def resolve_principal(principal, lookup):
    """Resolve principal ID to human-readable name."""
    if not principal:
        return principal
    if principal in lookup:
        return lookup[principal]
    if principal.startswith("User:"):
        user_part = principal[5:]
        if user_part in lookup:
            return lookup[user_part]
    return principal

def extract_details(row):
    """Extract additional details from data_json for display."""
    details = []
    data_json = row.get('data_json', '')
    method = row.get('methodName', '')

    if not data_json:
        return ''

    try:
        data = json.loads(data_json) if isinstance(data_json, str) else data_json
        req_data = data.get('request', {}).get('data', {})
        result = data.get('result', {})
        result_data = result.get('data', {})
        cloud_resources = data.get('cloudResources', [])

        # Extract resource ID from cloudResources
        for cr in cloud_resources[:2]:
            resource = cr.get('resource', {})
            rtype = resource.get('type', '')
            rid = resource.get('resourceId', '')
            if rtype and rid:
                short_type = rtype.replace('_', '')[:8]
                details.append(f"{short_type}: {rid}")

        # Common request fields
        for key in ['id', 'name', 'display_name', 'topic']:
            if req_data.get(key) and len(details) < 3:
                details.append(f"{key}: {req_data.get(key)}")

        # Result status
        if result.get('status') and result.get('status') != 'SUCCESS':
            details.append(f"Status: {result.get('status')}")

    except Exception:
        pass

    return ' | '.join(details)

def format_local_time(dt):
    """Format datetime to human-readable local time."""
    if pd.isna(dt):
        return ''
    try:
        local_dt = dt.tz_convert('Asia/Kolkata') if dt.tzinfo else dt
        return local_dt.strftime('%Y-%m-%d %H:%M:%S IST')
    except Exception:
        return str(dt)


def compute_criticality_vectorized(df):
    """Compute criticality level vectorized for performance."""
    method_col = df['methodName'].fillna('')
    result_status = df['resultStatus'].fillna('') if 'resultStatus' in df.columns else pd.Series([''] * len(df), index=df.index)
    granted = df['granted'] if 'granted' in df.columns else pd.Series([None] * len(df), index=df.index)

    # Start with LOW as default
    criticality = pd.Series('LOW', index=df.index)

    # MEDIUM: Modifications (applied first, then overwritten by higher severity)
    is_medium = method_col.str.contains('Update|Alter|Create', case=False, regex=True, na=False)
    criticality = criticality.mask(is_medium, 'MEDIUM')

    # HIGH: Other deletions and security-related operations
    high_patterns = 'APIKey|ApiKey|ServiceAccount|RoleBinding|ClusterLink'
    is_high = (
        method_col.str.contains('Delete', case=False, na=False) |
        method_col.str.contains(high_patterns, case=False, regex=True, na=False)
    )
    criticality = criticality.mask(is_high, 'HIGH')

    # CRITICAL: Important deletions
    critical_patterns = 'DeleteKafkaCluster|DeleteEnvironment|DeleteOrganization|DeleteServiceAccount|DeleteAPIKey|DeleteApiKey|DeleteSchemaRegistry|DeleteKsqlCluster|DeleteConnector|DeleteFlinkStatement|DeleteClusterLink'
    is_critical_delete = method_col.str.contains(critical_patterns, case=False, regex=True, na=False)

    # CRITICAL: Security failures
    is_critical_security = (
        result_status.isin(['UNAUTHENTICATED', 'PERMISSION_DENIED']) |
        (granted == False)
    )

    criticality = criticality.mask(is_critical_delete | is_critical_security, 'CRITICAL')

    return criticality


def compute_operation_flags(df):
    """Compute operation type flags from methodName if they're missing."""
    if 'methodName' not in df.columns:
        return df

    method_col = df['methodName'].fillna('')

    # Compute is_deletion if missing or all None
    if 'is_deletion' not in df.columns or df['is_deletion'].isna().all():
        df['is_deletion'] = method_col.str.contains('Delete', case=False, na=False)

    # Compute is_creation if missing or all None
    if 'is_creation' not in df.columns or df['is_creation'].isna().all():
        df['is_creation'] = method_col.str.contains('Create', case=False, na=False)

    # Compute is_modification if missing or all None
    if 'is_modification' not in df.columns or df['is_modification'].isna().all():
        df['is_modification'] = method_col.str.contains('Update|Alter', case=False, regex=True, na=False)

    # Compute is_security_event if missing or all None
    if 'is_security_event' not in df.columns or df['is_security_event'].isna().all():
        result_status = df['resultStatus'].fillna('') if 'resultStatus' in df.columns else pd.Series([''] * len(df))
        granted = df['granted'] if 'granted' in df.columns else pd.Series([None] * len(df))
        df['is_security_event'] = (
            result_status.isin(['UNAUTHENTICATED', 'PERMISSION_DENIED', 'FAILURE']) |
            (granted == False) |
            method_col.str.contains('Authentication|Authorization|RoleBinding|ACL', case=False, regex=True, na=False)
        )

    # Compute criticality if missing or all None (using vectorized function for speed)
    if 'criticality' not in df.columns or df['criticality'].isna().all():
        df['criticality'] = compute_criticality_vectorized(df)

    return df

# Page config
st.set_page_config(
    page_title="Audit Log Dashboard v2",
    page_icon="🛡️",
    layout="wide"
)

# Custom CSS with severity-based styling
st.markdown("""
<style>
    .stDataFrame { font-size: 12px; }
    .critical-card {
        background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);
        padding: 15px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .high-card {
        background: linear-gradient(135deg, #fd7e14 0%, #e96600 100%);
        padding: 15px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .medium-card {
        background: linear-gradient(135deg, #ffc107 0%, #e0a800 100%);
        padding: 15px;
        border-radius: 10px;
        color: #212529;
        text-align: center;
    }
    .low-card {
        background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%);
        padding: 15px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .metric-value { font-size: 2rem; font-weight: bold; }
    .metric-label { font-size: 0.9rem; opacity: 0.9; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=60)
def fetch_events(hours=None):
    """Fetch events from Kafka topic based on time range.

    Args:
        hours: Number of hours of data to fetch. None means fetch all available.

    Performance optimizations:
    - Reads only from recent offsets (last N messages per partition)
    - Uses hard limit on total events for fast loading
    - Filters by time after reading for accuracy
    """
    consumer = Consumer({
        'bootstrap.servers': BOOTSTRAP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': API_KEY,
        'sasl.password': API_SECRET,
        'group.id': f'dashboard-v2-{datetime.now().timestamp()}',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    })

    metadata = consumer.list_topics(TOPIC, timeout=30)
    if TOPIC not in metadata.topics:
        consumer.close()
        return []

    partition_ids = list(metadata.topics[TOPIC].partitions.keys())

    # Calculate how many messages to read per partition based on time range
    # The topic has high message volume (~250k msgs/partition), so we need larger windows
    # to ensure we capture all events in the requested time range
    if hours is not None:
        if hours <= 1:
            msgs_per_partition = 20000      # ~20k msgs for 1 hour
        elif hours <= 3:
            msgs_per_partition = 50000      # ~50k for 3 hours
        elif hours <= 6:
            msgs_per_partition = 80000      # ~80k for 6 hours
        elif hours <= 12:
            msgs_per_partition = 120000     # ~120k for 12 hours
        elif hours <= 24:
            msgs_per_partition = 200000     # ~200k for 24 hours (covers most of partition)
        else:
            msgs_per_partition = 300000     # ~300k for 7 days
    else:
        msgs_per_partition = 250000         # All available: read most of partition

    partitions = []
    for p in partition_ids:
        tp = TopicPartition(TOPIC, p)
        low, high = consumer.get_watermark_offsets(tp, timeout=30)
        start_offset = max(low, high - msgs_per_partition)
        partitions.append(TopicPartition(TOPIC, p, start_offset))

    consumer.assign(partitions)

    # Calculate cutoff time for filtering
    cutoff_time = None
    if hours is not None:
        cutoff_time = datetime.now(tz=None) - timedelta(hours=hours)

    events = []
    empty_polls = 0
    max_events = 200000  # Limit to ensure we capture events in the time range

    while len(events) < max_events and empty_polls < 20:
        msg = consumer.poll(0.1)  # Faster polling
        if msg is None:
            empty_polls += 1
            continue
        if msg.error():
            empty_polls += 1
            continue

        empty_polls = 0

        try:
            value = msg.value()
            if value and len(value) > 5 and value[0] == 0:
                value = value[5:]
            event = json.loads(value.decode('utf-8'))

            # Filter by time if cutoff specified
            if cutoff_time is not None:
                event_time_str = event.get('time', '')
                if event_time_str:
                    try:
                        event_time = datetime.fromisoformat(event_time_str.replace('Z', '+00:00'))
                        if event_time.tzinfo is not None:
                            cutoff_aware = cutoff_time.replace(tzinfo=event_time.tzinfo)
                        else:
                            cutoff_aware = cutoff_time
                        if event_time < cutoff_aware:
                            continue  # Skip old events
                    except:
                        pass

            events.append(event)
        except:
            pass

    consumer.close()
    return events

def create_severity_pie_chart(df):
    """Create a pie chart showing event distribution by severity."""
    if len(df) == 0 or 'criticality' not in df.columns:
        return None

    severity_counts = df['criticality'].value_counts()
    if len(severity_counts) == 0:
        return None

    fig = px.pie(
        values=severity_counts.values.tolist(),
        names=severity_counts.index.tolist(),
        color=severity_counts.index.tolist(),
        color_discrete_map=SEVERITY_COLORS,
        title='Events by Severity'
    )
    fig.update_traces(textposition='inside', textinfo='percent+label')
    fig.update_layout(showlegend=True, height=350)
    return fig

def create_operations_bar_chart(df):
    """Create a bar chart showing operation types."""
    if len(df) == 0:
        return None

    op_counts = {
        'Deletions': int(df['is_deletion'].sum()) if 'is_deletion' in df.columns else 0,
        'Creations': int(df['is_creation'].sum()) if 'is_creation' in df.columns else 0,
        'Modifications': int(df['is_modification'].sum()) if 'is_modification' in df.columns else 0,
        'Security Events': int(df['is_security_event'].sum()) if 'is_security_event' in df.columns else 0,
    }

    # If all counts are 0, return None
    if sum(op_counts.values()) == 0:
        return None

    fig = px.bar(
        x=list(op_counts.keys()),
        y=list(op_counts.values()),
        color=list(op_counts.keys()),
        color_discrete_map={
            'Deletions': '#dc3545',
            'Creations': '#28a745',
            'Modifications': '#17a2b8',
            'Security Events': '#fd7e14',
        },
        title='Event Types'
    )
    fig.update_layout(showlegend=False, height=350, xaxis_title='', yaxis_title='Count')
    return fig

def create_timeline_chart(df):
    """Create a timeline chart with severity coloring."""
    if 'time' not in df.columns or len(df) == 0:
        return None

    df_time = df.copy()
    df_time['hour'] = df_time['time'].dt.floor('h')

    if 'criticality' in df.columns:
        hourly = df_time.groupby(['hour', 'criticality']).size().reset_index(name='count')
        fig = px.area(
            hourly,
            x='hour',
            y='count',
            color='criticality',
            color_discrete_map=SEVERITY_COLORS,
            title='Events Over Time by Severity'
        )
    else:
        hourly = df_time.groupby('hour').size().reset_index(name='count')
        fig = px.line(
            hourly,
            x='hour',
            y='count',
            title='Events Over Time'
        )

    fig.update_layout(height=350, xaxis_title='Time', yaxis_title='Event Count')
    return fig

def create_top_principals_chart(df):
    """Create a horizontal bar chart of top principals."""
    if len(df) == 0:
        return None

    if 'principal_name' in df.columns:
        top = df['principal_name'].value_counts().head(10)
    elif 'principal' in df.columns:
        top = df['principal'].value_counts().head(10)
    else:
        return None

    if len(top) == 0:
        return None

    fig = px.bar(
        x=top.values.tolist(),
        y=top.index.tolist(),
        orientation='h',
        title='Top 10 Principals',
        color=top.values.tolist(),
        color_continuous_scale='Blues'
    )
    fig.update_layout(
        height=350,
        xaxis_title='Event Count',
        yaxis_title='',
        showlegend=False,
        coloraxis_showscale=False
    )
    return fig

def main():
    st.title("🛡️ Confluent Cloud Audit Log Dashboard v2")
    st.caption("Enhanced with severity classification and operation type filtering")

    # Sidebar
    st.sidebar.header("🎛️ Filters")

    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()

    # Time range selection (primary filter)
    st.sidebar.subheader("⏰ Time Range")
    time_range = st.sidebar.radio(
        "Show events from",
        options=['Last 1 hour', 'Last 3 hours', 'Last 6 hours', 'Last 12 hours', 'Last 24 hours', 'Last 7 days', 'All available'],
        index=3,  # Default to last 12 hours
        help="Select time range to load from Kafka. Longer ranges take more time to load."
    )

    # Map time range to hours
    time_range_hours = {
        'Last 1 hour': 1,
        'Last 3 hours': 3,
        'Last 6 hours': 6,
        'Last 12 hours': 12,
        'Last 24 hours': 24,
        'Last 7 days': 168,
        'All available': None
    }
    hours = time_range_hours[time_range]

    display_limit = st.sidebar.select_slider(
        "Table display limit",
        options=[100, 250, 500, 1000, 2000],
        value=500,
        help="Maximum rows to show in the events table"
    )

    # Load identity lookup
    with st.spinner("Loading identity mappings..."):
        identity_lookup = load_identity_lookup()
    st.sidebar.success(f"Loaded {len(identity_lookup)} identities")

    # Fetch data
    with st.spinner(f"Loading audit events ({time_range})..."):
        events = fetch_events(hours=hours)

    if not events:
        st.warning("No events found. Check if the forwarder is running.")
        return

    # Convert to DataFrame
    df = pd.DataFrame(events)

    # Compute operation flags (criticality, is_deletion, etc.) if missing from data
    # This handles the case where the forwarder hasn't been updated with the new fields
    df = compute_operation_flags(df)

    # Add resolved principal column
    if 'principal' in df.columns:
        df['principal_name'] = df['principal'].apply(lambda x: resolve_principal(x, identity_lookup))

    # Parse time column
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df = df.sort_values('time', ascending=False)
        df['time_local'] = df['time'].apply(format_local_time)

    # Extract details
    if 'data_json' in df.columns:
        df['details'] = df.apply(extract_details, axis=1)

    # Sidebar filters
    st.sidebar.subheader("🎯 Severity Filter")
    severity_filter = st.sidebar.multiselect(
        "Select severity levels",
        options=['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'],
        default=['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] if 'criticality' in df.columns else []
    )

    if severity_filter and 'criticality' in df.columns:
        df = df[df['criticality'].isin(severity_filter)]

    st.sidebar.subheader("📊 Operation Type")
    op_type = st.sidebar.radio(
        "Filter by operation",
        options=['All', 'Deletions', 'Creations', 'Modifications', 'Security Events'],
        index=0
    )

    if op_type == 'Deletions' and 'is_deletion' in df.columns:
        df = df[df['is_deletion'] == True]
    elif op_type == 'Creations' and 'is_creation' in df.columns:
        df = df[df['is_creation'] == True]
    elif op_type == 'Modifications' and 'is_modification' in df.columns:
        df = df[df['is_modification'] == True]
    elif op_type == 'Security Events' and 'is_security_event' in df.columns:
        df = df[df['is_security_event'] == True]

    # Method filter
    if 'methodName' in df.columns:
        methods = ['All'] + sorted(df['methodName'].dropna().unique().tolist())
        method_filter = st.sidebar.selectbox("Method", methods)
        if method_filter != "All":
            df = df[df['methodName'] == method_filter]

    # Search
    search = st.sidebar.text_input("🔎 Search")
    if search:
        mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
        df = df[mask]

    # Severity summary cards
    st.subheader("📊 Severity Summary")
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        critical_count = len(df[df['criticality'] == 'CRITICAL']) if 'criticality' in df.columns else 0
        st.markdown(f"""
        <div class="critical-card">
            <div class="metric-value">{critical_count:,}</div>
            <div class="metric-label">CRITICAL</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        high_count = len(df[df['criticality'] == 'HIGH']) if 'criticality' in df.columns else 0
        st.markdown(f"""
        <div class="high-card">
            <div class="metric-value">{high_count:,}</div>
            <div class="metric-label">HIGH</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        medium_count = len(df[df['criticality'] == 'MEDIUM']) if 'criticality' in df.columns else 0
        st.markdown(f"""
        <div class="medium-card">
            <div class="metric-value">{medium_count:,}</div>
            <div class="metric-label">MEDIUM</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        low_count = len(df[df['criticality'] == 'LOW']) if 'criticality' in df.columns else 0
        st.markdown(f"""
        <div class="low-card">
            <div class="metric-value">{low_count:,}</div>
            <div class="metric-label">LOW</div>
        </div>
        """, unsafe_allow_html=True)

    with col5:
        total = len(df)
        st.metric("📊 Total Events", f"{total:,}")

    st.divider()

    # Charts row
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        pie_chart = create_severity_pie_chart(df)
        if pie_chart:
            st.plotly_chart(pie_chart, use_container_width=True)

    with chart_col2:
        bar_chart = create_operations_bar_chart(df)
        if bar_chart:
            st.plotly_chart(bar_chart, use_container_width=True)

    chart_col3, chart_col4 = st.columns(2)

    with chart_col3:
        timeline = create_timeline_chart(df)
        if timeline:
            st.plotly_chart(timeline, use_container_width=True)

    with chart_col4:
        principals_chart = create_top_principals_chart(df)
        if principals_chart:
            st.plotly_chart(principals_chart, use_container_width=True)

    st.divider()

    # Tabs
    tab1, tab2, tab3 = st.tabs(["📋 Events Table", "🔍 Critical Events", "📊 Raw Data"])

    with tab1:
        # Display columns
        display_cols = ['time_local', 'criticality', 'principal_name', 'methodName', 'details', 'granted']
        available_cols = [c for c in display_cols if c in df.columns]

        if available_cols:
            display_df = df[available_cols].head(display_limit)

            def style_row(row):
                criticality = row.get('criticality', 'LOW')
                bg_color = SEVERITY_BG_COLORS.get(criticality, '')
                return [f'background-color: {bg_color}'] * len(row)

            if 'criticality' in display_df.columns:
                styled_df = display_df.style.apply(style_row, axis=1)
                st.dataframe(styled_df, use_container_width=True, height=600)
            else:
                st.dataframe(display_df, use_container_width=True, height=600)
        else:
            st.dataframe(df.head(display_limit), use_container_width=True, height=600)

    with tab2:
        st.subheader("🚨 Critical and High Severity Events")
        if 'criticality' in df.columns:
            critical_df = df[df['criticality'].isin(['CRITICAL', 'HIGH'])]
            if len(critical_df) > 0:
                display_cols = ['time_local', 'criticality', 'principal_name', 'methodName', 'details']
                available_cols = [c for c in display_cols if c in critical_df.columns]
                st.dataframe(critical_df[available_cols].head(200), use_container_width=True, height=400)
            else:
                st.success("No critical or high severity events found!")
        else:
            st.info("Criticality field not available. Run the updated forwarder to enable severity classification.")

    with tab3:
        st.subheader("Raw Event Data")
        if len(df) > 0:
            selected_idx = st.selectbox("Select event", range(min(100, len(df))))
            st.json(df.iloc[selected_idx].to_dict())

if __name__ == "__main__":
    main()
