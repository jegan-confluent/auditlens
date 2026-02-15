"""
Sink manager for coordinating multiple output sinks.

Handles:
- Sink initialization and lifecycle
- Parallel writes to multiple sinks
- DLQ routing for failures
- Health monitoring
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from .base_sink import BaseSink, SinkResult, SinkStatus
from .kafka_sink import KafkaSink
from .s3_sink import S3Sink
from .gcs_sink import GCSSink
from .dlq_sink import DLQSink
from ..transformer.cloudevents import AuditEvent
from ..config.settings import Settings

logger = logging.getLogger(__name__)


class SinkManager:
    """
    Manages multiple output sinks for audit events.

    Coordinates writes to enabled sinks (Kafka, S3, GCS) in parallel
    and routes failures to DLQ for later processing.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.sinks: Dict[str, BaseSink] = {}
        self.dlq_sink: Optional[DLQSink] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize all enabled sinks."""
        logger.info("Initializing sink manager...")

        # Initialize Kafka sink if enabled
        if "kafka" in self.settings.enabled_sinks:
            kafka_sink = KafkaSink(
                kafka_config=self.settings.get_kafka_dest_config(),
                schema_registry_config=self.settings.get_schema_registry_config(),
                enabled=True,
            )
            await kafka_sink.initialize()
            self.sinks["kafka"] = kafka_sink

        # Initialize S3 sink if enabled
        if "s3" in self.settings.enabled_sinks or self.settings.s3_enabled:
            s3_sink = S3Sink(
                config=self.settings.get_s3_sink_config(),
                enabled=True,
            )
            await s3_sink.initialize()
            self.sinks["s3"] = s3_sink

        # Initialize GCS sink if enabled
        if "gcs" in self.settings.enabled_sinks or self.settings.gcs_enabled:
            gcs_sink = GCSSink(
                config=self.settings.get_gcs_sink_config(),
                enabled=True,
            )
            await gcs_sink.initialize()
            self.sinks["gcs"] = gcs_sink

        # Initialize DLQ sink if enabled
        if self.settings.dlq_enabled:
            dlq_config = self.settings.get_dlq_config()
            self.dlq_sink = DLQSink(
                config=dlq_config,
                kafka_bootstrap=self.settings.dest_bootstrap,
                api_key=self.settings.dest_api_key,
                api_secret=self.settings.dest_api_secret,
                enabled=True,
            )
            await self.dlq_sink.initialize()

        self._initialized = True
        logger.info(f"Sink manager initialized with sinks: {list(self.sinks.keys())}")

    async def write(self, events: List[AuditEvent]) -> Dict[str, SinkResult]:
        """
        Write events to all enabled sinks in parallel.

        Returns a dict of sink_name -> SinkResult for each sink.
        Failed events are automatically routed to DLQ.
        """
        if not self._initialized:
            raise RuntimeError("Sink manager not initialized")

        if not events:
            return {}

        # Write to all sinks in parallel
        tasks = {
            name: asyncio.create_task(sink.write(events))
            for name, sink in self.sinks.items()
            if sink.enabled
        }

        results: Dict[str, SinkResult] = {}
        all_failures: List[tuple[AuditEvent, str, str]] = []

        # Gather results
        for name, task in tasks.items():
            try:
                result = await task
                results[name] = result

                # Collect failures for DLQ
                if result.failed_records:
                    for event in result.failed_records:
                        error_msg = result.errors[0] if result.errors else "Unknown error"
                        all_failures.append((event, f"{name}_sink_error", error_msg))

            except Exception as e:
                logger.error(f"Sink {name} failed: {e}")
                results[name] = SinkResult(
                    status=SinkStatus.FAILURE,
                    sink_name=name,
                    records_failed=len(events),
                    failed_records=events,
                    errors=[str(e)],
                )
                # All events failed for this sink
                for event in events:
                    all_failures.append((event, f"{name}_sink_exception", str(e)))

        # Route failures to DLQ
        if all_failures and self.dlq_sink and self.dlq_sink.enabled:
            # Deduplicate by event ID (event might fail in multiple sinks)
            seen_ids = set()
            unique_failures = []
            for event, error_type, error_msg in all_failures:
                if event.id not in seen_ids:
                    seen_ids.add(event.id)
                    unique_failures.append((event, error_type, error_msg))

            dlq_result = await self.dlq_sink.write_failures(unique_failures)
            results["dlq"] = dlq_result

        return results

    async def flush_all(self) -> None:
        """Flush all sinks."""
        tasks = [sink.flush() for sink in self.sinks.values()]
        if self.dlq_sink:
            tasks.append(self.dlq_sink.flush())

        await asyncio.gather(*tasks, return_exceptions=True)

    async def close_all(self) -> None:
        """Close all sinks."""
        logger.info("Closing all sinks...")

        # Flush first
        await self.flush_all()

        # Close sinks
        tasks = [sink.close() for sink in self.sinks.values()]
        if self.dlq_sink:
            tasks.append(self.dlq_sink.close())

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("All sinks closed")

    async def health_check(self) -> Dict[str, bool]:
        """Check health of all sinks."""
        results = {}

        for name, sink in self.sinks.items():
            try:
                results[name] = await sink.health_check()
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                results[name] = False

        if self.dlq_sink:
            try:
                results["dlq"] = await self.dlq_sink.health_check()
            except Exception as e:
                results["dlq"] = False

        return results

    def get_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics from all sinks."""
        metrics = {}

        for name, sink in self.sinks.items():
            metrics[name] = sink.get_metrics()

        if self.dlq_sink:
            metrics["dlq"] = self.dlq_sink.get_metrics()

        return metrics

    def get_status(self) -> Dict[str, Any]:
        """Get overall sink manager status."""
        sink_health = {}
        for name, sink in self.sinks.items():
            sink_health[name] = {
                "enabled": sink.enabled,
                "initialized": sink._is_initialized,
                "total_records": sink.metrics.total_records,
                "total_failures": sink.metrics.total_failures,
            }

        return {
            "initialized": self._initialized,
            "enabled_sinks": list(self.sinks.keys()),
            "dlq_enabled": self.dlq_sink is not None and self.dlq_sink.enabled,
            "sinks": sink_health,
        }
