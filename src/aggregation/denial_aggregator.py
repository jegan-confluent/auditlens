"""
Denial Aggregator for Confluent Audit Log Intelligence System.

Aggregates high-volume authorization denials into actionable alerts.
Instead of routing every mds.Authorize (granted=False) individually,
this aggregates them per principal per minute into summary alerts.

This reduces ~86% of MEDIUM topic noise while preserving security signals.
"""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Callable, TYPE_CHECKING
from collections import defaultdict

from confluent_kafka import Producer

from ..classification.methods import AUTHORIZATION_CHECK_METHODS, SECURITY_FAILURE_STATUSES

if TYPE_CHECKING:
    from ..alerting.webhook_sender import WebhookSender

logger = logging.getLogger(__name__)


@dataclass
class AggregatorConfig:
    """Configuration for the denial aggregator."""

    # Window duration in seconds
    window_seconds: int = 60

    # Threshold for elevating to HIGH criticality
    high_threshold: int = 10

    # Topic for aggregated alerts
    alerts_topic: str = "audit_events_alerts"

    # Maximum events to sample per bucket (for drill-down)
    max_sample_events: int = 5

    # Maximum unique values to track per field
    max_unique_values: int = 20

    # Enable/disable aggregation
    enabled: bool = True

    # Dry-run mode (log but don't produce)
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> 'AggregatorConfig':
        """Create configuration from environment variables."""
        return cls(
            window_seconds=int(os.getenv('DENIAL_AGGREGATOR_WINDOW', '60')),
            high_threshold=int(os.getenv('DENIAL_AGGREGATOR_THRESHOLD', '10')),
            alerts_topic=os.getenv('AUDIT_TOPIC_ALERTS', 'audit_events_alerts'),
            max_sample_events=int(os.getenv('DENIAL_AGGREGATOR_MAX_SAMPLES', '5')),
            max_unique_values=int(os.getenv('DENIAL_AGGREGATOR_MAX_UNIQUE', '20')),
            enabled=os.getenv('ENABLE_DENIAL_AGGREGATION', 'true').lower() == 'true',
            dry_run=os.getenv('DENIAL_AGGREGATOR_DRY_RUN', 'false').lower() == 'true',
        )


@dataclass
class DenialBucket:
    """Bucket for accumulating denials for a single principal."""

    principal: str
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    denial_count: int = 0
    operations: Set[str] = field(default_factory=set)
    resource_types: Set[str] = field(default_factory=set)
    resource_names: Set[str] = field(default_factory=set)
    source_ips: Set[str] = field(default_factory=set)
    sample_event_ids: List[str] = field(default_factory=list)
    principal_email: Optional[str] = None
    method_names: Set[str] = field(default_factory=set)

    # Context fields for multi-cluster/environment visibility
    cluster_ids: Set[str] = field(default_factory=set)
    environment_ids: Set[str] = field(default_factory=set)
    organization_ids: Set[str] = field(default_factory=set)

    def add_denial(
        self,
        event: Dict[str, Any],
        max_samples: int = 5,
        max_unique: int = 20,
    ):
        """Add a denial event to this bucket."""
        self.denial_count += 1

        # Track unique values (with limits to prevent memory growth)
        if len(self.operations) < max_unique:
            op = event.get('operation')
            if op:
                self.operations.add(op)

        if len(self.resource_types) < max_unique:
            rt = event.get('resourceType')
            if rt:
                self.resource_types.add(rt)

        if len(self.resource_names) < max_unique:
            rn = event.get('authzResourceName') or event.get('resourceName')
            if rn:
                self.resource_names.add(rn)

        if len(self.source_ips) < max_unique:
            ip = event.get('clientIp')
            if ip:
                self.source_ips.add(ip)

        if len(self.method_names) < max_unique:
            mn = event.get('methodName')
            if mn:
                self.method_names.add(mn)

        # Context: cluster, environment, organization
        if len(self.cluster_ids) < max_unique:
            cluster = event.get('cluster_id')
            if cluster:
                self.cluster_ids.add(cluster)

        if len(self.environment_ids) < max_unique:
            env = event.get('environment_id')
            if env:
                self.environment_ids.add(env)

        if len(self.organization_ids) < max_unique:
            org = event.get('organization_id')
            if org:
                self.organization_ids.add(org)

        # Sample event IDs for drill-down
        if len(self.sample_event_ids) < max_samples:
            event_id = event.get('id')
            if event_id:
                self.sample_event_ids.append(event_id)

        # Capture email if available
        if not self.principal_email:
            self.principal_email = event.get('email')


