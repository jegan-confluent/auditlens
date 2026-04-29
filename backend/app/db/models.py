from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("event_fingerprint", name="uq_audit_events_event_fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    result: Mapped[str] = mapped_column(String(32), default="Success", nullable=False)
    actor: Mapped[str] = mapped_column(String(255), default="Unknown actor", nullable=False)
    action: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    normalized_action: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    action_category: Mapped[str] = mapped_column(String(64), default="Other", nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), default="Unknown", nullable=False)
    resource_name: Mapped[str] = mapped_column(String(512), default="-", nullable=False)
    resource_display: Mapped[str] = mapped_column(String(768), default="Unknown", nullable=False)
    cluster_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    is_failure: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_denied: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_routine_noise: Mapped[bool] = mapped_column(default=False, nullable=False)


Index("idx_audit_events_timestamp", AuditEvent.timestamp)
Index("idx_audit_events_event_fingerprint", AuditEvent.event_fingerprint)
Index("idx_audit_events_actor", AuditEvent.actor)
Index("idx_audit_events_resource_type", AuditEvent.resource_type)
Index("idx_audit_events_resource_name", AuditEvent.resource_name)
Index("idx_audit_events_action_category", AuditEvent.action_category)
Index("idx_audit_events_result", AuditEvent.result)
Index("idx_audit_events_timestamp_desc", AuditEvent.timestamp.desc())
Index("idx_audit_events_resource_lookup", AuditEvent.resource_type, AuditEvent.resource_name, AuditEvent.timestamp.desc())
Index("idx_audit_events_resource_type_action_category_time", AuditEvent.resource_type, AuditEvent.action_category, AuditEvent.timestamp.desc())
Index("idx_audit_events_resource_name_time", AuditEvent.resource_name, AuditEvent.timestamp.desc())
Index("idx_audit_events_action_category_time", AuditEvent.action_category, AuditEvent.timestamp.desc())
Index("idx_audit_events_actor_time", AuditEvent.actor, AuditEvent.timestamp.desc())
Index("idx_audit_events_result_time", AuditEvent.result, AuditEvent.timestamp.desc())
