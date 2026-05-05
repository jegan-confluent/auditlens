import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

VALID_TRIAGE_STATUSES = {"open", "acknowledged", "approved", "investigating", "resolved", "false_positive"}
DEFAULT_TRIAGE = {
    "triage_status": "open",
    "triage_actor": None,
    "triage_timestamp": None,
    "triage_note": None,
}

_LOCK = Lock()
_CACHE: dict[str, dict[str, Any]] | None = None
_CACHE_PATH: Path | None = None


def _store_path() -> Path:
    return Path(os.getenv("TRIAGE_STATE_FILE", "data/triage_state.json"))


def triage_storage_note() -> str:
    return "File-backed triage is local and single-instance only."


def _read_store() -> dict[str, dict[str, Any]]:
    global _CACHE, _CACHE_PATH
    path = _store_path()
    if _CACHE is not None and _CACHE_PATH == path:
        return _CACHE
    if not path.exists():
        _CACHE = {}
        _CACHE_PATH = path
        return _CACHE
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        parsed = {}
    _CACHE = parsed if isinstance(parsed, dict) else {}
    _CACHE_PATH = path
    return _CACHE


def _write_store(data: dict[str, dict[str, Any]]) -> None:
    global _CACHE, _CACHE_PATH
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)
    _CACHE = data
    _CACHE_PATH = path


def get_triage(event_id: int | str) -> dict[str, Any]:
    with _LOCK:
        data = _read_store().get(str(event_id), {})
    return {**DEFAULT_TRIAGE, **data}


def set_triage(event_id: int | str, status: str, *, actor: str | None = None, note: str | None = None) -> dict[str, Any]:
    if status not in VALID_TRIAGE_STATUSES:
        raise ValueError(f"triage_status must be one of: {', '.join(sorted(VALID_TRIAGE_STATUSES))}")
    entry = {
        "triage_status": status,
        "triage_actor": actor or "api",
        "triage_timestamp": datetime.now(timezone.utc).isoformat(),
        "triage_note": note,
    }
    with _LOCK:
        data = _read_store()
        data[str(event_id)] = entry
        _write_store(data)
    return {**DEFAULT_TRIAGE, **entry}