@dataclass
class AggregatedDenialAlert:
    """Aggregated denial alert to be produced."""

    id: str
    method_name: str = "AggregatedAuthDenials"
    type: str = "io.confluent.audit.aggregated/denial_summary"
    criticality: str = "MEDIUM"
    window_start: str = ""
    window_end: str = ""
    principal: str = ""
    principal_email: Optional[str] = None
    denial_count: int = 0
    unique_operations: List[str] = field(default_factory=list)
    unique_resource_types: List[str] = field(default_factory=list)
    unique_resource_names: List[str] = field(default_factory=list)
    source_ips: List[str] = field(default_factory=list)
    sample_event_ids: List[str] = field(default_factory=list)
    threshold_exceeded: bool = False
    threshold: int = 10
    aggregated_methods: List[str] = field(default_factory=list)

    # Context fields
    cluster_ids: List[str] = field(default_factory=list)
    environment_ids: List[str] = field(default_factory=list)
    organization_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'methodName': self.method_name,
            'type': self.type,
            'time': self.window_end,  # Use end time as event time
            'criticality': self.criticality,
            'classification_reason': f"Aggregated {self.denial_count} auth denials in {self.threshold}s window",
            'is_security_event': True,
            'is_aggregated': True,
            'window_start': self.window_start,
            'window_end': self.window_end,
            'principal': self.principal,
            'email': self.principal_email,
            'denial_count': self.denial_count,
            'unique_operations': self.unique_operations,
            'unique_resource_types': self.unique_resource_types,
            'unique_resource_names': self.unique_resource_names,
            'source_ips': self.source_ips,
            'sample_event_ids': self.sample_event_ids,
            'threshold_exceeded': self.threshold_exceeded,
            'threshold': self.threshold,
            'aggregated_methods': self.aggregated_methods,
            'cluster_ids': self.cluster_ids,
            'environment_ids': self.environment_ids,
            'organization_ids': self.organization_ids,
        }


