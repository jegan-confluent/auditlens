#!/usr/bin/env python3
"""
Audit Events Dashboard v6 - TableFlow Edition (Optimized)
Uses PyIceberg to query Iceberg tables via Confluent TableFlow REST Catalog.
Computes derived fields (criticality, is_deletion, etc.) in Python.
Synced with audit_forwarder.py classification logic.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import json
import os
import time
import requests
from dotenv import load_dotenv
from confluent_kafka import Consumer, KafkaError

# Load environment
load_dotenv('.env')
load_dotenv('.secrets')

# TableFlow Configuration
TABLEFLOW_CATALOG_URI = os.getenv(
    'TABLEFLOW_CATALOG_URI',
    'https://tableflow.ap-south-1.aws.confluent.cloud/iceberg/catalog/organizations/f5f511c7-d821-48cc-8388-c96a6f11f12a/environments/env-p9r0mo'
)
CONFLUENT_CLOUD_API_KEY = os.getenv('CONFLUENT_CLOUD_API_KEY')
CONFLUENT_CLOUD_API_SECRET = os.getenv('CONFLUENT_CLOUD_API_SECRET')
ICEBERG_TABLE_NAME = os.getenv('ICEBERG_TABLE_NAME', 'lkc-3q9omo.audit_events_flattened')

# Columns that actually exist in the Iceberg table
ACTUAL_COLUMNS = [
    'id', 'time', 'principal', 'methodName', 'resourceType',
    'granted', 'resultStatus', 'operation', 'clientIp', 'serviceName'
]

# Maximum rows to load (for performance)
MAX_ROWS = 10000

# Forwarder metrics endpoint
FORWARDER_METRICS_URL = os.getenv('FORWARDER_METRICS_URL', 'http://localhost:8003/metrics')

# Kafka Direct Connection (for real-time monitoring)
KAFKA_BOOTSTRAP = os.getenv('DEST_BOOTSTRAP')
KAFKA_API_KEY = os.getenv('DEST_API_KEY')
KAFKA_API_SECRET = os.getenv('DEST_API_SECRET')

# Kafka topic names (for direct consumption)
KAFKA_TOPIC_CRITICAL = os.getenv('AUDIT_TOPIC_CRITICAL', 'audit_events_critical')
KAFKA_TOPIC_HIGH = os.getenv('AUDIT_TOPIC_HIGH', 'audit_events_high')
KAFKA_TOPIC_MEDIUM = os.getenv('AUDIT_TOPIC_MEDIUM', 'audit_events_medium')
KAFKA_TOPIC_LOW = os.getenv('AUDIT_TOPIC_LOW', 'audit_events_low')

# =============================================================================
# CLASSIFICATION LOGIC - Synced with audit_forwarder.py
# =============================================================================

# CRITICAL METHODS - Require immediate attention
CRITICAL_METHODS = frozenset({
    'DeleteKafkaCluster', 'PauseKafkaCluster',
    'DeleteEnvironment', 'DeleteOrganization',
    'kafka.DeleteTopics', 'kafka.DeleteRecords',
    'kafka.DeleteAcls', 'kafka.CreateAcls',
    'DeleteConnector',
    'DeleteKsqldbCluster',
    'DeleteFlinkCompute', 'DeleteFlinkStatement',
    'DeleteSchema', 'DeleteSubject',
    'DeletePrivateLinkAccess', 'DeleteNetworkLinkEndpoint',
    'DeleteNetworkLinkService', 'DeletePeering',
    'DeleteTransitGatewayAttachment',
    'DeleteServiceAccount',
    'DeleteIdentityProvider', 'DeleteIdentityPool',
    'DeleteAuditLogConfig', 'UpdateAuditLogConfig',
    'DeleteByokKey',
    'DeleteTableflow',
})

# HIGH METHODS - Require attention within hours
HIGH_METHODS = frozenset({
    'CreateApiKey', 'DeleteApiKey', 'UpdateApiKey', 'RotateApiKey',
    'CreateServiceAccount', 'UpdateServiceAccount',
    'CreateRoleBinding', 'DeleteRoleBinding', 'UpdateRoleBinding',
    'CreateInvitation', 'DeleteInvitation',
    'CreateUser', 'DeleteUser', 'UpdateUser',
    'CreateIdentityProvider', 'UpdateIdentityProvider',
    'CreateIdentityPool', 'UpdateIdentityPool',
    'CreatePrivateLinkAccess', 'UpdatePrivateLinkAccess',
    'CreateNetworkLinkEndpoint', 'UpdateNetworkLinkEndpoint',
    'CreateNetworkLinkService', 'UpdateNetworkLinkService',
    'CreatePeering', 'UpdatePeering',
    'CreateTransitGatewayAttachment', 'UpdateTransitGatewayAttachment',
    'CreateClusterLink', 'DeleteClusterLink', 'UpdateClusterLink',
    'CreateMirrorTopic', 'DeleteMirrorTopic',
    'CreateConnector', 'UpdateConnector',
    'PauseConnector', 'ResumeConnector',
    'UpdateMode', 'UpdateConfig',
    'kafka.DescribeAcls',
    'CreateByokKey', 'UpdateByokKey',
    'CreateAuditLogConfig',
    'CreateSSOGroupMapping', 'DeleteSSOGroupMapping', 'UpdateSSOGroupMapping',
})

# MEDIUM METHODS - Daily review
MEDIUM_METHODS = frozenset({
    'kafka.AlterConfigs', 'kafka.IncrementalAlterConfigs', 'kafka.DescribeConfigs',
    'UpdateKafkaCluster', 'CreateKafkaCluster', 'ResumeKafkaCluster',
    'CreateEnvironment', 'UpdateEnvironment',
    'kafka.CreateTopics', 'kafka.CreatePartitions',
    'kafka.DeleteGroups', 'kafka.OffsetDelete',
    'CreateKsqldbCluster', 'UpdateKsqldbCluster',
    'CreateFlinkCompute', 'UpdateFlinkCompute',
    'CreateFlinkStatement', 'UpdateFlinkStatement',
    'CreateSchema', 'UpdateSchema', 'CreateSubject',
    'CreateNetwork', 'UpdateNetwork', 'DeleteNetwork',
    'CreateTableflow', 'UpdateTableflow',
    'RestartConnector', 'RestartConnectorTask',
})

# AUTHORIZATION CHECK METHODS - Routine RBAC checks
AUTHORIZATION_CHECK_METHODS = frozenset({
    'mds.Authorize',
    'flink.Authorize',
    'ksql.Authorize',
    'schema-registry.Authorize',
})

# SECURITY FAILURE STATUSES
SECURITY_FAILURE_STATUSES = frozenset({
    'UNAUTHENTICATED',
    'PERMISSION_DENIED',
    'UNAUTHORIZED',
    'FORBIDDEN',
    'INVALID_CREDENTIALS',
})

# Page configuration - MUST be first Streamlit command
st.set_page_config(
    page_title="Audit Events Dashboard",
    page_icon="shield",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Light theme CSS
st.markdown("""
<style>
    .stApp {
        background-color: #f8f9fa;
    }
    .metric-card {
        background: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        text-align: center;
        margin: 5px;
    }
    .metric-value {
        font-size: 2.5em;
        font-weight: bold;
        color: #1a1a2e;
    }
    .metric-label {
        color: #666;
        font-size: 0.9em;
    }
    .critical { color: #dc3545 !important; }
    .high { color: #fd7e14 !important; }
    .medium { color: #ffc107 !important; }
    .low { color: #28a745 !important; }
    .header-title {
        font-size: 2em;
        font-weight: bold;
        color: #1a1a2e;
        margin-bottom: 0;
    }
    .header-subtitle {
        color: #666;
        font-size: 1em;
    }
    div[data-testid="stDataFrame"] {
        background: white;
        padding: 10px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


def compute_criticality(row):
    """
    Compute criticality based on methodName and resultStatus.
    Synced with audit_forwarder.py classification logic.
    """
    method_name = row.get('methodName', '') or ''
    result_status = str(row.get('resultStatus', '') or '').upper()
    granted = row.get('granted')

    # Priority 1: Security failures are always CRITICAL
    if result_status in SECURITY_FAILURE_STATUSES:
        return 'CRITICAL'

    # Priority 2: Denied access handling
    if granted is False:
        if method_name in AUTHORIZATION_CHECK_METHODS:
            # Routine authorization check denial - classify as MEDIUM
            return 'MEDIUM'
        elif method_name in CRITICAL_METHODS or method_name in HIGH_METHODS:
            # Denied access on important methods is CRITICAL
            return 'CRITICAL'
        else:
            # Other denied access - classify as HIGH (not CRITICAL)
            return 'HIGH'

    # Priority 3: Check explicit method classifications
    if method_name in CRITICAL_METHODS:
        return 'CRITICAL'

    if method_name in HIGH_METHODS:
        return 'HIGH'

    if method_name in MEDIUM_METHODS:
        return 'MEDIUM'

    # Priority 4: Pattern-based classification for unknown methods
    method_upper = method_name.upper()

    # Authorization checks (granted=True path) are routine RBAC checks - LOW
    if method_name in AUTHORIZATION_CHECK_METHODS:
        return 'LOW'

    # Check for deletion patterns
    if any(pattern in method_upper for pattern in ['DELETE', 'REMOVE', 'PURGE', 'DROP']):
        return 'HIGH'

    # Check for sensitive method patterns
    sensitive_keywords = ('APIKEY', 'API_KEY', 'SERVICEACCOUNT', 'SERVICE_ACCOUNT',
                         'ACL', 'ROLEBINDING', 'ROLE_BINDING')
    if any(keyword in method_upper for keyword in sensitive_keywords):
        return 'HIGH'

    # Check for creation/modification patterns
    if any(pattern in method_upper for pattern in ['CREATE', 'ADD', 'NEW', 'REGISTER',
                                                    'UPDATE', 'ALTER', 'MODIFY', 'CHANGE', 'SET']):
        return 'MEDIUM'

    # Default to LOW for read operations and unknown methods
    return 'LOW'


@st.cache_data(ttl=10)
def fetch_events_kafka_direct(criticality_filter='All', limit=1000, timeout_seconds=5):
    """
    Fetch events directly from Kafka topics in real-time.
    This is useful for monitoring critical/high events as they happen.
    """
    if not all([KAFKA_BOOTSTRAP, KAFKA_API_KEY, KAFKA_API_SECRET]):
        return pd.DataFrame(), "Kafka credentials not configured in .env"

    try:
        # Determine which topics to consume based on filter
        topics_to_consume = []
        if criticality_filter == 'All':
            topics_to_consume = [KAFKA_TOPIC_CRITICAL, KAFKA_TOPIC_HIGH, KAFKA_TOPIC_MEDIUM]
        elif criticality_filter == 'CRITICAL':
            topics_to_consume = [KAFKA_TOPIC_CRITICAL]
        elif criticality_filter == 'HIGH':
            topics_to_consume = [KAFKA_TOPIC_HIGH]
        elif criticality_filter == 'MEDIUM':
            topics_to_consume = [KAFKA_TOPIC_MEDIUM]
        elif criticality_filter == 'LOW':
            topics_to_consume = [KAFKA_TOPIC_LOW]
        else:
            topics_to_consume = [KAFKA_TOPIC_CRITICAL, KAFKA_TOPIC_HIGH]

        # Consumer configuration
        consumer_conf = {
            'bootstrap.servers': KAFKA_BOOTSTRAP,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanism': 'PLAIN',
            'sasl.username': KAFKA_API_KEY,
            'sasl.password': KAFKA_API_SECRET,
            'group.id': 'dashboard-realtime-viewer',
            'auto.offset.reset': 'latest',  # Start from latest for real-time view
            'enable.auto.commit': False,
        }

        consumer = Consumer(consumer_conf)
        consumer.subscribe(topics_to_consume)

        events = []
        start_time = time.time()

        # Consume messages for up to timeout_seconds
        while len(events) < limit and (time.time() - start_time) < timeout_seconds:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    st.error(f"Kafka error: {msg.error()}")
                continue

            try:
                event = json.loads(msg.value().decode('utf-8'))
                events.append(event)
            except Exception as e:
                continue

        consumer.close()

        if not events:
            return pd.DataFrame(), "No recent events found in Kafka topics"

        # Convert to DataFrame
        df = pd.DataFrame(events)

        # Parse time if exists
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], errors='coerce')
            df = df.sort_values('time', ascending=False)

        # Enrich with computed fields (only if not already present)
        df = enrich_dataframe(df)

        return df, None

    except Exception as e:
        return pd.DataFrame(), f"Kafka connection error: {str(e)}"


def get_forwarder_status():
    """
    Fetch forwarder metrics from http://localhost:8003/metrics.
    Returns status dict with running state and metrics.
    """
    try:
        response = requests.get(FORWARDER_METRICS_URL, timeout=2)
        if response.status_code == 200:
            text = response.text
            # Parse Prometheus metrics
            metrics = {
                'status': 'running',
                'processed': 0,
                'errors': 0,
                'by_criticality': {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0},
                'anomalies': 0,
                'last_check': datetime.now().strftime('%H:%M:%S')
            }

            for line in text.split('\n'):
                if line.startswith('audit_events_processed_total'):
                    metrics['processed'] = int(float(line.split()[-1]))
                elif line.startswith('audit_errors_total'):
                    metrics['errors'] = int(float(line.split()[-1]))
                elif line.startswith('audit_events_by_criticality') and '{criticality="CRITICAL"}' in line:
                    metrics['by_criticality']['CRITICAL'] = int(float(line.split()[-1]))
                elif line.startswith('audit_events_by_criticality') and '{criticality="HIGH"}' in line:
                    metrics['by_criticality']['HIGH'] = int(float(line.split()[-1]))
                elif line.startswith('audit_events_by_criticality') and '{criticality="MEDIUM"}' in line:
                    metrics['by_criticality']['MEDIUM'] = int(float(line.split()[-1]))
                elif line.startswith('audit_events_by_criticality') and '{criticality="LOW"}' in line:
                    metrics['by_criticality']['LOW'] = int(float(line.split()[-1]))
                elif line.startswith('audit_anomalies_detected_total'):
                    metrics['anomalies'] = int(float(line.split()[-1]))

            return metrics
    except Exception as e:
        pass

    return {
        'status': 'offline',
        'processed': 0,
        'errors': 0,
        'by_criticality': {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0},
        'anomalies': 0,
        'last_check': datetime.now().strftime('%H:%M:%S')
    }


def enrich_dataframe(df):
    """Add computed columns to the dataframe."""
    if df.empty:
        return df

    # Compute derived fields
    df['is_deletion'] = df['methodName'].str.contains('Delete', case=False, na=False)
    df['is_creation'] = df['methodName'].str.contains('Create', case=False, na=False)
    df['is_modification'] = df['methodName'].str.contains('Update|Alter', case=False, na=False, regex=True)

    # Compute criticality
    df['criticality'] = df.apply(compute_criticality, axis=1)

    # Security events
    df['is_security_event'] = (
        (df['granted'] == False) |
        (df['resultStatus'].isin(['UNAUTHENTICATED', 'PERMISSION_DENIED', 'FAILURE']))
    )

    return df


@st.cache_resource(ttl=300)
def get_iceberg_catalog():
    """Get cached Iceberg catalog connection."""
    try:
        from pyiceberg.catalog import load_catalog

        catalog = load_catalog(
            "confluent_tableflow",
            type="rest",
            uri=TABLEFLOW_CATALOG_URI,
            credential=f"{CONFLUENT_CLOUD_API_KEY}:{CONFLUENT_CLOUD_API_SECRET}",
        )
        return catalog, None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=30)
def fetch_events_iceberg_fast(hours=1, limit=MAX_ROWS):
    """
    Fetch events from Iceberg table with OPTIMIZED performance.
    Uses column projection and row limits.
    """
    try:
        catalog, error = get_iceberg_catalog()
        if error:
            return pd.DataFrame(), f"Catalog error: {error}"

        table = catalog.load_table(ICEBERG_TABLE_NAME)

        # Build time filter
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.strftime('%Y-%m-%dT%H:%M:%S')

        # Use column projection for faster queries
        scan = table.scan(
            row_filter=f"time >= '{cutoff_str}'",
            selected_fields=tuple(ACTUAL_COLUMNS),
            limit=limit
        )

        df = scan.to_pandas()

        # Parse time column and sort
        if 'time' in df.columns and len(df) > 0:
            df['time'] = pd.to_datetime(df['time'], errors='coerce')
            df = df.sort_values('time', ascending=False)

        # Add computed columns
        df = enrich_dataframe(df)

        return df, None

    except Exception as e:
        return pd.DataFrame(), str(e)


@st.cache_data(ttl=60)
def get_table_stats():
    """Get table row count (cached longer)."""
    try:
        catalog, error = get_iceberg_catalog()
        if error:
            return None, error

        table = catalog.load_table(ICEBERG_TABLE_NAME)
        # Just get a count by scanning with limit 0 - faster
        df = table.scan(selected_fields=('id',)).to_pandas()
        return len(df), None
    except Exception as e:
        return None, str(e)


def render_metrics(df):
    """Render metrics cards."""
    col1, col2, col3, col4, col5 = st.columns(5)

    total = len(df)
    critical = len(df[df['criticality'] == 'CRITICAL']) if 'criticality' in df.columns else 0
    high = len(df[df['criticality'] == 'HIGH']) if 'criticality' in df.columns else 0
    medium = len(df[df['criticality'] == 'MEDIUM']) if 'criticality' in df.columns else 0
    security = len(df[df['is_security_event'] == True]) if 'is_security_event' in df.columns else 0
    deletions = len(df[df['is_deletion'] == True]) if 'is_deletion' in df.columns else 0

    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">{total:,}</div>
            <div class="metric-label">Total Events</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value critical">{critical:,}</div>
            <div class="metric-label">Critical</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value high">{high:,}</div>
            <div class="metric-label">High</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value" style="color: #17a2b8;">{security:,}</div>
            <div class="metric-label">Security Events</div>
        </div>
        """, unsafe_allow_html=True)

    with col5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value" style="color: #6f42c1;">{deletions:,}</div>
            <div class="metric-label">Deletions</div>
        </div>
        """, unsafe_allow_html=True)


def render_criticality_distribution(df):
    """Render criticality distribution chart."""
    import plotly.graph_objects as go

    if 'criticality' not in df.columns or df.empty:
        return

    # Calculate distribution
    dist = df['criticality'].value_counts()
    total = len(df)

    # Ensure all levels are present
    levels = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
    counts = [dist.get(level, 0) for level in levels]
    percentages = [(count / total * 100) if total > 0 else 0 for count in counts]

    # Create bar chart
    fig = go.Figure(data=[
        go.Bar(
            x=levels,
            y=counts,
            text=[f"{p:.1f}%" for p in percentages],
            textposition='auto',
            marker_color=['#dc3545', '#fd7e14', '#ffc107', '#28a745']
        )
    ])

    fig.update_layout(
        title="Classification Distribution (validates forwarder sync)",
        xaxis_title="Criticality Level",
        yaxis_title="Event Count",
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
    )

    st.plotly_chart(fig, use_container_width=True)

    # Show expected vs actual
    st.caption(f"Expected: ~89% LOW, ~10% MEDIUM, ~1% HIGH, <1% CRITICAL")
    st.caption(f"Actual: {percentages[3]:.1f}% LOW, {percentages[2]:.1f}% MEDIUM, {percentages[1]:.1f}% HIGH, {percentages[0]:.2f}% CRITICAL")


def main():
    # Header
    st.markdown("""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <div>
            <div class="header-title">Audit Events Dashboard</div>
            <div class="header-subtitle">TableFlow Edition - Fast Iceberg Queries</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar controls
    with st.sidebar:
        st.markdown("### Data Source")

        # Data source selector
        data_source = st.radio(
            "Choose data source",
            options=['Iceberg Table (Historical)', 'Kafka Direct (Real-time)'],
            index=0,
            help="Iceberg: Query historical data from TableFlow. Kafka: Stream live events from topics."
        )

        use_kafka = data_source.startswith('Kafka')

        st.markdown("---")
        st.markdown("### Query Settings")

        if not use_kafka:
            # Time range - default to 1 hour for speed (Iceberg only)
            time_options = {
                'Last 15 minutes': 0.25,
                'Last 1 hour': 1,
                'Last 4 hours': 4,
                'Last 24 hours': 24,
                'Last 7 days': 168
            }
            selected_time = st.selectbox(
                "Time Range",
                options=list(time_options.keys()),
                index=1  # Default to 1 hour
            )
            hours = time_options[selected_time]
        else:
            hours = None
            st.info("Real-time mode: Showing latest events from Kafka")
            kafka_timeout = st.slider(
                "Fetch Timeout (seconds)",
                min_value=2,
                max_value=10,
                value=5,
                help="How long to wait for new messages"
            )

        # Criticality filter (applied after loading)
        criticality = st.selectbox(
            "Criticality",
            options=['All', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'],
            index=0
        )

        # Row limit
        if not use_kafka:
            row_limit = st.slider(
                "Max Rows",
                min_value=1000,
                max_value=50000,
                value=10000,
                step=1000
            )
        else:
            row_limit = st.slider(
                "Max Events",
                min_value=100,
                max_value=1000,
                value=500,
                step=100,
                help="Maximum events to fetch from Kafka"
            )

        # Auto-refresh toggle
        auto_refresh = st.checkbox("Auto-refresh every 30s", value=False)

        # Refresh button
        if st.button("Refresh Data", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")

        # Forwarder Status Panel
        st.markdown("### Forwarder Status")
        forwarder = get_forwarder_status()

        if forwarder['status'] == 'running':
            st.markdown("🟢 **Status:** Running")
            st.metric("Events Processed", f"{forwarder['processed']:,}")
            st.metric("Errors", forwarder['errors'], delta_color="inverse")
            if forwarder['anomalies'] > 0:
                st.metric("Anomalies Detected", forwarder['anomalies'], delta_color="off")
            st.caption(f"Last check: {forwarder['last_check']}")
        else:
            st.markdown("🔴 **Status:** Offline")
            st.caption("Forwarder not responding")

        st.markdown("---")

        # Table info
        total_rows, err = get_table_stats()
        if total_rows:
            st.info(f"Total rows in table: {total_rows:,}")

        st.markdown(f"""
        **Table:** `{ICEBERG_TABLE_NAME}`
        **Source:** TableFlow REST Catalog
        """)

    # Fetch data based on selected source
    if use_kafka:
        # Kafka Direct Mode
        with st.spinner(f"Fetching real-time events from Kafka..."):
            df, error = fetch_events_kafka_direct(
                criticality_filter=criticality,
                limit=row_limit,
                timeout_seconds=kafka_timeout
            )
    else:
        # Iceberg Table Mode
        with st.spinner(f"Loading events ({selected_time})..."):
            df, error = fetch_events_iceberg_fast(
                hours=hours,
                limit=row_limit
            )

    if error:
        st.error(f"Error loading data: {error}")
        st.stop()

    if df.empty:
        st.warning("No events found for the selected time range.")
        st.stop()

    # Apply criticality filter after loading
    if criticality != 'All':
        df = df[df['criticality'] == criticality]

    # Metrics
    render_metrics(df)

    st.markdown("---")

    # Distribution Chart
    render_criticality_distribution(df)

    st.markdown("---")

    # Tabs for different views
    tab1, tab2, tab3, tab4 = st.tabs(["All Events", "Critical & High", "Deletions", "Anomalies & Security"])

    with tab1:
        st.markdown(f"### All Events ({len(df):,} rows)")

        # Add filters
        col1, col2 = st.columns(2)
        with col1:
            filter_principal = st.text_input("Filter by Principal", "")
        with col2:
            filter_method = st.text_input("Filter by Method", "")

        # Apply filters
        filtered_df = df.copy()
        if filter_principal:
            filtered_df = filtered_df[filtered_df['principal'].str.contains(filter_principal, case=False, na=False)]
        if filter_method:
            filtered_df = filtered_df[filtered_df['methodName'].str.contains(filter_method, case=False, na=False)]

        # Display columns with color coding
        display_cols = ['time', 'principal', 'methodName', 'criticality', 'resourceType', 'resultStatus', 'is_security_event']
        available_cols = [c for c in display_cols if c in filtered_df.columns]

        # Style the dataframe
        def highlight_criticality(row):
            colors = {
                'CRITICAL': 'background-color: #ffebee',
                'HIGH': 'background-color: #fff3e0',
                'MEDIUM': 'background-color: #fffde7',
                'LOW': 'background-color: #f1f8e9'
            }
            if 'criticality' in row:
                return [colors.get(row['criticality'], '')] * len(row)
            return [''] * len(row)

        st.dataframe(
            filtered_df[available_cols].head(500),
            use_container_width=True,
            height=500
        )

        st.caption(f"Showing {len(filtered_df):,} of {len(df):,} events")

    with tab2:
        critical_df = df[df['criticality'].isin(['CRITICAL', 'HIGH'])] if 'criticality' in df.columns else pd.DataFrame()
        st.markdown(f"### Critical & High Events ({len(critical_df):,} rows)")

        if not critical_df.empty:
            display_cols = ['time', 'principal', 'methodName', 'criticality', 'resourceType', 'resultStatus']
            available_cols = [c for c in display_cols if c in critical_df.columns]
            st.dataframe(
                critical_df[available_cols].head(200),
                use_container_width=True,
                height=400
            )
        else:
            st.info("No critical or high severity events in this time range.")

    with tab3:
        delete_df = df[df['is_deletion'] == True] if 'is_deletion' in df.columns else pd.DataFrame()
        st.markdown(f"### Deletion Events ({len(delete_df):,} rows)")

        if not delete_df.empty:
            display_cols = ['time', 'principal', 'methodName', 'resourceType', 'criticality']
            available_cols = [c for c in display_cols if c in delete_df.columns]
            st.dataframe(
                delete_df[available_cols].head(200),
                use_container_width=True,
                height=400
            )
        else:
            st.info("No deletion events in this time range.")

    with tab4:
        st.markdown("### Anomalies & Security Analysis")

        # Auth Failure Analysis
        st.markdown("#### Authentication Failures")
        auth_failures = df[df['resultStatus'].isin(['UNAUTHENTICATED', 'PERMISSION_DENIED', 'FAILURE'])] if 'resultStatus' in df.columns else pd.DataFrame()

        if not auth_failures.empty:
            # Group by principal
            failure_counts = auth_failures.groupby('principal').size().reset_index(name='failure_count')
            failure_counts = failure_counts.sort_values('failure_count', ascending=False)

            # Highlight principals with >10 failures
            st.dataframe(
                failure_counts.head(20),
                use_container_width=True,
                height=200
            )

            # Show recent failures
            st.markdown("#### Recent Auth Failures")
            display_cols = ['time', 'principal', 'methodName', 'resultStatus', 'clientIp']
            available_cols = [c for c in display_cols if c in auth_failures.columns]
            st.dataframe(
                auth_failures[available_cols].head(50),
                use_container_width=True,
                height=300
            )
        else:
            st.info("No authentication failures in this time range.")

        st.markdown("---")

        # Suspicious Activity Detection
        st.markdown("#### Suspicious Activity")

        # Activity spikes (>100 events per principal)
        activity_counts = df.groupby('principal').size().reset_index(name='event_count') if 'principal' in df.columns else pd.DataFrame()
        if not activity_counts.empty:
            suspicious_activity = activity_counts[activity_counts['event_count'] > 100].sort_values('event_count', ascending=False)

            if not suspicious_activity.empty:
                st.markdown("**Principals with >100 events (potential activity spike):**")
                st.dataframe(suspicious_activity.head(10), use_container_width=True, height=200)
            else:
                st.info("No suspicious activity spikes detected.")

        # Multiple IPs per principal
        if 'clientIp' in df.columns and 'principal' in df.columns:
            ip_counts = df.groupby('principal')['clientIp'].nunique().reset_index(name='ip_count')
            multiple_ips = ip_counts[ip_counts['ip_count'] > 3].sort_values('ip_count', ascending=False)

            if not multiple_ips.empty:
                st.markdown("**Principals with >3 distinct IPs:**")
                st.dataframe(multiple_ips.head(10), use_container_width=True, height=200)
            else:
                st.info("No principals with multiple IPs detected.")

    # Footer
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with col2:
        st.caption(f"Showing {len(df):,} events (max {row_limit:,})")
    with col3:
        if use_kafka:
            st.caption("📡 Real-time (Kafka Direct)")
        else:
            st.caption("📊 Historical (Iceberg Table)")

    # Auto-refresh logic
    if auto_refresh:
        time.sleep(30)
        st.rerun()


if __name__ == "__main__":
    main()
