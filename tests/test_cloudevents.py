"""Tests for CloudEvents Parser."""

import pytest
from datetime import datetime
from src.transformer.cloudevents import CloudEventsParser, AuditEvent


class TestCloudEventsParser:
    """Test CloudEvents parsing functionality."""

    def setup_method(self):
        self.parser = CloudEventsParser()

    def test_parse_authentication_event(self):
        """Test parsing an authentication audit event."""
        raw_event = {
            "id": "event-123",
            "specversion": "1.0",
            "source": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
            "type": "io.confluent.kafka.server/authentication",
            "time": "2025-01-15T10:30:00.000Z",
            "subject": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
            "data": {
                "authenticationInfo": {
                    "principal": "User:sa-abc123"
                },
                "methodName": "kafka.Authentication",
                "serviceName": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
                "result": {
                    "status": "SUCCESS"
                }
            }
        }

        result = self.parser.parse(raw_event)

        assert isinstance(result, AuditEvent)
        assert result.id == "event-123"
        assert result.specversion == "1.0"
        assert result.event_type == "io.confluent.kafka.server/authentication"
        assert result.principal == "User:sa-abc123"
        assert result.result_status == "SUCCESS"
        assert result.service_category == "kafka"

    def test_parse_authorization_event(self):
        """Test parsing an authorization audit event."""
        raw_event = {
            "id": "event-456",
            "specversion": "1.0",
            "source": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
            "type": "io.confluent.kafka.server/authorization",
            "time": "2025-01-15T10:31:00.000Z",
            "data": {
                "authenticationInfo": {
                    "principal": "User:sa-abc123"
                },
                "authorizationInfo": {
                    "resourceType": "Topic",
                    "resourceName": "audit-logs",
                    "operation": "Write",
                    "patternType": "LITERAL"
                },
                "methodName": "kafka.Produce",
                "result": {
                    "status": "PERMISSION_DENIED",
                    "message": "User not authorized"
                }
            }
        }

        result = self.parser.parse(raw_event)

        assert result.event_type == "io.confluent.kafka.server/authorization"
        assert result.result_status == "PERMISSION_DENIED"
        assert result.result_message == "User not authorized"
        assert result.is_security_event is True

    def test_parse_request_event(self):
        """Test parsing a cloud request audit event."""
        raw_event = {
            "id": "event-789",
            "specversion": "1.0",
            "source": "crn://confluent.cloud/organization=org1",
            "type": "io.confluent.cloud/request",
            "time": "2025-01-15T10:32:00.000Z",
            "data": {
                "authenticationInfo": {
                    "principal": "User:admin@example.com"
                },
                "methodName": "CreateKafkaCluster",
                "serviceName": "kafka",
                "result": {
                    "status": "SUCCESS"
                }
            }
        }

        result = self.parser.parse(raw_event)

        assert result.event_type == "io.confluent.cloud/request"
        assert result.method_name == "CreateKafkaCluster"
        assert result.service_category == "organization"

    def test_parse_access_transparency_event(self):
        """Test parsing an access transparency event."""
        raw_event = {
            "id": "event-transparency-1",
            "specversion": "1.0",
            "source": "crn://confluent.cloud/organization=org1",
            "type": "io.confluent.cloud/access-transparency",
            "time": "2025-01-15T10:33:00.000Z",
            "data": {
                "authenticationInfo": {
                    "principal": "confluent-support@confluent.io"
                },
                "methodName": "SupportAccess",
                "result": {
                    "status": "SUCCESS"
                },
                "accessTransparency": {
                    "reason": "Customer support request",
                    "caseNumber": "CS-12345"
                }
            }
        }

        result = self.parser.parse(raw_event)

        assert result.event_type == "io.confluent.cloud/access-transparency"
        assert result.is_access_transparency is True
        assert result.principal == "confluent-support@confluent.io"

    def test_parse_with_crn_decomposition(self):
        """Test that CRN is properly decomposed."""
        raw_event = {
            "id": "event-crn-test",
            "specversion": "1.0",
            "source": "crn://confluent.cloud/organization=org123/environment=env456/kafka=lkc-789",
            "type": "io.confluent.kafka.server/authentication",
            "time": "2025-01-15T10:34:00.000Z",
            "data": {
                "result": {"status": "SUCCESS"}
            }
        }

        result = self.parser.parse(raw_event)

        assert result.organization_id == "org123"
        assert result.environment_id == "env456"
        assert result.cluster_id == "lkc-789"
        assert result.cluster_type == "kafka"

    def test_parse_timestamp_formats(self):
        """Test parsing various timestamp formats."""
        # ISO 8601 with milliseconds
        raw_event = {
            "id": "event-time-1",
            "specversion": "1.0",
            "type": "io.confluent.kafka.server/authentication",
            "time": "2025-01-15T10:30:00.123Z",
            "data": {"result": {"status": "SUCCESS"}}
        }

        result = self.parser.parse(raw_event)
        assert result.timestamp is not None

    def test_parse_missing_optional_fields(self):
        """Test parsing event with missing optional fields."""
        raw_event = {
            "id": "minimal-event",
            "specversion": "1.0",
            "type": "io.confluent.kafka.server/authentication",
            "data": {}
        }

        result = self.parser.parse(raw_event)

        assert result.id == "minimal-event"
        assert result.specversion == "1.0"
        assert result.source is None
        assert result.principal is None

    def test_classify_security_event(self):
        """Test security event classification."""
        # UNAUTHENTICATED should be security event
        raw_event = {
            "id": "sec-event-1",
            "specversion": "1.0",
            "type": "io.confluent.kafka.server/authentication",
            "data": {
                "result": {"status": "UNAUTHENTICATED"}
            }
        }

        result = self.parser.parse(raw_event)
        assert result.is_security_event is True

    def test_audit_event_to_dict(self):
        """Test AuditEvent to_dict method."""
        raw_event = {
            "id": "dict-test",
            "specversion": "1.0",
            "source": "crn://confluent.cloud/organization=org1",
            "type": "io.confluent.kafka.server/authentication",
            "time": "2025-01-15T10:30:00.000Z",
            "data": {
                "authenticationInfo": {"principal": "User:test"},
                "result": {"status": "SUCCESS"}
            }
        }

        result = self.parser.parse(raw_event)
        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["id"] == "dict-test"
        assert result_dict["specversion"] == "1.0"
        assert "timestamp" in result_dict

    def test_parse_schema_registry_event(self):
        """Test parsing Schema Registry event."""
        raw_event = {
            "id": "sr-event-1",
            "specversion": "1.0",
            "source": "crn://confluent.cloud/organization=org1/environment=env1/schema-registry=lsrc-123",
            "type": "io.confluent.kafka.schemaregistry/authentication",
            "data": {
                "result": {"status": "SUCCESS"}
            }
        }

        result = self.parser.parse(raw_event)
        assert result.service_category == "schema-registry"
        assert result.cluster_type == "schema-registry"

    def test_parse_ksqldb_event(self):
        """Test parsing ksqlDB event."""
        raw_event = {
            "id": "ksql-event-1",
            "specversion": "1.0",
            "source": "crn://confluent.cloud/organization=org1/environment=env1/ksqldb=lksqlc-123",
            "type": "io.confluent.ksqldb/authorization",
            "data": {
                "result": {"status": "SUCCESS"}
            }
        }

        result = self.parser.parse(raw_event)
        assert result.service_category == "ksqldb"