class DenialAggregator:
    """
    Aggregates authorization denials into summary alerts.

    Instead of routing each mds.Authorize (granted=False) event individually
    (which generates ~86% of MEDIUM events), this aggregates them per principal
    per time window and produces a single summary alert.

    Usage:
        config = AggregatorConfig.from_env()
        aggregator = DenialAggregator(producer, config)

        # In main loop:
        for event in events:
            if aggregator.should_aggregate(event):
                aggregator.add_event(event)
            else:
                topic_router.route_event(event)

        # On shutdown:
        aggregator.shutdown()
    """

    def __init__(
        self,
        producer: Optional[Producer] = None,
        config: Optional[AggregatorConfig] = None,
        on_flush: Optional[Callable[['AggregatedDenialAlert'], None]] = None,
        webhook_sender: Optional['WebhookSender'] = None,
    ):
        """
        Initialize the denial aggregator.

        Args:
            producer: Kafka producer instance
            config: Aggregator configuration
            on_flush: Optional callback when alerts are flushed
            webhook_sender: Optional webhook sender for HIGH alerts (Slack, etc.)
        """
        self.config = config or AggregatorConfig.from_env()
        self.producer = producer
        self.on_flush = on_flush
        self.webhook_sender = webhook_sender

        # Buckets: principal -> DenialBucket
        self._buckets: Dict[str, DenialBucket] = {}
        self._lock = threading.Lock()

        # Statistics
        self._stats = {
            'events_aggregated': 0,
            'alerts_produced': 0,
            'high_alerts': 0,
            'medium_alerts': 0,
            'flush_count': 0,
            'delivery_errors': 0,
        }

        # Timer thread for periodic flushing
        self._timer_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

        if self.config.enabled:
            self._start_timer()
            logger.info(
                f"DenialAggregator initialized: window={self.config.window_seconds}s, "
                f"threshold={self.config.high_threshold}, topic={self.config.alerts_topic}, "
                f"dry_run={self.config.dry_run}"
            )
        else:
            logger.info("DenialAggregator disabled")

    def _start_timer(self):
        """Start the background timer thread."""
        self._timer_thread = threading.Thread(
            target=self._timer_loop,
            daemon=True,
            name="DenialAggregator-Timer"
        )
        self._timer_thread.start()
        logger.debug("DenialAggregator timer thread started")

    def _timer_loop(self):
        """Background loop that flushes buckets periodically."""
        while not self._shutdown_event.wait(timeout=self.config.window_seconds):
            try:
                self._flush_all_buckets()
            except Exception as e:
                logger.error(f"Error in aggregator timer loop: {e}", exc_info=True)

    def should_aggregate(self, event: Dict[str, Any]) -> bool:
        """
        Determine if an event should be aggregated.

        Aggregates:
        - mds.Authorize, flink.Authorize, etc. (AUTHORIZATION_CHECK_METHODS)
        - Only when granted=False
        - NOT when resultStatus indicates security failure (those go CRITICAL)

        Args:
            event: The flattened audit event

        Returns:
            True if event should be aggregated, False otherwise
        """
        if not self.config.enabled:
            return False

        method_name = event.get('methodName', '')
        granted = event.get('granted')
        result_status = str(event.get('resultStatus', '') or '').upper()

        # Don't aggregate security failures (they should go to CRITICAL)
        if result_status in SECURITY_FAILURE_STATUSES:
            return False

        # Aggregate authorization check denials
        return (
            method_name in AUTHORIZATION_CHECK_METHODS and
            granted is False
        )

    def add_event(self, event: Dict[str, Any]) -> bool:
        """
        Add an event to the appropriate bucket.

        Args:
            event: The flattened audit event

        Returns:
            True if event was added, False otherwise
        """
        if not self.config.enabled:
            return False

        principal = event.get('principal') or event.get('principalResourceId') or 'unknown'

        with self._lock:
            # Get or create bucket for this principal
            if principal not in self._buckets:
                self._buckets[principal] = DenialBucket(principal=principal)

            bucket = self._buckets[principal]
            bucket.add_denial(
                event,
                max_samples=self.config.max_sample_events,
                max_unique=self.config.max_unique_values,
            )

            self._stats['events_aggregated'] += 1

        return True

    def _flush_all_buckets(self):
        """Flush all buckets and produce alerts."""
        window_end = datetime.now(timezone.utc)

        with self._lock:
            buckets_to_flush = list(self._buckets.items())
            self._buckets.clear()

        if not buckets_to_flush:
            logger.debug("No buckets to flush")
            return

        alerts_produced = 0
        high_count = 0
        medium_count = 0

        for principal, bucket in buckets_to_flush:
            if bucket.denial_count == 0:
                continue  # Skip empty buckets

            alert = self._create_alert(bucket, window_end)
            self._produce_alert(alert)
            alerts_produced += 1

            if alert.threshold_exceeded:
                high_count += 1
            else:
                medium_count += 1

        if alerts_produced > 0:
            self._stats['flush_count'] += 1
            self._stats['high_alerts'] += high_count
            self._stats['medium_alerts'] += medium_count

            logger.info(
                f"Aggregator flush #{self._stats['flush_count']}: "
                f"{alerts_produced} alerts ({high_count} HIGH, {medium_count} MEDIUM), "
                f"total aggregated: {self._stats['events_aggregated']}"
            )

    def _create_alert(
        self,
        bucket: DenialBucket,
        window_end: datetime,
    ) -> AggregatedDenialAlert:
        """Create an aggregated alert from a bucket."""
        threshold_exceeded = bucket.denial_count >= self.config.high_threshold
        criticality = "HIGH" if threshold_exceeded else "MEDIUM"

        return AggregatedDenialAlert(
            id=str(uuid.uuid4()),
            criticality=criticality,
            window_start=bucket.window_start.isoformat(),
            window_end=window_end.isoformat(),
            principal=bucket.principal,
            principal_email=bucket.principal_email,
            denial_count=bucket.denial_count,
            unique_operations=list(bucket.operations),
            unique_resource_types=list(bucket.resource_types),
            unique_resource_names=list(bucket.resource_names)[:10],  # Limit for readability
            source_ips=list(bucket.source_ips),
            sample_event_ids=bucket.sample_event_ids,
            threshold_exceeded=threshold_exceeded,
            threshold=self.config.high_threshold,
            aggregated_methods=list(bucket.method_names),
            cluster_ids=list(bucket.cluster_ids),
            environment_ids=list(bucket.environment_ids),
            organization_ids=list(bucket.organization_ids),
        )

    def _produce_alert(self, alert: AggregatedDenialAlert):
        """Produce an alert to Kafka and optionally send webhook for HIGH alerts."""
        if self.config.dry_run:
            logger.info(
                f"[DRY-RUN] Would produce alert: principal={alert.principal}, "
                f"count={alert.denial_count}, criticality={alert.criticality}, "
                f"operations={alert.unique_operations[:3]}"
            )
            self._stats['alerts_produced'] += 1
            return

        if not self.producer:
            logger.warning("No producer configured, cannot produce alert")
            return

        try:
            self.producer.produce(
                topic=self.config.alerts_topic,
                key=alert.principal.encode('utf-8'),
                value=json.dumps(alert.to_dict()).encode('utf-8'),
                callback=self._delivery_callback,
            )
            self._stats['alerts_produced'] += 1

            # Call optional callback
            if self.on_flush:
                self.on_flush(alert)

            # Send webhook for HIGH (threshold-exceeded) alerts
            if alert.threshold_exceeded and self.webhook_sender:
                try:
                    alert_dict = alert.to_dict()
                    # Map field names for webhook compatibility
                    alert_dict['operations'] = alert_dict.get('unique_operations', [])
                    self.webhook_sender.send_aggregated_denial_alert(alert_dict)
                except Exception as e:
                    logger.warning(f"Failed to send webhook for HIGH alert: {e}")

        except BufferError:
            logger.warning("Producer buffer full, polling...")
            self.producer.poll(1)
            # Retry once
            try:
                self.producer.produce(
                    topic=self.config.alerts_topic,
                    key=alert.principal.encode('utf-8'),
                    value=json.dumps(alert.to_dict()).encode('utf-8'),
                    callback=self._delivery_callback,
                )
                self._stats['alerts_produced'] += 1
            except Exception as e:
                logger.error(f"Failed to produce alert after retry: {e}")
                self._stats['delivery_errors'] += 1
        except Exception as e:
            logger.error(f"Failed to produce alert: {e}")
            self._stats['delivery_errors'] += 1

    def _delivery_callback(self, err, msg):
        """Callback for Kafka delivery reports."""
        if err:
            logger.error(f"Alert delivery failed: {err}")
            self._stats['delivery_errors'] += 1
        else:
            logger.debug(f"Alert delivered to {msg.topic()} [{msg.partition()}] @ {msg.offset()}")

    def flush(self):
        """Manually flush all buckets (call on shutdown)."""
        logger.info("Manual aggregator flush triggered")
        self._flush_all_buckets()
        if self.producer and not self.config.dry_run:
            self.producer.flush(timeout=5.0)

    def shutdown(self):
        """Shutdown the aggregator gracefully."""
        logger.info("Shutting down DenialAggregator...")

        # Signal timer to stop
        self._shutdown_event.set()

        # Wait for timer thread
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=5.0)

        # Final flush
        self.flush()

        logger.info(
            f"DenialAggregator shutdown complete. Stats: "
            f"aggregated={self._stats['events_aggregated']}, "
            f"alerts={self._stats['alerts_produced']}, "
            f"high={self._stats['high_alerts']}, "
            f"medium={self._stats['medium_alerts']}, "
            f"errors={self._stats['delivery_errors']}"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregator statistics."""
        with self._lock:
            stats = dict(self._stats)
            stats['active_buckets'] = len(self._buckets)
            stats['pending_denials'] = sum(b.denial_count for b in self._buckets.values())
            stats['config'] = {
                'window_seconds': self.config.window_seconds,
                'high_threshold': self.config.high_threshold,
                'alerts_topic': self.config.alerts_topic,
                'enabled': self.config.enabled,
                'dry_run': self.config.dry_run,
            }
        return stats
