"""Optimization schedules (ER diagram ``schedules``) and runtime system configuration."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPk, utcnow


class Schedule(UUIDPk, CreatedAt, Base):
    """An optimization plan (pump schedule or dosing setpoints) produced by the Optimization Service."""

    __tablename__ = "schedules"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(30), nullable=False)  # pump | dosing
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"))
    horizon_hours: Mapped[int] = mapped_column(Integer, default=24)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | approved | applied
    solver_status: Mapped[str | None] = mapped_column(String(60))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    baseline_cost: Mapped[float | None] = mapped_column(Float)
    savings_pct: Mapped[float | None] = mapped_column(Float)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow, onupdate=utcnow)
