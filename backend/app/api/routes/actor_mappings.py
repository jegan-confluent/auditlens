"""CRUD API for actor_mappings.yml entries.

The YAML file is the single source of truth. Extended fields managed outside
this API (trusted_ips, alert_on_new_ip, k8s_*) are preserved on update.
"""
from __future__ import annotations

import os
import threading
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api.routes.patterns import _require_admin, _require_viewer

router = APIRouter(tags=["actor_mappings"])

_write_lock = threading.Lock()


def _yaml_path() -> str:
    return os.getenv("ACTOR_MAPPINGS_FILE", "actor_mappings.yml")


def _load_yaml() -> dict[str, Any]:
    path = _yaml_path()
    if not os.path.isfile(path):
        return {"mappings": {}}
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw.get("mappings"), dict):
        raw["mappings"] = {}
    return raw


def _save_yaml(doc: dict[str, Any]) -> None:
    with open(_yaml_path(), "w", encoding="utf-8") as fh:
        yaml.dump(doc, fh, default_flow_style=False, allow_unicode=True)


def _entry_to_out(raw_id: str, value: Any) -> "ActorMappingOut":
    if isinstance(value, str):
        return ActorMappingOut(raw_id=raw_id, display_name=value, team=None, notes=None)
    if isinstance(value, dict):
        return ActorMappingOut(
            raw_id=raw_id,
            display_name=value.get("display_name") or "",
            team=value.get("team") or None,
            notes=value.get("notes") or None,
        )
    return ActorMappingOut(raw_id=raw_id, display_name=str(value), team=None, notes=None)


class ActorMappingIn(BaseModel):
    raw_id: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    team: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=500)


class ActorMappingOut(BaseModel):
    raw_id: str
    display_name: str
    team: str | None
    notes: str | None


@router.get("/actor-mappings", response_model=list[ActorMappingOut])
def list_actor_mappings(_auth: None = Depends(_require_viewer)) -> list[ActorMappingOut]:
    doc = _load_yaml()
    return [_entry_to_out(k, v) for k, v in doc.get("mappings", {}).items()]


@router.post("/actor-mappings", response_model=ActorMappingOut, status_code=201)
def create_actor_mapping(
    payload: ActorMappingIn,
    _auth: None = Depends(_require_admin),
) -> ActorMappingOut:
    with _write_lock:
        doc = _load_yaml()
        mappings = doc.setdefault("mappings", {})
        if payload.raw_id in mappings:
            raise HTTPException(
                status_code=409,
                detail=f"Mapping for '{payload.raw_id}' already exists.",
            )
        if payload.team or payload.notes:
            entry: Any = {"display_name": payload.display_name}
            if payload.team:
                entry["team"] = payload.team
            if payload.notes:
                entry["notes"] = payload.notes
        else:
            entry = payload.display_name
        mappings[payload.raw_id] = entry
        _save_yaml(doc)
    return ActorMappingOut(
        raw_id=payload.raw_id,
        display_name=payload.display_name,
        team=payload.team,
        notes=payload.notes,
    )


@router.put("/actor-mappings/{raw_id}", response_model=ActorMappingOut)
def update_actor_mapping(
    raw_id: str,
    payload: ActorMappingIn,
    _auth: None = Depends(_require_admin),
) -> ActorMappingOut:
    with _write_lock:
        doc = _load_yaml()
        mappings = doc.setdefault("mappings", {})
        if raw_id not in mappings:
            raise HTTPException(status_code=404, detail=f"Mapping for '{raw_id}' not found.")
        existing = mappings[raw_id]
        # Preserve advanced fields we don't manage via this API
        preserved = (
            {k: v for k, v in existing.items() if k not in ("display_name", "team", "notes")}
            if isinstance(existing, dict)
            else {}
        )
        if preserved or payload.team or payload.notes:
            entry: Any = {"display_name": payload.display_name, **preserved}
            if payload.team:
                entry["team"] = payload.team
            if payload.notes:
                entry["notes"] = payload.notes
        else:
            entry = payload.display_name
        mappings[raw_id] = entry
        _save_yaml(doc)
    return ActorMappingOut(
        raw_id=raw_id,
        display_name=payload.display_name,
        team=payload.team,
        notes=payload.notes,
    )


@router.delete("/actor-mappings/{raw_id}")
def delete_actor_mapping(
    raw_id: str,
    _auth: None = Depends(_require_admin),
) -> dict[str, Any]:
    with _write_lock:
        doc = _load_yaml()
        mappings = doc.setdefault("mappings", {})
        if raw_id not in mappings:
            raise HTTPException(status_code=404, detail=f"Mapping for '{raw_id}' not found.")
        del mappings[raw_id]
        _save_yaml(doc)
    return {"deleted": True, "raw_id": raw_id}
