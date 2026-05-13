"""Failures Tab - All denied access, errors, and failures"""

import streamlit as st
import pandas as pd
import plotly.express as px
from components.filters import render_paginated_dataframe


# Failure-specific columns
FAILURE_COLUMNS = [
    'time_display',      # When
    'criticality',       # Severity
    'user_display',      # Who
    'action',            # What action
    'methodName',        # Full method
    'resource_display',  # What resource
    'result_display',    # Result
    'resultStatus',      # Status code
    'cluster_id',        # Which cluster
    'environment_id',    # Which environment
    'clientIp',          # Source IP
    'clientId',          # Client application
]

FAILURE_COLUMN_CONFIG = {
    "time_display": st.column_config.TextColumn("When", width="medium"),
    "criticality": st.column_config.TextColumn("Severity", width="small"),
    "user_display": st.column_config.TextColumn("Who", width="medium"),
    "action": st.column_config.TextColumn("Action", width="small"),
    "methodName": st.column_config.TextColumn("Method", width="medium"),
    "resource_display": st.column_config.TextColumn("Resource", width="large"),
    "result_display": st.column_config.TextColumn("Result", width="small"),
    "resultStatus": st.column_config.TextColumn("Status", width="small"),
    "cluster_id": st.column_config.TextColumn("Cluster", width="small"),
    "environment_id": st.column_config.TextColumn("Environment", width="small"),
    "clientIp": st.column_config.TextColumn("Source IP", width="small"),
    "clientId": st.column_config.TextColumn("Client ID", width="small"),
}


def render_tab(df, config=None):
    """Render the Failures tab with pagination"""
    # Filter to failures only
    failure_df = df[df['is_failure'] == True].copy() if 'is_failure' in df.columns else pd.DataFrame()

    st.subheader(f"🚨 All Failures ({len(failure_df):,})")
    st.caption("Denied access, authentication failures, permission denials, and errors")

    if not failure_df.empty:
        # Sort by time descending
        if 'time' in failure_df.columns:
            failure_df = failure_df.sort_values('time', ascending=False)

        render_paginated_dataframe(
            df=failure_df,
            columns=FAILURE_COLUMNS,
            column_config=FAILURE_COLUMN_CONFIG,
            tab_key="failures",
            default_page_size=50
        )

        # Summary charts
        st.markdown("---")
        st.markdown("#### Failure Analysis")
        col1, col2 = st.columns(2)

        with col1:
            if 'resultStatus' in failure_df.columns:
                status_counts = failure_df['resultStatus'].value_counts().head(10)
                if not status_counts.empty:
                    fig = px.pie(values=status_counts.values, names=status_counts.index, title="By Status")
                    st.plotly_chart(fig, use_container_width=True)

        with col2:
            if 'user' in failure_df.columns:
                user_counts = failure_df['user'].value_counts().head(10)
                if not user_counts.empty:
                    fig = px.bar(x=user_counts.values, y=user_counts.index, orientation='h', title="Top Users with Failures")
                    fig.update_layout(yaxis={'categoryorder': 'total ascending'})
                    st.plotly_chart(fig, use_container_width=True)
    else:
        st.success("✅ No failure events found! All operations succeeded.")
