"""
Identity Activity Timeline Tab

Given any user or service account, shows everything they did across all clusters.
Provides identity profile card, activity timeline, and risk indicators.
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

# Try to import identity enricher
try:
    from src.identity import IdentityEnricher, IdentityInfo, IdentityType, get_enricher
    ENRICHMENT_AVAILABLE = True
except ImportError:
    ENRICHMENT_AVAILABLE = False
    logger.warning("Identity enrichment modules not available")


def calculate_risk_score(
    activity_df: pd.DataFrame,
    time_window_days: int = 7
) -> Tuple[str, List[str]]:
    """
    Calculate risk score for an identity based on their activity.

    Risk levels:
    - LOW: narrow access, expected methods, no denials
    - MEDIUM: broad access OR some denials OR new topics
    - HIGH: deletion operations OR many denials OR unusual IPs
    - CRITICAL: API key operations OR cross-cluster access patterns

    Returns:
        Tuple of (risk_level, list of risk indicators)
    """
    if activity_df.empty:
        return "UNKNOWN", ["No activity data"]

    indicators = []
    risk_points = 0

    # Check for denials
    denials = activity_df[activity_df['granted'] == False]
    denial_count = len(denials)

    if denial_count == 0:
        indicators.append("✅ No failed auth in last 24h")
    elif denial_count <= 3:
        indicators.append(f"⚠️ {denial_count} DENY events detected")
        risk_points += 1
    else:
        indicators.append(f"🚨 {denial_count} DENY events (investigate)")
        risk_points += 2

    # Check for deletion operations
    deletions = activity_df[activity_df['is_deletion'] == True]
    if len(deletions) > 0:
        indicators.append(f"⚠️ {len(deletions)} deletion operations")
        risk_points += 2

    # Check for API key operations
    api_key_ops = activity_df[
        activity_df['methodName'].str.contains('ApiKey', case=False, na=False)
    ]
    if len(api_key_ops) > 0:
        indicators.append(f"🔑 {len(api_key_ops)} API key operations")
        risk_points += 3

    # Check for cross-cluster activity
    unique_clusters = activity_df['cluster_id'].dropna().nunique()
    if unique_clusters > 3:
        indicators.append(f"⚠️ Activity across {unique_clusters} clusters")
        risk_points += 1
    elif unique_clusters > 1:
        indicators.append(f"ℹ️ Activity across {unique_clusters} clusters")

    # Check for new topics accessed recently
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=time_window_days)
    if 'time' in activity_df.columns:
        recent_df = activity_df[pd.to_datetime(activity_df['time']) >= recent_cutoff]
        new_resources = recent_df['resourceName'].dropna().nunique()
        if new_resources > 5:
            indicators.append(f"⚠️ Accessed {new_resources} resources this week")
            risk_points += 1

    # Check unique source IPs
    unique_ips = activity_df['clientIp'].dropna().nunique()
    if unique_ips > 10:
        indicators.append(f"⚠️ Activity from {unique_ips} different IPs")
        risk_points += 1

    # Check access pattern consistency
    methods = activity_df['methodName'].dropna().unique()
    if len(methods) <= 3:
        indicators.append("✅ Consistent access pattern")
    elif len(methods) > 10:
        indicators.append(f"⚠️ Broad access pattern ({len(methods)} methods)")
        risk_points += 1

    # Determine overall risk level
    if risk_points >= 5:
        risk_level = "CRITICAL"
    elif risk_points >= 3:
        risk_level = "HIGH"
    elif risk_points >= 1:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return risk_level, indicators


def get_identity_profile(principal: str, activity_df: pd.DataFrame) -> Dict[str, Any]:
    """Get profile information for an identity."""
    profile = {
        'principal': principal,
        'display_name': principal,
        'identity_type': 'Unknown',
        'first_seen': None,
        'last_seen': None,
        'clusters': [],
        'topics_accessed': 0,
        'methods_used': [],
        'total_events': 0,
    }

    # Try to get enriched info
    if ENRICHMENT_AVAILABLE:
        try:
            enricher = get_enricher()
            if enricher.enabled:
                info = enricher.resolve(principal)
                profile['display_name'] = str(info)
                profile['identity_type'] = info.identity_type.value if hasattr(info, 'identity_type') else 'Unknown'
        except Exception as e:
            logger.warning("Failed to get identity info: %s", e)

    # Get stats from activity data
    if not activity_df.empty:
        principal_df = activity_df[activity_df['principal'] == principal]

        if not principal_df.empty:
            if 'time' in principal_df.columns:
                times = pd.to_datetime(principal_df['time'], errors='coerce').dropna()
                if not times.empty:
                    profile['first_seen'] = times.min()
                    profile['last_seen'] = times.max()

            profile['clusters'] = principal_df['cluster_id'].dropna().unique().tolist()
            profile['topics_accessed'] = principal_df['resourceName'].dropna().nunique()
            profile['methods_used'] = principal_df['methodName'].dropna().unique().tolist()
            profile['total_events'] = len(principal_df)

    return profile


def render_identity_activity_tab(df: pd.DataFrame):
    """Render the Identity Activity Timeline tab."""
    st.header("👤 Identity Activity")

    if df.empty:
        st.info("No event data available.")
        return

    # Get unique principals from the data
    principals = df['principal'].dropna().unique().tolist()

    if not principals:
        st.info("No identity data available in the current dataset.")
        return

    # Identity selector
    col1, col2 = st.columns([2, 1])

    with col1:
        # Search box
        search_term = st.text_input(
            "Search Identity",
            placeholder="Type to search...",
            key="ia_search"
        )

    with col2:
        # Time range
        time_range = st.selectbox(
            "Time Range",
            [("Last 1 hour", 60), ("Last 6 hours", 360), ("Last 24 hours", 1440), ("Last 7 days", 10080)],
            format_func=lambda x: x[0],
            key="ia_time"
        )
        time_minutes = time_range[1]

    # Filter principals by search
    if search_term:
        filtered_principals = [p for p in principals if search_term.lower() in str(p).lower()]
    else:
        filtered_principals = principals[:100]  # Limit to 100 for performance

    # Enrich principal names for display
    display_names = {}
    if ENRICHMENT_AVAILABLE:
        try:
            enricher = get_enricher()
            for p in filtered_principals[:50]:  # Limit enrichment
                info = enricher.resolve(p)
                display_names[p] = str(info)
        except Exception:
            pass

    # Build options list
    options = [
        (p, display_names.get(p, p))
        for p in filtered_principals
    ]

    if not options:
        st.warning("No identities match your search.")
        return

    # Identity selector dropdown
    selected = st.selectbox(
        "Select Identity",
        options,
        format_func=lambda x: x[1],
        key="ia_identity"
    )

    if not selected:
        return

    selected_principal = selected[0]

    # Filter data for selected principal
    principal_df = df[df['principal'] == selected_principal].copy()

    # Apply time filter
    if 'time' in principal_df.columns:
        principal_df['time'] = pd.to_datetime(principal_df['time'], errors='coerce')
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=time_minutes)
        if principal_df['time'].dt.tz is None:
            principal_df['time'] = principal_df['time'].dt.tz_localize('UTC')
        principal_df = principal_df[principal_df['time'] >= cutoff]

    st.markdown("---")

    # Identity Profile Card
    render_identity_profile(selected_principal, principal_df, df)

    st.markdown("---")

    # Risk Indicators
    render_risk_indicators(principal_df)

    st.markdown("---")

    # Activity Timeline
    render_activity_timeline(principal_df)

    st.markdown("---")

    # Detailed Activity Table
    render_activity_table(principal_df)

    # Export button
    if not principal_df.empty:
        st.markdown("---")
        csv = principal_df.to_csv(index=False)
        st.download_button(
            label="📥 Export Identity Report as CSV",
            data=csv,
            file_name=f"identity_{selected_principal}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )


def render_identity_profile(principal: str, principal_df: pd.DataFrame, all_df: pd.DataFrame):
    """Render the identity profile card."""
    profile = get_identity_profile(principal, all_df)

    st.subheader("📋 Identity Profile")

    # Main identity info
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown(f"### 🔑 {profile['display_name']}")

        identity_type = profile['identity_type']
        if identity_type == 'service_account':
            st.markdown("**Type:** Service Account")
        elif identity_type == 'user':
            st.markdown("**Type:** User Account")
        else:
            st.markdown(f"**Type:** {identity_type}")

        if profile['first_seen']:
            st.markdown(f"**First Seen:** {profile['first_seen'].strftime('%Y-%m-%d')}")

    with col2:
        # Key metrics
        st.metric("Clusters", len(profile['clusters']))
        st.metric("Topics Accessed", profile['topics_accessed'])

    # Clusters list
    if profile['clusters']:
        st.markdown("**Clusters:** " + ", ".join([f"`{c}`" for c in profile['clusters'][:5]]))
        if len(profile['clusters']) > 5:
            st.markdown(f"_...and {len(profile['clusters']) - 5} more_")

    # Methods used
    if profile['methods_used']:
        methods_display = ", ".join(sorted(profile['methods_used'])[:10])
        st.markdown(f"**Methods Used:** `{methods_display}`")
        if len(profile['methods_used']) > 10:
            st.markdown(f"_...and {len(profile['methods_used']) - 10} more_")


def render_risk_indicators(principal_df: pd.DataFrame):
    """Render risk indicators panel."""
    st.subheader("🛡️ Risk Assessment")

    risk_level, indicators = calculate_risk_score(principal_df)

    # Risk level badge
    color_map = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢",
        "UNKNOWN": "⚪",
    }

    col1, col2 = st.columns([1, 3])

    with col1:
        st.markdown(f"### {color_map.get(risk_level, '⚪')} {risk_level}")

    with col2:
        for indicator in indicators:
            st.markdown(f"- {indicator}")


def render_activity_timeline(principal_df: pd.DataFrame):
    """Render activity timeline chart."""
    st.subheader("📈 Activity Timeline")

    if principal_df.empty or 'time' not in principal_df.columns:
        st.info("No timeline data available.")
        return

    # Prepare data for timeline
    timeline_df = principal_df.copy()
    timeline_df['time'] = pd.to_datetime(timeline_df['time'])
    timeline_df['hour'] = timeline_df['time'].dt.floor('H')

    # Aggregate by hour and method
    hourly = timeline_df.groupby(['hour', 'methodName']).size().reset_index(name='count')

    if hourly.empty:
        st.info("No activity data to display.")
        return

    # Create stacked bar chart
    fig = px.bar(
        hourly,
        x='hour',
        y='count',
        color='methodName',
        title='',
        labels={'hour': 'Time', 'count': 'Events', 'methodName': 'Method'},
    )

    fig.update_layout(
        height=300,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_title="",
        yaxis_title="Events",
    )

    st.plotly_chart(fig, use_container_width=True)


def render_activity_table(principal_df: pd.DataFrame):
    """Render detailed activity table."""
    st.subheader("📋 Detailed Activity")

    if principal_df.empty:
        st.info("No activity data available.")
        return

    # Select columns to display
    display_columns = [
        'time', 'cluster_id', 'methodName', 'resourceName', 'granted', 'resultStatus'
    ]

    available_columns = [c for c in display_columns if c in principal_df.columns]
    display_df = principal_df[available_columns].copy()

    # Format time
    if 'time' in display_df.columns:
        display_df['time'] = pd.to_datetime(display_df['time']).dt.strftime('%Y-%m-%d %H:%M:%S')

    # Format granted column
    if 'granted' in display_df.columns:
        display_df['granted'] = display_df['granted'].apply(
            lambda x: '✅ ALLOW' if x is True else ('❌ DENY' if x is False else str(x))
        )

    # Rename columns for display
    column_names = {
        'time': 'When',
        'cluster_id': 'Cluster',
        'methodName': 'Method',
        'resourceName': 'Resource',
        'granted': 'Result',
        'resultStatus': 'Status',
    }
    display_df = display_df.rename(columns=column_names)

    # Sort by time descending
    display_df = display_df.sort_values('When', ascending=False)

    st.dataframe(
        display_df.head(100),
        use_container_width=True,
        hide_index=True
    )

    if len(principal_df) > 100:
        st.info(f"Showing first 100 of {len(principal_df):,} events. Export for full data.")
