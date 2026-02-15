"""Multi-sink output module for audit events."""

from .base_sink import BaseSink, SinkResult, SinkStatus
from .kafka_sink import KafkaSink
from .s3_sink import S3Sink
from .gcs_sink import GCSSink
from .dlq_sink import DLQSink
from .sink_manager import SinkManager

__all__ = [
    "BaseSink",
    "SinkResult",
    "SinkStatus",
    "KafkaSink",
    "S3Sink",
    "GCSSink",
    "DLQSink",
    "SinkManager",
]
