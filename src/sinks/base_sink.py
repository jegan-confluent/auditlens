"""
Base sink interface for audit event output.

All sinks (Kafka, S3, GCS, DLQ) implement this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Any, Optional
import logging

from ..transformer.cloudevents import AuditEvent

logger = logging.getLogger(__name__)


class SinkStatus(str, Enum):
    """Sink operation status."""
    SUCCESS = "success"
    PARTIAL = "partial"  # Some records failed
    FAILURE = "failure"
    SKIPPED = "skipped"


@dataclass
class SinkResult:
    """Result of a sink write operation."""
    status: SinkStatus
    sink_name: str
    records_written: int = 0
    records_failed: int = 0
    failed_records: List[AuditEvent] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        return self.status == SinkStatus.SUCCESS

    @property
    def has_failures(self) -> bool:
        return self.records_failed > 0


@dataclass
class SinkMetrics:
    """Metrics for a sink."""
    total_writes: int = 0
    total_records: int = 0
    total_failures: int = 0
    total_bytes: int = 0
    last_write_time: Optional[datetime] = None
    last_error_time: Optional[datetime] = None
    last_error: Optional[str] = None
    avg_latency_ms: float = 0.0


class BaseSink(ABC):
    """
    Abstract base class for all audit event sinks.

    Implementations must provide:
    - write(): Write a batch of events
    - flush(): Flush any buffered data
    - close(): Clean up resources
    - health_check(): Verify sink is operational
    """

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled
        self.metrics = SinkMetrics()
        self._is_initialized = False

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the sink (create connections, verify access, etc.)."""
        pass

    @abstractmethod
    async def write(self, events: List[AuditEvent]) -> SinkResult:
        """
        Write a batch of events to the sink.

        Args:
            events: List of audit events to write

        Returns:
            SinkResult with write status and any failures
        """
        pass

    @abstractmethod
    async def flush(self) -> None:
        """Flush any buffered data to the sink."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the sink and release resources."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the sink is healthy and operational.

        Returns:
            True if sink is healthy, False otherwise
        """
        pass

    def _update_metrics(self, result: SinkResult) -> None:
        """Update sink metrics after a write operation."""
        self.metrics.total_writes += 1
        self.metrics.total_records += result.records_written
        self.metrics.total_failures += result.records_failed
        self.metrics.last_write_time = datetime.now(timezone.utc)

        if result.errors:
            self.metrics.last_error_time = datetime.now(timezone.utc)
            self.metrics.last_error = result.errors[-1]

        # Update rolling average latency
        if self.metrics.total_writes > 0:
            alpha = 0.1  # Exponential moving average factor
            self.metrics.avg_latency_ms = (
                alpha * result.duration_ms +
                (1 - alpha) * self.metrics.avg_latency_ms
            )

    def get_metrics(self) -> Dict[str, Any]:
        """Get sink metrics as a dictionary."""
        return {
            "sink_name": self.name,
            "enabled": self.enabled,
            "initialized": self._is_initialized,
            "total_writes": self.metrics.total_writes,
            "total_records": self.metrics.total_records,
            "total_failures": self.metrics.total_failures,
            "total_bytes": self.metrics.total_bytes,
            "last_write_time": self.metrics.last_write_time.isoformat() if self.metrics.last_write_time else None,
            "last_error_time": self.metrics.last_error_time.isoformat() if self.metrics.last_error_time else None,
            "last_error": self.metrics.last_error,
            "avg_latency_ms": self.metrics.avg_latency_ms,
        }


class BufferedSink(BaseSink):
    """
    Base class for sinks that buffer events before writing.

    Useful for cloud storage sinks where batch writes are more efficient.
    """

    def __init__(
        self,
        name: str,
        enabled: bool = True,
        buffer_size: int = 10000,
        flush_interval_seconds: int = 300,
    ):
        super().__init__(name, enabled)
        self.buffer_size = buffer_size
        self.flush_interval_seconds = flush_interval_seconds
        self._buffer: List[AuditEvent] = []
        self._last_flush: datetime = datetime.now(timezone.utc)

    async def write(self, events: List[AuditEvent]) -> SinkResult:
        """Add events to buffer, flush if necessary."""
        self._buffer.extend(events)

        should_flush = (
            len(self._buffer) >= self.buffer_size or
            self._time_since_flush_seconds() >= self.flush_interval_seconds
        )

        if should_flush:
            return await self._flush_buffer()

        # Return success without actual write
        return SinkResult(
            status=SinkStatus.SUCCESS,
            sink_name=self.name,
            records_written=0,  # Buffered, not written yet
            metadata={"buffered": len(events), "buffer_size": len(self._buffer)},
        )

    async def flush(self) -> None:
        """Flush the buffer."""
        if self._buffer:
            await self._flush_buffer()

    async def _flush_buffer(self) -> SinkResult:
        """Flush buffered events to storage."""
        if not self._buffer:
            return SinkResult(
                status=SinkStatus.SKIPPED,
                sink_name=self.name,
                metadata={"reason": "buffer_empty"},
            )

        events_to_write = self._buffer.copy()
        self._buffer.clear()
        self._last_flush = datetime.now(timezone.utc)

        return await self._write_batch(events_to_write)

    @abstractmethod
    async def _write_batch(self, events: List[AuditEvent]) -> SinkResult:
        """Actual implementation of batch write. Implemented by subclasses."""
        pass

    def _time_since_flush_seconds(self) -> float:
        """Get seconds since last flush."""
        return (datetime.now(timezone.utc) - self._last_flush).total_seconds()

    def get_buffer_status(self) -> Dict[str, Any]:
        """Get buffer status."""
        return {
            "buffer_count": len(self._buffer),
            "buffer_capacity": self.buffer_size,
            "buffer_utilization": len(self._buffer) / self.buffer_size if self.buffer_size > 0 else 0,
            "seconds_since_flush": self._time_since_flush_seconds(),
            "flush_interval_seconds": self.flush_interval_seconds,
        }
