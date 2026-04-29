"""
GCS sink for exporting audit events to Google Cloud Storage.

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
from typing import List, Dict, Any, Optional

from .base_sink import BufferedSink, SinkResult, SinkStatus
from ..transformer.cloudevents import AuditEvent
from ..config.settings import GCSSinkConfig

logger = logging.getLogger(__name__)


class GCSSink(BufferedSink):
    """
    GCS sink for audit events.

    Buffers events and writes them in batches to GCS as Parquet,
    JSON Lines, or CSV files with time-based partitioning.
    """

    def __init__(
        self,
        config: GCSSinkConfig,
        enabled: bool = True,
    ):
        super().__init__(
            name="gcs",
            enabled=enabled,
            buffer_size=config.batch_size,
            flush_interval_seconds=config.flush_interval_seconds,
        )
        self.config = config
        self._storage_client = None
        self._bucket = None
        self._file_counter = 0

    async def initialize(self) -> None:
        """Initialize GCS client."""
        if not self.enabled:
            logger.info("GCS sink is disabled, skipping initialization")
            return

        try:
            from google.cloud import storage

            # Create client
            if self.config.credentials_file:
                self._storage_client = storage.Client.from_service_account_json(
                    self.config.credentials_file,
                    project=self.config.project_id,
                )
            else:
                # Use default credentials (ADC)
                self._storage_client = storage.Client(project=self.config.project_id)

            # Get bucket reference
            self._bucket = self._storage_client.bucket(self.config.bucket)

            # Verify bucket exists
            if not self._bucket.exists():
                raise ValueError(f"Bucket {self.config.bucket} does not exist")

            self._is_initialized = True
            logger.info(f"GCS sink initialized, writing to gs://{self.config.bucket}/{self.config.prefix}")

        except ImportError:
            logger.error("google-cloud-storage not installed. Install with: pip install google-cloud-storage")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize GCS sink: {e}")
            raise

    async def _write_batch(self, events: List[AuditEvent]) -> SinkResult:
        """Write a batch of events to GCS."""
        if not self._bucket:
            return SinkResult(
                status=SinkStatus.FAILURE,
                sink_name=self.name,
                errors=["GCS client not initialized"],
            )

        start_time = time.time()

        try:
            # Generate file path with partitioning
            now = datetime.now(timezone.utc)
            partition_path = self._get_partition_path(now)
            file_name = self._generate_file_name(now)
            gcs_path = f"{self.config.prefix}{partition_path}/{file_name}"

            # Convert events to desired format
            content, content_type = self._serialize_events(events)
            content_size = len(content)

            # Upload to GCS
            blob = self._bucket.blob(gcs_path)
            blob.metadata = {
                "event-count": str(len(events)),
                "created-by": "audit-forwarder-v2",
            }
            blob.upload_from_string(content, content_type=content_type)

            duration_ms = (time.time() - start_time) * 1000

            result = SinkResult(
                status=SinkStatus.SUCCESS,
                sink_name=self.name,
                records_written=len(events),
                duration_ms=duration_ms,
                metadata={
                    "bucket": self.config.bucket,
                    "path": gcs_path,
                    "format": self.config.format,
                    "size_bytes": content_size,
                },
            )

            self.metrics.total_bytes += content_size
            self._update_metrics(result)

            logger.info(f"Wrote {len(events)} events to gs://{self.config.bucket}/{gcs_path}")
            return result

        except Exception as e:
            logger.error(f"Failed to write to GCS: {e}")
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

            records = [e.to_flat_dict() for e in events]
            table = pa.Table.from_pylist(records)

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

        fieldnames = list(events[0].to_flat_dict().keys())

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for event in events:
            row = event.to_flat_dict()
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
        logger.info("GCS sink closed")

    async def health_check(self) -> bool:
        """Check GCS connectivity."""
        if not self._bucket:
            return False

        try:
            return self._bucket.exists()
        except Exception as e:
            logger.error(f"GCS health check failed: {e}")
            return False
