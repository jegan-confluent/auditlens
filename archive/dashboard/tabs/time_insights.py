"""Time Insights Tab"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from data.export import export_to_csv, export_to_json
from data.kafka_consumer import load_security_alerts


def render_tab(df, config=None):
    """Render the Time Insights tab"""
    st.subheader("⏰ Time-Based Insights")

    if not df.empty and 'time' in df.columns:
        # Activity Heatmap (Hour x Day of Week)
        st.markdown("#### 🔥 Activity Heatmap")
        st.caption("When do events occur? Darker = more activity")

        if 'hour_of_day' in df.columns and 'day_of_week' in df.columns:
            # Create pivot table for heatmap
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            heatmap_data = df.groupby(['day_of_week', 'hour_of_day']).size().unstack(fill_value=0)

            # Reindex to ensure all days and hours are present
            heatmap_data = heatmap_data.reindex(day_order, fill_value=0)
            all_hours = list(range(24))
            heatmap_data = heatmap_data.reindex(columns=all_hours, fill_value=0)

            # Create heatmap
            fig = go.Figure(data=go.Heatmap(
                z=heatmap_data.values,
                x=[f"{h:02d}:00" for h in all_hours],
                y=day_order,
                colorscale='RdYlGn_r',  # Red = high activity
                hovertemplate='%{y} at %{x}: %{z} events<extra></extra>'
            ))

            fig.update_layout(
                title="Activity by Day & Hour",
                xaxis_title="Hour of Day",
                yaxis_title="Day of Week",
                height=350
            )
            st.plotly_chart(fig, use_container_width=True)

            # Peak activity summary
            max_val = heatmap_data.values.max()
            if max_val > 0:
                peak_idx = np.unravel_index(heatmap_data.values.argmax(), heatmap_data.values.shape)
                peak_day = day_order[peak_idx[0]]
                peak_hour = all_hours[peak_idx[1]]
                st.success(f"📈 Peak activity: **{peak_day} at {peak_hour:02d}:00** ({int(max_val)} events)")

        st.markdown("---")

        col1, col2 = st.columns(2)

        with col1:
            # Activity by hour of day
            if 'hour_of_day' in df.columns:
                hour_counts = df['hour_of_day'].value_counts().sort_index()
                fig = px.bar(
                    x=hour_counts.index,
                    y=hour_counts.values,
                    title="Activity by Hour of Day",
                    labels={'x': 'Hour', 'y': 'Event Count'},
                    color=hour_counts.values,
                    color_continuous_scale='Viridis'
                )
                fig.update_layout(xaxis=dict(tickmode='linear', tick0=0, dtick=2), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

                # Highlight unusual hours
                avg_events = hour_counts.mean()
                unusual_hours = hour_counts[hour_counts > avg_events * 2]
                if not unusual_hours.empty:
                    st.warning(f"⚠️ Unusual activity at: {', '.join([f'{h}:00' for h in unusual_hours.index])}")

        with col2:
            # Activity by day of week
            if 'day_of_week' in df.columns:
                day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                day_counts = df['day_of_week'].value_counts()
                day_counts = day_counts.reindex(day_order, fill_value=0)
                fig = px.bar(
                    x=day_counts.index,
                    y=day_counts.values,
                    title="Activity by Day of Week",
                    labels={'x': 'Day', 'y': 'Event Count'},
                    color=day_counts.values,
                    color_continuous_scale='Blues'
                )
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

                # Weekend activity warning
                weekend_events = day_counts.get('Saturday', 0) + day_counts.get('Sunday', 0)
                if weekend_events > 0:
                    st.info(f"📅 Weekend activity detected: {weekend_events:,} events")

        # Criticality by time
        st.markdown("#### 🚨 Criticality Distribution Over Time")
        if 'criticality' in df.columns:
            time_crit = df.groupby([df['time'].dt.floor('30min'), 'criticality']).size().unstack(fill_value=0)
            if not time_crit.empty:
                fig = px.area(
                    time_crit,
                    title="Events by Criticality (30-min buckets)",
                    color_discrete_map={
                        'CRITICAL': '#dc2626',
                        'HIGH': '#f59e0b',
                        'MEDIUM': '#3b82f6',
                        'LOW': '#10b981'
                    }
                )
                fig.update_layout(xaxis_title="Time", yaxis_title="Event Count")
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # First-time actions
        st.markdown("#### 🆕 First-Time Actions (New Patterns)")
        if 'user' in df.columns and 'action' in df.columns:
            user_actions = df.groupby(['user', 'action']).agg({
                'time': 'min',
                'time_display': 'first'
            }).reset_index()
            user_actions = user_actions.sort_values('time', ascending=False).head(20)
            user_actions = user_actions.rename(columns={'time_display': 'First Seen', 'user': 'User', 'action': 'Action'})
            st.dataframe(user_actions[['First Seen', 'User', 'Action']], use_container_width=True, height=300)
    else:
        st.info("No time data available")

# Tab 9: Export

