import json
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.product.actor_enrichment import enrich_actor
from src.product.source_enrichment import extract_source_info
from src.product.event_intelligence import event_digest_from_model
from src.product.event_signals import classify_signal
from src.product.triage_store import get_triage


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
    source_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)
    _source_context: Mapped[str | None] = mapped_column("source_context", String(255), nullable=True)
    _client_id: Mapped[str | None] = mapped_column("client_id", String(255), nullable=True)
    _connection_id: Mapped[str | None] = mapped_column("connection_id", String(255), nullable=True)
    _request_id: Mapped[str | None] = mapped_column("request_id", String(255), nullable=True)
    environment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    flink_region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    network_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    is_failure: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_denied: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_routine_noise: Mapped[bool] = mapped_column(default=False, nullable=False)

    def _intelligence(self) -> dict[str, str]:
        cached = getattr(self, "_event_intelligence_cache", None)
        if cached is None:
            cached = event_digest_from_model(self)
            setattr(self, "_event_intelligence_cache", cached)
        return cached

    @property
    def impact_type(self) -> str:
        return self._intelligence()["impact_type"]

    @property
    def risk_level(self) -> str:
        return self._intelligence()["risk_level"]

    @property
    def change_type(self) -> str:
        return self._intelligence()["change_type"]

    @property
    def resource_family(self) -> str:
        return self._intelligence()["resource_family"]

    @property
    def event_title(self) -> str:
        return self._intelligence()["event_title"]

    @property
    def event_summary(self) -> str:
        return self._intelligence()["event_summary"]

    @property
    def subject(self) -> str:
        return self._intelligence()["subject"]

    @property
    def subject_type(self) -> str:
        return self._intelligence()["subject_type"]

    @property
    def resource_display_short(self) -> str:
        return self._intelligence()["resource_display_short"]

    @property
    def source_context(self) -> str:
        return self._source_context or self._intelligence()["source_context"]

    @source_context.setter
    def source_context(self, value: str | None) -> None:
        self._source_context = value

    @property
    def decision_reason(self) -> str:
        return self._intelligence()["decision_reason"]

    def _source_enrichment(self) -> dict[str, str | None]:
        cached = getattr(self, "_source_enrichment_cache", None)
        if cached is None:
            try:
                payload = json.loads(self.raw_payload_json) if self.raw_payload_json else {}
            except json.JSONDecodeError:
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
            cached = classify_signal(self)
            setattr(self, "_event_signal_cache", cached)
        return cached

    @property
    def signal_type(self) -> str:
        return self._signal()["signal_type"]

    @property
    def signal_reason(self) -> str:
        return self._signal()["signal_reason"]

    @property
    def decision_label(self) -> str:
        return self._signal()["decision_label"]

    @property
    def recommended_action(self) -> str:
        return self._signal()["recommended_action"]

    def _actor_enrichment(self) -> dict[str, str | None]:
        cached = getattr(self, "_actor_enrichment_cache", None)
        if cached is None:
            cached = enrich_actor(self.actor, self.subject, self.subject_type)
            setattr(self, "_actor_enrichment_cache", cached)
        return cached

    @property
    def actor_display_name(self) -> str:
        return str(self._actor_display_name or self._actor_enrichment()["actor_display_name"] or "Unknown actor")

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
        triage = get_triage(self.event_fingerprint)
        if triage.get("triage_status") == "open":
            legacy = get_triage(self.id)
            if legacy.get("triage_status") != "open":
                return legacy
        return triage

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
Index("idx_audit_events_timestamp_desc", AuditEvent.timestamp.desc())
Index("idx_audit_events_resource_lookup", AuditEvent.resource_type, AuditEvent.resource_name, AuditEvent.timestamp.desc())
Index("idx_audit_events_resource_type_action_category_time", AuditEvent.resource_type, AuditEvent.action_category, AuditEvent.timestamp.desc())
Index("idx_audit_events_resource_name_time", AuditEvent.resource_name, AuditEvent.timestamp.desc())
Index("idx_audit_events_action_category_time", AuditEvent.action_category, AuditEvent.timestamp.desc())
Index("idx_audit_events_actor_time", AuditEvent.actor, AuditEvent.timestamp.desc())
Index("idx_audit_events_result_time", AuditEvent.result, AuditEvent.timestamp.desc())
