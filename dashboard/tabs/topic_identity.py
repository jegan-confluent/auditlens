"""
Topic × Identity Matrix Tab

Shows a matrix of Topics × Identities with their activity from audit events
and ACL permissions from the Confluent Cloud Admin API.

Data Sources:
1. Audit activity data - from Kafka consumer (who actually did what)
2. ACL data - from Confluent Admin API (who has access)
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
import logging
import os

logger = logging.getLogger(__name__)

# Try to import identity enricher and admin client
try:
    from src.identity import IdentityEnricher, get_enricher
    from src.confluent_api import ConfluentCloudClient, get_client, ACL
    ENRICHMENT_AVAILABLE = True
except ImportError:
    ENRICHMENT_AVAILABLE = False
    logger.warning("Identity enrichment modules not available")


def aggregate_topic_activity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate audit events by topic × identity.

    Returns DataFrame with columns:
    - cluster_id, topic_resource, principal, display_name
    - methods (list), event_count, first_seen, last_seen
    """
    if df.empty:
        return pd.DataFrame()

    # Filter to topic-related events
    topic_events = df[
        df['methodName'].str.contains('kafka\\.', case=False, na=False) |
        df['methodName'].str.contains('Produce|Fetch|Topic', case=True, na=False)
    ].copy()

    if topic_events.empty:
        return pd.DataFrame()

    # Extract topic name from resourceName or authzResourceName
    def extract_topic(row):
        resource = row.get('authzResourceName') or row.get('resourceName') or ''
        if not resource:
            return None
        # Parse CRN format: crn://...kafka=.../topic=payments-events
        if 'topic=' in str(resource):
            parts = str(resource).split('topic=')
            if len(parts) > 1:
                return parts[1].split('/')[0]
        # Simple topic name
        if '/' not in str(resource) and 'crn:' not in str(resource):
            return str(resource)
        return None

    topic_events['topic_resource'] = topic_events.apply(extract_topic, axis=1)
    topic_events = topic_events[topic_events['topic_resource'].notna()]

    if topic_events.empty:
        return pd.DataFrame()

    # Ensure time column is datetime
    if 'time' in topic_events.columns:
        topic_events['time'] = pd.to_datetime(topic_events['time'], errors='coerce')

    # Aggregate by cluster × topic × principal
    aggregated = topic_events.groupby(
        ['cluster_id', 'topic_resource', 'principal'],
        dropna=False
    ).agg({
        'methodName': lambda x: list(set(x.dropna())),
        'id': 'count',
        'time': ['min', 'max'],
    }).reset_index()

    # Flatten column names
    aggregated.columns = [
        'cluster_id', 'topic_resource', 'principal',
        'methods', 'event_count', 'first_seen', 'last_seen'
    ]

    # Sort by event count descending
    aggregated = aggregated.sort_values('event_count', ascending=False)

    return aggregated


def enrich_with_identity_names(df: pd.DataFrame) -> pd.DataFrame:
    """Add human-readable identity names to the dataframe."""
    if df.empty or not ENRICHMENT_AVAILABLE:
        if 'principal' in df.columns:
            df['display_name'] = df['principal']
        return df

    try:
        enricher = get_enricher()
        if not enricher.enabled:
            df['display_name'] = df['principal']
            return df

        # Resolve all unique principals
        principals = df['principal'].dropna().unique().tolist()
        resolved = enricher.batch_resolve(principals)

        # Map to display names
        df['display_name'] = df['principal'].apply(
            lambda p: str(resolved.get(p, p)) if p else 'Unknown'
        )

    except Exception as e:
        logger.warning("Failed to enrich identity names: %s", e)
        df['display_name'] = df['principal']

    return df


