"""Pattern management endpoints — list, suppress, and reactivate recurring patterns."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.limiter import limiter
from backend.app.db.database import get_db
from backend.app.services.admin_audit_service import log_admin_action
from backend.app.services.pattern_service import (
    list_patterns,
    mark_expected,
    reactivate_pattern,
    suppress_pattern,
)
from src.product.auth import AccessToken, AuthConfig, Authenticator, Role

router = APIRouter(tags=["patterns"])


# Matches UUID-ish (8-4-4-4-12 hex) or any long hex/digit segment. Used by
# _derive_action_and_target to recognise path segments that are IDs rather
# than action names, so /patterns/123/suppress logs as action=patterns.suppress
# with target_id=123 rather than burying the id inside the action string.
_UUID_OR_NUMERIC = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$|^[0-9]+$")


def _derive_action_and_target(path: str) -> tuple[str, str | None, str | None]:
    """Map a request URL path to (action, target_type, target_id).

    Path segments that are pure digits or UUID-shaped are treated as
    resource identifiers; everything else is concatenated with dots to
    form a stable action name. The segment immediately before an id
    becomes target_type. Examples:

      /patterns/123/suppress           → ("patterns.suppress", "patterns", "123")
      /admin/retention/cleanup         → ("admin.retention.cleanup", None, None)
      /events/export                   → ("events.export", None, None)
      /events/42/triage                → ("events.triage", "events", "42")
    """
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return ("unknown", None, None)
    target_type: str | None = None
    target_id: str | None = None
    cleaned: list[str] = []
    for i, p in enumerate(parts):
        if _UUID_OR_NUMERIC.match(p):
            target_id = p
            if i > 0:
                target_type = parts[i - 1]
            continue
        cleaned.append(p)
    return (".".join(cleaned) if cleaned else "unknown", target_type, target_id)


def _log_via_dep(request: Request, actor: AccessToken) -> None:
    """Auto-log this privileged request to admin_audit_log. Called by the
    role-gating deps below on non-GET methods. The dep has already
    validated the token, so we always have a real ``actor``.

    Fail-soft: log_admin_action swallows any DB error so a flaky audit
    write never blocks the route.
    """
    if request.method == "GET":
        return
    action, target_type, target_id = _derive_action_and_target(request.url.path)
    log_admin_action(
        actor=actor.actor_id,
        role=actor.role.value,
        action=action,
        target_type=target_type,
        target_id=target_id,
        request_id=request.headers.get("X-Request-ID"),
    )


def _authenticate(request: Request) -> "AuthResult":  # type: ignore[name-defined]
    try:
        config = AuthConfig.from_env()
        return Authenticator(config).authenticate(request.headers)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Auth configuration error") from exc


def _require_viewer(request: Request) -> None:
    try:
        config = AuthConfig.from_env()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Auth configuration error") from exc
    if not config.enabled:
        return
    result = _authenticate(request)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.error)
    if result.actor and result.actor.role in {Role.VIEWER, Role.RESPONDER, Role.ADMIN}:
        return
    raise HTTPException(status_code=403, detail="viewer role required")


def _require_responder(request: Request) -> None:
    try:
        config = AuthConfig.from_env()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Auth configuration error") from exc
    if not config.enabled:
        return
    result = _authenticate(request)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.error)
    if result.actor and result.actor.role in {Role.RESPONDER, Role.ADMIN}:
        _log_via_dep(request, result.actor)
        return
    raise HTTPException(status_code=403, detail="responder role required")


def _require_admin(request: Request) -> None:
    try:
        config = AuthConfig.from_env()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Auth configuration error") from exc
    if not config.enabled:
        return
    result = _authenticate(request)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.error)
    if result.actor and result.actor.role == Role.ADMIN:
        _log_via_dep(request, result.actor)
        return
    raise HTTPException(status_code=403, detail="admin role required")


def _require_exporter(request: Request) -> None:
    """Gate routes that emit PII-bearing data (CSV/JSON export of audit
    events). Mirrors the viewer/responder/admin pattern but checks the
    EXPORTER role specifically — admins still pass because they bypass
    everything by definition. Previously /events/export was gated only
    by _require_viewer, which let any read-only token exfiltrate up to
    10 000 rows of source-IP + actor + resource_name data.

    Every successful call is recorded in admin_audit_log via _log_via_dep
    so the export side of the threat model has a clear audit trail.
    Method check inside _log_via_dep means GET /events/export DOES log —
    it's a PII-bearing read so the GET-exemption doesn't apply."""
    try:
        config = AuthConfig.from_env()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Auth configuration error") from exc
    if not config.enabled:
        return
    result = _authenticate(request)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.error)
    if result.actor and result.actor.can_export():
        # Force-log even on GET because exports always carry PII.
        action, target_type, target_id = _derive_action_and_target(request.url.path)
        log_admin_action(
            actor=result.actor.actor_id,
            role=result.actor.role.value,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request.headers.get("X-Request-ID"),
        )
        return
    raise HTTPException(status_code=403, detail="exporter role required")


def _actor_id(request: Request) -> str:
    try:
        config = AuthConfig.from_env()
        result = Authenticator(config).authenticate(request.headers)
        if result.ok and result.actor:
            return result.actor.actor_id
    except Exception:
        pass
    return "api"


class SuppressRequest(BaseModel):
    duration_hours: int = 24
    reason: str = ""


class MarkExpectedRequest(BaseModel):
    reason: str = ""


@router.get("/patterns")
@limiter.limit("60/minute")
def get_patterns(
    request: Request,
    status: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    _require_viewer(request)
    try:
        return list_patterns(db, status=status, actor=actor, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/patterns/{pattern_id}/suppress")
@limiter.limit("60/minute")
def suppress(
    pattern_id: int,
    payload: SuppressRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    _require_responder(request)
    actor = _actor_id(request)
    pattern = suppress_pattern(
        db, pattern_id,
        duration_hours=payload.duration_hours,
        reason=payload.reason,
        suppressed_by=actor,
    )
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"status": "suppressed", "id": pattern.id}


@router.post("/patterns/{pattern_id}/mark-expected")
@limiter.limit("60/minute")
def mark_expected_endpoint(
    pattern_id: int,
    payload: MarkExpectedRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    _require_responder(request)
    actor = _actor_id(request)
    pattern = mark_expected(
        db, pattern_id, reason=payload.reason, marked_by=actor
    )
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"status": "expected", "id": pattern.id}


@router.post("/patterns/{pattern_id}/reactivate")
@limiter.limit("60/minute")
def reactivate(
    pattern_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    _require_admin(request)
    pattern = reactivate_pattern(db, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return {"status": "active", "id": pattern.id}
