"""Analytics Tab"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from data.export import export_to_csv, export_to_json
from data.kafka_consumer import load_security_alerts


def render_tab(df, config=None):
    """Render the Analytics tab"""
    st.subheader("📈 Analytics & Visualizations")

    if not df.empty:
        col1, col2 = st.columns(2)

        with col1:
            if 'criticality' in df.columns:
                crit_counts = df['criticality'].value_counts()
                colors = {'CRITICAL': '#dc2626', 'HIGH': '#f59e0b', 'MEDIUM': '#3b82f6', 'LOW': '#10b981'}
                fig = px.pie(
                    values=crit_counts.values,
                    names=crit_counts.index,
                    title="Events by Criticality",
                    color=crit_counts.index,
                    color_discrete_map=colors
                )
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            if 'methodName' in df.columns:
                method_counts = df['methodName'].value_counts().head(10)
                fig = px.bar(
                    x=method_counts.values,
                    y=method_counts.index,
                    orientation='h',
                    title="Top 10 Methods",
                    color=method_counts.values,
                    color_continuous_scale='Viridis'
                )
                fig.update_layout(yaxis={'categoryorder': 'total ascending'}, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        col3, col4 = st.columns(2)

        with col3:
            if 'time' in df.columns:
                time_series = df.set_index('time').resample('5min').size()
                fig = px.area(
                    x=time_series.index,
                    y=time_series.values,
                    title="Events Over Time (5-min intervals)"
                )
                fig.update_layout(xaxis_title="Time", yaxis_title="Event Count")
                st.plotly_chart(fig, use_container_width=True)

        with col4:
            if 'user' in df.columns:
                user_counts = df['user'].value_counts().head(10)
                fig = px.bar(
                    x=user_counts.values,
                    y=user_counts.index,
                    orientation='h',
                    title="Top 10 Active Users"
                )
                fig.update_layout(yaxis={'categoryorder': 'total ascending'})
                st.plotly_chart(fig, use_container_width=True)

# Tab 8: Time Insights

