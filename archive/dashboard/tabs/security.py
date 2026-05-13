"""Security Tab - RBAC and ACL authorization events"""

import streamlit as st
import pandas as pd
import plotly.express as px
from components.filters import render_paginated_dataframe


# Security-specific columns
SECURITY_COLUMNS = [
    'time_display',      # When
    'user_display',      # Who
    'action',            # What action
    'rbac_role',         # RBAC Role
    'rbac_scope',        # RBAC Scope
    'acl_permission_type', # ACL Permission
    'access_display',    # Result
    'resource_display',  # Resource
    'cluster_id',        # Which cluster
    'environment_id',    # Which environment
    'clientIp',          # Source IP
]

SECURITY_COLUMN_CONFIG = {
    "time_display": st.column_config.TextColumn("When", width="medium"),
    "user_display": st.column_config.TextColumn("Who", width="medium"),
    "action": st.column_config.TextColumn("Action", width="small"),
    "rbac_role": st.column_config.TextColumn("RBAC Role", width="small"),
    "rbac_scope": st.column_config.TextColumn("RBAC Scope", width="medium"),
    "acl_permission_type": st.column_config.TextColumn("ACL Permission", width="small"),
    "access_display": st.column_config.TextColumn("Result", width="small"),
    "resource_display": st.column_config.TextColumn("Resource", width="large"),
    "cluster_id": st.column_config.TextColumn("Cluster", width="small"),
    "environment_id": st.column_config.TextColumn("Environment", width="small"),
    "clientIp": st.column_config.TextColumn("Source IP", width="small"),
}


def render_tab(df, config=None):
    """Render the Security tab with pagination"""
    st.subheader("🛡️ Security & Authorization")
    st.caption("RBAC roles, ACL permissions, and authorization events")

    if not df.empty:
        # Summary charts at top
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### RBAC Roles Used")
            if 'rbac_role' in df.columns:
                rbac_df = df[df['rbac_role'].notna()]
                if not rbac_df.empty:
                    role_counts = rbac_df['rbac_role'].value_counts().head(10)
                    fig = px.bar(x=role_counts.values, y=role_counts.index, orientation='h')
                    fig.update_layout(yaxis={'categoryorder': 'total ascending'}, showlegend=False, height=300)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No RBAC role data available")
            else:
                st.info("No RBAC data in events")

        with col2:
            st.markdown("#### ACL Permissions")
            if 'acl_permission_type' in df.columns:
                acl_df = df[df['acl_permission_type'].notna()]
                if not acl_df.empty:
                    acl_counts = acl_df['acl_permission_type'].value_counts()
                    fig = px.pie(values=acl_counts.values, names=acl_counts.index)
                    fig.update_layout(height=300)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No ACL permission data available")
            else:
                st.info("No ACL data in events")

        # Authorization events table with pagination
        st.markdown("---")
        st.markdown("#### Authorization Events")

        # Sort by time descending
        if 'time' in df.columns:
            df = df.sort_values('time', ascending=False)

        render_paginated_dataframe(
            df=df,
            columns=SECURITY_COLUMNS,
            column_config=SECURITY_COLUMN_CONFIG,
            tab_key="security",
            default_page_size=50
        )
    else:
        st.info("No events to display")
