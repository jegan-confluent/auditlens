"""Plotly chart components"""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def create_timeline_chart(df):
    """Create events over time timeline chart"""
    if df.empty or 'time' not in df.columns:
        return None

    # Group by time intervals
    time_df = df.copy()
    time_df['time_rounded'] = time_df['time'].dt.floor('5min')
    timeline_data = time_df.groupby('time_rounded').size().reset_index(name='count')

    fig = px.line(
        timeline_data,
        x='time_rounded',
        y='count',
        title='Events Over Time (5-minute intervals)',
        labels={'time_rounded': 'Time', 'count': 'Event Count'}
    )
    fig.update_traces(line_color='#7c3aed', line_width=3)
    fig.update_layout(height=300, showlegend=False)
    return fig


def create_method_distribution_chart(df):
    """Create method distribution pie chart"""
    if df.empty or 'methodName' not in df.columns:
        return None

    method_counts = df['methodName'].value_counts().head(10)
    fig = px.pie(
        values=method_counts.values,
        names=method_counts.index,
        title='Top 10 Methods'
    )
    fig.update_layout(height=400)
    return fig


def create_user_activity_chart(df):
    """Create user activity bar chart"""
    if df.empty or 'user' not in df.columns:
        return None

    user_counts = df['user'].value_counts().head(15)
    fig = px.bar(
        x=user_counts.values,
        y=user_counts.index,
        orientation='h',
        title='Top 15 Most Active Users',
        labels={'x': 'Event Count', 'y': 'User'}
    )
    fig.update_traces(marker_color='#7c3aed')
    fig.update_layout(height=500, showlegend=False)
    return fig


def create_failure_distribution_chart(df):
    """Create failure distribution chart"""
    if df.empty or 'is_failure' not in df.columns:
        return None

    failure_counts = df.groupby('is_failure').size().reset_index(name='count')
    failure_counts['status'] = failure_counts['is_failure'].map({True: 'Failures', False: 'Success'})

    fig = px.pie(
        failure_counts,
        values='count',
        names='status',
        title='Success vs Failures',
        color='status',
        color_discrete_map={'Success': '#16a34a', 'Failures': '#dc2626'}
    )
    fig.update_layout(height=350)
    return fig


def create_hour_of_day_chart(df):
    """Create hour of day activity chart"""
    if df.empty or 'hour_of_day' not in df.columns:
        return None

    hour_counts = df.groupby('hour_of_day').size().reset_index(name='count')
    fig = px.bar(
        hour_counts,
        x='hour_of_day',
        y='count',
        title='Activity by Hour of Day',
        labels={'hour_of_day': 'Hour (UTC)', 'count': 'Event Count'}
    )
    fig.update_traces(marker_color='#3b82f6')
    fig.update_layout(height=350, showlegend=False)
    return fig


def create_day_of_week_chart(df):
    """Create day of week activity chart"""
    if df.empty or 'day_of_week' not in df.columns:
        return None

    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    day_counts = df.groupby('day_of_week').size().reindex(day_order, fill_value=0).reset_index(name='count')

    fig = px.bar(
        day_counts,
        x='index',
        y='count',
        title='Activity by Day of Week',
        labels={'index': 'Day', 'count': 'Event Count'}
    )
    fig.update_traces(marker_color='#10b981')
    fig.update_layout(height=350, showlegend=False)
    return fig


def create_service_distribution_chart(df):
    """Create service distribution chart"""
    if df.empty or 'service' not in df.columns:
        return None

    service_counts = df['service'].value_counts().head(10)
    fig = px.pie(
        values=service_counts.values,
        names=service_counts.index,
        title='Top 10 Services'
    )
    fig.update_layout(height=400)
    return fig


def create_criticality_chart(df):
    """Create criticality distribution chart"""
    if df.empty or 'criticality' not in df.columns:
        return None

    crit_counts = df.groupby('criticality').size().reset_index(name='count')

    color_map = {
        'CRITICAL': '#dc2626',
        'HIGH': '#ea580c',
        'MEDIUM': '#f59e0b',
        'LOW': '#16a34a'
    }

    fig = px.bar(
        crit_counts,
        x='criticality',
        y='count',
        title='Events by Criticality',
        labels={'criticality': 'Criticality Level', 'count': 'Event Count'},
        color='criticality',
        color_discrete_map=color_map
    )
    fig.update_layout(height=350, showlegend=False)
    return fig


def create_ip_activity_chart(df):
    """Create client IP activity chart"""
    if df.empty or 'clientIp' not in df.columns:
        return None

    ip_counts = df['clientIp'].value_counts().head(15)
    fig = px.bar(
        x=ip_counts.values,
        y=ip_counts.index,
        orientation='h',
        title='Top 15 Client IPs',
        labels={'x': 'Event Count', 'y': 'Client IP'}
    )
    fig.update_traces(marker_color='#6366f1')
    fig.update_layout(height=500, showlegend=False)
    return fig


def create_resource_type_chart(df):
    """Create resource type distribution chart"""
    if df.empty or 'resource_type' not in df.columns:
        return None

    resource_counts = df['resource_type'].value_counts().head(10)
    fig = px.pie(
        values=resource_counts.values,
        names=resource_counts.index,
        title='Top 10 Resource Types'
    )
    fig.update_layout(height=400)
    return fig
