"""Details Tab - Deep dive into individual events"""

import streamlit as st
import pandas as pd
import json


def render_tab(df, config=None):
    """Render the Details tab - inspect individual events"""
    st.subheader("📊 Event Details - Deep Dive")
    st.caption("Select an event to see full details")

    if df.empty or len(df) == 0:
        st.info("No events to display")
        return

    # Sort by time descending for event selection
    if 'time' in df.columns:
        df = df.sort_values('time', ascending=False).reset_index(drop=True)

    # Event selector with clear format
    event_idx = st.selectbox(
        "Select event to inspect",
        range(min(100, len(df))),
        format_func=lambda x: f"{df.iloc[x].get('time_display', 'N/A')} | {df.iloc[x].get('user_display', 'Unknown')[:30]} | {df.iloc[x].get('action', 'N/A')} | {df.iloc[x].get('criticality', '')}"
    )

    event = df.iloc[event_idx]

    # Core audit info at top
    st.markdown("---")
    st.markdown("### Core Audit Info")

    core_col1, core_col2, core_col3, core_col4 = st.columns(4)

    with core_col1:
        st.metric("When", event.get('time_display', 'N/A'))

    with core_col2:
        st.metric("Who", str(event.get('user_display', 'Unknown'))[:25])

    with core_col3:
        st.metric("Action", event.get('action', 'N/A'))

    with core_col4:
        result = event.get('result_display', event.get('resultStatus', 'N/A'))
        st.metric("Result", str(result)[:20] if result else 'N/A')

    # Resource info
    st.markdown("### Resource")
    res_col1, res_col2, res_col3 = st.columns(3)

    with res_col1:
        st.markdown(f"**Cluster:** {event.get('cluster_id', 'N/A')}")

    with res_col2:
        st.markdown(f"**Environment:** {event.get('environment_id', 'N/A')}")

    with res_col3:
        st.markdown(f"**Resource:** {str(event.get('resource_display', 'N/A'))[:60]}")

    # Detailed breakdown
    st.markdown("---")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**📅 Event Info**")
        st.json({
            'Time': event.get('time_display'),
            'Criticality': event.get('criticality'),
            'Method': event.get('methodName'),
            'Action': event.get('action'),
            'Service': event.get('serviceName'),
            'Result': event.get('resultStatus'),
            'Is Failure': bool(event.get('is_failure')),
            'Is Deletion': bool(event.get('is_deletion')),
        })

    with col2:
        st.markdown("**👤 Identity**")
        st.json({
            'Principal': event.get('principal'),
            'User': event.get('user'),
            'Email': event.get('email'),
            'Client IP': event.get('clientIp'),
            'Client ID': event.get('clientId'),
        })

    with col3:
        st.markdown("**🔐 Authorization**")
        st.json({
            'Granted': event.get('granted'),
            'RBAC Role': event.get('rbacRole') or event.get('rbac_role'),
            'RBAC Scope': event.get('rbacScope') or event.get('rbac_scope'),
            'ACL Permission': event.get('aclPermissionType') or event.get('acl_permission_type'),
            'ACL Host': event.get('aclHost') or event.get('acl_host'),
            'Operation': event.get('operation'),
        })

    col4, col5 = st.columns(2)

    with col4:
        st.markdown("**📦 Resource Details**")
        st.json({
            'Resource Name': event.get('resourceName'),
            'Resource Type': event.get('resourceType') or event.get('resource_type'),
            'Cluster ID': event.get('cluster_id'),
            'Environment ID': event.get('environment_id'),
            'Topic Name': event.get('topic_name'),
        })

    with col5:
        st.markdown("**🔗 Tracing**")
        st.json({
            'Request ID': event.get('requestId') or event.get('request_id'),
            'Correlation ID': event.get('correlationId') or event.get('correlation_id'),
            'Connection ID': event.get('connectionId') or event.get('connection_id'),
            'Source': event.get('source'),
            'Subject': event.get('subject'),
        })

    # Full data_json
    if 'data_json' in event.index and pd.notna(event.get('data_json')):
        with st.expander("🔍 View Full Event Data (JSON)", expanded=False):
            try:
                data = json.loads(event['data_json']) if isinstance(event['data_json'], str) else event['data_json']
                st.json(data)
            except Exception:
                st.text(str(event['data_json']))
