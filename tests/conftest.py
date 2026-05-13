"""Pytest configuration and fixtures for audit forwarder tests."""

import pytest
import asyncio


# Configure pytest-asyncio to use auto mode
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def sample_authentication_event():
    """Sample authentication event for testing."""
    return {
        "id": "test-event-001",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
        "type": "io.confluent.kafka.server/authentication",
        "time": "2025-01-15T10:30:00.000Z",
        "subject": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
        "data": {
            "authenticationInfo": {
                "principal": "User:sa-test123"
            },
            "methodName": "kafka.Authentication",
            "serviceName": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
            "result": {
                "status": "SUCCESS"
            }
        }
    }


@pytest.fixture
def sample_authorization_event():
    """Sample authorization event for testing."""
    return {
        "id": "test-event-002",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
        "type": "io.confluent.kafka.server/authorization",
        "time": "2025-01-15T10:31:00.000Z",
        "data": {
            "authenticationInfo": {
                "principal": "User:sa-test123"
            },
            "authorizationInfo": {
                "granted": True,
                "operation": "Write",
                "resourceType": "Topic",
                "resourceName": "test-topic"
            },
            "methodName": "kafka.Produce",
            "result": {
                "status": "SUCCESS"
            }
        }
    }


@pytest.fixture
def sample_security_event():
    """Sample security failure event for testing."""
    return {
        "id": "test-event-003",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
        "type": "io.confluent.kafka.server/authorization",
        "time": "2025-01-15T10:32:00.000Z",
        "data": {
            "authenticationInfo": {
                "principal": "User:unauthorized-user"
            },
            "authorizationInfo": {
                "granted": False,
                "operation": "Read",
                "resourceType": "Topic",
                "resourceName": "sensitive-data"
            },
            "methodName": "kafka.Fetch",
            "result": {
                "status": "PERMISSION_DENIED",
                "message": "User not authorized to read from topic"
            }
        }
    }


@pytest.fixture
def sample_authorization_denied_event():
    """Sample authorization denied event for testing."""
    return {
        "id": "test-event-004",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123",
        "type": "io.confluent.kafka.server/authorization",
        "time": "2025-01-15T10:33:00.000Z",
        "data": {
            "authenticationInfo": {
                "principal": "User:attacker"
            },
            "authorizationInfo": {
                "granted": False,
                "operation": "Write",
                "resourceType": "Topic",
                "resourceName": "production-data"
            },
            "methodName": "kafka.Produce",
            "result": {
                "status": "PERMISSION_DENIED",
                "message": "Access denied"
            }
        }
    }


@pytest.fixture
def sample_request_event():
    """Sample cloud request event for testing."""
    return {
        "id": "test-event-005",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org1",
        "type": "io.confluent.cloud/request",
        "time": "2025-01-15T10:34:00.000Z",
        "data": {
            "authenticationInfo": {
                "principal": "User:admin@example.com"
            },
            "methodName": "CreateEnvironment",
            "serviceName": "organization",
            "result": {
                "status": "SUCCESS"
            }
        }
    }

import os
import pytest

@pytest.fixture(autouse=True)
def _clear_confluent_credentials(request):
    """Ensure CONFLUENT_CLOUD_API_KEY/SECRET don't leak between tests.
    Tests that explicitly need credentials should set them via monkeypatch.
    """
    marker = request.node.get_closest_marker("needs_confluent_credentials")
    if marker:
        yield
        return
    saved_key = os.environ.pop("CONFLUENT_CLOUD_API_KEY", None)
    saved_secret = os.environ.pop("CONFLUENT_CLOUD_API_SECRET", None)
    yield
    if saved_key is not None:
        os.environ["CONFLUENT_CLOUD_API_KEY"] = saved_key
    if saved_secret is not None:
        os.environ["CONFLUENT_CLOUD_API_SECRET"] = saved_secret
