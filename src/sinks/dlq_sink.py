"""
Dead Letter Queue (DLQ) sink for failed events.

Stores events that fail processing along with error metadata
for later analysis and retry.
"""

import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from .base_sink import BaseSink, SinkResult, SinkStatus
from ..transformer.cloudevents import AuditEvent
from ..config.settings import DLQConfig

logger = logging.getLogger(__name__)


class DLQEvent:
    """Wrapper for events sent to DLQ with error context."""

    def __init__(
        self,
        original_event: AuditEvent,
        error_type: str,
        error_message: str,
        source_partition: Optional[int] = None,
        source_offset: Optional[int] = None,
        retry_count: int = 0,
    ):
        self.original_event = original_event
        self.error_type = error_type
        self.error_message = error_message
        self.source_partition = source_partition
        self.source_offset = source_offset
        self.retry_count = retry_count
        self.first_failure = datetime.utcnow()
        self.last_failure = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "original_event": self.original_event.to_dict(),
            "error": {
                "type": self.error_type,
                "message": self.error_message,
                "timestamp": self.last_failure.isoformat() + "Z",
            },
            "metadata": {
                "source_partition": self.source_partition,
                "source_offset": self.source_offset,
                "retry_count": self.retry_count,
                "first_failure": self.first_failure.isoformat() + "Z",
                "last_failure": self.last_failure.isoformat() + "Z",
            },
        }


class DLQSink(BaseSink):
    """
    Dead Letter Queue sink for failed events.

    Failed events are written to a DLQ Kafka topic for:
    - Later analysis and debugging
    - Retry processing
    - Alerting and monitoring
    """

    def __init__(
        self,
        config: DLQConfig,
        kafka_bootstrap: str,
        api_key: str,
        api_secret: str,
        enabled: bool = True,
    ):
        super().__init__(name="dlq", enabled=enabled)
        self.config = config
        self.kafka_bootstrap = kafka_bootstrap
        self.api_key = api_key
        self.api_secret = api_secret
        self._producer = None

    async def initialize(self) -> None:
        """Initialize DLQ producer."""
        if not self.enabled:
            logger.info("DLQ sink is disabled, skipping initialization")
            return

        try:
            from confluent_kafka import Producer

            producer_conf = {
                "bootstrap.servers": self.kafka_bootstrap,
                "security.protocol": "SASL_SSL",
                "sasl.mechanism": "PLAIN",
                "sasl.username": self.api_key,
                "sasl.password": self.api_secret,
                "acks": "all",
                "retries": 3,
                "delivery.timeout.ms": 30000,
            }

            self._producer = Producer(producer_conf)

            # Verify connectivity
            metadata = self._producer.list_topics(timeout=10.0)
            if self.config.topic not in metadata.topics:
                logger.warning(f"DLQ topic {self.config.topic} does not exist. It will be auto-created on first write.")

            self._is_initialized = True
            logger.info(f"DLQ sink initialized, writing to {self.config.topic}")

        except ImportError:
            logger.error("confluent-kafka not installed")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize DLQ sink: {e}")
            raise

    async def write(self, events: List[AuditEvent]) -> SinkResult:
        """Write events to DLQ (should not be called directly)."""
        # This method is for compatibility, but DLQ events should go through write_failures
        return SinkResult(
            status=SinkStatus.SKIPPED,
            sink_name=self.name,
            metadata={"reason": "use_write_failures_instead"},
        )

    async def write_failures(
        self,
        failures: List[tuple[AuditEvent, str, str]],  # (event, error_type, error_message)
        source_partition: Optional[int] = None,
        source_offset: Optional[int] = None,
    ) -> SinkResult:
        """
        Write failed events to DLQ with error context.

        Args:
            failures: List of (event, error_type, error_message) tuples
            source_partition: Source Kafka partition (optional)
            source_offset: Source Kafka offset (optional)
        """
        if not self.enabled:
            return SinkResult(
                status=SinkStatus.SKIPPED,
                sink_name=self.name,
                metadata={"reason": "sink_disabled"},
            )

        if not self._is_initialized or not self._producer:
            return SinkResult(
                status=SinkStatus.FAILURE,
                sink_name=self.name,
                errors=["DLQ sink not initialized"],
            )

        start_time = time.time()
        written = 0
        failed = 0
        errors = []

        for event, error_type, error_message in failures:
            try:
                dlq_event = DLQEvent(
                    original_event=event,
                    error_type=error_type,
                    error_message=error_message,
                    source_partition=source_partition,
                    source_offset=source_offset,
                )

                value = json.dumps(dlq_event.to_dict()).encode("utf-8")
                key = event.id.encode("utf-8") if event.id else None

                self._producer.produce(
                    topic=self.config.topic,
                    key=key,
                    value=value,
                )
                written += 1

            except Exception as e:
                logger.error(f"Failed to write to DLQ: {e}")
                failed += 1
                errors.append(str(e))

        # Flush to ensure delivery
        self._producer.flush(timeout=10)

        duration_ms = (time.time() - start_time) * 1000

        result = SinkResult(
            status=SinkStatus.SUCCESS if failed == 0 else SinkStatus.PARTIAL,
            sink_name=self.name,
            records_written=written,
            records_failed=failed,
            errors=errors,
            duration_ms=duration_ms,
            metadata={
                "topic": self.config.topic,
            },
        )

        self._update_metrics(result)
        return result

    async def flush(self) -> None:
        """Flush DLQ producer."""
        if self._producer:
            self._producer.flush(timeout=10)

    async def close(self) -> None:
        """Close the DLQ producer."""
        if self._producer:
            self._producer.flush(timeout=10)
            logger.info("DLQ sink closed")

    async def health_check(self) -> bool:
        """Check DLQ connectivity."""
        if not self._producer:
            return False

        try:
            metadata = self._producer.list_topics(timeout=5.0)
            return True
        except Exception as e:
            logger.error(f"DLQ health check failed: {e}")
            return False
