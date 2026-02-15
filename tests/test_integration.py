"""Integration tests for Audit Forwarder v2.

These tests require running infrastructure (Kafka, S3/GCS).
Use with pytest markers to skip when infrastructure is unavailable.
"""

import pytest
import asyncio
import os
from typing import List

# Skip markers for integration tests
pytestmark = pytest.mark.integration


def kafka_available():
    """Check if Kafka is available for testing."""
    return os.getenv("TEST_KAFKA_BOOTSTRAP") is not None


def s3_available():
    """Check if S3 is available for testing."""
    return (
        os.getenv("TEST_S3_BUCKET") is not None
        and os.getenv("AWS_ACCESS_KEY_ID") is not None
    )


def gcs_available():
    """Check if GCS is available for testing."""
    return (
        os.getenv("TEST_GCS_BUCKET") is not None
        and os.getenv("GOOGLE_APPLICATION_CREDENTIALS") is not None
    )


@pytest.mark.skipif(not kafka_available(), reason="Kafka not available")
class TestKafkaSinkIntegration:
    """Integration tests for Kafka sink."""

    @pytest.mark.asyncio
    async def test_kafka_sink_write(self, sample_authentication_event):
        """Test writing events to Kafka sink."""
        from src.sinks.kafka_sink import KafkaSink
        from src.transformer.cloudevents import CloudEventsParser

        bootstrap = os.getenv("TEST_KAFKA_BOOTSTRAP")
        topic = os.getenv("TEST_KAFKA_TOPIC", "test-audit-logs")

        parser = CloudEventsParser()
        event = parser.parse(sample_authentication_event)

        sink = KafkaSink(
            bootstrap_servers=bootstrap,
            topic=topic,
            client_id="test-producer"
        )

        await sink.initialize()

        try:
            result = await sink.write([event])
            assert result.success is True
            assert result.events_written == 1
        finally:
            await sink.close()

    @pytest.mark.asyncio
    async def test_kafka_sink_batch_write(self, sample_authentication_event, sample_authorization_event):
        """Test batch writing to Kafka sink."""
        from src.sinks.kafka_sink import KafkaSink
        from src.transformer.cloudevents import CloudEventsParser

        bootstrap = os.getenv("TEST_KAFKA_BOOTSTRAP")
        topic = os.getenv("TEST_KAFKA_TOPIC", "test-audit-logs")

        parser = CloudEventsParser()
        events = [
            parser.parse(sample_authentication_event),
            parser.parse(sample_authorization_event)
        ]

        sink = KafkaSink(
            bootstrap_servers=bootstrap,
            topic=topic,
            client_id="test-producer"
        )

        await sink.initialize()

        try:
            result = await sink.write(events)
            assert result.success is True
            assert result.events_written == 2
        finally:
            await sink.close()


@pytest.mark.skipif(not s3_available(), reason="S3 not available")
class TestS3SinkIntegration:
    """Integration tests for S3 sink."""

    @pytest.mark.asyncio
    async def test_s3_sink_write_parquet(self, sample_authentication_event):
        """Test writing Parquet to S3."""
        from src.sinks.s3_sink import S3Sink
        from src.transformer.cloudevents import CloudEventsParser

        bucket = os.getenv("TEST_S3_BUCKET")
        region = os.getenv("TEST_S3_REGION", "us-west-2")

        parser = CloudEventsParser()
        event = parser.parse(sample_authentication_event)

        sink = S3Sink(
            bucket=bucket,
            region=region,
            prefix="test-audit-logs/",
            format="parquet",
            batch_size=1
        )

        await sink.initialize()

        try:
            result = await sink.write([event])
            assert result.success is True
            assert result.events_written == 1
        finally:
            await sink.close()

    @pytest.mark.asyncio
    async def test_s3_sink_write_json(self, sample_authentication_event):
        """Test writing JSON to S3."""
        from src.sinks.s3_sink import S3Sink
        from src.transformer.cloudevents import CloudEventsParser

        bucket = os.getenv("TEST_S3_BUCKET")
        region = os.getenv("TEST_S3_REGION", "us-west-2")

        parser = CloudEventsParser()
        event = parser.parse(sample_authentication_event)

        sink = S3Sink(
            bucket=bucket,
            region=region,
            prefix="test-audit-logs/",
            format="json",
            batch_size=1
        )

        await sink.initialize()

        try:
            result = await sink.write([event])
            assert result.success is True
        finally:
            await sink.close()


@pytest.mark.skipif(not gcs_available(), reason="GCS not available")
class TestGCSSinkIntegration:
    """Integration tests for GCS sink."""

    @pytest.mark.asyncio
    async def test_gcs_sink_write_parquet(self, sample_authentication_event):
        """Test writing Parquet to GCS."""
        from src.sinks.gcs_sink import GCSSink
        from src.transformer.cloudevents import CloudEventsParser

        bucket = os.getenv("TEST_GCS_BUCKET")
        project = os.getenv("TEST_GCS_PROJECT")

        parser = CloudEventsParser()
        event = parser.parse(sample_authentication_event)

        sink = GCSSink(
            bucket=bucket,
            project_id=project,
            prefix="test-audit-logs/",
            format="parquet",
            batch_size=1
        )

        await sink.initialize()

        try:
            result = await sink.write([event])
            assert result.success is True
            assert result.events_written == 1
        finally:
            await sink.close()


class TestSinkManagerIntegration:
    """Integration tests for sink manager."""

    @pytest.mark.asyncio
    async def test_sink_manager_parallel_writes(self, sample_authentication_event):
        """Test sink manager coordinates parallel writes."""
        # This test uses mock sinks
        from src.sinks.sink_manager import SinkManager
        from src.sinks.base_sink import BaseSink, SinkResult
        from src.transformer.cloudevents import CloudEventsParser

        class MockSink(BaseSink):
            def __init__(self, name: str):
                self.name = name
                self.write_count = 0

            async def initialize(self):
                pass

            async def write(self, events: List) -> SinkResult:
                self.write_count += len(events)
                await asyncio.sleep(0.1)  # Simulate I/O
                return SinkResult(
                    success=True,
                    events_written=len(events),
                    sink_name=self.name
                )

            async def flush(self):
                pass

            async def close(self):
                pass

            async def health_check(self) -> bool:
                return True

        parser = CloudEventsParser()
        event = parser.parse(sample_authentication_event)

        sink1 = MockSink("sink1")
        sink2 = MockSink("sink2")

        manager = SinkManager([sink1, sink2])
        await manager.initialize()

        try:
            results = await manager.write([event])

            assert len(results) == 2
            assert all(r.success for r in results)
            assert sink1.write_count == 1
            assert sink2.write_count == 1
        finally:
            await manager.close()
