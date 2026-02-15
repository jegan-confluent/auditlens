#!/usr/bin/env python3
"""
Confluent Cloud Audit Log Collector

Simple, focused tool that:
1. Connects to Confluent Cloud audit log topic
2. Fetches events
3. Parses and flattens for easy querying
4. Writes Parquet files to S3/GCS

That's it. No complex processing. Let customers use their own query tools.
"""

import json
import os
import re
import signal
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from confluent_kafka import Consumer, KafkaError

# Optional cloud storage
try:
    import boto3
    HAS_S3 = True
except ImportError:
    HAS_S3 = False

try:
    from google.cloud import storage as gcs
    HAS_GCS = True
except ImportError:
    HAS_GCS = False


@dataclass
class AuditEvent:
    """Flattened audit event for easy querying."""
    # Core identification
    event_id: str
    event_time: Optional[str]
    event_type: str

    # Who
    principal: Optional[str]
    principal_type: Optional[str]  # User, ServiceAccount

    # What
    method_name: Optional[str]
    result_status: Optional[str]
    result_message: Optional[str]

    # Where (extracted from CRN)
    organization_id: Optional[str]
    environment_id: Optional[str]
    cluster_type: Optional[str]
    cluster_id: Optional[str]
    resource_type: Optional[str]
    resource_name: Optional[str]

    # Context
    client_ip: Optional[str]
    service_name: Optional[str]

    # Authorization details
    auth_resource_type: Optional[str]
    auth_resource_name: Optional[str]
    auth_operation: Optional[str]
    auth_granted: Optional[bool]

    # Flags for easy filtering
    is_security_event: bool
    is_auth_failure: bool
    is_permission_denied: bool

    # Raw data for advanced queries
    raw_source: Optional[str]
    raw_subject: Optional[str]


def parse_crn(crn: Optional[str]) -> Dict[str, Optional[str]]:
    """Extract components from Confluent Resource Name."""
    result = {
        'organization_id': None,
        'environment_id': None,
        'cluster_type': None,
        'cluster_id': None,
    }

    if not crn:
        return result

    # Organization
    match = re.search(r'organization=([^/]+)', crn)
    if match:
        result['organization_id'] = match.group(1)

    # Environment
    match = re.search(r'environment=([^/]+)', crn)
    if match:
        result['environment_id'] = match.group(1)

    # Cluster (try different types)
    for cluster_type in ['kafka', 'schema-registry', 'ksqldb', 'flink', 'connect']:
        match = re.search(f'{cluster_type}=([^/]+)', crn)
        if match:
            result['cluster_type'] = cluster_type
            result['cluster_id'] = match.group(1)
            break

    return result


def parse_event(raw: Dict[str, Any]) -> AuditEvent:
    """Parse raw CloudEvent into flattened AuditEvent."""
    data = raw.get('data', {})
    auth_info = data.get('authenticationInfo', {})
    authz_info = data.get('authorizationInfo', {})
    result = data.get('result', {})
    request_meta = data.get('requestMetadata', {})

    # Extract CRN components
    source = raw.get('source', '')
    crn = parse_crn(source)

    # Extract resource from subject if present
    subject = raw.get('subject', '')
    resource_match = re.search(r'/([^/=]+)=([^/]+)$', subject)
    resource_type = resource_match.group(1) if resource_match else None
    resource_name = resource_match.group(2) if resource_match else None

    # Principal parsing
    principal = auth_info.get('principal', '')
    principal_type = None
    if principal:
        if principal.startswith('User:sa-'):
            principal_type = 'ServiceAccount'
        elif principal.startswith('User:'):
            principal_type = 'User'

    # Status flags
    status = result.get('status', '')
    is_auth_failure = status == 'UNAUTHENTICATED'
    is_permission_denied = status == 'PERMISSION_DENIED'
    is_security_event = is_auth_failure or is_permission_denied

    return AuditEvent(
        event_id=raw.get('id', ''),
        event_time=raw.get('time'),
        event_type=raw.get('type', ''),
        principal=principal or None,
        principal_type=principal_type,
        method_name=data.get('methodName'),
        result_status=status or None,
        result_message=result.get('message'),
        organization_id=crn['organization_id'],
        environment_id=crn['environment_id'],
        cluster_type=crn['cluster_type'],
        cluster_id=crn['cluster_id'],
        resource_type=resource_type,
        resource_name=resource_name or data.get('resourceName'),
        client_ip=request_meta.get('clientAddress'),
        service_name=data.get('serviceName'),
        auth_resource_type=authz_info.get('resourceType'),
        auth_resource_name=authz_info.get('resourceName'),
        auth_operation=authz_info.get('operation'),
        auth_granted=authz_info.get('granted'),
        is_security_event=is_security_event,
        is_auth_failure=is_auth_failure,
        is_permission_denied=is_permission_denied,
        raw_source=source or None,
        raw_subject=subject or None,
    )


