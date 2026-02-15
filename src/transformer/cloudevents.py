"""
CloudEvents parser for Confluent audit logs.

Parses CloudEvents v1.0 formatted audit log events and extracts
all relevant fields into a flattened structure.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List

from .crn_parser import CRNParser, CRNComponents

logger = logging.getLogger(__name__)


@dataclass
class AuthenticationInfo:
    """Authentication information from audit event."""
    principal: Optional[str] = None
    principal_resource_id: Optional[str] = None
    identity: Optional[str] = None
    mechanism: Optional[str] = None
    api_key_identifier: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthorizationInfo:
    """Authorization information from audit event."""
    granted: Optional[bool] = None
    operation: Optional[str] = None
    resource_type: Optional[str] = None
    resource_name: Optional[str] = None
    pattern_type: Optional[str] = None
    # RBAC
    rbac_role: Optional[str] = None
    rbac_scope: Optional[str] = None
    rbac_acting_principal: Optional[str] = None
    # ACL
    acl_permission_type: Optional[str] = None
    acl_host: Optional[str] = None
    acl_acting_principal: Optional[str] = None
    # Assigned principals (group mapping)
    assigned_principals: List[str] = field(default_factory=list)


@dataclass
class RequestMetadata:
    """Request metadata from audit event."""
    client_id: Optional[str] = None
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    connection_id: Optional[str] = None
    client_ip: Optional[str] = None
    network_id: Optional[str] = None


@dataclass
class ResultInfo:
    """Result information from audit event."""
    status: Optional[str] = None
    message: Optional[str] = None
    data: Optional[str] = None


@dataclass
class AuditEvent:
    """
    Fully parsed and enriched audit event.

    Contains all CloudEvents standard fields plus Confluent-specific
    data fields in a flattened structure suitable for analytics.
    """
    # CloudEvents standard fields
    id: str
    specversion: str = "1.0"
    source: Optional[str] = None
    subject: Optional[str] = None
    type: Optional[str] = None
    time: Optional[str] = None
    time_epoch_ms: Optional[int] = None
    datacontenttype: Optional[str] = None

    # Parsed CRN components from source
    source_organization_id: Optional[str] = None
    source_environment_id: Optional[str] = None
    source_cluster_type: Optional[str] = None
    source_cluster_id: Optional[str] = None

    # Parsed CRN components from subject
    subject_resource_type: Optional[str] = None
    subject_resource_id: Optional[str] = None

    # Service info
    service_name: Optional[str] = None
    method_name: Optional[str] = None
    resource_name: Optional[str] = None

    # Authentication
    principal: Optional[str] = None
    principal_resource_id: Optional[str] = None
    identity: Optional[str] = None
    auth_mechanism: Optional[str] = None
    api_key_identifier: Optional[str] = None

    # Authorization
    granted: Optional[bool] = None
    operation: Optional[str] = None
    resource_type: Optional[str] = None
    authz_resource_name: Optional[str] = None
    pattern_type: Optional[str] = None
    rbac_role: Optional[str] = None
    rbac_scope: Optional[str] = None
    acl_permission_type: Optional[str] = None
    acl_host: Optional[str] = None

    # Request metadata
    client_id: Optional[str] = None
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    connection_id: Optional[str] = None
    client_ip: Optional[str] = None

    # Result
    result_status: Optional[str] = None
    result_message: Optional[str] = None
    result_data: Optional[str] = None

    # Event classification (enrichment)
    event_category: Optional[str] = None  # authentication, authorization, request, access-transparency
    service_category: Optional[str] = None  # kafka, schema-registry, ksqldb, flink, organization
    is_security_relevant: bool = False
    is_failure: bool = False
    is_access_transparency: bool = False

    # Raw data
    data_json: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values for compact storage."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_flat_dict(self) -> Dict[str, Any]:
        """Convert to dictionary including None values for schema consistency."""
        return asdict(self)


class CloudEventsParser:
    """
    Parser for CloudEvents-formatted Confluent audit logs.

    Usage:
        parser = CloudEventsParser()
        event = parser.parse(raw_event_dict)
        flat_data = event.to_dict()
    """

    def __init__(self):
        self.crn_parser = CRNParser()

    def parse(self, raw: Dict[str, Any]) -> AuditEvent:
        """Parse a raw audit log event into a structured AuditEvent."""
        # Extract CloudEvents standard fields
        event = AuditEvent(
            id=raw.get("id", ""),
            specversion=raw.get("specversion", "1.0"),
            source=raw.get("source"),
            subject=raw.get("subject"),
            type=raw.get("type"),
            time=raw.get("time"),
            datacontenttype=raw.get("datacontenttype"),
        )

        # Parse timestamp
        if event.time:
            event.time_epoch_ms = self._parse_timestamp(event.time)

        # Parse source CRN
        source_crn = self.crn_parser.parse_source(event.source)
        event.source_organization_id = source_crn.organization_id
        event.source_environment_id = source_crn.environment_id
        event.source_cluster_type = source_crn.cluster_type
        event.source_cluster_id = source_crn.cluster_id

        # Parse subject CRN
        subject_crn = self.crn_parser.parse_subject(event.subject)
        event.subject_resource_type = subject_crn.resource_type
        event.subject_resource_id = subject_crn.resource_id

        # Extract data payload
        data = raw.get("data", {})
        if data:
            self._parse_data(event, data)
            # Store raw data
            event.data_json = json.dumps(data, separators=(",", ":"))

        # Classify event
        self._classify_event(event)

        return event

    def _parse_timestamp(self, time_str: str) -> Optional[int]:
        """Parse RFC3339 timestamp to epoch milliseconds."""
        if not time_str:
            return None

        try:
            # Handle various timestamp formats
            formats = [
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z",
            ]

            # Normalize timezone indicator
            normalized = time_str.replace("+00:00", "Z").replace("-00:00", "Z")

            for fmt in formats:
                try:
                    dt = datetime.strptime(normalized, fmt)
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    continue

            # Try ISO format parsing
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)

        except Exception as e:
            logger.debug(f"Failed to parse timestamp '{time_str}': {e}")
            return None

    def _parse_data(self, event: AuditEvent, data: Dict[str, Any]) -> None:
        """Parse the data payload of an audit event."""
        # Service info
        event.service_name = data.get("serviceName")
        event.method_name = data.get("methodName")
        event.resource_name = data.get("resourceName")

        # Authentication info
        authn = data.get("authenticationInfo", {})
        if authn:
            event.principal = self._extract_principal(authn.get("principal"))
            event.principal_resource_id = authn.get("principalResourceId")
            event.identity = authn.get("identity")

            metadata = authn.get("metadata", {})
            if metadata:
                event.auth_mechanism = metadata.get("mechanism")
                event.api_key_identifier = metadata.get("identifier")

        # Authorization info
        authz = data.get("authorizationInfo", {})
        if authz:
            event.granted = authz.get("granted")
            event.operation = authz.get("operation")
            event.resource_type = authz.get("resourceType")
            event.authz_resource_name = authz.get("resourceName")
            event.pattern_type = authz.get("patternType")

            # RBAC authorization
            rbac = authz.get("rbacAuthorization", {})
            if rbac:
                event.rbac_role = rbac.get("role")
                scope = rbac.get("scope", {})
                outer_scope = scope.get("outerScope", [])
                if outer_scope:
                    event.rbac_scope = outer_scope[0] if isinstance(outer_scope, list) else str(outer_scope)

            # ACL authorization
            acl = authz.get("aclAuthorization", {})
            if acl:
                event.acl_permission_type = acl.get("permissionType")
                event.acl_host = acl.get("host")

        # Request info
        request = data.get("request", {})
        if request:
            event.client_id = request.get("clientId")
            event.correlation_id = request.get("correlation_id") or request.get("correlationId")

        # Request metadata
        metadata = data.get("requestMetadata", {})
        if metadata:
            event.request_id = metadata.get("request_id")
            event.connection_id = metadata.get("connection_id")

        # Client address
        client_address = data.get("clientAddress", [])
        if client_address and isinstance(client_address, list) and len(client_address) > 0:
            first_addr = client_address[0]
            if isinstance(first_addr, dict):
                event.client_ip = first_addr.get("ip")
            elif isinstance(first_addr, str):
                event.client_ip = first_addr

        # Result
        result = data.get("result", {})
        if result:
            event.result_status = result.get("status")
            event.result_message = result.get("message")
            result_data = result.get("data")
            if result_data:
                if isinstance(result_data, dict):
                    event.result_data = json.dumps(result_data, separators=(",", ":"))
                else:
                    event.result_data = str(result_data)

    def _extract_principal(self, principal: Any) -> Optional[str]:
        """Extract principal string from various formats."""
        if principal is None:
            return None

        if isinstance(principal, str):
            return principal

        if isinstance(principal, dict):
            # Try common principal object formats
            for key in ["confluentServiceAccount", "confluentUser", "identityPool", "group"]:
                if key in principal and isinstance(principal[key], dict):
                    resource_id = principal[key].get("resourceId")
                    if resource_id:
                        return resource_id

            # Check for email
            if "email" in principal:
                return principal["email"]

            # Fallback to JSON serialization
            return json.dumps(principal, separators=(",", ":"))

        return str(principal)

    def _classify_event(self, event: AuditEvent) -> None:
        """Classify the event for filtering and analysis."""
        event_type = event.type or ""

        # Determine event category
        if "/authentication" in event_type:
            event.event_category = "authentication"
        elif "/authorization" in event_type:
            event.event_category = "authorization"
        elif "/request" in event_type:
            event.event_category = "request"
        elif "access-transparency" in event_type:
            event.event_category = "access-transparency"
            event.is_access_transparency = True
        else:
            event.event_category = "unknown"

        # Determine service category
        if "kafka.server" in event_type or event.method_name and event.method_name.startswith("kafka."):
            event.service_category = "kafka"
        elif "sg.server" in event_type or "schema" in event_type.lower():
            event.service_category = "schema-registry"
        elif "ksql.server" in event_type:
            event.service_category = "ksqldb"
        elif "flink.server" in event_type:
            event.service_category = "flink"
        elif "confluent.cloud" in event_type:
            event.service_category = "organization"
        else:
            event.service_category = "unknown"

        # Determine if security relevant
        event.is_security_relevant = (
            event.event_category in ("authentication", "authorization", "access-transparency")
            or event.granted is False
            or event.result_status in ("FAILURE", "UNAUTHENTICATED", "PERMISSION_DENIED")
        )

        # Determine if failure
        event.is_failure = (
            event.granted is False
            or event.result_status in ("FAILURE", "UNAUTHENTICATED", "PERMISSION_DENIED")
        )


def parse_audit_event(raw: Dict[str, Any]) -> AuditEvent:
    """Convenience function to parse an audit event."""
    parser = CloudEventsParser()
    return parser.parse(raw)
