"""
Event router for dispatching audit events to appropriate handlers.

Routes events based on their type and service category to specialized
handlers for service-specific enrichment.
"""

import logging
from enum import Enum
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass

from .cloudevents import AuditEvent, CloudEventsParser

logger = logging.getLogger(__name__)


class EventCategory(str, Enum):
    """Audit event categories."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    REQUEST = "request"
    ACCESS_TRANSPARENCY = "access-transparency"
    UNKNOWN = "unknown"


class ServiceCategory(str, Enum):
    """Service categories for audit events."""
    KAFKA = "kafka"
    SCHEMA_REGISTRY = "schema-registry"
    KSQLDB = "ksqldb"
    FLINK = "flink"
    ORGANIZATION = "organization"
    UNKNOWN = "unknown"


@dataclass
class RoutingResult:
    """Result of routing an event through handlers."""
    event: AuditEvent
    handlers_applied: List[str]
    enrichments: Dict[str, Any]
    errors: List[str]


class EventHandler:
    """Base class for event handlers."""

    def __init__(self, name: str):
        self.name = name

    def can_handle(self, event: AuditEvent) -> bool:
        """Check if this handler can process the event."""
        raise NotImplementedError

    def handle(self, event: AuditEvent) -> Dict[str, Any]:
        """
        Process the event and return enrichments.

        Returns a dict of additional fields to add to the event.
        """
        raise NotImplementedError


class KafkaEventHandler(EventHandler):
    """Handler for Kafka-specific audit events."""

    def __init__(self):
        super().__init__("kafka")

    def can_handle(self, event: AuditEvent) -> bool:
        return event.service_category == ServiceCategory.KAFKA.value

    def handle(self, event: AuditEvent) -> Dict[str, Any]:
        enrichments = {}

        # Extract topic name from various fields
        if event.resource_type == "Topic" and event.authz_resource_name:
            enrichments["kafka_topic"] = event.authz_resource_name

        # Categorize Kafka operation
        method = event.method_name or ""
        if "Authentication" in method:
            enrichments["kafka_operation_type"] = "authentication"
        elif "Produce" in method or "Write" in method:
            enrichments["kafka_operation_type"] = "produce"
        elif "Fetch" in method or "Read" in method:
            enrichments["kafka_operation_type"] = "consume"
        elif "Metadata" in method or "Describe" in method:
            enrichments["kafka_operation_type"] = "metadata"
        elif "CreateTopics" in method:
            enrichments["kafka_operation_type"] = "topic_create"
        elif "DeleteTopics" in method:
            enrichments["kafka_operation_type"] = "topic_delete"
        elif "AlterConfigs" in method:
            enrichments["kafka_operation_type"] = "config_alter"
        elif "CreateAcls" in method or "DeleteAcls" in method:
            enrichments["kafka_operation_type"] = "acl_management"

        return enrichments


class SchemaRegistryEventHandler(EventHandler):
    """Handler for Schema Registry audit events."""

    def __init__(self):
        super().__init__("schema-registry")

    def can_handle(self, event: AuditEvent) -> bool:
        return event.service_category == ServiceCategory.SCHEMA_REGISTRY.value

    def handle(self, event: AuditEvent) -> Dict[str, Any]:
        enrichments = {}

        # Extract subject name
        if event.subject_resource_type == "subject" and event.subject_resource_id:
            enrichments["schema_subject"] = event.subject_resource_id

        # Categorize operation
        method = event.method_name or ""
        if "GetSchema" in method or "GetSubject" in method:
            enrichments["schema_operation_type"] = "read"
        elif "RegisterSchema" in method:
            enrichments["schema_operation_type"] = "register"
        elif "DeleteSubject" in method or "DeleteSchema" in method:
            enrichments["schema_operation_type"] = "delete"
        elif "UpdateCompatibility" in method:
            enrichments["schema_operation_type"] = "compatibility_update"

        return enrichments


class KsqlDBEventHandler(EventHandler):
    """Handler for ksqlDB audit events."""

    def __init__(self):
        super().__init__("ksqldb")

    def can_handle(self, event: AuditEvent) -> bool:
        return event.service_category == ServiceCategory.KSQLDB.value

    def handle(self, event: AuditEvent) -> Dict[str, Any]:
        enrichments = {}

        method = event.method_name or ""
        if "ExecuteStatement" in method:
            enrichments["ksql_operation_type"] = "execute_statement"
        elif "RunQuery" in method:
            enrichments["ksql_operation_type"] = "run_query"
        elif "TerminateQuery" in method:
            enrichments["ksql_operation_type"] = "terminate_query"

        return enrichments


class FlinkEventHandler(EventHandler):
    """Handler for Flink audit events."""

    def __init__(self):
        super().__init__("flink")

    def can_handle(self, event: AuditEvent) -> bool:
        return event.service_category == ServiceCategory.FLINK.value

    def handle(self, event: AuditEvent) -> Dict[str, Any]:
        enrichments = {}

        # Extract compute pool info
        if event.subject_resource_type == "compute-pool":
            enrichments["flink_compute_pool"] = event.subject_resource_id

        method = event.method_name or ""
        if "CreateStatement" in method or "ExecuteStatement" in method:
            enrichments["flink_operation_type"] = "execute_statement"
        elif "GetStatement" in method:
            enrichments["flink_operation_type"] = "get_statement"
        elif "DeleteStatement" in method:
            enrichments["flink_operation_type"] = "delete_statement"

        return enrichments


class OrganizationEventHandler(EventHandler):
    """Handler for organization-level audit events."""

    def __init__(self):
        super().__init__("organization")

    def can_handle(self, event: AuditEvent) -> bool:
        return event.service_category == ServiceCategory.ORGANIZATION.value

    def handle(self, event: AuditEvent) -> Dict[str, Any]:
        enrichments = {}

        method = event.method_name or ""

        # Categorize organization operations
        if "ServiceAccount" in method:
            enrichments["org_operation_type"] = "service_account"
        elif "ApiKey" in method:
            enrichments["org_operation_type"] = "api_key"
        elif "User" in method or "Invitation" in method:
            enrichments["org_operation_type"] = "user_management"
        elif "RoleBinding" in method:
            enrichments["org_operation_type"] = "rbac"
        elif "Environment" in method:
            enrichments["org_operation_type"] = "environment"
        elif "Cluster" in method or "Kafka" in method:
            enrichments["org_operation_type"] = "cluster_management"
        elif "Network" in method or "Peering" in method or "PrivateLink" in method:
            enrichments["org_operation_type"] = "networking"
        elif "Connector" in method:
            enrichments["org_operation_type"] = "connector"

        return enrichments


class AccessTransparencyHandler(EventHandler):
    """Handler for Access Transparency events (Confluent personnel access)."""

    def __init__(self):
        super().__init__("access-transparency")

    def can_handle(self, event: AuditEvent) -> bool:
        return event.is_access_transparency

    def handle(self, event: AuditEvent) -> Dict[str, Any]:
        enrichments = {
            "access_transparency_event": True,
            "confluent_access": True,
        }

        # These events are always security relevant
        enrichments["security_alert_level"] = "info"

        return enrichments


class EventRouter:
    """
    Routes audit events through appropriate handlers.

    Usage:
        router = EventRouter()
        result = router.route(raw_event)
        processed_event = result.event
    """

    def __init__(self):
        self.parser = CloudEventsParser()
        self.handlers: List[EventHandler] = [
            KafkaEventHandler(),
            SchemaRegistryEventHandler(),
            KsqlDBEventHandler(),
            FlinkEventHandler(),
            OrganizationEventHandler(),
            AccessTransparencyHandler(),
        ]

    def add_handler(self, handler: EventHandler) -> None:
        """Add a custom handler."""
        self.handlers.append(handler)

    def route(self, raw_event: Dict[str, Any]) -> RoutingResult:
        """
        Parse and route an event through appropriate handlers.

        Returns a RoutingResult with the processed event and metadata.
        """
        handlers_applied = []
        enrichments = {}
        errors = []

        # Parse the raw event
        try:
            event = self.parser.parse(raw_event)
        except Exception as e:
            logger.error(f"Failed to parse event: {e}")
            # Create minimal event
            event = AuditEvent(id=raw_event.get("id", "unknown"))
            errors.append(f"Parse error: {str(e)}")

        # Route through handlers
        for handler in self.handlers:
            try:
                if handler.can_handle(event):
                    handler_enrichments = handler.handle(event)
                    enrichments.update(handler_enrichments)
                    handlers_applied.append(handler.name)
            except Exception as e:
                logger.error(f"Handler {handler.name} failed: {e}")
                errors.append(f"Handler {handler.name}: {str(e)}")

        return RoutingResult(
            event=event,
            handlers_applied=handlers_applied,
            enrichments=enrichments,
            errors=errors,
        )

    def process_batch(self, raw_events: List[Dict[str, Any]]) -> List[RoutingResult]:
        """Process a batch of events."""
        return [self.route(event) for event in raw_events]
