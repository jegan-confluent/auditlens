"""Self-audit log for privileged AuditLens actions.

Why this exists: AuditLens audits Confluent Cloud activity, but until now
it had no record of its OWN admin/responder actions. SOC2 + customer
compliance asks need "who triggered the retention sweep, who suppressed
the pattern, who downloaded the PII export."

This module exposes:
- ``log_admin_action(...)``: synchronous, fail-soft write of one row.
  Callers (auth-gate deps + explicit routes) call this after the token
  has been validated. Failures here MUST NOT block the route — the
  audit log is best-effort observability, not a transaction prerequisite.
- ``list_admin_actions(...)``: paginated newest-first read used by
  ``GET /admin/audit-log``.

A fresh ``SessionLocal()`` is used per write so the write commits in
its own short-lived transaction and never participates in the route's
SQLAlchemy session (which would risk rollback-cascade if the route
itself errors after the audit-log call returned).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.database import SessionLocal
from backend.app.db.models import AdminAuditLog

logger = logging.getLogger("auditlens.backend.admin_audit")


def log_admin_action(
    *,
    actor: str,
    role: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    """Insert one row into admin_audit_log. Fail-soft — exceptions are
    swallowed and logged at WARNING so a transient DB blip never breaks
    the underlying admin/responder action."""
    try:
        db: Session = SessionLocal()
        try:
            row = AdminAuditLog(
                timestamp=datetime.now(timezone.utc),
                actor=actor,
                role=role,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail,
                request_id=request_id,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — fail-soft is the contract
        logger.warning(
            "admin audit log write failed (non-fatal): action=%s actor=%s err=%s",
            action, actor, exc,
        )


def list_admin_actions(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    actor: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` rows from admin_audit_log, newest first.
    ``actor`` and ``action`` apply as exact-match filters when provided."""
    stmt = select(AdminAuditLog).order_by(AdminAuditLog.timestamp.desc())
    if actor:
        stmt = stmt.where(AdminAuditLog.actor == actor)
    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
    stmt = stmt.offset(offset).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "actor": r.actor,
            "role": r.role,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "detail": r.detail,
            "request_id": r.request_id,
        }
        for r in rows
    ]