class ParquetWriter:
    """Write events to Parquet files."""

    SCHEMA = pa.schema([
        ('event_id', pa.string()),
        ('event_time', pa.string()),
        ('event_type', pa.string()),
        ('principal', pa.string()),
        ('principal_type', pa.string()),
        ('method_name', pa.string()),
        ('result_status', pa.string()),
        ('result_message', pa.string()),
        ('organization_id', pa.string()),
        ('environment_id', pa.string()),
        ('cluster_type', pa.string()),
        ('cluster_id', pa.string()),
        ('resource_type', pa.string()),
        ('resource_name', pa.string()),
        ('client_ip', pa.string()),
        ('service_name', pa.string()),
        ('auth_resource_type', pa.string()),
        ('auth_resource_name', pa.string()),
        ('auth_operation', pa.string()),
        ('auth_granted', pa.bool_()),
        ('is_security_event', pa.bool_()),
        ('is_auth_failure', pa.bool_()),
        ('is_permission_denied', pa.bool_()),
        ('raw_source', pa.string()),
        ('raw_subject', pa.string()),
    ])

    def __init__(self, output_dir: str = '/tmp/audit-logs'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, events: List[AuditEvent]) -> str:
        """Write events to a Parquet file, return file path."""
        if not events:
            return None

        # Create partitioned path: year=YYYY/month=MM/day=DD/
        now = datetime.now(timezone.utc)
        partition_path = self.output_dir / f"year={now.year}" / f"month={now.month:02d}" / f"day={now.day:02d}"
        partition_path.mkdir(parents=True, exist_ok=True)

        # File name with timestamp
        filename = f"events_{now.strftime('%Y%m%d_%H%M%S')}_{len(events)}.parquet"
        file_path = partition_path / filename

        # Convert to Arrow table
        data = {field.name: [] for field in self.SCHEMA}
        for event in events:
            event_dict = asdict(event)
            for field in self.SCHEMA:
                data[field.name].append(event_dict.get(field.name))

        table = pa.table(data, schema=self.SCHEMA)

        # Write with Snappy compression
        pq.write_table(table, file_path, compression='snappy')

        return str(file_path)


class S3Uploader:
    """Upload Parquet files to S3."""

    def __init__(self, bucket: str, prefix: str = 'confluent-audit-logs/'):
        if not HAS_S3:
            raise ImportError("boto3 not installed. Run: pip install boto3")
        self.bucket = bucket
        self.prefix = prefix.rstrip('/') + '/'
        self.client = boto3.client('s3')

    def upload(self, local_path: str) -> str:
        """Upload file to S3, return S3 URI."""
        # Preserve partition structure
        path = Path(local_path)
        # Find partition parts (year=, month=, day=)
        parts = []
        for part in path.parts:
            if part.startswith(('year=', 'month=', 'day=')):
                parts.append(part)
        parts.append(path.name)

        s3_key = self.prefix + '/'.join(parts)

        self.client.upload_file(local_path, self.bucket, s3_key)

        return f"s3://{self.bucket}/{s3_key}"


class GCSUploader:
    """Upload Parquet files to GCS."""

    def __init__(self, bucket: str, prefix: str = 'confluent-audit-logs/'):
        if not HAS_GCS:
            raise ImportError("google-cloud-storage not installed. Run: pip install google-cloud-storage")
        self.bucket_name = bucket
        self.prefix = prefix.rstrip('/') + '/'
        self.client = gcs.Client()
        self.bucket = self.client.bucket(bucket)

    def upload(self, local_path: str) -> str:
        """Upload file to GCS, return GCS URI."""
        path = Path(local_path)
        parts = []
        for part in path.parts:
            if part.startswith(('year=', 'month=', 'day=')):
                parts.append(part)
        parts.append(path.name)

        gcs_path = self.prefix + '/'.join(parts)

        blob = self.bucket.blob(gcs_path)
        blob.upload_from_filename(local_path)

        return f"gs://{self.bucket_name}/{gcs_path}"


