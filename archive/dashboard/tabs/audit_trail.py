"""Audit Trail Tab - Core audit view: Who did What, When, on What Resource"""

import streamlit as st
import pandas as pd
from components.filters import render_paginated_dataframe


# Standard audit columns - consistent across all tabs
AUDIT_COLUMNS = [
    'time_display',      # When
    'user_display',      # Who
    'action',            # What action
    'methodName',        # Full method name
    'resource_display',  # What resource
    'result_display',    # Success/Failure
    'cluster_id',        # Which cluster
    'environment_id',    # Which environment
    'clientIp',          # Source IP
    'clientId',          # Client application
]

AUDIT_COLUMN_CONFIG = {
    "time_display": st.column_config.TextColumn("When", width="medium"),
    "user_display": st.column_config.TextColumn("Who", width="medium"),
    "action": st.column_config.TextColumn("Action", width="small"),
    "methodName": st.column_config.TextColumn("Method", width="medium"),
    "resource_display": st.column_config.TextColumn("Resource", width="large"),
    "result_display": st.column_config.TextColumn("Result", width="small"),
    "cluster_id": st.column_config.TextColumn("Cluster", width="small"),
    "environment_id": st.column_config.TextColumn("Environment", width="small"),
    "clientIp": st.column_config.TextColumn("Source IP", width="small"),
    "clientId": st.column_config.TextColumn("Client ID", width="small"),
}


def render_tab(df, config=None):
    """Render the Audit Trail tab with pagination"""
    st.subheader("🔍 Security Audit Trail")
    st.caption("Complete audit trail: **Who** did **What** action on **What** resource, **When**, with **Result**")

    if not df.empty:
        # Sort by time descending (most recent first)
        if 'time' in df.columns:
            df = df.sort_values('time', ascending=False)

        render_paginated_dataframe(
            df=df,
            columns=AUDIT_COLUMNS,
            column_config=AUDIT_COLUMN_CONFIG,
            tab_key="audit_trail",
            default_page_size=50
        )
    else:
        st.info("No events to display")
        st.markdown("""
**💡 Try these suggestions:**
- **Expand Time Window**: Increase to 1 hour or more in sidebar
- **Uncheck "Hide internal"**: Some events may be filtered
- **Clear Search Filters**: Remove any text filters
- **Check Criticality**: Make sure "All" is selected
        """)
