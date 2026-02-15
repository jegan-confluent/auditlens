"""Unit tests for topic routing module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.routing import TopicRouter, RouterConfig, TopicConfig, RoutingResult, RoutingStats
from src.classification import CriticalityLevel


class TestRouterConfig:
    """Tests for RouterConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RouterConfig()
        assert config.critical_topic == "audit_events_critical"
        assert config.high_topic == "audit_events_high"
        assert config.medium_topic == "audit_events_medium"
        assert config.low_topic == "audit_events_low"
        assert config.dry_run is False

    def test_config_from_env(self):
        """Test configuration from environment variables."""
        env_vars = {
            'AUDIT_TOPIC_CRITICAL': 'my_critical',
            'AUDIT_TOPIC_HIGH': 'my_high',
            'AUDIT_TOPIC_MEDIUM': 'my_medium',
            'AUDIT_TOPIC_LOW': 'my_low',
            'AUDIT_TOPIC_ALL': 'my_all',
            'AUDIT_ENABLE_CRITICAL': 'true',
            'AUDIT_ENABLE_HIGH': 'false',
            'AUDIT_ENABLE_MEDIUM': 'true',
            'AUDIT_ENABLE_LOW': 'false',
            'AUDIT_ENABLE_ALL_EVENTS': 'true',
            'AUDIT_ROUTER_DRY_RUN': 'true',
        }
        with patch.dict('os.environ', env_vars, clear=False):
            config = RouterConfig.from_env()
            assert config.dry_run is True
            assert config.critical_topic == 'my_critical'
            assert config.enable_high is False
            assert config.enable_all_events is True

    def test_topic_config(self):
        """Test TopicConfig creation."""
        topic_config = TopicConfig(
            topic_name='test_topic',
            enabled=True,
        )
        assert topic_config.topic_name == 'test_topic'
        assert topic_config.enabled is True


class TestRoutingResult:
    """Tests for RoutingResult enum."""

    def test_routing_result_values(self):
        """Test RoutingResult enum values."""
        assert RoutingResult.ROUTED.value == "routed"
        assert RoutingResult.DRY_RUN.value == "dry_run"
        assert RoutingResult.SKIPPED.value == "skipped"
        assert RoutingResult.ERROR.value == "error"


class TestRoutingStats:
    """Tests for RoutingStats dataclass."""

    def test_routing_stats_defaults(self):
        """Test RoutingStats default values."""
        stats = RoutingStats()
        assert stats.total_events == 0
        assert stats.critical_routed == 0
        assert stats.high_routed == 0
        assert stats.medium_routed == 0
        assert stats.low_routed == 0
        assert stats.errors == 0

    def test_routing_stats_to_dict(self):
        """Test RoutingStats to_dict method."""
        stats = RoutingStats(
            total_events=10,
            critical_routed=1,
            high_routed=2,
            medium_routed=3,
            low_routed=4,
            errors=0,
        )
        d = stats.to_dict()
        assert d['total_events'] == 10
        assert d['critical_routed'] == 1
        assert d['high_routed'] == 2


