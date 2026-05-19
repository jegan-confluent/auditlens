"""Notifications config UI routes.

Read-only view + enable/disable toggle for notifications.yml destinations.
Webhook URLs and integration keys are NEVER returned in the response —
secrets stay on disk. PATCH performs an atomic temp-write + flock and
relies on the forwarder's mtime-based reload to pick up the change.

Architecture (intentional): the API process parses notifications.yml
directly. Per-destination runtime state (last_sent / last_status) lives
in the forwarder's in-process notifier — we intentionally do not surface
it here. Adding that would require a new forwarder endpoint + proxy.
"""
from __future__ import annotations

import fcntl
import logging
import os
import tempfile
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.routes.admin import require_admin

logger = logging.getLogger("auditlens.backend.notifications")

router = APIRouter(tags=["notifications"])


def _config_path() -> str:
    """Resolve the notifications.yml path. Override via env for tests/ops."""
    return os.getenv("NOTIFICATIONS_CONFIG_PATH", "notifications.yml")


def _safe_destination_view(entry: dict[str, Any]) -> dict[str, Any]:
    """Project a raw yml entry into the public view — no URLs, no keys."""
    filters = entry.get("filters") if isinstance(entry.get("filters"), dict) else {}
    return {
        "name": str(entry.get("name") or "unnamed"),
        "type": str(entry.get("type") or "").lower(),
        "enabled": bool(entry.get("enabled", True)),
        "mode": str(entry.get("mode") or "realtime"),
        "digest_schedule": str(entry.get("digest_schedule") or "09:00"),
        "rate_limit_per_minute": entry.get("rate_limit_per_minute", 10),
        "filters": {
            "signal_type": list(filters.get("signal_type") or []),
            "min_risk_level": filters.get("min_risk_level"),
            "action_category": list(filters.get("action_category") or []),
            "exclude_actions": list(filters.get("exclude_actions") or []),
        },
    }


def _load_yaml_or_none(path: str) -> dict[str, Any] | None:
    """Return parsed yml as dict, or None if missing/unparseable."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None
    return raw if isinstance(raw, dict) else None


@router.get("/notifications/destinations")
def list_destinations(_: None = Depends(require_admin)) -> dict[str, Any]:
    """List configured notification destinations.

    Returns an empty list with status='no_config' when notifications.yml is
    absent — the typical state before an operator configures the file.
    """
    path = _config_path()
    raw = _load_yaml_or_none(path)
    if raw is None:
        return {
            "status": "no_config" if not os.path.isfile(path) else "parse_error",
            "config_path": path,
            "destinations": [],
        }
    entries = raw.get("destinations")
    if not isinstance(entries, list):
        return {"status": "no_destinations", "config_path": path, "destinations": []}
    destinations = [_safe_destination_view(e) for e in entries if isinstance(e, dict)]
    return {"status": "ok", "config_path": path, "destinations": destinations}


@router.patch("/notifications/destinations/{name}/toggle")
def toggle_destination(name: str, _: None = Depends(require_admin)) -> dict[str, Any]:
    """Flip the enabled flag for a destination. Writes atomically.

    503 if notifications.yml is missing or unwritable. 404 if no destination
    with that name exists. Round-tripping through yaml.safe_dump intentionally
    loses comments and reorders keys — operator was warned in the example yml.
    """
    path = _config_path()
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=503,
            detail=(
                f"notifications.yml not found at {path}. Create it from "
                "notifications.example.yml and mount it into the api container."
            ),
        )
    # Serialise against concurrent writers via flock on the file itself.
    # Opening for r+ (read+write, no truncate) keeps the file present for
    # the duration of the lock; we never actually mutate via this handle.
    try:
        with open(path, "r+", encoding="utf-8") as fh:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise HTTPException(status_code=503, detail=f"Could not lock {path}: {exc}")
            try:
                fh.seek(0)
                raw = yaml.safe_load(fh)
            except yaml.YAMLError as exc:
                raise HTTPException(status_code=503, detail=f"Cannot parse {path}: {exc}")
            if not isinstance(raw, dict):
                raise HTTPException(status_code=503, detail=f"{path}: top-level must be a mapping")
            entries = raw.get("destinations")
            if not isinstance(entries, list):
                raise HTTPException(status_code=404, detail="No destinations array in config")
            target_idx = None
            for i, entry in enumerate(entries):
                if isinstance(entry, dict) and str(entry.get("name") or "") == name:
                    target_idx = i
                    break
            if target_idx is None:
                raise HTTPException(status_code=404, detail=f"No destination named '{name}'")
            new_enabled = not bool(entries[target_idx].get("enabled", True))
            entries[target_idx]["enabled"] = new_enabled
            # Atomic write: write to a sibling tmp then os.replace into place.
            directory = os.path.dirname(os.path.abspath(path)) or "."
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=".notifications.", suffix=".yml.tmp", dir=directory
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_fh:
                    yaml.safe_dump(raw, tmp_fh, sort_keys=False, default_flow_style=False)
                os.chmod(tmp_path, 0o644)
                os.replace(tmp_path, path)
            except OSError as exc:
                # Best-effort cleanup of the tmp file if rename failed.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise HTTPException(status_code=503, detail=f"Atomic write failed: {exc}")
            logger.info(
                "Toggled notification destination '%s' enabled=%s (config %s)",
                name,
                new_enabled,
                path,
            )
            return {
                "name": name,
                "enabled": new_enabled,
                "config_path": path,
            }
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Cannot open {path}: {exc}")
