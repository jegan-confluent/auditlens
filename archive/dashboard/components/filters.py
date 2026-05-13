"""Filter components"""

import streamlit as st
import pandas as pd
from config import QUICK_FILTERS


def render_alert_banner(anomalies):
    """Render alert banner for detected anomalies."""
    if not anomalies:
        return

    # Group by severity
    critical_anomalies = [a for a in anomalies if a.get('severity') == 'CRITICAL']
    high_anomalies = [a for a in anomalies if a.get('severity') == 'HIGH']

    if critical_anomalies:
        messages = [a['message'] for a in critical_anomalies]
        st.markdown(
            f'<div class="alert-banner">⚠️ {" | ".join(messages)}</div>',
            unsafe_allow_html=True
        )

    if high_anomalies:
        messages = [a['message'] for a in high_anomalies]
        st.markdown(
            f'<div class="alert-banner alert-banner-warning">⚡ {" | ".join(messages)}</div>',
            unsafe_allow_html=True
        )


def render_quick_filters(current_filter):
    """Render quick filter buttons in two rows with highlighting.

    Returns:
        - filter_key: if a NEW filter was clicked
        - "__CLEAR__": if the active filter was clicked (to deactivate)
        - None: if no button was clicked (just a rerun)
    """
    filters_list = list(QUICK_FILTERS.items())

    # Track which filter was clicked this render
    clicked_filter = None

    # First row - most important filters (first 5)
    row1_filters = filters_list[:5]
    cols1 = st.columns(len(row1_filters))

    for idx, (filter_key, filter_config) in enumerate(row1_filters):
        with cols1[idx]:
            is_active = current_filter == filter_key
            button_type = "primary" if is_active else "secondary"
            if st.button(
                filter_config['label'],
                key=f"qf_{filter_key}",
                type=button_type,
                use_container_width=True
            ):
                # Toggle: if already active, return clear signal; otherwise return new filter
                clicked_filter = "__CLEAR__" if is_active else filter_key

    # Second row - additional filters (remaining)
    row2_filters = filters_list[5:]
    if row2_filters:
        cols2 = st.columns(len(row2_filters))

        for idx, (filter_key, filter_config) in enumerate(row2_filters):
            with cols2[idx]:
                is_active = current_filter == filter_key
                button_type = "primary" if is_active else "secondary"
                if st.button(
                    filter_config['label'],
                    key=f"qf_{filter_key}",
                    type=button_type,
                    use_container_width=True
                ):
                    clicked_filter = "__CLEAR__" if is_active else filter_key

    return clicked_filter


def apply_quick_filter(df, filter_key):
    """Apply quick filter to dataframe."""
    if not filter_key or filter_key not in QUICK_FILTERS:
        return df

    if df.empty:
        return df

    filter_config = QUICK_FILTERS[filter_key]

    # Handle ALL FAILURES filter
    if filter_config.get('type') == 'failure':
        if 'is_failure' in df.columns:
            return df[df['is_failure'] == True]
        return df

    # Handle granted filter (for Denied)
    if 'granted' in filter_config:
        if 'granted' in df.columns:
            return df[df['granted'] == filter_config['granted']]
        return df

    # Handle method_contains filter
    if 'method_contains' in filter_config:
        method_filter = filter_config['method_contains']
        if 'methodName' in df.columns:
            if isinstance(method_filter, list):
                # Multiple patterns - combine with OR
                pattern = '|'.join(method_filter)
                return df[df['methodName'].str.contains(pattern, case=False, na=False)]
            else:
                return df[df['methodName'].str.contains(method_filter, case=False, na=False)]

    return df


def render_paginated_dataframe(df, columns, column_config, tab_key, default_page_size=50):
    """
    Render a dataframe with pagination controls.

    Args:
        df: DataFrame to display
        columns: List of columns to show
        column_config: Streamlit column_config dict
        tab_key: Unique key for this tab (for session state)
        default_page_size: Default rows per page

    Returns:
        None (renders directly)
    """
    if df.empty:
        return

    # Filter to available columns
    available_cols = [c for c in columns if c in df.columns]
    if not available_cols:
        st.warning("No columns available to display")
        return

    # Pagination state keys
    page_key = f"{tab_key}_page"
    size_key = f"{tab_key}_page_size"

    # Initialize session state
    if page_key not in st.session_state:
        st.session_state[page_key] = 0
    if size_key not in st.session_state:
        st.session_state[size_key] = default_page_size

    total_rows = len(df)

    # Pagination controls - top
    col1, col2, col3, col4 = st.columns([1, 1, 2, 1])

    with col1:
        page_size = st.selectbox(
            "Rows per page",
            options=[10, 20, 50, 100, 200],
            index=[10, 20, 50, 100, 200].index(st.session_state[size_key]) if st.session_state[size_key] in [10, 20, 50, 100, 200] else 2,
            key=f"{tab_key}_size_select"
        )
        if page_size != st.session_state[size_key]:
            st.session_state[size_key] = page_size
            st.session_state[page_key] = 0  # Reset to first page
            st.rerun()

    page_size = st.session_state[size_key]
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    current_page = min(st.session_state[page_key], total_pages - 1)

    with col2:
        st.markdown(f"**Page {current_page + 1} of {total_pages}** ({total_rows:,} rows)")

    with col3:
        # Navigation buttons
        nav_col1, nav_col2, nav_col3, nav_col4 = st.columns(4)
        with nav_col1:
            if st.button("⏮️", key=f"{tab_key}_first", disabled=current_page == 0):
                st.session_state[page_key] = 0
                st.rerun()
        with nav_col2:
            if st.button("◀️", key=f"{tab_key}_prev", disabled=current_page == 0):
                st.session_state[page_key] = current_page - 1
                st.rerun()
        with nav_col3:
            if st.button("▶️", key=f"{tab_key}_next", disabled=current_page >= total_pages - 1):
                st.session_state[page_key] = current_page + 1
                st.rerun()
        with nav_col4:
            if st.button("⏭️", key=f"{tab_key}_last", disabled=current_page >= total_pages - 1):
                st.session_state[page_key] = total_pages - 1
                st.rerun()

    with col4:
        # Jump to page
        jump_page = st.number_input(
            "Go to page",
            min_value=1,
            max_value=total_pages,
            value=current_page + 1,
            key=f"{tab_key}_jump"
        )
        if jump_page != current_page + 1:
            st.session_state[page_key] = jump_page - 1
            st.rerun()

    # Calculate slice
    start_idx = current_page * page_size
    end_idx = min(start_idx + page_size, total_rows)

    # Display dataframe slice
    st.dataframe(
        df[available_cols].iloc[start_idx:end_idx],
        use_container_width=True,
        height=min(400, (end_idx - start_idx + 1) * 35 + 40),
        column_config=column_config
    )
