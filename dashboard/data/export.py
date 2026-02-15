"""Export functions for audit data"""

import pandas as pd
from datetime import datetime
from io import BytesIO

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False


def export_to_csv(df, filename_prefix="audit_events"):
    """Export dataframe to CSV."""
    export_cols = [
        'time_display', 'criticality', 'user_display', 'action', 'methodName',
        'resource_display', 'access_display', 'resultStatus', 'clientIp',
        'rbac_role', 'rbac_scope', 'acl_permission_type',
        'cluster_id', 'environment_id', 'topic_name',
        'principal', 'email', 'request_id', 'correlation_id'
    ]
    available_cols = [c for c in export_cols if c in df.columns]
    export_df = df[available_cols].copy()

    # Rename columns for clarity
    column_names = {
        'time_display': 'Timestamp',
        'criticality': 'Severity',
        'user_display': 'User',
        'action': 'Action',
        'methodName': 'Method',
        'resource_display': 'Resource',
        'access_display': 'Access Result',
        'resultStatus': 'Status',
        'clientIp': 'Client IP',
        'rbac_role': 'RBAC Role',
        'rbac_scope': 'RBAC Scope',
        'acl_permission_type': 'ACL Permission',
        'cluster_id': 'Cluster ID',
        'environment_id': 'Environment ID',
        'topic_name': 'Topic Name',
        'principal': 'Principal',
        'email': 'Email',
        'request_id': 'Request ID',
        'correlation_id': 'Correlation ID'
    }
    export_df = export_df.rename(columns=column_names)

    return export_df.to_csv(index=False)


def export_to_json(df, filename_prefix="audit_events"):
    """Export dataframe to JSON."""
    export_cols = [
        'time', 'criticality', 'principal', 'email', 'methodName', 'action',
        'resourceName', 'resource_display', 'granted', 'resultStatus', 'clientIp',
        'rbac_role', 'rbac_scope', 'acl_permission_type', 'acl_host',
        'cluster_id', 'environment_id', 'topic_name',
        'request_id', 'correlation_id', 'connection_id',
        'is_failure', 'is_deletion', 'is_creation'
    ]
    available_cols = [c for c in export_cols if c in df.columns]
    export_df = df[available_cols].copy()

    # Convert timestamps to string
    if 'time' in export_df.columns:
        export_df['time'] = export_df['time'].astype(str)

    return export_df.to_json(orient='records', indent=2)


def export_to_pdf(df, title="Audit Compliance Report"):
    """Export dataframe to PDF compliance report."""
    if not FPDF_AVAILABLE:
        return None

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, title, ln=True, align='C')
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(0, 8, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}", ln=True, align='C')
    pdf.ln(5)

    # Summary section
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 8, "Executive Summary", ln=True)
    pdf.set_font('Helvetica', '', 10)

    total_events = len(df)
    critical_count = len(df[df['criticality'] == 'CRITICAL']) if 'criticality' in df.columns else 0
    high_count = len(df[df['criticality'] == 'HIGH']) if 'criticality' in df.columns else 0
    failure_count = int(df['is_failure'].sum()) if 'is_failure' in df.columns else 0
    deletion_count = int(df['is_deletion'].sum()) if 'is_deletion' in df.columns else 0
    unique_users = df['user'].nunique() if 'user' in df.columns else 0

    pdf.cell(0, 6, f"Total Events: {total_events:,}", ln=True)
    pdf.cell(0, 6, f"Critical Events: {critical_count:,}", ln=True)
    pdf.cell(0, 6, f"High Severity: {high_count:,}", ln=True)
    pdf.cell(0, 6, f"Failures: {failure_count:,}", ln=True)
    pdf.cell(0, 6, f"Deletions: {deletion_count:,}", ln=True)
    pdf.cell(0, 6, f"Unique Users: {unique_users:,}", ln=True)
    pdf.ln(5)

    # Critical Events section
    if critical_count > 0:
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 8, "Critical Events Detail", ln=True)
        pdf.set_font('Helvetica', '', 9)

        critical_df = df[df['criticality'] == 'CRITICAL'].head(20)
        for _, row in critical_df.iterrows():
            time_str = row.get('time_display', str(row.get('time', 'N/A')))[:19]
            user = str(row.get('user', 'N/A'))[:20]
            action = str(row.get('action', row.get('methodName', 'N/A')))[:25]
            resource = str(row.get('resource_display', row.get('resourceName', 'N/A')))[:30]
            line = f"{time_str} | {user} | {action} | {resource}"
            pdf.cell(0, 5, line, ln=True)
        pdf.ln(3)

    # Failures section
    if failure_count > 0:
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 8, "Failed Operations", ln=True)
        pdf.set_font('Helvetica', '', 9)

        failure_df = df[df['is_failure'] == True].head(15) if 'is_failure' in df.columns else pd.DataFrame()
        for _, row in failure_df.iterrows():
            time_str = row.get('time_display', str(row.get('time', 'N/A')))[:19]
            user = str(row.get('user', 'N/A'))[:20]
            action = str(row.get('action', row.get('methodName', 'N/A')))[:25]
            status = str(row.get('resultStatus', 'N/A'))[:15]
            line = f"{time_str} | {user} | {action} | {status}"
            pdf.cell(0, 5, line, ln=True)
        pdf.ln(3)

    # Deletions section
    if deletion_count > 0:
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 8, "Deletion Operations", ln=True)
        pdf.set_font('Helvetica', '', 9)

        deletion_df = df[df['is_deletion'] == True].head(15) if 'is_deletion' in df.columns else pd.DataFrame()
        for _, row in deletion_df.iterrows():
            time_str = row.get('time_display', str(row.get('time', 'N/A')))[:19]
            user = str(row.get('user', 'N/A'))[:20]
            action = str(row.get('action', row.get('methodName', 'N/A')))[:25]
            resource = str(row.get('resource_display', row.get('resourceName', 'N/A')))[:30]
            line = f"{time_str} | {user} | {action} | {resource}"
            pdf.cell(0, 5, line, ln=True)

    # Footer
    pdf.ln(10)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.cell(0, 5, "Generated by Confluent AuditLens - Kafka Audit Intelligence Dashboard", ln=True, align='C')

    # Return as bytes
    return bytes(pdf.output())
