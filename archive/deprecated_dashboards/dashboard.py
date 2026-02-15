#!/usr/bin/env python3
"""
Audit Log Dashboard
====================
A simple web UI to query and visualize Confluent Cloud audit events.

Run: streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
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
                # Map various ID formats
                lookup[sa_id] = name  # sa-xxxxx -> name
                lookup[f"User:{sa_id}"] = name  # User:sa-xxxxx -> name
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
                # Map various ID formats
                lookup[user_id] = display  # u-xxxxx -> name (email)
                lookup[f"User:{user_id}"] = display  # User:u-xxxxx -> name (email)
    except Exception as e:
        st.sidebar.warning(f"Could not load users: {e}")

    return lookup

def resolve_principal(principal, lookup):
    """Resolve principal ID to human-readable name."""
    if not principal:
        return principal

    # Direct lookup
    if principal in lookup:
        return lookup[principal]

    # Try extracting ID from "User:xxxxx" format
    if principal.startswith("User:"):
        user_part = principal[5:]
        if user_part in lookup:
            return lookup[user_part]
        # Numeric user ID (e.g., User:1389855) - look for matching u-xxxxx
        if user_part.isdigit():
            return principal  # Can't resolve numeric IDs without additional mapping

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

        # === API Key Operations ===
        if 'APIKey' in method or 'ApiKey' in method:
            # Look for API_KEY in cloudResources
            for cr in cloud_resources:
                resource = cr.get('resource', {})
                if resource.get('type') == 'API_KEY':
                    details.append(f"Key: {resource.get('resourceId', 'N/A')}")
                    break
            # Check request.data for key details
            if req_data.get('id') and 'Key:' not in ' '.join(details):
                details.append(f"Key: {req_data.get('id')}")
            # Check spec for description
            spec = req_data.get('spec', {})
            if spec.get('description'):
                details.append(f"Desc: {spec.get('description')}")

        # === Kafka Topic Operations ===
        elif 'CreateTopics' in method or 'DeleteTopics' in method:
            topic_name = None
            for cr in cloud_resources:
                resource = cr.get('resource', {})
                if resource.get('type') == 'TOPIC':
                    topic_name = resource.get('resourceId', 'N/A')
                    break
            if not topic_name and req_data.get('name'):
                topic_name = req_data.get('name')
            if topic_name:
                details.append(f"Topic: {topic_name}")
            if req_data.get('numPartitions'):
                details.append(f"Partitions: {int(req_data.get('numPartitions'))}")

        # === Kafka Produce/Fetch Operations ===
        elif 'Produce' in method or 'Fetch' in method:
            topic_name = None
            for cr in cloud_resources:
                resource = cr.get('resource', {})
                if resource.get('type') == 'TOPIC':
                    topic_name = resource.get('resourceId', 'N/A')
                    break
            if not topic_name and req_data.get('topic'):
                topic_name = req_data.get('topic')
            if topic_name:
                details.append(f"Topic: {topic_name}")
            if req_data.get('partition') is not None:
                details.append(f"Part: {int(req_data.get('partition'))}")
            if result_data.get('errorCode') and result_data.get('errorCode') != 0:
                details.append(f"Error: {result_data.get('errorType', result_data.get('errorCode'))}")

        # === Flink Operations ===
        elif 'Statement' in method or 'Flink' in method.lower():
            for cr in cloud_resources:
                resource = cr.get('resource', {})
                if resource.get('type') == 'STATEMENT':
                    details.append(f"Statement: {resource.get('resourceId', 'N/A')}")
                elif resource.get('type') == 'COMPUTE_POOL':
                    details.append(f"Pool: {resource.get('resourceId', 'N/A')}")
            if req_data.get('statement_name'):
                details.append(f"Name: {req_data.get('statement_name')}")

        # === Schema Registry Operations ===
        elif 'schema-registry' in method.lower() or 'Schema' in method or 'Subject' in method:
            for cr in cloud_resources:
                resource = cr.get('resource', {})
                if resource.get('type') == 'SCHEMA_REGISTRY':
                    details.append(f"SR: {resource.get('resourceId', 'N/A')}")
                    break

        # === ksqlDB Operations ===
        elif 'ksql' in method.lower() or 'KSQL' in method:
            for cr in cloud_resources:
                resource = cr.get('resource', {})
                if resource.get('type') in ('KSQL', 'KSQL_CLUSTER'):
                    details.append(f"ksqlDB: {resource.get('resourceId', 'N/A')}")
                    break

        # === Connect Operations ===
        elif 'Connect' in method or 'Connector' in method:
            for cr in cloud_resources:
                resource = cr.get('resource', {})
                if resource.get('type') == 'CLOUD_CLUSTER':
                    details.append(f"Cluster: {resource.get('resourceId', 'N/A')}")
                    break

        # === SignIn Events ===
        elif method == 'SignIn':
            if result_data.get('assigned_principals'):
                principals = result_data.get('assigned_principals', [])
                if principals and len(principals) > 0:
                    details.append(f"Principals: {len(principals)}")

        # === Authorization Events ===
        elif 'Authorize' in method:
            auth_info = data.get('authorizationInfo', [])
            if auth_info and len(auth_info) > 0:
                first_auth = auth_info[0] if isinstance(auth_info, list) else auth_info
                if isinstance(first_auth, dict):
                    granted = first_auth.get('granted')
                    operation = first_auth.get('operation', '')
                    if operation:
                        details.append(f"Op: {operation}")
                    if granted is False:
                        details.append("DENIED")

        # === Environment/Cluster Operations ===
        elif 'Environment' in method or 'Cluster' in method:
            for cr in cloud_resources:
                resource = cr.get('resource', {})
                rtype = resource.get('type', '')
                rid = resource.get('resourceId', '')
                if rtype in ('ENVIRONMENT', 'CLOUD_CLUSTER', 'KAFKA_CLUSTER') and rid:
                    details.append(f"{rtype[:3]}: {rid}")
                    break

        # === Extract resource types for any remaining methods ===
        if not details:
            for cr in cloud_resources[:2]:  # Limit to first 2 resources
                resource = cr.get('resource', {})
                rtype = resource.get('type', '')
                rid = resource.get('resourceId', '')
                if rtype and rid:
                    short_type = rtype.replace('_', '')[:6]
                    details.append(f"{short_type}: {rid}")

        # === Common fields for all events ===
        # Client IP
        client_addr = data.get('clientAddress', data.get('requestMetadata', {}).get('clientAddress', []))
        if client_addr and isinstance(client_addr, list) and len(client_addr) > 0:
            ip = client_addr[0].get('ip', '')
            if ip:
                details.append(f"IP: {ip}")

        # Result status (only if not SUCCESS to keep output cleaner)
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
        # Convert to local timezone
        local_dt = dt.tz_convert('Asia/Kolkata') if dt.tzinfo else dt
        return local_dt.strftime('%Y-%m-%d %H:%M:%S IST')
    except Exception:
        return str(dt)

# Page config
st.set_page_config(
    page_title="Audit Log Dashboard",
    page_icon="🔍",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .stDataFrame { font-size: 12px; }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .success { color: #00c853; }
    .danger { color: #ff5252; }
    .warning { color: #ffc107; }
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_consumer():
    """Create Kafka consumer."""
    return Consumer({
        'bootstrap.servers': BOOTSTRAP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': API_KEY,
        'sasl.password': API_SECRET,
        'group.id': f'dashboard-{datetime.now().timestamp()}',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    })

def deep_search_events(search_term, max_events=100000):
    """Search ALL events in the topic for rare events."""
    consumer = Consumer({
        'bootstrap.servers': BOOTSTRAP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': API_KEY,
        'sasl.password': API_SECRET,
        'group.id': f'deep-search-{datetime.now().timestamp()}',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    })

    metadata = consumer.list_topics(TOPIC, timeout=30)
    if TOPIC not in metadata.topics:
        consumer.close()
        return []

    partition_ids = list(metadata.topics[TOPIC].partitions.keys())

    # Start from beginning of each partition
    partitions = []
    for p in partition_ids:
        tp = TopicPartition(TOPIC, p)
        low, high = consumer.get_watermark_offsets(tp, timeout=30)
        partitions.append(TopicPartition(TOPIC, p, low))

    consumer.assign(partitions)

    found = []
    count = 0
    empty_polls = 0
    search_lower = search_term.lower()

    while count < max_events and empty_polls < 50:
        msg = consumer.poll(0.3)
        if msg is None:
            empty_polls += 1
            continue
        if msg.error():
            empty_polls += 1
            continue

        empty_polls = 0
        count += 1

        try:
            value = msg.value()
            if value and len(value) > 5 and value[0] == 0:
                value = value[5:]
            event = json.loads(value.decode('utf-8'))

            # Search in method name and other fields
            event_str = json.dumps(event).lower()
            if search_lower in event_str:
                found.append(event)
        except:
            pass

    consumer.close()
    return found

# Important methods that customers care about (Create, Delete, Alter operations)
IMPORTANT_METHODS = {
    'CreateAPIKey', 'DeleteAPIKey', 'GetAPIKey', 'GetAPIKeys',
    'CreateKafkaCluster', 'DeleteKafkaCluster', 'UpdateKafkaCluster',
    'CreateKafkaTopic', 'DeleteKafkaTopic', 'kafka.CreateTopics', 'kafka.DeleteTopics',
    'CreateServiceAccount', 'DeleteServiceAccount', 'UpdateServiceAccount',
    'CreateEnvironment', 'DeleteEnvironment', 'UpdateEnvironment',
    'CreateNetwork', 'DeleteNetwork',
    'CreateConnector', 'DeleteConnector', 'UpdateConnector',
    'CreateSchema', 'DeleteSchema',
    'CreateRoleBinding', 'DeleteRoleBinding',
    'GrantRoleResourcesForPrincipal', 'UnbindAllRolesForPrincipal',
    'CreateStatement', 'DeleteStatement', 'UpdateStatement',
    'CreateComputePool', 'DeleteComputePool',
    'CreateKSQLCluster', 'DeleteKSQLCluster',
    'SignIn',  # Login events are important for security
}

@st.cache_data(ttl=60)
def fetch_events(max_events=100000):
    """Fetch ALL events from Kafka topic, prioritizing important events."""
    consumer = Consumer({
        'bootstrap.servers': BOOTSTRAP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': API_KEY,
        'sasl.password': API_SECRET,
        'group.id': f'dashboard-fetch-{datetime.now().timestamp()}',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    })

    metadata = consumer.list_topics(TOPIC, timeout=30)
    if TOPIC not in metadata.topics:
        consumer.close()
        return []

    partition_ids = list(metadata.topics[TOPIC].partitions.keys())

    # Start from BEGINNING to get all important events
    partitions = []
    for p in partition_ids:
        tp = TopicPartition(TOPIC, p)
        low, high = consumer.get_watermark_offsets(tp, timeout=30)
        partitions.append(TopicPartition(TOPIC, p, low))

    consumer.assign(partitions)

    important_events = []  # Create/Delete/Alter events
    other_events = []  # Authentication and other events
    count = 0
    empty_polls = 0

    while count < max_events and empty_polls < 50:
        msg = consumer.poll(0.3)
        if msg is None:
            empty_polls += 1
            continue
        if msg.error():
            empty_polls += 1
            continue

        empty_polls = 0
        count += 1

        try:
            value = msg.value()
            if value and len(value) > 5 and value[0] == 0:
                value = value[5:]  # Skip schema registry header
            event = json.loads(value.decode('utf-8'))

            method = event.get('methodName', '')

            # Prioritize important events
            if method in IMPORTANT_METHODS or 'Create' in method or 'Delete' in method or 'Update' in method:
                important_events.append(event)
            elif len(other_events) < 5000:  # Limit noise events
                other_events.append(event)
        except:
            pass

    consumer.close()

    # Return important events first, then recent other events
    return important_events + other_events[-5000:]

def main():
    st.title("🔍 Confluent Cloud Audit Log Dashboard")

    # Sidebar filters
    st.sidebar.header("🎛️ Filters")

    # Refresh button
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()

    # Load identity lookup
    with st.spinner("Loading identity mappings..."):
        identity_lookup = load_identity_lookup()
    st.sidebar.success(f"Loaded {len(identity_lookup)} identities")

    # Fetch data
    with st.spinner("Loading audit events..."):
        events = fetch_events()

    if not events:
        st.warning("No events found in topic. The topic may be empty or there may be a connection issue.")
        st.info("Try clicking 'Refresh Data' or check if the forwarder is running.")
        return

    # Convert to DataFrame
    df = pd.DataFrame(events)

    # Add resolved principal column
    if 'principal' in df.columns:
        df['principal_name'] = df['principal'].apply(lambda x: resolve_principal(x, identity_lookup))

    # Parse time column and create local time display
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df = df.sort_values('time', ascending=False)
        df['time_local'] = df['time'].apply(format_local_time)

    # Extract additional details from data_json
    if 'data_json' in df.columns:
        df['details'] = df.apply(extract_details, axis=1)

    # Sidebar filters
    st.sidebar.subheader("Time Range")
    time_filter = st.sidebar.selectbox(
        "Select time range",
        ["All", "Last 1 hour", "Last 6 hours", "Last 24 hours", "Last 7 days"]
    )

    # Apply time filter first (affects what methods/principals appear in dropdowns)
    if time_filter != "All" and 'time' in df.columns:
        now = datetime.now(df['time'].dt.tz)
        if time_filter == "Last 1 hour":
            df = df[df['time'] > now - timedelta(hours=1)]
        elif time_filter == "Last 6 hours":
            df = df[df['time'] > now - timedelta(hours=6)]
        elif time_filter == "Last 24 hours":
            df = df[df['time'] > now - timedelta(hours=24)]
        elif time_filter == "Last 7 days":
            df = df[df['time'] > now - timedelta(days=7)]

    # Method filter - now shows only methods present in the time-filtered data
    if 'methodName' in df.columns:
        methods = ['All'] + sorted(df['methodName'].dropna().unique().tolist())
        method_filter = st.sidebar.selectbox("Method", methods, help="Filtered by time range")
        if method_filter != "All":
            df = df[df['methodName'] == method_filter]

    # Principal filter - now shows only principals present in the time-filtered data
    if 'principal' in df.columns:
        principals = ['All'] + sorted(df['principal'].dropna().unique().tolist())[:50]
        principal_filter = st.sidebar.selectbox("Principal", principals, help="Filtered by time range (max 50)")
        if principal_filter != "All":
            df = df[df['principal'] == principal_filter]

    # Search box
    search = st.sidebar.text_input("🔎 Search (resource, method, principal)")
    if search:
        mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
        df = df[mask]

    # Deep search for rare events
    st.sidebar.divider()
    st.sidebar.subheader("🔬 Deep Search")
    deep_search = st.sidebar.text_input("Search ALL events (slower)", key="deep_search",
                                         help="Search entire topic history for rare events like DeleteAPIKey")
    if deep_search and st.sidebar.button("🔍 Search All"):
        with st.spinner(f"Searching all events for '{deep_search}'..."):
            deep_results = deep_search_events(deep_search, max_events=100000)
            if deep_results:
                st.sidebar.success(f"Found {len(deep_results)} matching events!")
                # Replace df with deep search results
                df = pd.DataFrame(deep_results)
                if 'principal' in df.columns:
                    df['principal_name'] = df['principal'].apply(lambda x: resolve_principal(x, identity_lookup))
                if 'time' in df.columns:
                    df['time'] = pd.to_datetime(df['time'], errors='coerce')
                    df = df.sort_values('time', ascending=False)
                    df['time_local'] = df['time'].apply(format_local_time)
                if 'data_json' in df.columns:
                    df['details'] = df.apply(extract_details, axis=1)
            else:
                st.sidebar.warning(f"No events found matching '{deep_search}'")

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("📊 Total Events", f"{len(df):,}")

    with col2:
        if 'methodName' in df.columns:
            unique_methods = df['methodName'].nunique()
            st.metric("🔧 Unique Methods", unique_methods)

    with col3:
        if 'principal' in df.columns:
            unique_principals = df['principal'].nunique()
            st.metric("👤 Unique Principals", unique_principals)

    with col4:
        if 'granted' in df.columns:
            denied = len(df[df['granted'] == False])
            st.metric("🚫 Access Denied", denied, delta_color="inverse")

    st.divider()

    # Quick filters - Customer-focused categories (using session_state for persistence)
    st.subheader("⚡ Quick Filters (What customers care about)")

    # Initialize quick filter state
    if 'quick_filter' not in st.session_state:
        st.session_state.quick_filter = None

    qcol1, qcol2, qcol3, qcol4, qcol5, qcol6, qcol7 = st.columns(7)

    with qcol1:
        if st.button("🗑️ Deletions", help="Who deleted what?",
                     type="primary" if st.session_state.quick_filter == 'delete' else "secondary"):
            st.session_state.quick_filter = 'delete' if st.session_state.quick_filter != 'delete' else None
            st.rerun()
    with qcol2:
        if st.button("➕ Creations", help="Who created what?",
                     type="primary" if st.session_state.quick_filter == 'create' else "secondary"):
            st.session_state.quick_filter = 'create' if st.session_state.quick_filter != 'create' else None
            st.rerun()
    with qcol3:
        if st.button("✏️ Updates", help="Who changed what?",
                     type="primary" if st.session_state.quick_filter == 'update' else "secondary"):
            st.session_state.quick_filter = 'update' if st.session_state.quick_filter != 'update' else None
            st.rerun()
    with qcol4:
        if st.button("🔑 API Keys", help="API key operations",
                     type="primary" if st.session_state.quick_filter == 'apikey' else "secondary"):
            st.session_state.quick_filter = 'apikey' if st.session_state.quick_filter != 'apikey' else None
            st.rerun()
    with qcol5:
        if st.button("👤 Users/SA", help="User and Service Account changes",
                     type="primary" if st.session_state.quick_filter == 'users' else "secondary"):
            st.session_state.quick_filter = 'users' if st.session_state.quick_filter != 'users' else None
            st.rerun()
    with qcol6:
        if st.button("📋 Topics", help="Topic create/delete",
                     type="primary" if st.session_state.quick_filter == 'topics' else "secondary"):
            st.session_state.quick_filter = 'topics' if st.session_state.quick_filter != 'topics' else None
            st.rerun()
    with qcol7:
        if st.session_state.quick_filter:
            if st.button("❌ Clear", help="Clear quick filter"):
                st.session_state.quick_filter = None
                st.rerun()

    # Apply quick filter
    if st.session_state.quick_filter == 'delete':
        df = df[df['methodName'].str.contains('Delete', case=False, na=False)]
        st.info(f"Showing {len(df)} deletion events")
    elif st.session_state.quick_filter == 'create':
        df = df[df['methodName'].str.contains('Create', case=False, na=False)]
        st.info(f"Showing {len(df)} creation events")
    elif st.session_state.quick_filter == 'update':
        df = df[df['methodName'].str.contains('Update|Alter|Modify|Grant|Bind', case=False, na=False)]
        st.info(f"Showing {len(df)} update events")
    elif st.session_state.quick_filter == 'apikey':
        df = df[df['methodName'].str.contains('APIKey|ApiKey', case=False, na=False)]
        st.info(f"Showing {len(df)} API key events")
    elif st.session_state.quick_filter == 'users':
        df = df[df['methodName'].str.contains('User|ServiceAccount|SignIn', case=False, na=False)]
        st.info(f"Showing {len(df)} user/service account events")
    elif st.session_state.quick_filter == 'topics':
        df = df[df['methodName'].str.contains('Topic', case=False, na=False)]
        st.info(f"Showing {len(df)} topic events")

    st.divider()

    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["📋 Events Table", "📊 Analytics", "🔍 Raw Data"])

    with tab1:
        # Display columns - use time_local and principal_name, include details
        display_cols = ['time_local', 'principal_name', 'methodName', 'details', 'granted']
        available_cols = [c for c in display_cols if c in df.columns]

        if available_cols:
            display_df = df[available_cols].head(500)

            # Color code granted column
            def highlight_granted(val):
                if val == True:
                    return 'background-color: #c8e6c9'
                elif val == False:
                    return 'background-color: #ffcdd2'
                return ''

            if 'granted' in display_df.columns:
                styled_df = display_df.style.map(highlight_granted, subset=['granted'])
                st.dataframe(styled_df, use_container_width=True, height=600)
            else:
                st.dataframe(display_df, use_container_width=True, height=600)
        else:
            st.dataframe(df.head(500), use_container_width=True, height=600)

    with tab2:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Events by Method")
            if 'methodName' in df.columns:
                method_counts = df['methodName'].value_counts().head(15)
                st.bar_chart(method_counts)

        with col2:
            st.subheader("Events by Principal")
            if 'principal_name' in df.columns:
                principal_counts = df['principal_name'].value_counts().head(15)
                st.bar_chart(principal_counts)
            elif 'principal' in df.columns:
                principal_counts = df['principal'].value_counts().head(15)
                st.bar_chart(principal_counts)

        if 'time' in df.columns and len(df) > 0:
            st.subheader("Events Over Time")
            df_time = df.set_index('time')
            if len(df_time) > 0:
                hourly = df_time.resample('1h').size()
                st.line_chart(hourly)

    with tab3:
        st.subheader("Raw Event Data")
        if len(df) > 0:
            selected_idx = st.selectbox("Select event", range(min(100, len(df))))
            st.json(df.iloc[selected_idx].to_dict())

if __name__ == "__main__":
    main()
