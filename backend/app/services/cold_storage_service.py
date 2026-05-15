"""Cold storage archival — S3, GCS, or disabled.

Architecture:
- ColdStorageBackend Protocol: upload(key, data) → bool, exists(key) → bool, test_connection() → (bool, str)
- S3Backend, GCSBackend, DisabledBackend implementations
- get_backend(db) factory reads credentials from SettingsService
- archive_events_for_date(db, date, dry_run) → bytes archived (0 if disabled)
- wire_into_retention(db, cutoff_date, ...) → called from cleanup_retention Step 0
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

logger = logging.getLogger("auditlens.backend.cold_storage")

_ARCHIVE_STATE_LOCK = threading.Lock()
_archive_state: dict[str, Any] = {
    "enabled": False,
    "provider": None,
    "bucket": None,
    "last_archive_at": None,
    "last_archive_bytes": None,
    "total_archived_events": 0,
    "status": "disabled",
}


@runtime_checkable
class ColdStorageBackend(Protocol):
    def upload(self, key: str, data: bytes) -> bool: ...
    def exists(self, key: str) -> bool: ...
    def test_connection(self) -> tuple[bool, str]: ...


class DisabledBackend:
    def upload(self, key: str, data: bytes) -> bool:
        return False

    def exists(self, key: str) -> bool:
        return False

    def test_connection(self) -> tuple[bool, str]:
        return False, "cold storage is disabled"


class S3Backend:
    def __init__(self, bucket: str, prefix: str, region: str, access_key: str, secret_key: str) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key

    def _client(self):
        try:
            import boto3
            return boto3.client(
                "s3",
                region_name=self._region,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
            )
        except ImportError as exc:
            raise RuntimeError("boto3 required for S3 cold storage: pip install boto3") from exc

    def upload(self, key: str, data: bytes) -> bool:
        try:
            full_key = f"{self._prefix}/{key}" if self._prefix else key
            self._client().put_object(Bucket=self._bucket, Key=full_key, Body=data, ContentType="application/gzip")
            return True
        except Exception as exc:
            logger.error("S3 upload failed key=%s: %s", key, exc)
            return False

    def exists(self, key: str) -> bool:
        try:
            full_key = f"{self._prefix}/{key}" if self._prefix else key
            self._client().head_object(Bucket=self._bucket, Key=full_key)
            return True
        except Exception as exc:
            logger.debug("S3 exists check failed for key=%s: %s", key, exc)
            return False

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._client().head_bucket(Bucket=self._bucket)
            return True, f"S3 bucket {self._bucket} accessible"
        except Exception as exc:
            return False, str(exc)


class GCSBackend:
    def __init__(self, bucket: str, prefix: str, credentials_json: str) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._credentials_json = credentials_json

    def _client(self):
        try:
            import json as _json
            from google.cloud import storage
            from google.oauth2 import service_account
            creds_dict = _json.loads(self._credentials_json)
            creds = service_account.Credentials.from_service_account_info(creds_dict)
            return storage.Client(credentials=creds)
        except ImportError as exc:
            raise RuntimeError("google-cloud-storage required: pip install google-cloud-storage") from exc

    def upload(self, key: str, data: bytes) -> bool:
        try:
            client = self._client()
            bucket = client.bucket(self._bucket)
            full_key = f"{self._prefix}/{key}" if self._prefix else key
            blob = bucket.blob(full_key)
            blob.upload_from_string(data, content_type="application/gzip")
            return True
        except Exception as exc:
            logger.error("GCS upload failed key=%s: %s", key, exc)
            return False

    def exists(self, key: str) -> bool:
        try:
            client = self._client()
            bucket = client.bucket(self._bucket)
            full_key = f"{self._prefix}/{key}" if self._prefix else key
            return bucket.blob(full_key).exists()
        except Exception as exc:
            logger.debug("GCS exists check failed for key=%s: %s", key, exc)
            return False

    def test_connection(self) -> tuple[bool, str]:
        try:
            client = self._client()
            bucket = client.bucket(self._bucket)
            bucket.reload()
            return True, f"GCS bucket {self._bucket} accessible"
        except Exception as exc:
            return False, str(exc)


def get_backend(db: Session) -> ColdStorageBackend:
    """Factory: reads config from app_settings. Returns DisabledBackend if not configured."""
    try:
        from backend.app.services import settings_service
        enabled = settings_service.get(db, "cold_storage", "enabled")
        if enabled not in ("true", "1", "yes"):
            return DisabledBackend()
        provider = settings_service.get(db, "cold_storage", "provider") or ""
        bucket = settings_service.get(db, "cold_storage", "bucket") or ""
        prefix = settings_service.get(db, "cold_storage", "prefix") or "auditlens"
        if not bucket:
            return DisabledBackend()
        if provider.lower() == "s3":
            region = settings_service.get(db, "cold_storage", "aws_region") or "us-east-1"
            access_key = settings_service.get(db, "cold_storage", "aws_access_key") or ""
            secret_key = settings_service.get(db, "cold_storage", "aws_secret_key") or ""
            return S3Backend(bucket=bucket, prefix=prefix, region=region, access_key=access_key, secret_key=secret_key)
        if provider.lower() == "gcs":
            creds = settings_service.get(db, "cold_storage", "gcs_credentials") or ""
            return GCSBackend(bucket=bucket, prefix=prefix, credentials_json=creds)
        return DisabledBackend()
    except Exception as exc:
        logger.warning("cold_storage get_backend failed: %s", exc)
        return DisabledBackend()


def _serialize_events_for_date(db: Session, target_date: date) -> tuple[bytes, int]:
    """Serialize all audit_events for a given UTC date to NDJSON.gz (no raw_payload_json)."""
    from datetime import timedelta

    from sqlalchemy import text

    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    rows = db.execute(
        text(
            "SELECT id, event_fingerprint, timestamp, result, actor, action, normalized_action, "
            "action_category, resource_type, resource_name, source_ip, actor_display_name, "
            "signal_type, risk_level, impact_type FROM audit_events "
            "WHERE timestamp >= :start AND timestamp < :end ORDER BY timestamp"
        ),
        {"start": start, "end": end},
    ).fetchall()

    lines = []
    for row in rows:
        record = {
            "id": row[0],
            "event_fingerprint": row[1],
            "timestamp": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
            "result": row[3],
            "actor": row[4],
            "action": row[5],
            "normalized_action": row[6],
            "action_category": row[7],
            "resource_type": row[8],
            "resource_name": row[9],
            "source_ip": row[10],
            "actor_display_name": row[11],
            "signal_type": row[12],
            "risk_level": row[13],
            "impact_type": row[14],
        }
        lines.append(json.dumps(record, default=str))

    ndjson = "\n".join(lines).encode("utf-8")
    compressed = gzip.compress(ndjson)
    return compressed, len(rows)


def archive_events_before(db: Session, cutoff: datetime, prefix: str = "auditlens", dry_run: bool = False) -> dict[str, Any]:
    """Archive all days strictly before cutoff to cold storage.
    Returns summary of what was/would be archived.
    NEVER deletes from Postgres — deletion is the caller's responsibility."""
    backend = get_backend(db)
    if isinstance(backend, DisabledBackend):
        return {"enabled": False, "days_archived": 0, "bytes_archived": 0, "error": None}

    from sqlalchemy import text

    # Find distinct dates to archive
    result = db.execute(
        text("SELECT DISTINCT DATE(timestamp) as d FROM audit_events WHERE timestamp < :cutoff ORDER BY d"),
        {"cutoff": cutoff},
    ).fetchall()
    days = [row[0] for row in result]

    total_bytes = 0
    total_events = 0
    days_archived = 0
    errors = []

    for day in days:
        if isinstance(day, str):
            target_date = date.fromisoformat(day)
        else:
            target_date = day

        key = f"year={target_date.year:04d}/month={target_date.month:02d}/day={target_date.day:02d}/events_{days_archived:06d}.ndjson.gz"
        full_key = f"{prefix.rstrip('/')}/{key}" if prefix else key

        if not dry_run:
            data, count = _serialize_events_for_date(db, target_date)
            if not backend.upload(full_key, data):
                errors.append(f"upload failed for {target_date}")
                continue
            total_bytes += len(data)
            total_events += count
        days_archived += 1

    with _ARCHIVE_STATE_LOCK:
        if not dry_run and days_archived > 0:
            _archive_state.update({
                "enabled": True,
                "last_archive_at": datetime.now(timezone.utc).isoformat(),
                "last_archive_bytes": total_bytes,
                "total_archived_events": _archive_state["total_archived_events"] + total_events,
                "status": "healthy" if not errors else "error",
            })

    return {
        "enabled": True,
        "days_archived": days_archived,
        "bytes_archived": total_bytes,
        "events_archived": total_events,
        "errors": errors,
        "dry_run": dry_run,
    }


def get_cold_storage_status(db: Session) -> dict[str, Any]:
    """Returns the cold_storage block for /system/status."""
    try:
        from backend.app.services import settings_service
        enabled = settings_service.get(db, "cold_storage", "enabled")
        provider = settings_service.get(db, "cold_storage", "provider")
        bucket = settings_service.get(db, "cold_storage", "bucket")
    except Exception as exc:
        logger.warning("Failed to read cold storage settings: %s", exc)
        enabled = None
        provider = None
        bucket = None

    with _ARCHIVE_STATE_LOCK:
        state = dict(_archive_state)

    is_enabled = enabled in ("true", "1", "yes")
    return {
        "enabled": is_enabled,
        "provider": provider if is_enabled else None,
        "bucket": bucket if is_enabled else None,
        "last_archive_at": state["last_archive_at"],
        "last_archive_bytes": state["last_archive_bytes"],
        "total_archived_events": state["total_archived_events"],
        "status": "disabled" if not is_enabled else state["status"],
    }
