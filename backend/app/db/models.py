import json
import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, object_session

from src.product.actor_enrichment import enrich_actor
from src.product.event_intelligence import decision_snapshot_from_model
from src.product.resource_intelligence import extract_resource_context
from src.product.source_enrichment import extract_source_info
from src.product.event_signals import classify_signal
from src.product.triage_store import get_triage

logger = logging.getLogger("auditlens.backend.models")


_PRINCIPAL_PREFIXES = ("user:", "u-", "sa-", "api-key-", "apikey", "pool-", "org-", "lkc-", "env-")


def _is_enriched_display_name(value: str | None) -> bool:
    """Return True only when value looks like a real name or email, not a raw ID or JSON blob."""
    if not value:
        return False
    if value.startswith(("{", "[")):
        return False
    lowered = value.strip().lower()
    if "@" in lowered:
        return True
    return not lowered.startswith(_PRINCIPAL_PREFIXES)


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
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    _actor_display_name: Mapped[str | None] = mapped_column("actor_display_name", String(255), nullable=True)
    _actor_email: Mapped[str | None] = mapped_column("actor_email", String(255), nullable=True)
    _actor_type: Mapped[str | None] = mapped_column("actor_type", String(64), nullable=True)
    _actor_source: Mapped[str | None] = mapped_column("actor_source", String(64), nullable=True)
    _actor_confidence: Mapped[str | None] = mapped_column("actor_confidence", String(32), nullable=True)
    actor_enriched_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    normalized_action: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    action_category: Mapped[str] = mapped_column(String(64), default="Other", nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), default="Unknown", nullable=False)
    resource_name: Mapped[str] = mapped_column(String(512), default="-", nullable=False)
    resource_display: Mapped[str] = mapped_column(String(768), default="Unknown", nullable=False)
    cluster_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    _cluster_name: Mapped[str | None] = mapped_column("cluster_name", String(255), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)
    _source_context: Mapped[str | None] = mapped_column("source_context", String(255), nullable=True)
    _client_id: Mapped[str | None] = mapped_column("client_id", String(255), nullable=True)
    _connection_id: Mapped[str | None] = mapped_column("connection_id", String(255), nullable=True)
    _request_id: Mapped[str | None] = mapped_column("request_id", String(255), nullable=True)
    environment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    _environment_name: Mapped[str | None] = mapped_column("environment_name", String(255), nullable=True)
    _parent_resource: Mapped[str | None] = mapped_column("parent_resource", String(255), nullable=True)
    _resource_scope: Mapped[str | None] = mapped_column("resource_scope", String(512), nullable=True)
    _resource_display_name: Mapped[str | None] = mapped_column("resource_display_name", String(768), nullable=True)
    _resource_criticality: Mapped[str | None] = mapped_column("resource_criticality", String(32), nullable=True)
    _blast_radius_hint: Mapped[str | None] = mapped_column("blast_radius_hint", String(64), nullable=True)
    _production_hint: Mapped[str | None] = mapped_column("production_hint", String(64), nullable=True)
    flink_region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    network_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    _signal_type: Mapped[str | None] = mapped_column("signal_type", String(32), nullable=True)
    _signal_reason: Mapped[str | None] = mapped_column("signal_reason", String(128), nullable=True)
    _impact_type: Mapped[str | None] = mapped_column("impact_type", String(64), nullable=True)
    _risk_level: Mapped[str | None] = mapped_column("risk_level", String(32), nullable=True)
    _change_type: Mapped[str | None] = mapped_column("change_type", String(32), nullable=True)
    _resource_family: Mapped[str | None] = mapped_column("resource_family", String(64), nullable=True)
    _event_title: Mapped[str | None] = mapped_column("event_title", String(255), nullable=True)
    _event_summary: Mapped[str | None] = mapped_column("event_summary", String(768), nullable=True)
    _decision_reason: Mapped[str | None] = mapped_column("decision_reason", String(255), nullable=True)
    _decision_label: Mapped[str | None] = mapped_column("decision_label", String(32), nullable=True)
    _recommended_action: Mapped[str | None] = mapped_column("recommended_action", String(255), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    is_failure: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_denied: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_routine_noise: Mapped[bool] = mapped_column(default=False, nullable=False)

    def _intelligence(self) -> dict[str, str]:
        cached = getattr(self, "_event_intelligence_cache", None)
        if cached is None:
            stored = {
                "impact_type": self._impact_type,
                "risk_level": self._risk_level,
                "change_type": self._change_type,
                "resource_family": self._resource_family,
                "event_title": self._event_title,
                "event_summary": self._event_summary,
                "decision_reason": self._decision_reason,
            }
            computed = decision_snapshot_from_model(self)
            cached = {**computed, **{key: value for key, value in stored.items() if value not in (None, "")}}
            setattr(self, "_event_intelligence_cache", cached)
        return cached

    @property
    def impact_type(self) -> str:
        return self._intelligence()["impact_type"]

    @impact_type.setter
    def impact_type(self, value: str | None) -> None:
        self._impact_type = value

    @property
    def risk_level(self) -> str:
        return self._intelligence()["risk_level"]

    @risk_level.setter
    def risk_level(self, value: str | None) -> None:
        self._risk_level = value

    @property
    def change_type(self) -> str:
        return self._intelligence()["change_type"]

    @change_type.setter
    def change_type(self, value: str | None) -> None:
        self._change_type = value

    @property
    def resource_family(self) -> str:
        return self._intelligence()["resource_family"]

    @resource_family.setter
    def resource_family(self, value: str | None) -> None:
        self._resource_family = value

    @property
    def event_title(self) -> str:
        return self._intelligence()["event_title"]

    @event_title.setter
    def event_title(self, value: str | None) -> None:
        self._event_title = value

    @property
    def event_summary(self) -> str:
        return self._intelligence()["event_summary"]

    @event_summary.setter
    def event_summary(self, value: str | None) -> None:
        self._event_summary = value

    @property
    def subject(self) -> str:
        return self._intelligence()["subject"]

    @property
    def subject_type(self) -> str:
        return self._intelligence()["subject_type"]

    @property
    def resource_display_short(self) -> str:
        return self._intelligence()["resource_display_short"]

    def _resource_enrichment(self) -> dict[str, str | None]:
        cached = getattr(self, "_resource_enrichment_cache", None)
        if cached is None:
            if "raw_payload_json" in self.__dict__:
                try:
                    payload = json.loads(self.raw_payload_json) if self.raw_payload_json else {}
                except json.JSONDecodeError:
                    # Corrupt or non-JSON payload. Fall back to empty enrichment
                    # but record the decode failure at debug level so data
                    # quality regressions are not silently absorbed.
                    logger.debug(
                        "resource enrichment: raw_payload_json failed to decode for event_fingerprint=%s",
                        getattr(self, "event_fingerprint", "<unknown>"),
                        exc_info=True,
                    )
                    payload = {}
                cached = extract_resource_context(payload, self).to_event_fields()
            else:
                cached = extract_resource_context({}, self).to_event_fields()
            setattr(self, "_resource_enrichment_cache", cached)
        stored = {
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "resource_display_name": self._resource_display_name,
            "cluster_id": self.cluster_id,
            "cluster_name": self._cluster_name,
            "environment_id": self.environment_id,
            "environment_name": self._environment_name,
            "parent_resource": self._parent_resource,
            "resource_scope": self._resource_scope,
            "resource_criticality": self._resource_criticality,
            "blast_radius_hint": self._blast_radius_hint,
            "production_hint": self._production_hint,
        }
        placeholders = {None, "", "-", "Unknown", "unknown", "Not provided by audit event"}
        return {**cached, **{key: value for key, value in stored.items() if value not in placeholders}}

    @property
    def source_context(self) -> str:
        return self._source_context or self._intelligence()["source_context"]

    @source_context.setter
    def source_context(self, value: str | None) -> None:
        self._source_context = value

    @property
    def decision_reason(self) -> str:
        return self._intelligence()["decision_reason"]

    @decision_reason.setter
    def decision_reason(self, value: str | None) -> None:
        self._decision_reason = value

    @property
    def resource_display_name(self) -> str:
        return str(self._resource_enrichment()["resource_display_name"] or self.resource_display or "Unknown")

    @resource_display_name.setter
    def resource_display_name(self, value: str | None) -> None:
        self._resource_display_name = value

    @property
    def parent_resource(self) -> str | None:
        return self._resource_enrichment()["parent_resource"]

    @parent_resource.setter
    def parent_resource(self, value: str | None) -> None:
        self._parent_resource = value

    @property
    def resource_scope(self) -> str:
        return str(self._resource_enrichment()["resource_scope"] or "unknown")

    @resource_scope.setter
    def resource_scope(self, value: str | None) -> None:
        self._resource_scope = value

    @property
    def cluster_name(self) -> str | None:
        return self._resource_enrichment()["cluster_name"]

    @cluster_name.setter
    def cluster_name(self, value: str | None) -> None:
        self._cluster_name = value

    @property
    def environment_name(self) -> str | None:
        return self._resource_enrichment()["environment_name"]

    @environment_name.setter
    def environment_name(self, value: str | None) -> None:
        self._environment_name = value

    @property
    def resource_criticality(self) -> str:
        return str(self._resource_enrichment()["resource_criticality"] or "unknown")

    @resource_criticality.setter
    def resource_criticality(self, value: str | None) -> None:
        self._resource_criticality = value

    @property
    def blast_radius_hint(self) -> str:
        return str(self._resource_enrichment()["blast_radius_hint"] or "unknown")

    @blast_radius_hint.setter
    def blast_radius_hint(self, value: str | None) -> None:
        self._blast_radius_hint = value

    @property
    def production_hint(self) -> str:
        return str(self._resource_enrichment()["production_hint"] or "unknown")

    @production_hint.setter
    def production_hint(self, value: str | None) -> None:
        self._production_hint = value

    def _source_enrichment(self) -> dict[str, str | None]:
        cached = getattr(self, "_source_enrichment_cache", None)
        if cached is None:
            try:
                payload = json.loads(self.raw_payload_json) if self.raw_payload_json else {}
            except json.JSONDecodeError:
                # Same handling as _resource_enrichment: a bad payload should
                # not break enrichment but it must not be silent — it indicates
                # an upstream data quality regression.
                logger.debug(
                    "source enrichment: raw_payload_json failed to decode for event_fingerprint=%s",
                    getattr(self, "event_fingerprint", "<unknown>"),
                    exc_info=True,
                )
                payload = {}
            cached = extract_source_info(payload, self)
            setattr(self, "_source_enrichment_cache", cached)
        return cached

    @property
    def source_display(self) -> str:
        return str(self._source_enrichment()["source_display"] or "Not provided by audit event")

    @property
    def source_reason(self) -> str:
        return str(self._source_enrichment()["source_reason"] or "missing")

    @property
    def client_id(self) -> str | None:
        return self._client_id or self._source_enrichment()["client_id"]

    @client_id.setter
    def client_id(self, value: str | None) -> None:
        self._client_id = value

    @property
    def connection_id(self) -> str | None:
        return self._connection_id or self._source_enrichment()["connection_id"]

    @connection_id.setter
    def connection_id(self, value: str | None) -> None:
        self._connection_id = value

    @property
    def request_id(self) -> str | None:
        return self._request_id or self._source_enrichment()["request_id"]

    @request_id.setter
    def request_id(self, value: str | None) -> None:
        self._request_id = value

    def _signal(self) -> dict[str, str]:
        cached = getattr(self, "_event_signal_cache", None)
        if cached is None:
            cached = {
                "signal_type": self._signal_type or self._intelligence()["signal_type"],
                "signal_reason": self._signal_reason or self._intelligence()["signal_reason"],
                "decision_label": self._decision_label or self._intelligence()["decision_label"],
                "recommended_action": self._recommended_action or self._intelligence()["recommended_action"],
            }
            if not all(cached.values()):
                computed = classify_signal(self)
                cached = {key: cached.get(key) or computed.get(key) for key in ("signal_type", "signal_reason", "decision_label", "recommended_action")}
            setattr(self, "_event_signal_cache", cached)
        return cached

    @property
    def signal_type(self) -> str:
        return self._signal()["signal_type"]

    @signal_type.setter
    def signal_type(self, value: str | None) -> None:
        self._signal_type = value

    @property
    def signal_reason(self) -> str:
        return self._signal()["signal_reason"]

    @signal_reason.setter
    def signal_reason(self, value: str | None) -> None:
        self._signal_reason = value

    @property
    def decision_label(self) -> str:
        return self._signal()["decision_label"]

    @decision_label.setter
    def decision_label(self, value: str | None) -> None:
        self._decision_label = value

    @property
    def recommended_action(self) -> str:
        return self._signal()["recommended_action"]

    @recommended_action.setter
    def recommended_action(self, value: str | None) -> None:
        self._recommended_action = value

    @property
    def suppressed(self) -> bool:
        return getattr(self, "_suppressed", False)

    def _actor_enrichment(self) -> dict[str, str | None]:
        cached = getattr(self, "_actor_enrichment_cache", None)
        if cached is None:
            cached = enrich_actor(self.actor, self.subject, self.subject_type)
            setattr(self, "_actor_enrichment_cache", cached)
        return cached

    @property
    def actor_display_name(self) -> str:
        stored = self._actor_display_name
        if _is_enriched_display_name(stored):
            return stored  # type: ignore[return-value]
        return str(
            self._actor_enrichment()["actor_display_name"]
            or self.actor
            or ""
        )

    @actor_display_name.setter
    def actor_display_name(self, value: str | None) -> None:
        self._actor_display_name = value

    @property
    def actor_email(self) -> str | None:
        return self._actor_email or self._actor_enrichment()["actor_email"]

    @actor_email.setter
    def actor_email(self, value: str | None) -> None:
        self._actor_email = value

    @property
    def actor_type(self) -> str:
        return str(self._actor_type or self._actor_enrichment()["actor_type"] or "unknown")

    @actor_type.setter
    def actor_type(self, value: str | None) -> None:
        self._actor_type = value

    @property
    def actor_raw_id(self) -> str | None:
        return self.actor_id or self._actor_enrichment()["actor_raw_id"]

    @actor_raw_id.setter
    def actor_raw_id(self, value: str | None) -> None:
        self.actor_id = value

    @property
    def actor_source(self) -> str:
        return str(self._actor_source or self._actor_enrichment()["actor_source"] or "fallback")

    @actor_source.setter
    def actor_source(self, value: str | None) -> None:
        self._actor_source = value

    @property
    def actor_confidence(self) -> str:
        return str(self._actor_confidence or self._actor_enrichment()["actor_confidence"] or "low")

    @actor_confidence.setter
    def actor_confidence(self, value: str | None) -> None:
        self._actor_confidence = value

    def _triage(self) -> dict[str, str | None]:
        cached = getattr(self, "_triage_cache", None)
        if cached is not None:
            return {**get_triage(self.event_fingerprint), **cached}
        session = object_session(self)
        if session is not None:
            record = session.scalar(select(AuditEventTriage).where(AuditEventTriage.event_fingerprint == self.event_fingerprint))
            if record is not None:
                timestamp = record.reviewed_at or record.resolved_at or record.updated_at or record.created_at
                return {
                    "triage_status": record.triage_status or "open",
                    "triage_actor": record.triage_actor,
                    "triage_timestamp": timestamp.isoformat() if timestamp is not None else None,
                    "triage_note": record.triage_note,
                }
        return get_triage(self.event_fingerprint)

    @property
    def triage_status(self) -> str:
        return str(self._triage()["triage_status"] or "open")

    @property
    def triage_actor(self) -> str | None:
        return self._triage()["triage_actor"]

    @property
    def triage_timestamp(self) -> str | None:
        return self._triage()["triage_timestamp"]

    @property
    def triage_note(self) -> str | None:
        return self._triage()["triage_note"]


class AuditEventTriage(Base):
    __tablename__ = "audit_event_triage"
    __table_args__ = (
        UniqueConstraint("event_fingerprint", name="uq_audit_event_triage_event_fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # FK to audit_events.event_fingerprint with ON DELETE CASCADE so retention
    # cleanup automatically removes triage rows when their parent event is
    # purged. On Postgres the FK is enforced by the database; on SQLite the FK
    # is honoured when foreign_keys PRAGMA is on, with an application-level
    # cleanup safety net inside event_service.cleanup_retention.
    event_fingerprint: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("audit_events.event_fingerprint", ondelete="CASCADE", name="fk_audit_event_triage_event_fingerprint"),
        nullable=False,
    )
    triage_status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    triage_actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    triage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    triage_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEventPattern(Base):
    __tablename__ = "audit_event_patterns"
    __table_args__ = (
        UniqueConstraint("pattern_key", name="uq_audit_event_patterns_pattern_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_key: Mapped[str] = mapped_column(String(512), nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    suppressed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    suppression_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ResourceCatalog(Base):
    __tablename__ = "resource_catalog"
    __table_args__ = (
        UniqueConstraint("resource_id", name="uq_resource_catalog_resource_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[str] = mapped_column(String(512), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(768), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cluster_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_resource: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_criticality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    blast_radius_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    production_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("idx_audit_event_triage_event_fingerprint", AuditEventTriage.event_fingerprint)
Index("idx_audit_event_triage_status", AuditEventTriage.triage_status)
Index("idx_resource_catalog_resource_type", ResourceCatalog.resource_type)
Index("idx_resource_catalog_resource_name", ResourceCatalog.resource_name)


class ActorIpBaseline(Base):
    __tablename__ = "actor_ip_baseline"
    __table_args__ = (
        UniqueConstraint("actor", "source_ip", name="uq_actor_ip"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    source_ip: Mapped[str] = mapped_column(String(128), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cloud_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_trusted: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


Index("ix_actor_ip_baseline_actor", ActorIpBaseline.actor)
Index("ix_actor_ip_baseline_is_trusted", ActorIpBaseline.is_trusted)
Index("idx_resource_catalog_cluster_id", ResourceCatalog.cluster_id)
Index("idx_resource_catalog_environment_id", ResourceCatalog.environment_id)
Index("idx_resource_catalog_last_seen_at", ResourceCatalog.last_seen_at)


Index("idx_audit_events_timestamp", AuditEvent.timestamp)
Index("idx_audit_events_event_fingerprint", AuditEvent.event_fingerprint)
Index("idx_audit_events_actor", AuditEvent.actor)
Index("idx_audit_events_actor_id", AuditEvent.actor_id)
Index("idx_audit_events_resource_type", AuditEvent.resource_type)
Index("idx_audit_events_resource_name", AuditEvent.resource_name)
Index("idx_audit_events_source_ip", AuditEvent.source_ip)
Index("idx_audit_events_environment_id", AuditEvent.environment_id)
Index("idx_audit_events_action_category", AuditEvent.action_category)
Index("idx_audit_events_result", AuditEvent.result)
Index("idx_audit_events_signal_type", AuditEvent._signal_type)
Index("idx_audit_events_impact_type", AuditEvent._impact_type)
Index("idx_audit_events_risk_level", AuditEvent._risk_level)
Index("idx_audit_events_change_type", AuditEvent._change_type)
Index("idx_audit_events_resource_family", AuditEvent._resource_family)
Index("idx_audit_events_timestamp_desc", AuditEvent.timestamp.desc())
Index("idx_audit_events_timestamp_signal_type", AuditEvent.timestamp.desc(), AuditEvent._signal_type)
Index("idx_audit_events_timestamp_impact_type", AuditEvent.timestamp.desc(), AuditEvent._impact_type)
Index("idx_audit_events_timestamp_risk_level", AuditEvent.timestamp.desc(), AuditEvent._risk_level)
Index("idx_audit_events_resource_lookup", AuditEvent.resource_type, AuditEvent.resource_name, AuditEvent.timestamp.desc())
Index("idx_audit_events_resource_type_action_category_time", AuditEvent.resource_type, AuditEvent.action_category, AuditEvent.timestamp.desc())
Index("idx_audit_events_resource_name_time", AuditEvent.resource_name, AuditEvent.timestamp.desc())
Index("idx_audit_events_action_category_time", AuditEvent.action_category, AuditEvent.timestamp.desc())
Index("idx_audit_events_actor_time", AuditEvent.actor, AuditEvent.timestamp.desc())
Index("idx_audit_events_result_time", AuditEvent.result, AuditEvent.timestamp.desc())
# Phase 4 summary-aggregation support (mirrors Alembic revision
# 0004_summary_aggregation_indexes). Composite for GROUP BY resource_type with
# a time window, plus partial indexes that make the failure/denial counts
# constant-time relative to the matching subset of rows.
Index(
    "idx_audit_events_resource_type_time",
    AuditEvent.resource_type,
    AuditEvent.timestamp.desc(),
)
Index(
    "idx_audit_events_failure_time",
    AuditEvent.timestamp.desc(),
    postgresql_where=AuditEvent.is_failure.is_(True),
    sqlite_where=AuditEvent.is_failure.is_(True),
)
Index(
    "idx_audit_events_denied_time",
    AuditEvent.timestamp.desc(),
    postgresql_where=AuditEvent.is_denied.is_(True),
    sqlite_where=AuditEvent.is_denied.is_(True),
)
# Phase 4 follow-up: partial indexes scoped to non-empty values for
# /filters/options (mirrors Alembic 0005_filter_options_partial_indexes).
Index(
    "idx_audit_events_resource_type_notnull",
    AuditEvent.resource_type,
    postgresql_where=(AuditEvent.resource_type.isnot(None)) & (AuditEvent.resource_type != ""),
    sqlite_where=(AuditEvent.resource_type.isnot(None)) & (AuditEvent.resource_type != ""),
)
Index(
    "idx_audit_events_actor_notnull",
    AuditEvent.actor,
    postgresql_where=(AuditEvent.actor.isnot(None)) & (AuditEvent.actor != ""),
    sqlite_where=(AuditEvent.actor.isnot(None)) & (AuditEvent.actor != ""),
)


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        UniqueConstraint("category", "key", name="uq_app_settings_category_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_enc: Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True)
    is_secret: Mapped[bool] = mapped_column(default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)


Index("idx_app_settings_category", AppSettings.category)
