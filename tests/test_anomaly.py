"""Unit tests for anomaly detection module."""

import pytest
import time
from unittest.mock import patch, MagicMock
from src.anomaly import (
    RateTracker,
    RateTrackerConfig,
    AnomalyType,
    AnomalyAlert,
)
from src.anomaly.rate_tracker import RateCounter


class TestRateTrackerConfig:
    """Tests for RateTrackerConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RateTrackerConfig()
        assert config.window_seconds == 60
        assert config.auth_failure_threshold == 10
        assert config.activity_spike_threshold == 100
        assert config.deletion_threshold == 5
        assert config.api_key_threshold == 10
        assert config.enable_auth_failure_detection is True
        assert config.enable_activity_spike_detection is True
        assert config.enable_deletion_detection is True
        assert config.enable_api_key_detection is True

    def test_config_from_env(self):
        """Test configuration from environment variables."""
        env_vars = {
            'ANOMALY_WINDOW_SECONDS': '120',
            'ANOMALY_AUTH_FAILURE_THRESHOLD': '20',
            'ANOMALY_ACTIVITY_SPIKE_THRESHOLD': '200',
            'ANOMALY_DELETION_THRESHOLD': '10',
            'ANOMALY_API_KEY_THRESHOLD': '15',
            'ANOMALY_ENABLE_AUTH': 'false',
            'ANOMALY_ENABLE_ACTIVITY': 'true',
            'ANOMALY_ENABLE_DELETION': 'false',
            'ANOMALY_ENABLE_API_KEY': 'true',
        }
        with patch.dict('os.environ', env_vars, clear=False):
            config = RateTrackerConfig.from_env()
            assert config.window_seconds == 120
            assert config.auth_failure_threshold == 20
            assert config.activity_spike_threshold == 200
            assert config.deletion_threshold == 10
            assert config.api_key_threshold == 15
            assert config.enable_auth_failure_detection is False
            assert config.enable_activity_spike_detection is True
            assert config.enable_deletion_detection is False
            assert config.enable_api_key_detection is True


class TestRateCounter:
    """Tests for RateCounter class."""

    def test_rate_counter_creation(self):
        """Test creating a RateCounter."""
        counter = RateCounter(window_seconds=60)
        assert counter.window_seconds == 60

    def test_add_event(self):
        """Test adding events to counter."""
        counter = RateCounter(window_seconds=60)
        counter.add_event()
        count, rate = counter.get_rate()
        assert count == 1

    def test_get_rate_calculation(self):
        """Test rate calculation."""
        counter = RateCounter(window_seconds=60)
        # Add 30 events
        for _ in range(30):
            counter.add_event()
        count, rate = counter.get_rate()
        assert count == 30
        # Rate should be 30 events per 60 seconds = 30 events per minute
        assert rate == 30.0

    def test_events_expire_outside_window(self):
        """Test that events outside window are cleaned up."""
        counter = RateCounter(window_seconds=1)  # 1 second window
        counter.add_event()
        count1, _ = counter.get_rate()
        assert count1 == 1

        # Wait for events to expire
        time.sleep(1.5)
        count2, _ = counter.get_rate()
        assert count2 == 0


class TestAnomalyAlert:
    """Tests for AnomalyAlert dataclass."""

    def test_alert_creation(self):
        """Test creating an AnomalyAlert."""
        from datetime import datetime, timezone
        alert = AnomalyAlert(
            anomaly_type=AnomalyType.AUTH_FAILURE_SPIKE,
            severity='CRITICAL',
            principal='User:test',
            source_ip='192.168.1.1',
            rate=15.0,
            threshold=10,
            window_seconds=60,
            timestamp=datetime.now(timezone.utc),
            details={'failure_count': 15},
        )
        assert alert.anomaly_type == AnomalyType.AUTH_FAILURE_SPIKE
        assert alert.severity == 'CRITICAL'
        assert alert.principal == 'User:test'
        assert alert.rate == 15.0

    def test_alert_to_dict(self):
        """Test converting alert to dictionary."""
        from datetime import datetime, timezone
        alert = AnomalyAlert(
            anomaly_type=AnomalyType.ACTIVITY_SPIKE,
            severity='HIGH',
            principal='User:admin',
            source_ip='10.0.0.1',
            rate=150.0,
            threshold=100,
            window_seconds=60,
            timestamp=datetime.now(timezone.utc),
        )
        result = alert.to_dict()
        assert result['anomaly_type'] == 'activity_spike'
        assert result['severity'] == 'HIGH'
        assert result['principal'] == 'User:admin'
        assert result['rate'] == 150.0
        assert 'timestamp' in result


class TestAnomalyType:
    """Tests for AnomalyType enum."""

    def test_anomaly_types(self):
        """Test that all expected anomaly types exist."""
        assert AnomalyType.AUTH_FAILURE_SPIKE.value == 'auth_failure_spike'
        assert AnomalyType.ACTIVITY_SPIKE.value == 'activity_spike'
        assert AnomalyType.NEW_SOURCE_IP.value == 'new_source_ip'
        assert AnomalyType.UNUSUAL_HOUR.value == 'unusual_hour'
        assert AnomalyType.RAPID_DELETIONS.value == 'rapid_deletions'
        assert AnomalyType.API_KEY_ABUSE.value == 'api_key_abuse'


class TestRateTracker:
    """Tests for RateTracker class."""

    def test_tracker_initialization(self):
        """Test RateTracker initialization."""
        config = RateTrackerConfig()
        tracker = RateTracker(config)
        assert tracker.config == config

    def test_track_normal_event(self):
        """Test tracking a normal event produces no alerts."""
        config = RateTrackerConfig(
            activity_spike_threshold=100,
            auth_failure_threshold=10,
        )
        tracker = RateTracker(config)

        event = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'SUCCESS',
            'principal': 'User:app',
            'clientIp': '192.168.1.1',
        }

        alerts = tracker.track_event(event)
        assert len(alerts) == 0

    def test_detect_auth_failure_spike(self):
        """Test detection of authentication failure spike."""
        config = RateTrackerConfig(
            auth_failure_threshold=5,  # Low threshold for testing
            window_seconds=60,
        )
        tracker = RateTracker(config)

        # Generate auth failures exceeding threshold
        for i in range(6):
            event = {
                'methodName': 'kafka.Produce',
                'resultStatus': 'UNAUTHENTICATED',
                'principal': 'User:attacker',
                'clientIp': '10.0.0.1',
            }
            alerts = tracker.track_event(event)

        # Should detect auth failure spike
        assert len(alerts) > 0
        assert any(a.anomaly_type == AnomalyType.AUTH_FAILURE_SPIKE for a in alerts)

    def test_detect_permission_denied_spike(self):
        """Test detection of permission denied spike."""
        config = RateTrackerConfig(
            auth_failure_threshold=5,
            window_seconds=60,
        )
        tracker = RateTracker(config)

        # Generate permission denied events
        for i in range(6):
            event = {
                'methodName': 'kafka.Fetch',
                'resultStatus': 'PERMISSION_DENIED',
                'granted': False,
                'principal': 'User:unauthorized',
                'clientIp': '10.0.0.2',
            }
            alerts = tracker.track_event(event)

        # Should detect auth failure spike
        assert len(alerts) > 0
        assert any(a.anomaly_type == AnomalyType.AUTH_FAILURE_SPIKE for a in alerts)

    def test_detect_activity_spike(self):
        """Test detection of activity spike."""
        config = RateTrackerConfig(
            activity_spike_threshold=10,  # Low threshold for testing
            window_seconds=60,
        )
        tracker = RateTracker(config)

        # Generate many events from same principal
        all_alerts = []
        for i in range(15):
            event = {
                'methodName': 'kafka.Produce',
                'resultStatus': 'SUCCESS',
                'principal': 'User:hyperactive',
                'clientIp': '192.168.1.1',
            }
            alerts = tracker.track_event(event)
            all_alerts.extend(alerts)

        # Should detect activity spike
        assert len(all_alerts) > 0
        assert any(a.anomaly_type == AnomalyType.ACTIVITY_SPIKE for a in all_alerts)

    def test_detect_rapid_deletions(self):
        """Test detection of rapid deletion operations."""
        config = RateTrackerConfig(
            deletion_threshold=3,  # Low threshold for testing
            window_seconds=60,
        )
        tracker = RateTracker(config)

        # Generate delete operations
        all_alerts = []
        for i in range(5):
            event = {
                'methodName': 'kafka.DeleteTopics',
                'resultStatus': 'SUCCESS',
                'principal': 'User:deleter',
                'clientIp': '192.168.1.1',
            }
            alerts = tracker.track_event(event)
            all_alerts.extend(alerts)

        # Should detect rapid deletions
        assert any(a.anomaly_type == AnomalyType.RAPID_DELETIONS for a in all_alerts)

    def test_detect_api_key_abuse(self):
        """Test detection of API key operation abuse."""
        config = RateTrackerConfig(
            api_key_threshold=5,  # Low threshold for testing
            window_seconds=60,
        )
        tracker = RateTracker(config)

        # Generate API key operations
        all_alerts = []
        for i in range(6):
            event = {
                'methodName': 'CreateApiKey',
                'resultStatus': 'SUCCESS',
                'principal': 'User:apikey-abuser',
                'clientIp': '192.168.1.1',
            }
            alerts = tracker.track_event(event)
            all_alerts.extend(alerts)

        # Should detect API key abuse
        assert any(a.anomaly_type == AnomalyType.API_KEY_ABUSE for a in all_alerts)

    def test_detect_new_source_ip(self):
        """Test detection of new source IP."""
        config = RateTrackerConfig()
        tracker = RateTracker(config)

        # First, establish a known IP
        event1 = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'SUCCESS',
            'principal': 'User:test',
            'clientIp': '192.168.1.1',
        }
        tracker.track_event(event1)

        # Now use a new IP
        event2 = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'SUCCESS',
            'principal': 'User:test',
            'clientIp': '10.0.0.99',  # New IP
        }
        alerts = tracker.track_event(event2)

        # Should detect new source IP
        assert any(a.anomaly_type == AnomalyType.NEW_SOURCE_IP for a in alerts)

    def test_alert_cooldown(self):
        """Test that alerts have a cooldown period."""
        config = RateTrackerConfig(
            auth_failure_threshold=2,
            window_seconds=60,
        )
        tracker = RateTracker(config)
        tracker._alert_cooldown = 1  # 1 second cooldown for testing

        # Generate alerts
        events = [
            {
                'methodName': 'kafka.Produce',
                'resultStatus': 'UNAUTHENTICATED',
                'principal': 'User:test',
                'clientIp': '192.168.1.1',
            }
            for _ in range(5)
        ]

        all_alerts = []
        for event in events:
            alerts = tracker.track_event(event)
            all_alerts.extend(alerts)

        # Should have exactly 1 alert due to cooldown
        auth_alerts = [a for a in all_alerts if a.anomaly_type == AnomalyType.AUTH_FAILURE_SPIKE]
        assert len(auth_alerts) == 1

        # Wait for cooldown
        time.sleep(1.5)

        # Generate more events
        for _ in range(3):
            alerts = tracker.track_event(events[0])
            all_alerts.extend(alerts)

        # Should now have 2 auth failure alerts
        auth_alerts = [a for a in all_alerts if a.anomaly_type == AnomalyType.AUTH_FAILURE_SPIKE]
        assert len(auth_alerts) == 2

    def test_on_alert_callback(self):
        """Test that on_alert callback is called."""
        callback_alerts = []

        def capture_alert(alert):
            callback_alerts.append(alert)

        config = RateTrackerConfig(
            auth_failure_threshold=2,
            window_seconds=60,
        )
        tracker = RateTracker(config, on_alert=capture_alert)

        # Generate alerts
        for _ in range(5):
            event = {
                'methodName': 'kafka.Produce',
                'resultStatus': 'UNAUTHENTICATED',
                'principal': 'User:test',
                'clientIp': '192.168.1.1',
            }
            tracker.track_event(event)

        # Callback should have been invoked
        assert len(callback_alerts) > 0

    def test_disabled_detection(self):
        """Test that disabled detection types don't produce alerts."""
        config = RateTrackerConfig(
            auth_failure_threshold=2,
            enable_auth_failure_detection=False,
            window_seconds=60,
        )
        tracker = RateTracker(config)

        # Generate auth failures
        for _ in range(10):
            event = {
                'methodName': 'kafka.Produce',
                'resultStatus': 'UNAUTHENTICATED',
                'principal': 'User:test',
                'clientIp': '192.168.1.1',
            }
            alerts = tracker.track_event(event)

        # Should not have any auth failure alerts
        # (detection is disabled)

    def test_get_stats(self):
        """Test getting tracking statistics."""
        config = RateTrackerConfig()
        tracker = RateTracker(config)

        # Track some events
        events = [
            {'methodName': 'kafka.Produce', 'resultStatus': 'SUCCESS', 'principal': 'User:a', 'clientIp': '10.0.0.1'},
            {'methodName': 'kafka.Produce', 'resultStatus': 'SUCCESS', 'principal': 'User:b', 'clientIp': '10.0.0.2'},
            {'methodName': 'kafka.Fetch', 'resultStatus': 'SUCCESS', 'principal': 'User:a', 'clientIp': '10.0.0.1'},
        ]

        for event in events:
            tracker.track_event(event)

        stats = tracker.get_stats()
        assert 'tracked_principals' in stats
        assert stats['tracked_principals'] >= 2
        assert 'tracked_ips' in stats
        assert stats['tracked_ips'] >= 2

    def test_get_principal_rates(self):
        """Test getting rates for a specific principal."""
        config = RateTrackerConfig()
        tracker = RateTracker(config)

        # Track events for a principal
        for _ in range(5):
            event = {
                'methodName': 'kafka.Produce',
                'resultStatus': 'SUCCESS',
                'principal': 'User:test-principal',
                'clientIp': '192.168.1.1',
            }
            tracker.track_event(event)

        rates = tracker.get_principal_rates('User:test-principal')
        assert 'activity_rate' in rates
        assert rates['activity_rate'] > 0
        assert 'auth_failure_rate' in rates
        assert 'deletion_rate' in rates
        assert 'api_key_rate' in rates

    def test_cleanup(self):
        """Test cleanup of old tracking data."""
        config = RateTrackerConfig(
            data_retention_seconds=1,  # Short retention for testing
            window_seconds=1,
        )
        tracker = RateTracker(config)

        # Track events
        event = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'SUCCESS',
            'principal': 'User:temp',
            'clientIp': '192.168.1.1',
        }
        tracker.track_event(event)

        stats1 = tracker.get_stats()
        assert stats1['tracked_principals'] > 0

        # Wait for data to expire
        time.sleep(2)

        # Cleanup
        tracker.cleanup()

        stats2 = tracker.get_stats()
        # Should have cleaned up the empty counters
        assert stats2['tracked_principals'] <= stats1['tracked_principals']

    def test_empty_event(self):
        """Test handling of empty event."""
        config = RateTrackerConfig()
        tracker = RateTracker(config)

        alerts = tracker.track_event({})
        assert len(alerts) == 0

    def test_event_without_principal(self):
        """Test handling of event without principal."""
        config = RateTrackerConfig()
        tracker = RateTracker(config)

        event = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'SUCCESS',
        }
        alerts = tracker.track_event(event)
        assert len(alerts) == 0  # Should return early


