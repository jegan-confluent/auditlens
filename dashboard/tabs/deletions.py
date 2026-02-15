"""Deletions Tab - Critical irreversible deletion operations"""

import streamlit as st
import pandas as pd
import plotly.express as px
from components.filters import render_paginated_dataframe


# Deletion-specific columns
DELETION_COLUMNS = [
    'time_display',      # When
    'criticality',       # Severity
    'user_display',      # Who
    'action',            # What action (DeleteTopic, etc.)
    'methodName',        # Full method
    'resource_display',  # What was deleted
    'topic_name',        # Topic name if applicable
    'result_display',    # Success/Failure
    'cluster_id',        # Which cluster
    'environment_id',    # Which environment
    'clientIp',          # Source IP
    'clientId',          # Client application
]

DELETION_COLUMN_CONFIG = {
    "time_display": st.column_config.TextColumn("When", width="medium"),
    "criticality": st.column_config.TextColumn("Severity", width="small"),
    "user_display": st.column_config.TextColumn("Who", width="medium"),
    "action": st.column_config.TextColumn("Action", width="small"),
    "methodName": st.column_config.TextColumn("What Deleted", width="medium"),
    "resource_display": st.column_config.TextColumn("Resource", width="large"),
    "topic_name": st.column_config.TextColumn("Topic", width="small"),
    "result_display": st.column_config.TextColumn("Result", width="small"),
    "cluster_id": st.column_config.TextColumn("Cluster", width="small"),
    "environment_id": st.column_config.TextColumn("Environment", width="small"),
    "clientIp": st.column_config.TextColumn("Source IP", width="small"),
    "clientId": st.column_config.TextColumn("Client ID", width="small"),
}


def render_tab(df, config=None):
    """Render the Deletions tab with pagination"""
    # Filter to deletions only
    deletion_df = df[df['is_deletion'] == True].copy() if 'is_deletion' in df.columns else pd.DataFrame()

    st.subheader(f"🗑️ Deletion Events ({len(deletion_df):,})")
    st.caption("**CRITICAL**: Irreversible deletion operations - topics, clusters, connectors, API keys, RBAC roles")

    if not deletion_df.empty:
        # Sort by time descending
        if 'time' in deletion_df.columns:
            deletion_df = deletion_df.sort_values('time', ascending=False)

        render_paginated_dataframe(
            df=deletion_df,
            columns=DELETION_COLUMNS,
            column_config=DELETION_COLUMN_CONFIG,
            tab_key="deletions",
            default_page_size=50
        )

        # Summary
        st.markdown("---")
        st.markdown("#### Deletion Summary")
        col1, col2 = st.columns(2)

        with col1:
            if 'methodName' in deletion_df.columns:
                method_counts = deletion_df['methodName'].value_counts().head(10)
                if not method_counts.empty:
                    fig = px.pie(values=method_counts.values, names=method_counts.index, title="By Deletion Type")
                    st.plotly_chart(fig, use_container_width=True)

        with col2:
            if 'user' in deletion_df.columns:
                user_counts = deletion_df['user'].value_counts().head(10)
                if not user_counts.empty:
                    fig = px.bar(x=user_counts.values, y=user_counts.index, orientation='h', title="Top Users Deleting")
                    fig.update_layout(yaxis={'categoryorder': 'total ascending'})
                    st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No deletion events found")
        st.caption("💡 No topics, clusters, or resources were deleted in this time window.")
