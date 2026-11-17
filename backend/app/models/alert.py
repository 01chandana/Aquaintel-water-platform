"""Rules engine persistence: AlertRule (Table 6.5), Alert, AlertEvent, Incident, Notification."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk
from app.models.enums import AlertStatus, NotificationChannel, RuleType, Severity, pg_enum


class AlertRule(UUIDPk, CreatedAt, Base):
    __tablename__ = "alert_rules"

    # --- Table 6.5 columns -------------------------------------------------------------
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"))
    tag_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telemetry_tags.id", ondelete="CASCADE"), index=True
    )
    rule_type: Mapped[RuleType] = mapped_column(pg_enum(RuleType, "rule_type"), nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "severity"), nullable=False)
    escalation_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # --- Listing 13.1 structure ----------------------------------------------------------
    description: Mapped[str | None] = mapped_column(Text)
    escalation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    notification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    suppression: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")  # dedup window
    kpi_code: Mapped[str | None] = mapped_column(String(40))  # links a rule to a KPI alert condition
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Incident(UUIDPk, Timestamps, Base):
    """Group of correlated alerts (Use Case 6, Ch. 13.7 aggregation)."""

    __tablename__ = "incidents"

    title: Mapped[str] = mapped_column(String(250), nullable=False)
    root_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id"))
    severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "severity"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open")
    alert_count: Mapped[int] = mapped_column(Integer, default=1)
    root_cause_hint: Mapped[str | None] = mapped_column(Text)


class Alert(UUIDPk, Timestamps, Base):
    __tablename__ = "alerts"

    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"))
    tag_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("telemetry_tags.id", ondelete="SET NULL"))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"))
    severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "severity"), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(
        pg_enum(AlertStatus, "alert_status"), default=AlertStatus.TRIGGERED, server_default="triggered"
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="rule")  # rule | ml | kpi | manual
    trigger_value: Mapped[float | None] = mapped_column(Float)
    threshold_value: Mapped[float | None] = mapped_column(Float)
    fault_code: Mapped[str | None] = mapped_column(String(50))  # predictive maintenance (Ch. 5.3.2)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_false_positive: Mapped[bool | None] = mapped_column(Boolean)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_triggered_at: Mapped[datetime | None] = mapped_column()
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column()
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column()

    rule: Mapped[AlertRule | None] = relationship(lazy="joined")
    asset = relationship("Asset", lazy="joined")
    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="alert", order_by="AlertEvent.created_at", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_alerts_asset_created", "asset_id", "created_at"),  # Table 6.7
        Index("ix_alerts_severity_status_created", "severity", "status", "created_at"),  # Table 6.7
        Index("ix_alerts_rule_status", "rule_id", "status"),
    )


class AlertEvent(UUIDPk, CreatedAt, Base):
    """Alert timeline entry: every lifecycle transition (Figure 13.1) is recorded."""

    __tablename__ = "alert_events"

    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    actor: Mapped[str | None] = mapped_column(String(150))
    note: Mapped[str | None] = mapped_column(Text)

    alert: Mapped[Alert] = relationship(back_populates="events")


class Notification(UUIDPk, CreatedAt, Base):
    __tablename__ = "notifications"

    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    channel: Mapped[NotificationChannel] = mapped_column(pg_enum(NotificationChannel, "notification_channel"))
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent | failed | skipped
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