class TestRateTrackerIntegration:
    """Integration tests for RateTracker."""

    def test_complex_attack_scenario(self):
        """Test detection of a simulated attack scenario."""
        config = RateTrackerConfig(
            auth_failure_threshold=5,
            activity_spike_threshold=20,
            deletion_threshold=3,
            window_seconds=60,
        )
        tracker = RateTracker(config)

        all_alerts = []

        # Phase 1: Attacker tries to authenticate repeatedly
        for i in range(10):
            event = {
                'methodName': 'kafka.Authentication',
                'resultStatus': 'UNAUTHENTICATED',
                'principal': 'User:attacker',
                'clientIp': '203.0.113.1',
            }
            alerts = tracker.track_event(event)
            all_alerts.extend(alerts)

        # Should detect auth failure spike
        assert any(a.anomaly_type == AnomalyType.AUTH_FAILURE_SPIKE for a in all_alerts)
        assert any(a.source_ip == '203.0.113.1' for a in all_alerts)

    def test_multiple_principals_independent(self):
        """Test that tracking is independent per principal."""
        config = RateTrackerConfig(
            auth_failure_threshold=3,
            window_seconds=60,
        )
        tracker = RateTracker(config)

        # User A has failures
        for _ in range(2):
            tracker.track_event({
                'methodName': 'kafka.Produce',
                'resultStatus': 'UNAUTHENTICATED',
                'principal': 'User:A',
                'clientIp': '10.0.0.1',
            })

        # User B has failures
        for _ in range(2):
            tracker.track_event({
                'methodName': 'kafka.Produce',
                'resultStatus': 'UNAUTHENTICATED',
                'principal': 'User:B',
                'clientIp': '10.0.0.2',
            })

        # Neither should trigger yet (threshold is 3)
        rates_a = tracker.get_principal_rates('User:A')
        rates_b = tracker.get_principal_rates('User:B')

        # Each should have 2 failures, not 4
        assert rates_a['auth_failure_rate'] < config.auth_failure_threshold * (60 / config.window_seconds)
        assert rates_b['auth_failure_rate'] < config.auth_failure_threshold * (60 / config.window_seconds)