class AuditLogCollector:
    """Main collector that ties everything together."""

    def __init__(self):
        # Kafka config
        self.bootstrap = os.environ['AUDIT_BOOTSTRAP']
        self.api_key = os.environ['AUDIT_API_KEY']
        self.api_secret = os.environ['AUDIT_API_SECRET']
        self.topic = os.environ.get('AUDIT_TOPIC', 'confluent-audit-log-events')
        self.group_id = os.environ.get('CONSUMER_GROUP', 'audit-log-collector')

        # Batching config
        self.batch_size = int(os.environ.get('BATCH_SIZE', '10000'))
        self.flush_interval = int(os.environ.get('FLUSH_INTERVAL', '300'))

        # Output config
        self.output_dir = os.environ.get('OUTPUT_DIR', '/tmp/audit-logs')
        self.writer = ParquetWriter(self.output_dir)

        # Cloud storage
        self.uploader = None
        if os.environ.get('S3_BUCKET'):
            self.uploader = S3Uploader(
                bucket=os.environ['S3_BUCKET'],
                prefix=os.environ.get('S3_PREFIX', 'confluent-audit-logs/')
            )
        elif os.environ.get('GCS_BUCKET'):
            self.uploader = GCSUploader(
                bucket=os.environ['GCS_BUCKET'],
                prefix=os.environ.get('GCS_PREFIX', 'confluent-audit-logs/')
            )

        # State
        self.running = True
        self.buffer: List[AuditEvent] = []
        self.last_flush = datetime.now()
        self.total_events = 0
        self.total_files = 0

    def _create_consumer(self) -> Consumer:
        """Create Kafka consumer."""
        config = {
            'bootstrap.servers': self.bootstrap,
            'security.protocol': 'SASL_SSL',
            'sasl.mechanisms': 'PLAIN',
            'sasl.username': self.api_key,
            'sasl.password': self.api_secret,
            'group.id': self.group_id,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 5000,
        }
        return Consumer(config)

    def _should_flush(self) -> bool:
        """Check if we should flush the buffer."""
        if len(self.buffer) >= self.batch_size:
            return True
        elapsed = (datetime.now() - self.last_flush).total_seconds()
        if elapsed >= self.flush_interval and self.buffer:
            return True
        return False

    def _flush(self):
        """Write buffered events to storage."""
        if not self.buffer:
            return

        # Write to local Parquet
        local_path = self.writer.write(self.buffer)
        print(f"Wrote {len(self.buffer)} events to {local_path}")

        # Upload to cloud storage
        if self.uploader and local_path:
            cloud_path = self.uploader.upload(local_path)
            print(f"Uploaded to {cloud_path}")

            # Clean up local file
            Path(local_path).unlink()

        self.total_events += len(self.buffer)
        self.total_files += 1
        self.buffer = []
        self.last_flush = datetime.now()

    def run(self):
        """Main loop: consume, parse, buffer, write."""
        consumer = self._create_consumer()
        consumer.subscribe([self.topic])

        print(f"Starting Audit Log Collector")
        print(f"  Topic: {self.topic}")
        print(f"  Batch size: {self.batch_size}")
        print(f"  Flush interval: {self.flush_interval}s")
        print(f"  Output: {self.uploader.__class__.__name__ if self.uploader else 'local'}")
        print("-" * 50)

        try:
            while self.running:
                msg = consumer.poll(timeout=1.0)

                if msg is None:
                    if self._should_flush():
                        self._flush()
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    print(f"Consumer error: {msg.error()}")
                    continue

                # Parse and buffer
                try:
                    raw = json.loads(msg.value().decode('utf-8'))
                    event = parse_event(raw)
                    self.buffer.append(event)
                except (json.JSONDecodeError, Exception) as e:
                    print(f"Parse error: {e}")
                    continue

                # Check flush
                if self._should_flush():
                    self._flush()

        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            # Final flush
            self._flush()
            consumer.close()
            print(f"\nTotal: {self.total_events} events in {self.total_files} files")

    def stop(self):
        """Signal to stop the collector."""
        self.running = False


def main():
    # Validate required env vars
    required = ['AUDIT_BOOTSTRAP', 'AUDIT_API_KEY', 'AUDIT_API_SECRET']
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        print("\nRequired:")
        print("  AUDIT_BOOTSTRAP  - Confluent audit cluster bootstrap servers")
        print("  AUDIT_API_KEY    - API key for audit cluster")
        print("  AUDIT_API_SECRET - API secret")
        print("\nOptional:")
        print("  S3_BUCKET        - S3 bucket for storage")
        print("  GCS_BUCKET       - GCS bucket for storage")
        print("  BATCH_SIZE       - Events per file (default: 10000)")
        print("  FLUSH_INTERVAL   - Seconds between writes (default: 300)")
        sys.exit(1)

    collector = AuditLogCollector()

    # Handle signals
    def signal_handler(sig, frame):
        collector.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    collector.run()


if __name__ == '__main__':
    main()