class TestTopicRouter:
    """Tests for TopicRouter class."""

    def test_router_initialization_dry_run(self):
        """Test router initialization in dry-run mode."""
        config = RouterConfig(dry_run=True)
        router = TopicRouter(config=config)
        assert router.config == config
        assert router.config.dry_run is True

    def test_router_initialization_requires_producer(self):
        """Test that router requires producer when not in dry-run mode."""
        config = RouterConfig(dry_run=False)
        with pytest.raises(ValueError, match="Producer is required"):
            TopicRouter(config=config)

    def test_router_with_producer(self):
        """Test router initialization with producer."""
        mock_producer = Mock()
        config = RouterConfig(dry_run=False)
        router = TopicRouter(producer=mock_producer, config=config)
        assert router.producer == mock_producer

    def test_get_enabled_topic_names(self):
        """Test get_enabled_topic_names method."""
        config = RouterConfig(
            enable_critical=True,
            enable_high=True,
            enable_medium=True,
            enable_low=True,
            enable_all_events=False,
            dry_run=True,
        )
        router = TopicRouter(config=config)
        topics = router.get_enabled_topic_names()

        assert "audit_events_critical" in topics
        assert "audit_events_high" in topics
        assert "audit_events_medium" in topics
        assert "audit_events_low" in topics
        assert len(topics) == 4

    def test_get_enabled_topic_names_with_all_events(self):
        """Test get_enabled_topic_names includes all-events topic when enabled."""
        config = RouterConfig(
            enable_critical=True,
            enable_high=False,
            enable_medium=False,
            enable_low=False,
            enable_all_events=True,
            all_events_topic="audit_events_all",
            dry_run=True,
        )
        router = TopicRouter(config=config)
        topics = router.get_enabled_topic_names()

        assert "audit_events_critical" in topics
        assert "audit_events_all" in topics
        assert len(topics) == 2

    def test_route_event_dry_run(self):
        """Test routing an event in dry-run mode."""
        config = RouterConfig(dry_run=True)
        router = TopicRouter(config=config)

        event = {
            'methodName': 'DeleteKafkaCluster',
            'resultStatus': 'SUCCESS',
            'principal': 'User:admin',
        }

        result = router.route_event(event)
        assert result == RoutingResult.DRY_RUN
        assert router.stats.dry_run_events == 1

    def test_route_event_with_producer(self):
        """Test routing an event with a real producer (mocked)."""
        mock_producer = Mock()
        config = RouterConfig(dry_run=False)
        router = TopicRouter(producer=mock_producer, config=config)

        event = {
            'methodName': 'kafka.Produce',
            'resultStatus': 'SUCCESS',
            'principal': 'User:app',
        }

        result = router.route_event(event)
        assert result == RoutingResult.ROUTED
        assert mock_producer.produce.called

    def test_route_event_disabled_topic(self):
        """Test routing to a disabled topic returns SKIPPED."""
        config = RouterConfig(
            enable_critical=True,
            enable_high=True,
            enable_medium=True,
            enable_low=False,  # Disable low
            dry_run=True,
        )
        router = TopicRouter(config=config)

        event = {
            'methodName': 'kafka.Produce',  # LOW criticality
            'resultStatus': 'SUCCESS',
            'principal': 'User:app',
        }

        result = router.route_event(event)
        assert result == RoutingResult.SKIPPED

    def test_get_stats(self):
        """Test getting routing statistics."""
        config = RouterConfig(dry_run=True)
        router = TopicRouter(config=config)

        # Route some events
        events = [
            {'methodName': 'DeleteKafkaCluster', 'resultStatus': 'SUCCESS'},
            {'methodName': 'CreateApiKey', 'resultStatus': 'SUCCESS'},
            {'methodName': 'kafka.Produce', 'resultStatus': 'SUCCESS'},
            {'methodName': 'kafka.Produce', 'resultStatus': 'SUCCESS'},
        ]

        for event in events:
            router.route_event(event)

        stats = router.get_stats()
        assert 'total_events' in stats
        assert stats['total_events'] == 4
        assert 'dry_run_events' in stats
        assert stats['dry_run_events'] == 4

    def test_route_batch(self):
        """Test routing a batch of events."""
        config = RouterConfig(dry_run=True)
        router = TopicRouter(config=config)

        events = [
            {'methodName': 'DeleteKafkaCluster', 'resultStatus': 'SUCCESS'},
            {'methodName': 'CreateApiKey', 'resultStatus': 'SUCCESS'},
            {'methodName': 'kafka.AlterConfigs', 'resultStatus': 'SUCCESS'},
            {'methodName': 'kafka.Produce', 'resultStatus': 'SUCCESS'},
        ]

        results = router.route_batch(events)
        assert results[RoutingResult.DRY_RUN.value] == 4

    def test_reset_stats(self):
        """Test resetting routing statistics."""
        config = RouterConfig(dry_run=True)
        router = TopicRouter(config=config)

        router.route_event({'methodName': 'kafka.Produce', 'resultStatus': 'SUCCESS'})
        assert router.stats.total_events == 1

        router.reset_stats()
        assert router.stats.total_events == 0


class TestTopicRouterIntegration:
    """Integration tests for TopicRouter."""

    def test_router_with_sample_events(
        self,
        sample_authorization_event,
        sample_authorization_denied_event,
    ):
        """Test routing with sample events from conftest."""
        config = RouterConfig(dry_run=True)
        router = TopicRouter(config=config)

        # Convert sample events to flattened format
        normal_event = {
            'methodName': sample_authorization_event['data']['methodName'],
            'resultStatus': sample_authorization_event['data']['result']['status'],
            'granted': sample_authorization_event['data']['authorizationInfo']['granted'],
        }
        denied_event = {
            'methodName': sample_authorization_denied_event['data']['methodName'],
            'resultStatus': sample_authorization_denied_event['data']['result']['status'],
            'granted': sample_authorization_denied_event['data']['authorizationInfo']['granted'],
        }

        normal_result = router.route_event(normal_event)
        denied_result = router.route_event(denied_event)

        # Both should return DRY_RUN in dry-run mode
        assert normal_result == RoutingResult.DRY_RUN
        assert denied_result == RoutingResult.DRY_RUN


