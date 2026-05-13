"""
Topic Router for Confluent Audit Log Intelligence System.

This module provides multi-topic routing based on event criticality.
Events are routed to different Kafka topics based on their classification,
enabling tiered processing, alerting, and retention policies.
"""

import logging
import os

import orjson
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from enum import Enum

from confluent_kafka import Producer, KafkaError, KafkaException

from ..classification import classify_event, CriticalityLevel

logger = logging.getLogger(__name__)


@dataclass
class TopicConfig:
    """Configuration for a destination topic."""
    topic_name: str
    enabled: bool = True
    # Optional: Different producer configs per topic (e.g., acks, compression)
    producer_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouterConfig:
    """Configuration for the topic router."""
    # Topic names by criticality level
    critical_topic: str = "audit_events_critical"
    high_topic: str = "audit_events_high"
    medium_topic: str = "audit_events_medium"
    low_topic: str = "audit_events_low"

    # Also send all events to a unified topic (optional)
    all_events_topic: Optional[str] = "audit_events_all"

    # Dry-run mode: log routing decisions without producing
    dry_run: bool = False

    # Enable/disable specific topics
    enable_critical: bool = True
    enable_high: bool = True
    enable_medium: bool = True
    enable_low: bool = True
    enable_all_events: bool = False

    # Drop LOW events entirely (don't produce them)
    # This saves ~89% of produce load when most events are LOW criticality
    drop_low_events: bool = False

    @classmethod
    def from_env(cls) -> 'RouterConfig':
        """Create configuration from environment variables."""
        return cls(
            critical_topic=os.getenv('AUDIT_TOPIC_CRITICAL', 'audit_events_critical'),
            high_topic=os.getenv('AUDIT_TOPIC_HIGH', 'audit_events_high'),
            medium_topic=os.getenv('AUDIT_TOPIC_MEDIUM', 'audit_events_medium'),
            low_topic=os.getenv('AUDIT_TOPIC_LOW', 'audit_events_low'),
            all_events_topic=os.getenv('AUDIT_TOPIC_ALL', 'audit_events_all'),
            dry_run=os.getenv('AUDIT_ROUTER_DRY_RUN', 'false').lower() == 'true',
            enable_critical=os.getenv('AUDIT_ENABLE_CRITICAL', 'true').lower() == 'true',
            enable_high=os.getenv('AUDIT_ENABLE_HIGH', 'true').lower() == 'true',
            enable_medium=os.getenv('AUDIT_ENABLE_MEDIUM', 'true').lower() == 'true',
            enable_low=os.getenv('AUDIT_ENABLE_LOW', 'true').lower() == 'true',
            enable_all_events=os.getenv('AUDIT_ENABLE_ALL_EVENTS', 'false').lower() == 'true',
            drop_low_events=os.getenv('DROP_LOW_EVENTS', 'false').lower() == 'true',
        )


class RoutingResult(str, Enum):
    """Result of routing an event."""
    ROUTED = "routed"
    DRY_RUN = "dry_run"
    SKIPPED = "skipped"
    DROPPED = "dropped"  # Event was dropped (e.g., DROP_LOW_EVENTS)
    ERROR = "error"


@dataclass
class RoutingStats:
    """Statistics for routing operations."""
    total_events: int = 0
    critical_routed: int = 0
    high_routed: int = 0
    medium_routed: int = 0
    low_routed: int = 0
    low_dropped: int = 0  # LOW events dropped due to DROP_LOW_EVENTS
    dry_run_events: int = 0
    errors: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            'total_events': self.total_events,
            'critical_routed': self.critical_routed,
            'high_routed': self.high_routed,
            'medium_routed': self.medium_routed,
            'low_routed': self.low_routed,
            'low_dropped': self.low_dropped,
            'dry_run_events': self.dry_run_events,
            'errors': self.errors,
        }


