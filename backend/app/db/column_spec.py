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
    "actor_enriched_at": "TIMESTAMP WITH TIME ZONE",
    "source_context": "VARCHAR(255)",
    "client_id": "VARCHAR(255)",
    "client_tool": "VARCHAR(128)",
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
    # Flattened authorizationInfo fields from data_json. Distinct from the
    # outer resource_type / pattern_type columns — these mirror the
    # authorizationInfo.{granted,operation,resourceType,patternType} fields
    # so Tableflow can surface them as queryable columns.
    "auth_granted": "BOOLEAN",
    "auth_operation": "VARCHAR(255)",
    "auth_resource_type": "VARCHAR(128)",
    "auth_pattern_type": "VARCHAR(64)",
    # Flattened result.data.id — set by methods that return a created or
    # mutated resource id. Empty for read methods.
    "result_resource_id": "VARCHAR(255)",
    # Flattened request.accessType — usually READ_ONLY / READ_WRITE.
    # Used by event_normalization to demote READ_ONLY events to
    # signal_type=informational.
    "access_type": "VARCHAR(64)",
    # Role-binding alert support (Feature 2). auth_role is the role being
    # granted in BindRoleForPrincipal events (request.data.role_name), with
    # rbacAuthorization.role as a fallback for other contexts. auth_role_target
    # is the principal receiving the grant (request.data.principal).
    "auth_role": "VARCHAR(255)",
    "auth_role_target": "VARCHAR(255)",
    # IP-filter denial support (Feature 3). Populated from
    # authorizationInfo.ipfilterAuthorization.{client_ip, resource_group}.
    # Both NULL on the vast majority of events; non-NULL marks an IP-filter-
    # mediated authorization decision distinct from ACL/RBAC denials.
    "ipfilter_client_ip": "VARCHAR(45)",
    "ipfilter_resource_group": "VARCHAR(255)",
    # Access Transparency support (Feature 4). Populated only when
    # event type == "io.confluent.cloud/access-transparency": the operator
    # who accessed customer resources and the business justification.
    "at_justification": "TEXT",
    "at_operator": "VARCHAR(255)",
}