class TestVerifyPrerequisites:
    """Tests for verify_prerequisites function."""

    @patch('confluent_kafka.admin.AdminClient')
    def test_verify_prerequisites_success(self, mock_admin_class):
        """Test successful prerequisite verification."""
        from src.routing.topic_router import verify_prerequisites

        # Mock the AdminClient
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        # Mock list_topics to return all required topics
        mock_metadata = MagicMock()
        mock_metadata.topics = {
            'audit_events_critical': MagicMock(),
            'audit_events_high': MagicMock(),
            'audit_events_medium': MagicMock(),
            'audit_events_low': MagicMock(),
        }
        mock_admin.list_topics.return_value = mock_metadata

        config = RouterConfig()
        result = verify_prerequisites(
            bootstrap_servers='localhost:9092',
            api_key='test',
            api_secret='secret',
            config=config,
        )

        assert result['success'] is True
        assert len(result['topics_missing']) == 0

    @patch('confluent_kafka.admin.AdminClient')
    def test_verify_prerequisites_missing_topics(self, mock_admin_class):
        """Test prerequisite verification with missing topics."""
        from src.routing.topic_router import verify_prerequisites

        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        # Mock list_topics to return only some topics
        mock_metadata = MagicMock()
        mock_metadata.topics = {
            'audit_events_critical': MagicMock(),
        }
        mock_admin.list_topics.return_value = mock_metadata

        config = RouterConfig()
        result = verify_prerequisites(
            bootstrap_servers='localhost:9092',
            api_key='test',
            api_secret='secret',
            config=config,
        )

        assert result['success'] is False
        assert len(result['topics_missing']) > 0

    @patch('confluent_kafka.admin.AdminClient')
    def test_verify_prerequisites_connection_error(self, mock_admin_class):
        """Test prerequisite verification with connection error."""
        from src.routing.topic_router import verify_prerequisites

        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        # Mock list_topics to raise an exception
        mock_admin.list_topics.side_effect = Exception("Connection failed")

        config = RouterConfig()
        result = verify_prerequisites(
            bootstrap_servers='localhost:9092',
            api_key='test',
            api_secret='secret',
            config=config,
        )

        assert result['success'] is False
        assert 'errors' in result
        assert len(result['errors']) > 0


class TestCreateTopicsIfMissing:
    """Tests for create_topics_if_missing function."""

    @patch('confluent_kafka.admin.AdminClient')
    def test_create_topics_all_exist(self, mock_admin_class):
        """Test that no topics are created when all exist."""
        from src.routing.topic_router import create_topics_if_missing

        # Mock the AdminClient for verify_prerequisites
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        # Mock list_topics to return all required topics
        mock_metadata = MagicMock()
        mock_metadata.topics = {
            'audit_events_critical': MagicMock(),
            'audit_events_high': MagicMock(),
            'audit_events_medium': MagicMock(),
            'audit_events_low': MagicMock(),
        }
        mock_admin.list_topics.return_value = mock_metadata

        result = create_topics_if_missing(
            bootstrap_servers='localhost:9092',
            api_key='test',
            api_secret='secret',
        )

        assert result['success'] is True
        assert result['message'] == 'All topics exist'

    @patch('confluent_kafka.admin.AdminClient')
    def test_create_topics_success(self, mock_admin_class):
        """Test successful topic creation."""
        from src.routing.topic_router import create_topics_if_missing

        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        # First call for verify_prerequisites returns missing topics
        mock_metadata_missing = MagicMock()
        mock_metadata_missing.topics = {
            'audit_events_critical': MagicMock(),
        }
        mock_admin.list_topics.return_value = mock_metadata_missing

        # Mock create_topics to return success futures
        mock_future = MagicMock()
        mock_future.result.return_value = None  # No error
        mock_admin.create_topics.return_value = {
            'audit_events_high': mock_future,
            'audit_events_medium': mock_future,
            'audit_events_low': mock_future,
        }

        result = create_topics_if_missing(
            bootstrap_servers='localhost:9092',
            api_key='test',
            api_secret='secret',
        )

        assert result['success'] is True
        mock_admin.create_topics.assert_called_once()