class TopicRouter:
    """
    Routes audit events to different Kafka topics based on criticality.

    Usage:
        config = RouterConfig.from_env()
        router = TopicRouter(producer, config)

        for event in events:
            result = router.route_event(event)
    """

    def __init__(
        self,
        producer: Optional[Producer] = None,
        config: Optional[RouterConfig] = None,
        on_delivery: Optional[Callable] = None,
    ):
        """
        Initialize the topic router.

        Args:
            producer: Kafka producer instance (optional in dry-run mode)
            config: Router configuration
            on_delivery: Optional callback for delivery reports
        """
        self.config = config or RouterConfig.from_env()
        self.producer = producer
        self.on_delivery = on_delivery or self._default_delivery_callback
        self.stats = RoutingStats()

        # Build topic mapping
        self._topic_map = {
            CriticalityLevel.CRITICAL: (
                self.config.critical_topic,
                self.config.enable_critical
            ),
            CriticalityLevel.HIGH: (
                self.config.high_topic,
                self.config.enable_high
            ),
            CriticalityLevel.MEDIUM: (
                self.config.medium_topic,
                self.config.enable_medium
            ),
            CriticalityLevel.LOW: (
                self.config.low_topic,
                self.config.enable_low
            ),
        }

        if self.config.dry_run:
            logger.info("TopicRouter initialized in DRY-RUN mode")
        else:
            if not self.producer:
                raise ValueError("Producer is required when not in dry-run mode")
            logger.info(f"TopicRouter initialized with topics: {self._get_enabled_topics()}")

    def _get_enabled_topics(self) -> List[str]:
        """Get list of enabled topic names with level prefix (for logging)."""
        topics = []
        for level, (topic, enabled) in self._topic_map.items():
            if enabled:
                topics.append(f"{level.value}:{topic}")
        if self.config.enable_all_events and self.config.all_events_topic:
            topics.append(f"ALL:{self.config.all_events_topic}")
        return topics

    def get_enabled_topic_names(self) -> List[str]:
        """Get list of enabled topic names (without level prefix)."""
        topics = []
        for level, (topic, enabled) in self._topic_map.items():
            if enabled:
                topics.append(topic)
        if self.config.enable_all_events and self.config.all_events_topic:
            topics.append(self.config.all_events_topic)
        return topics

    def _default_delivery_callback(self, err, msg):
        """Default callback for delivery reports."""
        if err:
            logger.error(f"Delivery failed for {msg.topic()}: {err}")
            self.stats.errors += 1
        else:
            logger.debug(f"Delivered to {msg.topic()} [{msg.partition()}] @ {msg.offset()}")

    def route_event(self, event: Dict[str, Any]) -> RoutingResult:
        """
        Route a single event to the appropriate topic(s).

        Args:
            event: The audit event to route

        Returns:
            RoutingResult indicating success/failure
        """
        self.stats.total_events += 1

        try:
            # Classify the event
            criticality, enrichment = classify_event(event)

            # Enrich the event with classification data
            enriched_event = {**event, **enrichment}

            # Drop LOW events if configured (saves ~89% of produce load)
            if criticality == CriticalityLevel.LOW.value and self.config.drop_low_events:
                self.stats.low_dropped += 1
                logger.debug(f"Dropping LOW event (DROP_LOW_EVENTS enabled): {event.get('methodName', 'unknown')}")
                return RoutingResult.DROPPED

            # Get target topic
            topic, enabled = self._topic_map.get(
                CriticalityLevel(criticality),
                (self.config.low_topic, self.config.enable_low)
            )

            if not enabled:
                logger.debug(f"Topic {topic} is disabled, skipping event")
                return RoutingResult.SKIPPED

            # Dry-run mode
            if self.config.dry_run:
                self._log_dry_run(enriched_event, topic, criticality)
                self.stats.dry_run_events += 1
                return RoutingResult.DRY_RUN

            # Produce to criticality-specific topic
            self._produce_event(enriched_event, topic)
            self._update_stats(criticality)

            # Also produce to all-events topic if enabled
            if self.config.enable_all_events and self.config.all_events_topic:
                self._produce_event(enriched_event, self.config.all_events_topic)

            return RoutingResult.ROUTED

        except Exception as e:
            logger.error("Error routing event: %s", e, exc_info=True)
            self.stats.errors += 1
            return RoutingResult.ERROR

    def _produce_event(self, event: Dict[str, Any], topic: str):
        """Produce an event to a Kafka topic."""
        try:
            # Use event ID as the key for partitioning
            key = event.get('id', '')

            self.producer.produce(
                topic=topic,
                key=key.encode('utf-8') if key else None,
                value=orjson.dumps(event),
                callback=self.on_delivery,
            )
        except BufferError:
            logger.warning("Producer queue full, polling...")
            self.producer.poll(1)
            # Retry once
            self.producer.produce(
                topic=topic,
                key=key.encode('utf-8') if key else None,
                value=orjson.dumps(event),
                callback=self.on_delivery,
            )

    def _log_dry_run(self, event: Dict[str, Any], topic: str, criticality: str):
        """Log routing decision in dry-run mode."""
        event_id = event.get('id', 'unknown')
        method = event.get('methodName', 'unknown')
        principal = event.get('principal', 'unknown')
        reason = event.get('classification_reason', 'unknown')

        logger.info(
            f"[DRY-RUN] Would route to {topic}: "
            f"id={event_id[:8]}... method={method} "
            f"criticality={criticality} principal={principal} "
            f"reason={reason}"
        )

    def _update_stats(self, criticality: str):
        """Update routing statistics."""
        if criticality == CriticalityLevel.CRITICAL.value:
            self.stats.critical_routed += 1
        elif criticality == CriticalityLevel.HIGH.value:
            self.stats.high_routed += 1
        elif criticality == CriticalityLevel.MEDIUM.value:
            self.stats.medium_routed += 1
        else:
            self.stats.low_routed += 1

    def route_batch(self, events: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Route a batch of events.

        Args:
            events: List of events to route

        Returns:
            Dictionary with counts of each routing result
        """
        results = {
            RoutingResult.ROUTED.value: 0,
            RoutingResult.DRY_RUN.value: 0,
            RoutingResult.SKIPPED.value: 0,
            RoutingResult.DROPPED.value: 0,
            RoutingResult.ERROR.value: 0,
        }

        for event in events:
            result = self.route_event(event)
            results[result.value] += 1

        # Flush if we have a producer
        if self.producer and not self.config.dry_run:
            unconfirmed = self.producer.flush(timeout=10)
            if unconfirmed > 0:
                logger.warning(
                    "producer.flush() timed out with %d message(s) still in queue — "
                    "delivery not confirmed for this batch",
                    unconfirmed,
                )

        return results

    def get_stats(self) -> Dict[str, int]:
        """Get routing statistics."""
        return self.stats.to_dict()

    def reset_stats(self):
        """Reset routing statistics."""
        self.stats = RoutingStats()

    def flush(self, timeout: float = 30.0):
        """Flush any pending messages."""
        if self.producer:
            self.producer.flush(timeout=timeout)


def verify_prerequisites(
    bootstrap_servers: str,
    api_key: str,
    api_secret: str,
    config: Optional[RouterConfig] = None,
) -> Dict[str, Any]:
    """
    Verify that all required topics exist and are accessible.

    This is a startup health check to ensure the routing infrastructure
    is properly configured before processing events.

    Args:
        bootstrap_servers: Kafka bootstrap servers
        api_key: API key for authentication
        api_secret: API secret for authentication
        config: Router configuration (optional)

    Returns:
        Dictionary with verification results
    """
    from confluent_kafka.admin import AdminClient

    config = config or RouterConfig.from_env()

    results = {
        'success': True,
        'topics_checked': [],
        'topics_missing': [],
        'errors': [],
    }

    # Build list of topics to check
    topics_to_check = []
    if config.enable_critical:
        topics_to_check.append(config.critical_topic)
    if config.enable_high:
        topics_to_check.append(config.high_topic)
    if config.enable_medium:
        topics_to_check.append(config.medium_topic)
    if config.enable_low:
        topics_to_check.append(config.low_topic)
    if config.enable_all_events and config.all_events_topic:
        topics_to_check.append(config.all_events_topic)

    try:
        admin_client = AdminClient({
            'bootstrap.servers': bootstrap_servers,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanisms': 'PLAIN',
            'sasl.username': api_key,
            'sasl.password': api_secret,
        })

        # Get cluster metadata
        metadata = admin_client.list_topics(timeout=30)
        existing_topics = set(metadata.topics.keys())

        for topic in topics_to_check:
            results['topics_checked'].append(topic)
            if topic not in existing_topics:
                results['topics_missing'].append(topic)
                results['success'] = False
                logger.warning(f"Topic '{topic}' does not exist")
            else:
                logger.info(f"Topic '{topic}' verified")

    except Exception as e:
        results['success'] = False
        results['errors'].append(str(e))
        logger.error(f"Error verifying prerequisites: {e}")

    return results


def create_topics_if_missing(
    bootstrap_servers: str,
    api_key: str,
    api_secret: str,
    config: Optional[RouterConfig] = None,
    num_partitions: int = 6,
    replication_factor: int = 3,
) -> Dict[str, Any]:
    """
    Create missing topics for the router.

    Args:
        bootstrap_servers: Kafka bootstrap servers
        api_key: API key for authentication
        api_secret: API secret for authentication
        config: Router configuration (optional)
        num_partitions: Number of partitions for new topics
        replication_factor: Replication factor for new topics

    Returns:
        Dictionary with creation results
    """
    from confluent_kafka.admin import AdminClient, NewTopic

    config = config or RouterConfig.from_env()

    # First verify what's missing
    prereq_results = verify_prerequisites(
        bootstrap_servers, api_key, api_secret, config
    )

    if not prereq_results['topics_missing']:
        return {'success': True, 'created': [], 'message': 'All topics exist'}

    results = {
        'success': True,
        'created': [],
        'errors': [],
    }

    try:
        admin_client = AdminClient({
            'bootstrap.servers': bootstrap_servers,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanisms': 'PLAIN',
            'sasl.username': api_key,
            'sasl.password': api_secret,
        })

        new_topics = [
            NewTopic(
                topic,
                num_partitions=num_partitions,
                replication_factor=replication_factor,
            )
            for topic in prereq_results['topics_missing']
        ]

        futures = admin_client.create_topics(new_topics)

        for topic, future in futures.items():
            try:
                future.result()
                results['created'].append(topic)
                logger.info(f"Created topic '{topic}'")
            except Exception as e:
                results['errors'].append(f"{topic}: {e}")
                results['success'] = False
                logger.error(f"Failed to create topic '{topic}': {e}")

    except Exception as e:
        results['success'] = False
        results['errors'].append(str(e))
        logger.error(f"Error creating topics: {e}")

    return results
