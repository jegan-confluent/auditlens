import os
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import check_db_health_session


def get_storage_usage(db: Session) -> dict[str, Any]:
    settings = get_settings()
    if settings.database_mode == "sqlite":
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        if db_path == ":memory:":
            return {"mode": "sqlite", "path": ":memory:", "bytes": 0}
        size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        wal_path = f"{db_path}-wal"
        wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        return {"mode": "sqlite", "path": db_path, "bytes": size + wal_size, "db_bytes": size, "wal_bytes": wal_size}
    size = db.scalar(text("select pg_database_size(current_database())"))
    return {"mode": "postgres", "bytes": int(size or 0)}


def get_forwarder_status() -> dict[str, Any]:
    settings = get_settings()
    try:
        response = httpx.get(settings.forwarder_health_url, timeout=2.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {
            "consumer_state": "unknown",
            "last_successful_poll": None,
            "retry_count": 0,
            "consecutive_error_count": 0,
            "last_error": str(exc),
            "consumer_lag": None,
            "records_consumed_total": 0,
            "db_writer_enabled": False,
            "db_writer_state": "unknown",
            "db_write_success_total": 0,
            "db_write_error_total": 0,
            "db_write_batch_size": 0,
            "db_last_successful_write": None,
            "db_last_error": str(exc),
            "db_last_cleanup_at": None,
            "db_last_cleanup_deleted_count": 0,
        }
    runtime = payload.get("observability", {}).get("consumer_runtime", {})
    db_writer = payload.get("observability", {}).get("db_writer", {})
    return {
        "consumer_state": runtime.get("consumer_state") or payload.get("components", [{}])[0].get("status", "unknown"),
        "last_successful_poll": runtime.get("last_successful_poll"),
        "retry_count": int(runtime.get("retry_count") or 0),
        "consecutive_error_count": int(runtime.get("consecutive_error_count") or 0),
        "last_error": runtime.get("last_error"),
        "consumer_lag": payload.get("consumer_lag"),
        "records_consumed_total": int(runtime.get("records_consumed_total") or 0),
        "db_writer_enabled": bool(db_writer.get("enabled", False)),
        "db_writer_state": db_writer.get("db_writer_state", "unknown"),
        "db_write_success_total": int(db_writer.get("db_write_success_total") or 0),
        "db_write_error_total": int(db_writer.get("db_write_error_total") or 0),
        "db_write_batch_size": int(db_writer.get("db_write_batch_size") or 0),
        "db_last_successful_write": db_writer.get("db_last_successful_write"),
        "db_last_error": db_writer.get("db_last_error"),
        "db_last_cleanup_at": db_writer.get("db_last_cleanup_at"),
        "db_last_cleanup_deleted_count": int(db_writer.get("db_last_cleanup_deleted_count") or 0),
    }


def get_system_status(db: Session) -> dict[str, Any]:
    status = get_forwarder_status()
    status["database_mode"] = get_settings().database_mode
    try:
        status["storage_usage"] = get_storage_usage(db)
    except Exception as exc:
        status["storage_usage"] = {"mode": status["database_mode"], "error": str(exc)}
    try:
        status["db_health"] = check_db_health_session(db)
    except Exception as exc:
        status["db_health"] = {"can_connect": False, "can_query": False, "error": str(exc)}
    return status
