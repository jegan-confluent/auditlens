"""Pytest configuration and fixtures."""

import pytest
import asyncio
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_authentication_event():
    """Sample authentication audit event."""
    return {
        "id": "auth-event-001",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org-123/environment=env-456/kafka=lkc-789",
        "type": "io.confluent.kafka.server/authentication",
        "time": "2025-01-15T10:30:00.000Z",
        "subject": "crn://confluent.cloud/organization=org-123/environment=env-456/kafka=lkc-789",
        "datacontenttype": "application/json",
        "data": {
            "authenticationInfo": {
                "principal": "User:sa-service-account"
            },
            "methodName": "kafka.Authentication",
            "serviceName": "crn://confluent.cloud/organization=org-123/environment=env-456/kafka=lkc-789",
            "resourceName": "kafka",
            "result": {
                "status": "SUCCESS"
            },
            "requestMetadata": {
                "clientAddress": "192.168.1.100"
            }
        }
    }


@pytest.fixture
def sample_authorization_event():
    """Sample authorization audit event."""
    return {
        "id": "authz-event-001",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org-123/environment=env-456/kafka=lkc-789",
        "type": "io.confluent.kafka.server/authorization",
        "time": "2025-01-15T10:31:00.000Z",
        "data": {
            "authenticationInfo": {
                "principal": "User:sa-service-account"
            },
            "authorizationInfo": {
                "resourceType": "Topic",
                "resourceName": "test-topic",
                "operation": "Write",
                "patternType": "LITERAL",
                "granted": True
            },
            "methodName": "kafka.Produce",
            "result": {
                "status": "SUCCESS"
            }
        }
    }


@pytest.fixture
def sample_authorization_denied_event():
    """Sample authorization denied audit event."""
    return {
        "id": "authz-denied-001",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org-123/environment=env-456/kafka=lkc-789",
        "type": "io.confluent.kafka.server/authorization",
        "time": "2025-01-15T10:32:00.000Z",
        "data": {
            "authenticationInfo": {
                "principal": "User:unauthorized-user"
            },
            "authorizationInfo": {
                "resourceType": "Topic",
                "resourceName": "restricted-topic",
                "operation": "Read",
                "patternType": "LITERAL",
                "granted": False
            },
            "methodName": "kafka.Fetch",
            "result": {
                "status": "PERMISSION_DENIED",
                "message": "User not authorized to access topic"
            }
        }
    }


@pytest.fixture
def sample_access_transparency_event():
    """Sample access transparency audit event."""
    return {
        "id": "transparency-001",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org-123",
        "type": "io.confluent.cloud/access-transparency",
        "time": "2025-01-15T10:33:00.000Z",
        "data": {
            "authenticationInfo": {
                "principal": "confluent-support@confluent.io"
            },
            "methodName": "SupportAccess",
            "serviceName": "support",
            "result": {
                "status": "SUCCESS"
            },
            "accessTransparency": {
                "reason": "Customer-initiated support ticket",
                "caseNumber": "CS-2025-12345",
                "accessedBy": "support-engineer@confluent.io"
            }
        }
    }


@pytest.fixture
def sample_request_event():
    """Sample cloud request audit event."""
    return {
        "id": "request-001",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org-123",
        "type": "io.confluent.cloud/request",
        "time": "2025-01-15T10:34:00.000Z",
        "data": {
            "authenticationInfo": {
                "principal": "User:admin@example.com"
            },
            "methodName": "CreateEnvironment",
            "serviceName": "organization",
            "request": {
                "environmentName": "production",
                "region": "us-west-2"
            },
            "result": {
                "status": "SUCCESS"
            }
        }
    }


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    return {
        "audit_bootstrap": "localhost:9092",
        "audit_api_key": "test-key",
        "audit_api_secret": "test-secret",
        "audit_topics": ["confluent-audit-log-events"],
        "consumer_group_id": "test-consumer-group",
        "dest_bootstrap": "localhost:9092",
        "dest_api_key": "test-dest-key",
        "dest_api_secret": "test-dest-secret",
        "dest_topic": "audit-logs-processed",
        "s3_enabled": False,
        "gcs_enabled": False,
        "mcp_enabled": True,
        "metrics_port": 8000,
        "health_port": 8001
    }
