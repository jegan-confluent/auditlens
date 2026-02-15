"""Export Tab"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from data.export import export_to_csv, export_to_json, export_to_pdf
from data.kafka_consumer import load_security_alerts


def render_tab(df, config=None):
    """Render the Export tab"""
    st.subheader("💾 Export Data")
    st.markdown("Download audit events for compliance, reporting, or integration")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 📄 CSV Export")
        st.caption("Excel-compatible format with all key fields")

        csv_data = export_to_csv(df)
        st.download_button(
            label="📥 Download CSV",
            data=csv_data,
            file_name=f"audit_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

        st.caption(f"Contains {len(df):,} events with 19 fields")

    with col2:
        st.markdown("### 📋 JSON Export")
        st.caption("Machine-readable format for integration")

        json_data = export_to_json(df)
        st.download_button(
            label="📥 Download JSON",
            data=json_data,
            file_name=f"audit_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True
        )

        st.caption(f"Contains {len(df):,} events with full data")

    with col3:
        st.markdown("### 📑 PDF Report")
        st.caption("Compliance-ready executive summary")

        pdf_data = export_to_pdf(df)
        if pdf_data:
            st.download_button(
                label="📥 Download PDF",
                data=pdf_data,
                file_name=f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
            st.caption("Summary + Critical + Failures + Deletions")
        else:
            st.warning("PDF export not available")

    st.markdown("---")

    # Quick stats for export
    st.markdown("### 📊 Export Preview")
    preview_cols = ['time_display', 'user_display', 'action', 'resource_display', 'access_display']
    available_cols = [c for c in preview_cols if c in df.columns]
    st.dataframe(df[available_cols].head(10), use_container_width=True)

# Tab 10: Security Alerts (Aggregated Denial Alerts)

