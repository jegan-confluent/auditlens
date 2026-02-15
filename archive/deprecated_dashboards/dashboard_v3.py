#!/usr/bin/env python3
"""
Audit Log Dashboard v6 - TableFlow Edition
===========================================
Uses PyIceberg + Confluent TableFlow REST Catalog for fast SQL-like queries
instead of scanning Kafka topics.

Benefits:
- No Kafka consumer overhead
- Filter pushdown to Parquet (fast)
- SQL-like row filters
- Historical data beyond Kafka retention

Requirements:
    pip install streamlit pandas plotly pyiceberg pyarrow python-dotenv

Environment Variables:
    TABLEFLOW_CATALOG_URI - TableFlow REST catalog endpoint
    CONFLUENT_CLOUD_API_KEY - Cloud API key (not Kafka API key)
    CONFLUENT_CLOUD_API_SECRET - Cloud API secret
    ICEBERG_TABLE_NAME - Full table name (e.g., "default.audit_events_flattened")
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

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
ICEBERG_TABLE_NAME = os.getenv('ICEBERG_TABLE_NAME', 'default.audit_events_flattened')

# Severity configuration
SEVERITY_CONFIG = {
    'CRITICAL': {'color': '#dc2626', 'bg': '#fef2f2', 'border': '#fecaca', 'icon': '🔴'},
    'HIGH': {'color': '#ea580c', 'bg': '#fff7ed', 'border': '#fed7aa', 'icon': '🟠'},
    'MEDIUM': {'color': '#ca8a04', 'bg': '#fefce8', 'border': '#fef08a', 'icon': '🟡'},
    'LOW': {'color': '#16a34a', 'bg': '#f0fdf4', 'border': '#bbf7d0', 'icon': '🟢'},
}
SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

# Quick filter categories
QUICK_FILTERS = {
    'deletions': {'label': '🗑️ Deletions', 'filter': "methodName LIKE '%Delete%'", 'help': 'Who deleted what?'},
    'creations': {'label': '➕ Creations', 'filter': "methodName LIKE '%Create%'", 'help': 'Who created what?'},
    'apikeys': {'label': '🔑 API Keys', 'filter': "methodName LIKE '%APIKey%' OR methodName LIKE '%ApiKey%'", 'help': 'API key operations'},
    'topics': {'label': '📋 Topics', 'filter': "methodName LIKE '%Topic%'", 'help': 'Topic operations'},
    'users': {'label': '👤 Users/SA', 'filter': "methodName LIKE '%User%' OR methodName LIKE '%ServiceAccount%' OR methodName LIKE '%SignIn%'", 'help': 'User operations'},
    'connectors': {'label': '🔌 Connectors', 'filter': "methodName LIKE '%Connector%'", 'help': 'Connector operations'},
    'flink': {'label': '⚡ Flink', 'filter': "methodName LIKE '%Statement%' OR methodName LIKE '%ComputePool%'", 'help': 'Flink operations'},
    'rbac': {'label': '🛡️ RBAC', 'filter': "methodName LIKE '%Role%' OR methodName LIKE '%Acl%' OR methodName LIKE '%Bind%'", 'help': 'Permission changes'},
    'denied': {'label': '🚫 Denied', 'filter': "granted = false", 'help': 'Access denied events'},
}

# Page config
st.set_page_config(
    page_title="Audit Dashboard (TableFlow)",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Modern Light Theme CSS
st.markdown("""
<style>
    .stApp { background: #f8fafc; }
    [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e2e8f0; }
    
    .main-header {
        background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%);
        border-radius: 12px;
        padding: 20px 28px;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(14, 165, 233, 0.25);
    }
    .main-title { font-size: 1.5rem; font-weight: 700; color: white; margin: 0; }
    .main-subtitle { color: rgba(255,255,255,0.9); font-size: 0.85rem; margin-top: 4px; }
    .main-badge {
        display: inline-block;
        background: rgba(255,255,255,0.2);
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.7rem;
        color: white;
        margin-left: 10px;
    }
    
    .metric-card {
        background: white;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        border: 1px solid #f1f5f9;
    }
    .metric-value { font-size: 1.75rem; font-weight: 700; margin: 0; }
    .metric-label { font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px; font-weight: 600; }
    
    .severity-critical { background: #fef2f2; border: 1px solid #fecaca; }
    .severity-high { background: #fff7ed; border: 1px solid #fed7aa; }
    
    .spotlight-section {
        background: white;
        border-radius: 10px;
        padding: 16px;
        margin: 16px 0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        border: 1px solid #f1f5f9;
    }
    .spotlight-title { font-size: 0.9rem; font-weight: 600; color: #334155; margin-bottom: 12px; }
    .spotlight-item { padding: 10px 14px; margin: 6px 0; border-radius: 8px; font-size: 0.85rem; }
    .spotlight-item-critical { background: #fef2f2; border-left: 3px solid #dc2626; }
    .spotlight-item-high { background: #fff7ed; border-left: 3px solid #ea580c; }
    .spotlight-method { font-weight: 600; color: #1e293b; }
    .spotlight-details { color: #64748b; font-size: 0.8rem; margin-top: 2px; }
    
    .info-box { background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 10px 14px; color: #0369a1; font-size: 0.85rem; }
    .warning-box { background: #fefce8; border: 1px solid #fef08a; border-radius: 8px; padding: 10px 14px; color: #a16207; font-size: 0.85rem; }
    .success-box { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 10px 14px; color: #166534; font-size: 0.85rem; }
    
    .stButton > button {
        background: linear-gradient(135deg, #0ea5e9, #6366f1);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #0284c7, #4f46e5);
    }
    
    .stTabs [data-baseweb="tab-list"] { gap: 4px; background: #f1f5f9; border-radius: 8px; padding: 4px; }
    .stTabs [data-baseweb="tab"] { background: transparent; border-radius: 6px; color: #64748b; font-weight: 500; }
    .stTabs [aria-selected="true"] { background: white; color: #0ea5e9; box-shadow: 0 1px 2px rgba(0,0,0,0.08); }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ============================================================================
# PYICEBERG CATALOG CONNECTION
# ============================================================================

@st.cache_resource
def get_iceberg_catalog():
    """Initialize PyIceberg catalog connection to TableFlow."""
    try:
        from pyiceberg.catalog import load_catalog
        
        if not CONFLUENT_CLOUD_API_KEY or not CONFLUENT_CLOUD_API_SECRET:
            return None, "Missing CONFLUENT_CLOUD_API_KEY or CONFLUENT_CLOUD_API_SECRET"
        
        catalog = load_catalog(
            "confluent_tableflow",
            type="rest",
            uri=TABLEFLOW_CATALOG_URI,
            credential=f"{CONFLUENT_CLOUD_API_KEY}:{CONFLUENT_CLOUD_API_SECRET}",
        )
        return catalog, None
    except ImportError:
        return None, "PyIceberg not installed. Run: pip install pyiceberg pyarrow"
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=60)
def fetch_events_iceberg(hours=24, row_filter=None):
    """Fetch events from Iceberg table via TableFlow REST Catalog."""
    catalog, error = get_iceberg_catalog()
    
    if error:
        return None, error
    
    try:
        # Load table
        table = catalog.load_table(ICEBERG_TABLE_NAME)
        
        # Build time filter
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.strftime('%Y-%m-%dT%H:%M:%S')
        
        # Combine filters
        filters = [f"time >= '{cutoff_str}'"]
        if row_filter:
            filters.append(f"({row_filter})")
        
        combined_filter = " AND ".join(filters)
        
        # Scan with filter pushdown
        df = table.scan(
            row_filter=combined_filter
        ).to_pandas()
        
        return df, None
        
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=60)
def fetch_events_with_sql(sql_filter=None, limit=10000):
    """Fetch events with custom SQL-like filter."""
    catalog, error = get_iceberg_catalog()
    
    if error:
        return None, error
    
    try:
        table = catalog.load_table(ICEBERG_TABLE_NAME)
        
        scan = table.scan(row_filter=sql_filter) if sql_filter else table.scan()
        df = scan.to_pandas()
        
        if len(df) > limit:
            df = df.head(limit)
        
        return df, None
        
    except Exception as e:
        return None, str(e)


# ============================================================================
# FALLBACK: KAFKA CONSUMER (if PyIceberg not available)
# ============================================================================

def fetch_events_kafka_fallback(hours=24):
    """Fallback to Kafka consumer if PyIceberg not available."""
    from confluent_kafka import Consumer, TopicPartition
    
    BOOTSTRAP = os.getenv('DEST_BOOTSTRAP')
    API_KEY = os.getenv('DEST_API_KEY')
    API_SECRET = os.getenv('DEST_API_SECRET')
    TOPIC = os.getenv('DEST_TOPIC', 'audit_events_flattened')
    
    consumer = Consumer({
        'bootstrap.servers': BOOTSTRAP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': API_KEY,
        'sasl.password': API_SECRET,
        'group.id': f'dashboard-v6-{datetime.now().timestamp()}',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    })

    metadata = consumer.list_topics(TOPIC, timeout=30)
    if TOPIC not in metadata.topics:
        consumer.close()
        return []

    partition_ids = list(metadata.topics[TOPIC].partitions.keys())
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    partitions_to_seek = [TopicPartition(TOPIC, p, cutoff_ms) for p in partition_ids]
    offsets = consumer.offsets_for_times(partitions_to_seek, timeout=30)

    assigned = []
    for tp in offsets:
        if tp.offset >= 0:
            assigned.append(TopicPartition(TOPIC, tp.partition, tp.offset))
        else:
            low, high = consumer.get_watermark_offsets(TopicPartition(TOPIC, tp.partition), timeout=30)
            assigned.append(TopicPartition(TOPIC, tp.partition, max(low, high - 1000)))

    consumer.assign(assigned)

    events = {}
    empty_batches = 0

    while empty_batches < 5 and len(events) < 100000:
        messages = consumer.consume(num_messages=1000, timeout=1.0)
        if not messages:
            empty_batches += 1
            continue

        empty_batches = 0
        for msg in messages:
            if msg.error():
                continue
            try:
                value = msg.value()
                if value and len(value) > 5 and value[0] == 0:
                    value = value[5:]
                event = json.loads(value.decode('utf-8'))
                event_id = event.get('id', str(len(events)))
                events[event_id] = event
            except:
                pass

    consumer.close()
    return list(events.values())


# ============================================================================
# DATA PROCESSING
# ============================================================================

def extract_resource_details(row):
    """Extract resource details from data_json."""
    data_json = row.get('data_json')
    method_name = row.get('methodName', '')
    resource_name = row.get('resourceName', '')
    
    details = {
        'api_key_id': None, 'topic_name': None, 'cluster_id': None,
        'environment_id': None, 'service_account': None, 'client_ip': None, 'summary': ''
    }
    
    if not data_json:
        return details
    
    try:
        data = json.loads(data_json) if isinstance(data_json, str) else data_json
        summary_parts = []
        
        # Extract from cloudResources
        for cr in data.get('cloudResources', []):
            resource = cr.get('resource', {})
            rtype, rid = resource.get('type', ''), resource.get('resourceId', '')
            
            if rtype == 'API_KEY' and rid:
                details['api_key_id'] = rid
                summary_parts.append(f"🔑 {rid}")
            elif rtype == 'TOPIC' and rid:
                details['topic_name'] = rid
                summary_parts.append(f"📋 {rid}")
            elif rtype == 'SERVICE_ACCOUNT' and rid:
                details['service_account'] = rid
                summary_parts.append(f"👤 {rid}")
            
            for sr in cr.get('scope', {}).get('resources', []):
                if sr.get('type') in ('KAFKA_CLUSTER', 'CLOUD_CLUSTER'):
                    details['cluster_id'] = sr.get('resourceId')
                elif sr.get('type') == 'ENVIRONMENT':
                    details['environment_id'] = sr.get('resourceId')
        
        # Extract from request.data
        req_data = data.get('request', {}).get('data', {})
        if req_data.get('name') and not details['topic_name'] and 'Topic' in method_name:
            details['topic_name'] = req_data.get('name')
            summary_parts.append(f"📋 {req_data.get('name')}")
        
        # Extract topic from resourceName
        if resource_name and not details['topic_name'] and 'topic=' in str(resource_name):
            import re
            match = re.search(r'topic=([^/]+)', str(resource_name))
            if match:
                details['topic_name'] = match.group(1)
                summary_parts.append(f"📋 {match.group(1)}")
        
        # Client IP
        client_addr = data.get('requestMetadata', {}).get('clientAddress', [])
        if client_addr:
            details['client_ip'] = client_addr[0].get('ip', '')
            if details['client_ip']:
                summary_parts.append(f"📍 {details['client_ip']}")
        
        details['summary'] = ' | '.join(summary_parts[:3])
        
    except:
        pass
    
    return details


@st.cache_data(ttl=7200)
def load_identity_lookup():
    """Load user and service account mappings."""
    lookup = {}
    try:
        result = subprocess.run(['confluent', 'iam', 'service-account', 'list', '-o', 'json'],
                                capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            for sa in json.loads(result.stdout):
                lookup[sa.get('id', '')] = sa.get('name', '')
                lookup[f"User:{sa.get('id', '')}"] = sa.get('name', '')
    except: pass

    try:
        result = subprocess.run(['confluent', 'iam', 'user', 'list', '-o', 'json'],
                                capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            for user in json.loads(result.stdout):
                uid = user.get('id', '')
                name = user.get('name', '') or user.get('email', '')
                lookup[uid] = name
                lookup[f"User:{uid}"] = name
    except: pass

    return lookup


def compute_fields(df, identity_lookup):
    """Compute derived fields."""
    if len(df) == 0:
        return df

    method = df['methodName'].fillna('')

    # Criticality
    if 'criticality' in df.columns and not df['criticality'].isna().all():
        df['criticality'] = df['criticality'].fillna('LOW')
    else:
        criticality = pd.Series('LOW', index=df.index)
        result_status = df['resultStatus'].fillna('') if 'resultStatus' in df.columns else pd.Series([''] * len(df))
        granted = df['granted'] if 'granted' in df.columns else pd.Series([None] * len(df))
        
        criticality = criticality.mask(method.str.contains('Update|Alter|Create', case=False, regex=True, na=False), 'MEDIUM')
        criticality = criticality.mask(method.str.contains('Delete|APIKey|ServiceAccount', case=False, regex=True, na=False), 'HIGH')
        criticality = criticality.mask(
            method.str.contains('DeleteKafkaCluster|DeleteEnvironment', case=False, regex=True, na=False) |
            result_status.isin(['UNAUTHENTICATED', 'PERMISSION_DENIED']) |
            (granted == False),
            'CRITICAL'
        )
        df['criticality'] = criticality

    # Flags
    df['is_deletion'] = method.str.contains('Delete', case=False, na=False)
    df['is_creation'] = method.str.contains('Create', case=False, na=False)
    df['severity_icon'] = df['criticality'].map(lambda x: SEVERITY_CONFIG.get(x, {}).get('icon', ''))

    # Time
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df = df.sort_values('time', ascending=False)
        df['time_display'] = df['time'].dt.tz_convert('Asia/Kolkata').dt.strftime('%Y-%m-%d %H:%M:%S')

    # Principals
    if 'principal' in df.columns:
        df['user'] = df['principal'].apply(
            lambda x: identity_lookup.get(x, identity_lookup.get(str(x).replace('User:', ''), x)) if x else ''
        )

    # Resource details
    if 'data_json' in df.columns:
        extracted = df.apply(extract_resource_details, axis=1)
        extracted_df = pd.DataFrame(extracted.tolist())
        for col in extracted_df.columns:
            df[col] = extracted_df[col]

    # Granted display
    if 'granted' in df.columns:
        df['granted_display'] = df['granted'].apply(
            lambda x: '✅' if x == True else ('❌' if x == False else '—')
        )

    return df


# ============================================================================
# UI COMPONENTS
# ============================================================================

def render_metric_card(value, label, color='#6366f1', bg_class=''):
    return f"""
    <div class="metric-card {bg_class}">
        <div class="metric-value" style="color: {color};">{value:,}</div>
        <div class="metric-label">{label}</div>
    </div>
    """


def render_spotlight(df):
    """Render critical events spotlight."""
    critical_df = df[df['criticality'].isin(['CRITICAL', 'HIGH'])].head(5)
    if len(critical_df) == 0:
        return
    
    html_parts = ['<div class="spotlight-section">', '<div class="spotlight-title">🚨 Recent Critical Events</div>']
    
    for _, event in critical_df.iterrows():
        sev = event.get('criticality', 'HIGH')
        sev_class = 'spotlight-item-critical' if sev == 'CRITICAL' else 'spotlight-item-high'
        icon = SEVERITY_CONFIG.get(sev, {}).get('icon', '🟠')
        
        html_parts.append(f'''
        <div class="spotlight-item {sev_class}">
            <span class="spotlight-method">{icon} {event.get('methodName', 'Unknown')}</span>
            <div class="spotlight-details">
                👤 {event.get('user', event.get('principal', 'Unknown'))} • 
                🕐 {event.get('time_display', '')}
                {f" • {event.get('summary', '')}" if event.get('summary') else ''}
            </div>
        </div>''')
    
    html_parts.append('</div>')
    st.markdown(''.join(html_parts), unsafe_allow_html=True)


def render_quick_filters(current_filter):
    """Render quick filter buttons."""
    cols = st.columns(len(QUICK_FILTERS) + 1)
    new_filter = current_filter
    
    for i, (key, config) in enumerate(QUICK_FILTERS.items()):
        with cols[i]:
            is_active = current_filter == key
            if st.button(config['label'], key=f"qf_{key}", help=config['help'],
                        type="primary" if is_active else "secondary", use_container_width=True):
                new_filter = None if is_active else key
    
    with cols[-1]:
        if current_filter and st.button("❌ Clear", use_container_width=True):
            new_filter = None
    
    return new_filter


def create_severity_chart(df):
    sev_counts = df['criticality'].value_counts().reindex(SEVERITY_ORDER, fill_value=0)
    colors = [SEVERITY_CONFIG[s]['color'] for s in sev_counts.index]
    
    fig = go.Figure(data=[go.Pie(
        labels=sev_counts.index.tolist(),
        values=sev_counts.values.tolist(),
        hole=0.5,
        marker_colors=colors,
        textinfo='percent+label',
        textposition='outside'
    )])
    fig.update_layout(
        title=dict(text="By Severity", font=dict(size=13, color='#334155')),
        paper_bgcolor='rgba(0,0,0,0)', height=280,
        margin=dict(t=40, b=20, l=20, r=20), showlegend=False
    )
    return fig


def create_operations_chart(df):
    if 'methodName' not in df.columns:
        return None
    
    groups = {
        'Delete': len(df[df['methodName'].str.contains('Delete', case=False, na=False)]),
        'Create': len(df[df['methodName'].str.contains('Create', case=False, na=False)]),
        'Update': len(df[df['methodName'].str.contains('Update|Alter', case=False, regex=True, na=False)]),
        'Auth': len(df[df['methodName'].str.contains('Sign|Auth|Role', case=False, regex=True, na=False)]),
    }
    groups = {k: v for k, v in groups.items() if v > 0}
    colors = {'Delete': '#dc2626', 'Create': '#16a34a', 'Update': '#3b82f6', 'Auth': '#8b5cf6'}
    
    fig = go.Figure(data=[go.Bar(
        x=list(groups.keys()), y=list(groups.values()),
        marker_color=[colors.get(k, '#64748b') for k in groups.keys()],
        text=list(groups.values()), textposition='outside'
    )])
    fig.update_layout(
        title=dict(text="By Operation", font=dict(size=13, color='#334155')),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=280,
        margin=dict(t=40, b=40, l=40, r=20),
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor='#e2e8f0')
    )
    return fig


def create_timeline_chart(df):
    if 'time' not in df.columns or len(df) == 0:
        return None
    
    df_copy = df.copy()
    df_copy['hour'] = df_copy['time'].dt.floor('h')
    timeline_agg = df_copy.groupby(['hour', 'criticality']).size().reset_index(name='count')
    pivot_df = timeline_agg.pivot(index='hour', columns='criticality', values='count').fillna(0)
    
    for sev in SEVERITY_ORDER:
        if sev not in pivot_df.columns:
            pivot_df[sev] = 0
    pivot_df = pivot_df[SEVERITY_ORDER]
    
    fig = go.Figure()
    for sev in SEVERITY_ORDER:
        fig.add_trace(go.Scatter(
            x=pivot_df.index, y=pivot_df[sev], name=sev, mode='lines',
            stackgroup='one', line=dict(width=0), fillcolor=SEVERITY_CONFIG[sev]['color']
        ))
    
    fig.update_layout(
        title=dict(text="Events Timeline", font=dict(size=13, color='#334155')),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=200,
        margin=dict(t=40, b=30, l=40, r=20),
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor='#e2e8f0'),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified'
    )
    return fig


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <h1 class="main-title">🔐 Confluent Audit Dashboard <span class="main-badge">TableFlow</span></h1>
        <p class="main-subtitle">Powered by PyIceberg + Confluent TableFlow REST Catalog • Fast SQL-like queries on Parquet</p>
    </div>
    """, unsafe_allow_html=True)

    # Initialize session state
    if 'quick_filter' not in st.session_state:
        st.session_state.quick_filter = None
    if 'use_kafka_fallback' not in st.session_state:
        st.session_state.use_kafka_fallback = False

    # Sidebar
    with st.sidebar:
        st.markdown("### ⚙️ Settings")
        
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")
        
        # Data source toggle
        st.markdown("### 📊 Data Source")
        data_source = st.radio(
            "Select source",
            ["TableFlow (Iceberg)", "Kafka (Fallback)"],
            index=0 if not st.session_state.use_kafka_fallback else 1,
            label_visibility="collapsed"
        )
        st.session_state.use_kafka_fallback = (data_source == "Kafka (Fallback)")
        
        st.markdown("---")
        
        # Time range
        st.markdown("### ⏰ Time Range")
        time_options = {
            'Last 1 hour': 1, 'Last 6 hours': 6, 'Last 12 hours': 12,
            'Last 24 hours': 24, 'Last 3 days': 72, 'Last 7 days': 168
        }
        time_range = st.radio("Select period", list(time_options.keys()), index=3, label_visibility="collapsed")
        hours = time_options[time_range]

        st.markdown("---")
        
        # Load identities
        identity_lookup = load_identity_lookup()
        st.markdown(f'<div class="success-box">✓ {len(identity_lookup)} identities</div>', unsafe_allow_html=True)

    # Fetch data
    with st.spinner(f"Loading events ({time_range})..."):
        if st.session_state.use_kafka_fallback:
            # Kafka fallback
            events = fetch_events_kafka_fallback(hours)
            if events:
                df = pd.DataFrame(events)
                error = None
            else:
                df, error = None, "No events found"
            source_label = "Kafka Consumer"
        else:
            # TableFlow / PyIceberg
            quick_filter_sql = QUICK_FILTERS.get(st.session_state.quick_filter, {}).get('filter') if st.session_state.quick_filter else None
            df, error = fetch_events_iceberg(hours, quick_filter_sql)
            source_label = "TableFlow (Iceberg)"

    # Handle errors
    if error:
        st.markdown(f'<div class="warning-box">⚠️ {error}</div>', unsafe_allow_html=True)
        
        if "PyIceberg" in str(error) or "Missing" in str(error):
            st.markdown("""
            ### Setup Required
            
            1. **Install PyIceberg:**
            ```bash
            pip install pyiceberg pyarrow
            ```
            
            2. **Set environment variables:**
            ```bash
            export CONFLUENT_CLOUD_API_KEY="your-cloud-api-key"
            export CONFLUENT_CLOUD_API_SECRET="your-cloud-api-secret"
            export TABLEFLOW_CATALOG_URI="https://tableflow.ap-south-1.aws.confluent.cloud/iceberg/catalog/..."
            export ICEBERG_TABLE_NAME="default.audit_events_flattened"
            ```
            
            3. **Or use Kafka fallback** (toggle in sidebar)
            """)
        return

    if df is None or len(df) == 0:
        st.warning("⚠️ No events found.")
        return

    # Compute fields
    df = compute_fields(df, identity_lookup)

    # Show data source info
    st.markdown(f'<div class="info-box">📊 Source: {source_label} | {len(df):,} events loaded</div>', unsafe_allow_html=True)

    # Quick filters (only for Kafka mode, Iceberg uses SQL filters)
    if st.session_state.use_kafka_fallback:
        st.markdown("### ⚡ Quick Filters")
        new_filter = render_quick_filters(st.session_state.quick_filter)
        
        if new_filter != st.session_state.quick_filter:
            st.session_state.quick_filter = new_filter
            st.rerun()
        
        # Apply quick filter (client-side for Kafka)
        if st.session_state.quick_filter:
            pattern = QUICK_FILTERS[st.session_state.quick_filter].get('filter', '')
            # Convert SQL-like filter to pandas
            if 'LIKE' in pattern:
                import re
                matches = re.findall(r"methodName LIKE '%([^%]+)%'", pattern)
                if matches:
                    regex_pattern = '|'.join(matches)
                    df = df[df['methodName'].str.contains(regex_pattern, case=False, regex=True, na=False)]
            elif 'granted = false' in pattern.lower():
                df = df[df['granted'] == False]
    else:
        # Iceberg mode - show active filter
        st.markdown("### ⚡ Quick Filters")
        new_filter = render_quick_filters(st.session_state.quick_filter)
        
        if new_filter != st.session_state.quick_filter:
            st.session_state.quick_filter = new_filter
            st.cache_data.clear()  # Re-fetch with new filter
            st.rerun()

    # Sidebar filters
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🎯 Filters")

        if 'methodName' in df.columns:
            methods = ['All'] + sorted(df['methodName'].dropna().value_counts().head(30).index.tolist())
            selected_method = st.selectbox("Method", methods)
            if selected_method != 'All':
                df = df[df['methodName'] == selected_method]

        if 'user' in df.columns:
            users = ['All'] + sorted(df['user'].dropna().value_counts().head(30).index.tolist())
            selected_user = st.selectbox("User", users)
            if selected_user != 'All':
                df = df[df['user'] == selected_user]

        search_term = st.text_input("🔍 Search", placeholder="any field...")
        if search_term:
            search_cols = ['methodName', 'user', 'summary', 'api_key_id', 'topic_name']
            available = [c for c in search_cols if c in df.columns]
            mask = df[available].astype(str).apply(lambda x: x.str.contains(search_term, case=False, na=False)).any(axis=1)
            df = df[mask]

    # Metrics
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.markdown(render_metric_card(len(df[df['criticality'] == 'CRITICAL']), "Critical", "#dc2626", "severity-critical"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_metric_card(len(df[df['criticality'] == 'HIGH']), "High", "#ea580c", "severity-high"), unsafe_allow_html=True)
    with col3:
        st.markdown(render_metric_card(len(df[df['is_deletion'] == True]), "Deletions", "#dc2626"), unsafe_allow_html=True)
    with col4:
        st.markdown(render_metric_card(len(df[df['is_creation'] == True]), "Creations", "#16a34a"), unsafe_allow_html=True)
    with col5:
        denied = len(df[df['granted'] == False]) if 'granted' in df.columns else 0
        st.markdown(render_metric_card(denied, "Denied", "#dc2626"), unsafe_allow_html=True)
    with col6:
        st.markdown(render_metric_card(len(df), "Total", "#0ea5e9"), unsafe_allow_html=True)

    # Spotlight
    render_spotlight(df)

    # Timeline
    timeline_fig = create_timeline_chart(df)
    if timeline_fig:
        st.plotly_chart(timeline_fig, use_container_width=True)

    # Charts
    chart_cols = st.columns(3)
    with chart_cols[0]:
        st.plotly_chart(create_severity_chart(df), use_container_width=True)
    with chart_cols[1]:
        ops_fig = create_operations_chart(df)
        if ops_fig:
            st.plotly_chart(ops_fig, use_container_width=True)
    with chart_cols[2]:
        if 'user' in df.columns:
            top_users = df['user'].value_counts().head(5)
            fig = go.Figure(data=[go.Bar(
                y=top_users.index.tolist()[::-1], x=top_users.values.tolist()[::-1],
                orientation='h', marker_color='#0ea5e9'
            )])
            fig.update_layout(
                title=dict(text="Top Users", font=dict(size=13, color='#334155')),
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=280,
                margin=dict(t=40, b=20, l=120, r=20)
            )
            st.plotly_chart(fig, use_container_width=True)

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 All Events", "🗑️ Deletions", "🔑 API Keys", "📋 Topics", "📊 Details"])

    table_cols = ['time_display', 'severity_icon', 'methodName', 'user', 'summary', 'granted_display']
    available_cols = [c for c in table_cols if c in df.columns]

    with tab1:
        st.markdown(f"**{len(df):,} events**")
        if len(df) > 0:
            st.dataframe(df[available_cols].head(1000), use_container_width=True, height=500,
                column_config={
                    "time_display": st.column_config.TextColumn("Time", width=140),
                    "severity_icon": st.column_config.TextColumn("", width=30),
                    "methodName": st.column_config.TextColumn("Method", width=180),
                    "user": st.column_config.TextColumn("User", width=180),
                    "summary": st.column_config.TextColumn("Details", width=250),
                    "granted_display": st.column_config.TextColumn("Access", width=90),
                })

    with tab2:
        del_df = df[df['is_deletion'] == True]
        st.markdown(f"**{len(del_df):,} deletions**")
        if len(del_df) > 0:
            st.dataframe(del_df[available_cols].head(500), use_container_width=True, height=400)

    with tab3:
        apikey_df = df[df['methodName'].str.contains('APIKey|ApiKey', case=False, regex=True, na=False)]
        st.markdown(f"**{len(apikey_df):,} API key events**")
        if len(apikey_df) > 0:
            cols = ['time_display', 'methodName', 'user', 'api_key_id', 'client_ip']
            st.dataframe(apikey_df[[c for c in cols if c in apikey_df.columns]].head(500), use_container_width=True, height=400)

    with tab4:
        topic_df = df[df['methodName'].str.contains('Topic', case=False, na=False)]
        st.markdown(f"**{len(topic_df):,} topic events**")
        if len(topic_df) > 0:
            cols = ['time_display', 'methodName', 'user', 'topic_name', 'cluster_id']
            st.dataframe(topic_df[[c for c in cols if c in topic_df.columns]].head(500), use_container_width=True, height=400)

    with tab5:
        if len(df) > 0:
            event_idx = st.selectbox("Select event", range(min(100, len(df))),
                format_func=lambda x: f"{df.iloc[x].get('time_display', '')} - {df.iloc[x].get('methodName', '')}")
            event = df.iloc[event_idx]
            
            col1, col2 = st.columns(2)
            with col1:
                st.json({'id': event.get('id'), 'time': event.get('time_display'),
                        'method': event.get('methodName'), 'criticality': event.get('criticality'),
                        'user': event.get('user'), 'granted': event.get('granted')})
            with col2:
                st.json({'api_key_id': event.get('api_key_id'), 'topic_name': event.get('topic_name'),
                        'cluster_id': event.get('cluster_id'), 'environment_id': event.get('environment_id'),
                        'client_ip': event.get('client_ip')})
            
            if event.get('data_json'):
                with st.expander("📄 Raw data_json"):
                    try: st.json(json.loads(event['data_json']))
                    except: st.text(event['data_json'])


if __name__ == "__main__":
    main()