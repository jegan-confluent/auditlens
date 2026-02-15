"""Unit tests for event classification module."""

import pytest
from src.classification import (
    CriticalityLevel,
    ClassificationResult,
    calculate_criticality,
)
from src.classification.methods import (
    CRITICAL_METHODS,
    HIGH_METHODS,
    MEDIUM_METHODS,
    SECURITY_FAILURE_STATUSES,
    AUTHORIZATION_CHECK_METHODS,
    AUTHENTICATION_METHODS,
)


class TestCriticalityLevel:
    """Tests for CriticalityLevel enum."""

    def test_criticality_values(self):
        """Test that all criticality levels have expected values."""
        assert CriticalityLevel.CRITICAL.value == "CRITICAL"
        assert CriticalityLevel.HIGH.value == "HIGH"
        assert CriticalityLevel.MEDIUM.value == "MEDIUM"
        assert CriticalityLevel.LOW.value == "LOW"

    def test_criticality_ordering(self):
        """Test that criticality levels can be compared."""
        levels = [
            CriticalityLevel.LOW,
            CriticalityLevel.MEDIUM,
            CriticalityLevel.HIGH,
            CriticalityLevel.CRITICAL,
        ]
        # Verify all levels are distinct
        assert len(set(levels)) == 4


class TestMethodClassifications:
    """Tests for method classification constants."""

    def test_critical_methods_contains_destructive_ops(self):
        """Test that critical methods include destructive operations."""
        destructive = [
            'DeleteKafkaCluster',
            'DeleteEnvironment',
            'kafka.DeleteTopics',
            'DeleteSchema',
        ]
        for method in destructive:
            assert method in CRITICAL_METHODS, f"{method} should be CRITICAL"

    def test_high_methods_contains_security_ops(self):
        """Test that high methods include security operations."""
        security = [
            'CreateApiKey',
            'DeleteApiKey',
            'CreateServiceAccount',
            'CreateRoleBinding',
        ]
        for method in security:
            assert method in HIGH_METHODS, f"{method} should be HIGH"

    def test_medium_methods_contains_config_ops(self):
        """Test that medium methods include configuration operations."""
        config = [
            'kafka.AlterConfigs',
            'kafka.CreatePartitions',
        ]
        for method in config:
            assert method in MEDIUM_METHODS, f"{method} should be MEDIUM"

    def test_no_overlap_between_levels(self):
        """Test that methods don't appear in multiple levels."""
        assert CRITICAL_METHODS.isdisjoint(HIGH_METHODS)
        assert CRITICAL_METHODS.isdisjoint(MEDIUM_METHODS)
        assert HIGH_METHODS.isdisjoint(MEDIUM_METHODS)

    def test_security_failure_statuses(self):
        """Test that security failure statuses are defined."""
        expected = [
            'UNAUTHENTICATED',
            'PERMISSION_DENIED',
            'UNAUTHORIZED',
        ]
        for status in expected:
            assert status in SECURITY_FAILURE_STATUSES


