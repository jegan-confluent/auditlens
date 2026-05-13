"""Single source of truth for audit_event supplemental columns.

All three callers — database.py, alembic 0002, and db_writer.py — import
from here so a new column only needs to be added in one place.
"""

AUDIT_EVENT_COLUMNS: dict[str, str] = {
    "actor_id": "VARCHAR(255)",
    "actor_display_name": "VARCHAR(255)",
    "actor_email": "VARCHAR(255)",
    "actor_type": "VARCHAR(64)",
    "actor_source": "VARCHAR(64)",
    "actor_confidence": "VARCHAR(32)",
    "actor_enriched_at": "VARCHAR(64)",
    "source_context": "VARCHAR(255)",
    "client_id": "VARCHAR(255)",
    "connection_id": "VARCHAR(255)",
    "request_id": "VARCHAR(255)",
    "environment_id": "VARCHAR(255)",
    "cluster_name": "VARCHAR(255)",
    "environment_name": "VARCHAR(255)",
    "parent_resource": "VARCHAR(255)",
    "resource_scope": "VARCHAR(512)",
    "resource_display_name": "VARCHAR(768)",
    "resource_criticality": "VARCHAR(32)",
    "blast_radius_hint": "VARCHAR(64)",
    "production_hint": "VARCHAR(64)",
    "flink_region": "VARCHAR(255)",
    "network_id": "VARCHAR(255)",
    "signal_type": "VARCHAR(32)",
    "signal_reason": "VARCHAR(128)",
    "impact_type": "VARCHAR(64)",
    "risk_level": "VARCHAR(32)",
    "change_type": "VARCHAR(32)",
    "resource_family": "VARCHAR(64)",
    "event_title": "VARCHAR(255)",
    "event_summary": "VARCHAR(768)",
    "decision_reason": "VARCHAR(255)",
    "decision_label": "VARCHAR(32)",
    "recommended_action": "VARCHAR(255)",
}
