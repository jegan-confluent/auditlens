"""Security Alerts Tab - Aggregated authorization denials"""

import streamlit as st
from data.kafka_consumer import load_security_alerts


def render_tab(df, config=None):
    """Render the Security Alerts tab"""
    st.subheader("🔔 Security Alerts - Aggregated Authorization Denials")
    st.caption("Aggregated alerts for principals with repeated access denials (threshold-based)")

    # Load alerts
    time_minutes = config.get('time_minutes', 60) if config else 60
    alerts_df = load_security_alerts(time_minutes=time_minutes, max_alerts=500)

    if not alerts_df.empty:
        # Stats cards at top
        col1, col2, col3, col4 = st.columns(4)

        critical_alerts = len(alerts_df[alerts_df['criticality'] == 'CRITICAL']) if 'criticality' in alerts_df.columns else 0
        high_alerts = len(alerts_df[alerts_df['criticality'] == 'HIGH']) if 'criticality' in alerts_df.columns else 0
        medium_alerts = len(alerts_df[alerts_df['criticality'] == 'MEDIUM']) if 'criticality' in alerts_df.columns else 0
        total_denials = alerts_df['denial_count'].sum() if 'denial_count' in alerts_df.columns else 0

        with col1:
            st.metric("🔴 CRITICAL", critical_alerts)
        with col2:
            st.metric("🟠 HIGH", high_alerts)
        with col3:
            st.metric("🟡 MEDIUM", medium_alerts)
        with col4:
            st.metric("📊 Total Denials", f"{total_denials:,}")

        # Display alerts table
        st.markdown("### Recent Security Alerts")

        display_cols = ['window_end', 'principal', 'denial_count', 'criticality', 'operations_display', 'resources_display', 'source_ips_display']
        available_cols = [c for c in display_cols if c in alerts_df.columns]

        st.dataframe(
            alerts_df[available_cols].head(100),
            use_container_width=True,
            height=500,
            column_config={
                "window_end": st.column_config.DatetimeColumn("Alert Time", width="medium"),
                "principal": st.column_config.TextColumn("Principal", width="medium"),
                "denial_count": st.column_config.NumberColumn("Denials", width="small"),
                "criticality": st.column_config.TextColumn("Severity", width="small"),
                "operations_display": st.column_config.TextColumn("Operations Attempted", width="large"),
                "resources_display": st.column_config.TextColumn("Resources Targeted", width="large"),
                "source_ips_display": st.column_config.TextColumn("Source IPs", width="medium"),
            }
        )
    else:
        st.info("No security alerts found in the selected time range")
        st.markdown("""
**💡 What are Security Alerts?**
- Security alerts are generated when a principal (user or service account) has multiple authorization denials
- Alerts are aggregated over 5-minute windows
- **CRITICAL**: 20+ denials in a window
- **HIGH**: 10-19 denials in a window
- **MEDIUM**: 5-9 denials in a window
        """)
