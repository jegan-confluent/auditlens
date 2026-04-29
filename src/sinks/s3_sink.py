"""
S3 sink for exporting audit events to Amazon S3.

Features:
- Parquet, JSON, and CSV formats
- Time-based partitioning
- Snappy/GZIP compression
- Buffered writes for efficiency
"""

import asyncio
import io
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from .base_sink import BufferedSink, SinkResult, SinkStatus
from ..transformer.cloudevents import AuditEvent
from ..config.settings import S3SinkConfig

logger = logging.getLogger(__name__)


class S3Sink(BufferedSink):
    """
    S3 sink for audit events.

    Buffers events and writes them in batches to S3 as Parquet,
    JSON Lines, or CSV files with time-based partitioning.
    """

    def __init__(
        self,
        config: S3SinkConfig,
        enabled: bool = True,
    ):
        super().__init__(
            name="s3",
            enabled=enabled,
            buffer_size=config.batch_size,
            flush_interval_seconds=config.flush_interval_seconds,
        )
        self.config = config
        self._s3_client = None
        self._file_counter = 0

    async def initialize(self) -> None:
        """Initialize S3 client."""
        if not self.enabled:
            logger.info("S3 sink is disabled, skipping initialization")
            return

        try:
            import boto3
            from botocore.config import Config as BotoConfig

            # Configure client
            boto_config = BotoConfig(
                region_name=self.config.region,
                retries={"max_attempts": 3, "mode": "adaptive"},
            )

            # Create client with optional credentials
            client_kwargs = {"config": boto_config}
            if self.config.aws_access_key_id and self.config.aws_secret_access_key:
                client_kwargs["aws_access_key_id"] = self.config.aws_access_key_id
                client_kwargs["aws_secret_access_key"] = self.config.aws_secret_access_key

            self._s3_client = boto3.client("s3", **client_kwargs)

            # Verify bucket access
            self._s3_client.head_bucket(Bucket=self.config.bucket)

            self._is_initialized = True
            logger.info(f"S3 sink initialized, writing to s3://{self.config.bucket}/{self.config.prefix}")

        except ImportError:
            logger.error("boto3 not installed. Install with: pip install boto3")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize S3 sink: {e}")
            raise

    async def _write_batch(self, events: List[AuditEvent]) -> SinkResult:
        """Write a batch of events to S3."""
        if not self._s3_client:
            return SinkResult(
                status=SinkStatus.FAILURE,
                sink_name=self.name,
                errors=["S3 client not initialized"],
            )

        start_time = time.time()

        try:
            # Generate file path with partitioning
            now = datetime.now(timezone.utc)
            partition_path = self._get_partition_path(now)
            file_name = self._generate_file_name(now)
            s3_key = f"{self.config.prefix}{partition_path}/{file_name}"

            # Convert events to desired format
            content, content_type = self._serialize_events(events)
            content_size = len(content)

            # Upload to S3
            self._s3_client.put_object(
                Bucket=self.config.bucket,
                Key=s3_key,
                Body=content,
                ContentType=content_type,
                Metadata={
                    "event-count": str(len(events)),
                    "created-by": "audit-forwarder-v2",
                },
            )

            duration_ms = (time.time() - start_time) * 1000

            result = SinkResult(
                status=SinkStatus.SUCCESS,
                sink_name=self.name,
                records_written=len(events),
                duration_ms=duration_ms,
                metadata={
                    "bucket": self.config.bucket,
                    "key": s3_key,
                    "format": self.config.format,
                    "size_bytes": content_size,
                },
            )

            self.metrics.total_bytes += content_size
            self._update_metrics(result)

            logger.info(f"Wrote {len(events)} events to s3://{self.config.bucket}/{s3_key}")
            return result

        except Exception as e:
            logger.error(f"Failed to write to S3: {e}")
            return SinkResult(
                status=SinkStatus.FAILURE,
                sink_name=self.name,
                records_failed=len(events),
                failed_records=events,
                errors=[str(e)],
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _get_partition_path(self, timestamp: datetime) -> str:
        """Generate partition path based on configuration."""
        if self.config.partition_by == "hour":
            return f"year={timestamp.year}/month={timestamp.month:02d}/day={timestamp.day:02d}/hour={timestamp.hour:02d}"
        elif self.config.partition_by == "day":
            return f"year={timestamp.year}/month={timestamp.month:02d}/day={timestamp.day:02d}"
        elif self.config.partition_by == "event_type":
            # This would need to be per-event, so we use time for the base
            return f"dt={timestamp.strftime('%Y-%m-%d')}"
        else:
            return f"dt={timestamp.strftime('%Y-%m-%d')}/hr={timestamp.hour:02d}"

    def _generate_file_name(self, timestamp: datetime) -> str:
        """Generate unique file name."""
        self._file_counter += 1
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S")

        ext = self.config.format
        if self.config.compression == "gzip":
            ext = f"{ext}.gz"
        elif self.config.compression == "snappy" and self.config.format == "parquet":
            pass  # Snappy is embedded in Parquet

        return f"audit_events_{ts_str}_{self._file_counter:06d}.{ext}"

    def _serialize_events(self, events: List[AuditEvent]) -> tuple[bytes, str]:
        """Serialize events to the configured format."""
        if self.config.format == "parquet":
            return self._to_parquet(events), "application/octet-stream"
        elif self.config.format == "json":
            return self._to_json_lines(events), "application/x-ndjson"
        elif self.config.format == "csv":
            return self._to_csv(events), "text/csv"
        else:
            return self._to_json_lines(events), "application/x-ndjson"

    def _to_parquet(self, events: List[AuditEvent]) -> bytes:
        """Convert events to Parquet format."""
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            # Convert to list of dicts
            records = [e.to_flat_dict() for e in events]

            # Create PyArrow table
            table = pa.Table.from_pylist(records)

            # Write to buffer
            buffer = io.BytesIO()
            pq.write_table(
                table,
                buffer,
                compression=self.config.compression if self.config.compression != "none" else None,
            )

            return buffer.getvalue()

        except ImportError:
            logger.error("pyarrow not installed. Install with: pip install pyarrow")
            raise

    def _to_json_lines(self, events: List[AuditEvent]) -> bytes:
        """Convert events to JSON Lines format."""
        lines = [json.dumps(e.to_dict(), separators=(",", ":")) for e in events]
        content = "\n".join(lines).encode("utf-8")

        if self.config.compression == "gzip":
            import gzip
            content = gzip.compress(content)

        return content

    def _to_csv(self, events: List[AuditEvent]) -> bytes:
        """Convert events to CSV format."""
        import csv
        from io import StringIO

        if not events:
            return b""

        # Get all possible fields from first event
        fieldnames = list(events[0].to_flat_dict().keys())

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for event in events:
            row = event.to_flat_dict()
            # Convert non-string values to strings
            for k, v in row.items():
                if v is not None and not isinstance(v, str):
                    row[k] = str(v)
            writer.writerow(row)

        content = output.getvalue().encode("utf-8")

        if self.config.compression == "gzip":
            import gzip
            content = gzip.compress(content)

        return content

    async def close(self) -> None:
        """Flush and close the sink."""
        await self.flush()
        logger.info("S3 sink closed")

    async def health_check(self) -> bool:
        """Check S3 connectivity."""
        if not self._s3_client:
            return False

        try:
            self._s3_client.head_bucket(Bucket=self.config.bucket)
            return True
        except Exception as e:
            logger.error(f"S3 health check failed: {e}")
            return False
