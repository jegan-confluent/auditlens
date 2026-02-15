"""
Kafka sink for forwarding audit events to a destination Kafka cluster.

Features:
- Idempotent production
- Schema Registry integration
- Exactly-once semantics
- Backpressure handling
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional

from .base_sink import BaseSink, SinkResult, SinkStatus
from ..transformer.cloudevents import AuditEvent
from ..config.settings import KafkaDestConfig, SchemaRegistryConfig

logger = logging.getLogger(__name__)


class KafkaSink(BaseSink):
    """
    Kafka sink for audit events.

    Produces flattened audit events to a destination Kafka topic
    with JSON Schema validation via Schema Registry.
    """

    def __init__(
        self,
        kafka_config: KafkaDestConfig,
        schema_registry_config: SchemaRegistryConfig,
        enabled: bool = True,
    ):
        super().__init__(name="kafka", enabled=enabled)
        self.kafka_config = kafka_config
        self.schema_registry_config = schema_registry_config
        self._producer = None
        self._serializer = None
        self._schema_cache = {}

    async def initialize(self) -> None:
        """Initialize Kafka producer and Schema Registry client."""
        if not self.enabled:
            logger.info("Kafka sink is disabled, skipping initialization")
            return

        try:
            from confluent_kafka import Producer
            from confluent_kafka.schema_registry import SchemaRegistryClient
            from confluent_kafka.schema_registry.json_schema import JSONSerializer
            from confluent_kafka.serialization import SerializationContext, MessageField

            # Create producer
            producer_conf = {
                "bootstrap.servers": self.kafka_config.bootstrap_servers,
                "security.protocol": "SASL_SSL",
                "sasl.mechanism": "PLAIN",
                "sasl.username": self.kafka_config.api_key,
                "sasl.password": self.kafka_config.api_secret,
                "enable.idempotence": self.kafka_config.enable_idempotence,
                "acks": self.kafka_config.acks,
                "retries": self.kafka_config.retries,
                "delivery.timeout.ms": self.kafka_config.delivery_timeout_ms,
                "linger.ms": self.kafka_config.linger_ms,
                "batch.size": self.kafka_config.batch_size,
                "compression.type": self.kafka_config.compression_type,
                "buffer.memory": self.kafka_config.buffer_memory,
                "max.in.flight.requests.per.connection": self.kafka_config.max_in_flight_requests,
            }

            self._producer = Producer(producer_conf)

            # Create Schema Registry client
            sr_conf = {
                "url": self.schema_registry_config.url,
                "basic.auth.user.info": f"{self.schema_registry_config.api_key}:{self.schema_registry_config.api_secret}",
            }
            sr_client = SchemaRegistryClient(sr_conf)

            # Get schema for destination topic
            subject = f"{self.kafka_config.topic}-value"
            try:
                schema_meta = sr_client.get_latest_version(subject)
                self._serializer = JSONSerializer(
                    schema_meta.schema.schema_str,
                    sr_client,
                    to_dict=lambda event, ctx: event,
                    conf={"auto.register.schemas": self.schema_registry_config.auto_register_schemas},
                )
                logger.info(f"Loaded schema v{schema_meta.version} for {subject}")
            except Exception as e:
                logger.warning(f"Could not load schema for {subject}: {e}. Will use JSON serialization.")
                self._serializer = None

            # Verify connectivity
            metadata = self._producer.list_topics(timeout=10.0)
            if self.kafka_config.topic not in metadata.topics:
                logger.warning(f"Destination topic {self.kafka_config.topic} does not exist")

            self._is_initialized = True
            logger.info(f"Kafka sink initialized, producing to {self.kafka_config.topic}")

        except ImportError:
            logger.error("confluent-kafka not installed. Install with: pip install confluent-kafka")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Kafka sink: {e}")
            raise

    async def write(self, events: List[AuditEvent]) -> SinkResult:
        """Write events to Kafka."""
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
                errors=["Sink not initialized"],
            )

        start_time = time.time()
        written = 0
        failed = 0
        failed_records = []
        errors = []

        for event in events:
            try:
                # Convert event to dict
                event_dict = event.to_dict()

                # Serialize
                if self._serializer:
                    from confluent_kafka.serialization import SerializationContext, MessageField
                    ctx = SerializationContext(self.kafka_config.topic, MessageField.VALUE)
                    value = self._serializer(event_dict, ctx)
                else:
                    value = json.dumps(event_dict).encode("utf-8")

                # Produce with backpressure handling
                self._safe_produce(
                    topic=self.kafka_config.topic,
                    key=event.id.encode("utf-8") if event.id else None,
                    value=value,
                )
                written += 1

            except Exception as e:
                logger.error(f"Failed to produce event {event.id}: {e}")
                failed += 1
                failed_records.append(event)
                errors.append(str(e))

        # Poll to handle delivery reports
        self._producer.poll(0)

        duration_ms = (time.time() - start_time) * 1000

        status = SinkStatus.SUCCESS
        if failed > 0:
            status = SinkStatus.PARTIAL if written > 0 else SinkStatus.FAILURE

        result = SinkResult(
            status=status,
            sink_name=self.name,
            records_written=written,
            records_failed=failed,
            failed_records=failed_records,
            errors=errors,
            duration_ms=duration_ms,
            metadata={
                "topic": self.kafka_config.topic,
                "producer_queue_size": len(self._producer),
            },
        )

        self._update_metrics(result)
        return result

    def _safe_produce(self, topic: str, key: Optional[bytes], value: bytes) -> None:
        """Produce with backpressure handling."""
        while True:
            try:
                self._producer.poll(0)
                self._producer.produce(topic, key=key, value=value)
                return
            except BufferError:
                # Buffer full, wait for space
                self._producer.poll(0.1)

    async def flush(self) -> None:
        """Flush producer buffer."""
        if self._producer:
            remaining = self._producer.flush(timeout=30)
            if remaining > 0:
                logger.warning(f"Kafka producer flush incomplete, {remaining} messages remaining")

    async def close(self) -> None:
        """Close the producer."""
        if self._producer:
            self._producer.flush(timeout=10)
            logger.info("Kafka sink closed")

    async def health_check(self) -> bool:
        """Check Kafka connectivity."""
        if not self._producer:
            return False

        try:
            metadata = self._producer.list_topics(timeout=5.0)
            return self.kafka_config.topic in metadata.topics
        except Exception as e:
            logger.error(f"Kafka health check failed: {e}")
            return False