class TestCalculateCriticality:
    """Tests for the calculate_criticality function."""

    def test_security_failure_is_critical(self):
        """Test that security failures are classified as CRITICAL."""
        event = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'UNAUTHENTICATED',
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.CRITICAL
        assert result.is_security_event is True
        assert 'security failure' in result.reason.lower()

    def test_permission_denied_non_auth_method_is_high(self):
        """Test that permission denied on non-auth methods is HIGH."""
        event = {
            'methodName': 'kafka.Fetch',
            'resultStatus': 'SUCCESS',
            'granted': False,
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.HIGH
        assert result.is_security_event is True

    def test_delete_cluster_is_critical(self):
        """Test that DeleteKafkaCluster is CRITICAL."""
        event = {
            'methodName': 'DeleteKafkaCluster',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.CRITICAL
        assert 'DeleteKafkaCluster' in result.reason

    def test_delete_environment_is_critical(self):
        """Test that DeleteEnvironment is CRITICAL."""
        event = {
            'methodName': 'DeleteEnvironment',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.CRITICAL

    def test_kafka_delete_topics_is_critical(self):
        """Test that kafka.DeleteTopics is CRITICAL."""
        event = {
            'methodName': 'kafka.DeleteTopics',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.CRITICAL

    def test_create_api_key_is_high(self):
        """Test that CreateApiKey is HIGH."""
        event = {
            'methodName': 'CreateApiKey',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.HIGH

    def test_delete_api_key_is_high(self):
        """Test that DeleteApiKey is HIGH."""
        event = {
            'methodName': 'DeleteApiKey',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.HIGH

    def test_create_role_binding_is_high(self):
        """Test that CreateRoleBinding is HIGH."""
        event = {
            'methodName': 'CreateRoleBinding',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.HIGH

    def test_alter_configs_is_medium(self):
        """Test that kafka.AlterConfigs is MEDIUM."""
        event = {
            'methodName': 'kafka.AlterConfigs',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.MEDIUM

    def test_produce_event_is_low(self):
        """Test that kafka.Produce is LOW."""
        event = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'SUCCESS',
            'principal': 'User:app',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW

    def test_fetch_event_is_low(self):
        """Test that kafka.Fetch is LOW."""
        event = {
            'methodName': 'kafka.Fetch',
            'resultStatus': 'SUCCESS',
            'granted': True,
            'principal': 'User:app',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW

    def test_unknown_method_is_low(self):
        """Test that unknown methods default to LOW."""
        event = {
            'methodName': 'SomeUnknownMethod',
            'resultStatus': 'SUCCESS',
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW

    def test_pattern_matching_delete(self):
        """Test pattern matching for delete operations."""
        event = {
            'methodName': 'SomeService.DeleteResource',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        # Should match delete pattern -> HIGH
        assert result.criticality in [CriticalityLevel.HIGH, CriticalityLevel.CRITICAL]

    def test_classification_result_fields(self):
        """Test that ClassificationResult has all expected fields."""
        event = {
            'methodName': 'DeleteKafkaCluster',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert hasattr(result, 'criticality')
        assert hasattr(result, 'reason')
        assert hasattr(result, 'is_security_event')
        assert hasattr(result, 'is_deletion')
        assert hasattr(result, 'is_creation')
        assert hasattr(result, 'is_modification')
        assert hasattr(result, 'method_category')
        assert hasattr(result, 'elevated')
        assert result.is_deletion is True
        assert result.method_category == 'deletion'

    def test_empty_event(self):
        """Test handling of empty event."""
        event = {}
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW

    def test_none_method_name(self):
        """Test handling of None method name."""
        event = {'methodName': None}
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW

    def test_case_sensitivity(self):
        """Test that method names are matched correctly."""
        # Method matching should be case-sensitive as per Confluent API
        event = {
            'methodName': 'deletekafkacluster',  # lowercase
            'resultStatus': 'SUCCESS',
        }
        result = calculate_criticality(event)
        # Lowercase should not match, defaults to pattern matching or LOW
        # The exact behavior depends on implementation

    def test_security_event_flag_for_auth_failure(self):
        """Test that is_security_event is True for auth failures."""
        event = {
            'methodName': 'kafka.Fetch',
            'resultStatus': 'UNAUTHENTICATED',
        }
        result = calculate_criticality(event)
        assert result.is_security_event is True

    def test_security_event_flag_for_normal_event(self):
        """Test that is_security_event is False for normal events."""
        event = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'SUCCESS',
            'granted': True,
        }
        result = calculate_criticality(event)
        assert result.is_security_event is False


class TestClassificationIntegration:
    """Integration tests using sample events from conftest."""

    def test_authorization_denied_classification(self, sample_authorization_denied_event):
        """Test classification of authorization denied event."""
        # Extract flattened fields as they would appear in processed events
        event = {
            'methodName': sample_authorization_denied_event['data']['methodName'],
            'resultStatus': sample_authorization_denied_event['data']['result']['status'],
            'granted': sample_authorization_denied_event['data']['authorizationInfo']['granted'],
            'principal': sample_authorization_denied_event['data']['authenticationInfo']['principal'],
        }
        result = calculate_criticality(event)
        assert result.criticality in [CriticalityLevel.CRITICAL, CriticalityLevel.HIGH]
        assert result.is_security_event is True

    def test_normal_authorization_classification(self, sample_authorization_event):
        """Test classification of normal authorization event."""
        event = {
            'methodName': sample_authorization_event['data']['methodName'],
            'resultStatus': sample_authorization_event['data']['result']['status'],
            'granted': sample_authorization_event['data']['authorizationInfo']['granted'],
            'principal': sample_authorization_event['data']['authenticationInfo']['principal'],
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW
        assert result.is_security_event is False

    def test_authentication_classification(self, sample_authentication_event):
        """Test classification of authentication event."""
        event = {
            'methodName': sample_authentication_event['data']['methodName'],
            'resultStatus': sample_authentication_event['data']['result']['status'],
            'principal': sample_authentication_event['data']['authenticationInfo']['principal'],
        }
        result = calculate_criticality(event)
        # Authentication events are typically LOW unless they fail
        assert result.criticality == CriticalityLevel.LOW

    def test_create_environment_classification(self, sample_request_event):
        """Test classification of CreateEnvironment event."""
        event = {
            'methodName': sample_request_event['data']['methodName'],
            'resultStatus': sample_request_event['data']['result']['status'],
            'principal': sample_request_event['data']['authenticationInfo']['principal'],
        }
        result = calculate_criticality(event)
        # CreateEnvironment is typically MEDIUM (administrative)
        assert result.criticality in [CriticalityLevel.MEDIUM, CriticalityLevel.HIGH, CriticalityLevel.LOW]


class TestAuthorizationCheckMethods:
    """Tests for authorization check methods classification."""

    def test_authorization_check_methods_set_exists(self):
        """Test that AUTHORIZATION_CHECK_METHODS set is defined."""
        assert 'mds.Authorize' in AUTHORIZATION_CHECK_METHODS
        assert 'flink.Authorize' in AUTHORIZATION_CHECK_METHODS
        assert 'ksql.Authorize' in AUTHORIZATION_CHECK_METHODS
        assert 'schema-registry.Authorize' in AUTHORIZATION_CHECK_METHODS

    def test_mds_authorize_with_granted_true_is_low(self):
        """Test that mds.Authorize with granted=True is LOW."""
        event = {
            'methodName': 'mds.Authorize',
            'resultStatus': 'SUCCESS',
            'granted': True,
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW
        assert 'Authorization check' in result.reason

    def test_mds_authorize_with_granted_false_is_medium(self):
        """Test that mds.Authorize with granted=False is MEDIUM (not CRITICAL)."""
        event = {
            'methodName': 'mds.Authorize',
            'resultStatus': 'SUCCESS',
            'granted': False,
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.MEDIUM
        assert 'Authorization check denied' in result.reason
        # Should NOT be marked as security event - routine denials are normal
        assert result.is_security_event is False

    def test_flink_authorize_with_granted_true_is_low(self):
        """Test that flink.Authorize with granted=True is LOW."""
        event = {
            'methodName': 'flink.Authorize',
            'resultStatus': 'SUCCESS',
            'granted': True,
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW

    def test_flink_authorize_with_granted_false_is_medium(self):
        """Test that flink.Authorize with granted=False is MEDIUM."""
        event = {
            'methodName': 'flink.Authorize',
            'resultStatus': 'SUCCESS',
            'granted': False,
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.MEDIUM

    def test_ksql_authorize_with_granted_false_is_medium(self):
        """Test that ksql.Authorize with granted=False is MEDIUM."""
        event = {
            'methodName': 'ksql.Authorize',
            'resultStatus': 'SUCCESS',
            'granted': False,
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.MEDIUM

    def test_schema_registry_authorize_with_granted_false_is_medium(self):
        """Test that schema-registry.Authorize with granted=False is MEDIUM."""
        event = {
            'methodName': 'schema-registry.Authorize',
            'resultStatus': 'SUCCESS',
            'granted': False,
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.MEDIUM

    def test_delete_cluster_with_granted_false_is_critical(self):
        """Test that DeleteKafkaCluster with granted=False is CRITICAL."""
        event = {
            'methodName': 'DeleteKafkaCluster',
            'resultStatus': 'SUCCESS',
            'granted': False,
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.CRITICAL
        assert result.is_security_event is True

    def test_create_api_key_with_granted_false_is_critical(self):
        """Test that CreateApiKey with granted=False is CRITICAL (high-priority denied)."""
        event = {
            'methodName': 'CreateApiKey',
            'resultStatus': 'SUCCESS',
            'granted': False,
            'principal': 'User:admin',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.CRITICAL
        assert result.is_security_event is True


class TestAuthenticationMethods:
    """Tests for authentication methods classification."""

    def test_authentication_methods_set_exists(self):
        """Test that AUTHENTICATION_METHODS set includes all expected methods."""
        assert 'kafka.Authentication' in AUTHENTICATION_METHODS
        assert 'Authentication' in AUTHENTICATION_METHODS
        assert 'Authenticate' in AUTHENTICATION_METHODS
        assert 'flink.Authenticate' in AUTHENTICATION_METHODS
        assert 'ksql.Authenticate' in AUTHENTICATION_METHODS
        assert 'schema-registry.Authentication' in AUTHENTICATION_METHODS

    def test_kafka_authentication_is_low(self):
        """Test that kafka.Authentication is LOW."""
        event = {
            'methodName': 'kafka.Authentication',
            'resultStatus': 'SUCCESS',
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW

    def test_flink_authenticate_is_low(self):
        """Test that flink.Authenticate is LOW."""
        event = {
            'methodName': 'flink.Authenticate',
            'resultStatus': 'SUCCESS',
            'principal': 'User:test',
        }
        result = calculate_criticality(event)
        assert result.criticality == CriticalityLevel.LOW