def get_acl_data(cluster_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get ACL data for the specified clusters.

    Returns dict mapping topic_name to list of ACL entries.
    """
    if not ENRICHMENT_AVAILABLE:
        return {}

    # Get cluster API credentials from environment
    cluster_api_key = os.getenv("DEST_API_KEY")
    cluster_api_secret = os.getenv("DEST_API_SECRET")

    if not cluster_api_key or not cluster_api_secret:
        logger.debug("Cluster API credentials not available for ACL lookup")
        return {}

    topic_acls: Dict[str, List[Dict[str, Any]]] = {}

    try:
        client = get_client()
        if not client.enabled:
            return {}

        for cluster_id in cluster_ids:
            if not cluster_id:
                continue

            # Get clusters to find REST endpoint
            clusters = client.list_clusters()
            rest_endpoint = None
            for c in clusters:
                if c.id == cluster_id:
                    rest_endpoint = c.rest_endpoint
                    break

            if not rest_endpoint:
                continue

            # Get ACLs for this cluster
            acls = client.list_acls(
                cluster_id,
                cluster_api_key,
                cluster_api_secret,
                rest_endpoint
            )

            for acl in acls:
                if acl.resource_type != "TOPIC":
                    continue

                topic_name = acl.resource_name
                if topic_name not in topic_acls:
                    topic_acls[topic_name] = []

                topic_acls[topic_name].append({
                    'principal': acl.principal,
                    'operation': acl.operation,
                    'permission': acl.permission,
                    'pattern_type': acl.pattern_type,
                    'cluster_id': cluster_id,
                })

    except Exception as e:
        logger.warning("Failed to get ACL data: %s", e)

    return topic_acls


def find_stale_acls(
    activity_df: pd.DataFrame,
    acl_data: Dict[str, List[Dict[str, Any]]],
    stale_days: int = 30
) -> pd.DataFrame:
    """
    Find ACLs for principals with no recent activity.

    Returns DataFrame with stale ACL entries.
    """
    if activity_df.empty or not acl_data:
        return pd.DataFrame()

    # Get active principals per topic
    active_principals: Dict[str, set] = {}
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=stale_days)

    for _, row in activity_df.iterrows():
        topic = row.get('topic_resource')
        principal = row.get('principal')
        last_seen = row.get('last_seen')

        if not topic or not principal:
            continue

        # Check if activity is recent
        if pd.notna(last_seen):
            if isinstance(last_seen, str):
                last_seen = pd.to_datetime(last_seen)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if last_seen >= cutoff_time:
                if topic not in active_principals:
                    active_principals[topic] = set()
                active_principals[topic].add(principal)

    # Find ACL principals with no activity
    stale_entries = []

    for topic, acls in acl_data.items():
        active = active_principals.get(topic, set())

        for acl in acls:
            principal = acl.get('principal', '')
            # Normalize principal for comparison
            normalized = principal.replace('User:', '')

            # Check if this principal has recent activity
            has_activity = any(
                normalized in str(ap) or str(ap) in normalized
                for ap in active
            )

            if not has_activity:
                stale_entries.append({
                    'topic': topic,
                    'principal': principal,
                    'operation': acl.get('operation'),
                    'permission': acl.get('permission'),
                    'cluster_id': acl.get('cluster_id'),
                    'stale_days': stale_days,
                })

    return pd.DataFrame(stale_entries)


def render_topic_identity_tab(df: pd.DataFrame):
    """Render the Topic × Identity Matrix tab."""
    st.header("🔗 Topic × Identity Matrix")

    # Check if enrichment is available
    if not ENRICHMENT_AVAILABLE:
        st.warning(
            "⚠️ Identity enrichment modules not available. "
            "Install src/identity and src/confluent_api modules."
        )

    # Check for Cloud API credentials
    cloud_api_key = os.getenv("CONFLUENT_CLOUD_API_KEY")
    if not cloud_api_key and ENRICHMENT_AVAILABLE:
        st.info(
            "ℹ️ Configure CONFLUENT_CLOUD_API_KEY and CONFLUENT_CLOUD_API_SECRET "
            "to see ACL data and enriched identity names."
        )

    # Filters
    col1, col2, col3 = st.columns(3)

    with col1:
        clusters = ['All'] + sorted(df['cluster_id'].dropna().unique().tolist())
        selected_cluster = st.selectbox("Cluster", clusters, key="ti_cluster")

    with col2:
        stale_threshold = st.selectbox(
            "Stale ACL Threshold",
            [7, 14, 30, 60, 90],
            index=2,
            format_func=lambda x: f"{x} days",
            key="ti_stale"
        )

    with col3:
        search = st.text_input("Search", placeholder="Topic or identity...", key="ti_search")

    # Filter data
    filtered_df = df.copy()
    if selected_cluster != 'All':
        filtered_df = filtered_df[filtered_df['cluster_id'] == selected_cluster]

    if search:
        mask = (
            filtered_df['topic_resource'].str.contains(search, case=False, na=False) |
            filtered_df['principal'].str.contains(search, case=False, na=False)
        )
        filtered_df = filtered_df[mask]

    # Aggregate topic activity
    activity_df = aggregate_topic_activity(filtered_df)
    activity_df = enrich_with_identity_names(activity_df)

    # Get ACL data
    cluster_ids = filtered_df['cluster_id'].dropna().unique().tolist()
    acl_data = get_acl_data(cluster_ids) if cloud_api_key else {}

    # Find stale ACLs
    stale_acls = find_stale_acls(activity_df, acl_data, stale_threshold)

    # View mode selector
    st.markdown("---")
    view_mode = st.radio(
        "View Mode",
        ["Topic → Identities", "Identity → Topics", "Stale ACLs"],
        horizontal=True,
        key="ti_view"
    )

    # Render selected view
    if view_mode == "Topic → Identities":
        render_topic_to_identities(activity_df, acl_data)
    elif view_mode == "Identity → Topics":
        render_identity_to_topics(activity_df)
    else:
        render_stale_acls(stale_acls, activity_df)

    # Sankey diagram
    if not activity_df.empty and len(activity_df) < 100:
        st.markdown("---")
        st.subheader("📊 Identity → Topic Flow")
        render_sankey_diagram(activity_df)


def render_topic_to_identities(activity_df: pd.DataFrame, acl_data: Dict):
    """Render Topic → Identities view."""
    st.subheader("📋 Topics and Their Identities")

    if activity_df.empty:
        st.info("No topic activity data available.")
        return

    # Group by topic
    topics = activity_df['topic_resource'].unique()

    for topic in sorted(topics)[:50]:  # Limit to 50 topics
        topic_data = activity_df[activity_df['topic_resource'] == topic]
        acls = acl_data.get(topic, [])

        with st.expander(f"📁 **{topic}** ({len(topic_data)} identities)", expanded=False):
            # Active identities table
            display_df = topic_data[[
                'display_name', 'methods', 'event_count', 'last_seen'
            ]].copy()

            display_df['methods'] = display_df['methods'].apply(
                lambda x: ', '.join(x[:3]) + ('...' if len(x) > 3 else '') if isinstance(x, list) else str(x)
            )

            display_df['last_seen'] = pd.to_datetime(display_df['last_seen']).dt.strftime('%Y-%m-%d %H:%M')

            display_df.columns = ['Identity', 'Methods', 'Events', 'Last Active']

            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True
            )

            # Show ACL-only identities if available
            if acls:
                active_principals = set(topic_data['principal'].dropna())
                acl_only = [
                    acl for acl in acls
                    if acl['principal'] not in active_principals
                    and acl['principal'].replace('User:', '') not in active_principals
                ]

                if acl_only:
                    st.markdown("**⚠️ ACL-only (no recent activity):**")
                    for acl in acl_only[:5]:
                        st.markdown(f"- `{acl['principal']}`: {acl['operation']} ({acl['permission']})")


def render_identity_to_topics(activity_df: pd.DataFrame):
    """Render Identity → Topics view."""
    st.subheader("👤 Identities and Their Topics")

    if activity_df.empty:
        st.info("No identity activity data available.")
        return

    # Group by identity
    identities = activity_df.groupby('principal').agg({
        'display_name': 'first',
        'topic_resource': lambda x: list(set(x)),
        'methods': lambda x: list(set([m for methods in x for m in (methods if isinstance(methods, list) else [methods])])),
        'event_count': 'sum',
        'last_seen': 'max',
    }).reset_index()

    identities = identities.sort_values('event_count', ascending=False)

    # Identity selector
    identity_options = identities['display_name'].tolist()
    selected_identity = st.selectbox(
        "Select Identity",
        identity_options,
        key="ti_identity_select"
    )

    if selected_identity:
        identity_data = identities[identities['display_name'] == selected_identity].iloc[0]

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Topics Accessed", len(identity_data['topic_resource']))
        with col2:
            st.metric("Total Events", f"{identity_data['event_count']:,}")
        with col3:
            last_seen = pd.to_datetime(identity_data['last_seen'])
            st.metric("Last Active", last_seen.strftime('%Y-%m-%d %H:%M'))

        st.markdown("**Topics:**")
        for topic in sorted(identity_data['topic_resource']):
            st.markdown(f"- `{topic}`")

        st.markdown("**Methods Used:**")
        methods_str = ', '.join(sorted(identity_data['methods']))
        st.code(methods_str)


def render_stale_acls(stale_acls: pd.DataFrame, activity_df: pd.DataFrame):
    """Render Stale ACLs view."""
    st.subheader("⚠️ Stale ACL Report")

    if stale_acls.empty:
        if activity_df.empty:
            st.info("No activity data available to detect stale ACLs.")
        else:
            st.success("✅ No stale ACLs detected. All ACL principals have recent activity.")
        return

    st.warning(f"Found **{len(stale_acls)}** ACL entries with no recent activity.")

    # Enrich with identity names
    stale_acls = enrich_with_identity_names(stale_acls.rename(columns={'principal': 'principal'}))

    display_df = stale_acls[[
        'principal', 'topic', 'operation', 'permission', 'cluster_id'
    ]].copy()

    display_df.columns = ['Identity', 'Topic', 'Operation', 'Permission', 'Cluster']

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    # Export button
    csv = stale_acls.to_csv(index=False)
    st.download_button(
        label="📥 Export Stale ACLs as CSV",
        data=csv,
        file_name=f"stale_acls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


def render_sankey_diagram(activity_df: pd.DataFrame):
    """Render Sankey diagram of Identity → Topic flows."""
    if activity_df.empty or len(activity_df) > 50:
        st.info("Sankey diagram available for 50 or fewer identity-topic pairs.")
        return

    # Prepare nodes and links
    identities = activity_df['display_name'].unique().tolist()
    topics = activity_df['topic_resource'].unique().tolist()

    # Create node labels
    node_labels = identities + topics
    node_colors = ['#3498db'] * len(identities) + ['#2ecc71'] * len(topics)

    # Create links
    sources = []
    targets = []
    values = []

    for _, row in activity_df.iterrows():
        identity = row['display_name']
        topic = row['topic_resource']
        count = row['event_count']

        if identity in identities and topic in topics:
            sources.append(identities.index(identity))
            targets.append(len(identities) + topics.index(topic))
            values.append(count)

    if not sources:
        return

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=node_labels,
            color=node_colors,
        ),
        link=dict(
            source=sources,
            target=targets,
            value=values,
        )
    )])

    fig.update_layout(
        title_text="",
        font_size=10,
        height=400,
    )

    st.plotly_chart(fig, use_container_width=True)
