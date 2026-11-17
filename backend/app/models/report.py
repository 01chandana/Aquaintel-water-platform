"""Reports, report schedules and regulatory limits (Ch. 7.10, Use Cases 2 & 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPk
from app.models.enums import ReportFormat, ReportStatus, pg_enum


class Report(UUIDPk, CreatedAt, Base):
    __tablename__ = "reports"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    format: Mapped[ReportFormat] = mapped_column(pg_enum(ReportFormat, "report_format"))
    status: Mapped[ReportStatus] = mapped_column(pg_enum(ReportStatus, "report_status"), default=ReportStatus.PENDING)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    file_key: Mapped[str | None] = mapped_column(String(300))
    file_uri: Mapped[str | None] = mapped_column(String(500))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    due_at: Mapped[datetime | None] = mapped_column()  # regulatory submission deadline (KPI 27)
    submitted_at: Mapped[datetime | None] = mapped_column()
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("report_schedules.id", ondelete="SET NULL"))
    generated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)


class ReportSchedule(UUIDPk, CreatedAt, Base):
    __tablename__ = "report_schedules"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    format: Mapped[ReportFormat] = mapped_column(pg_enum(ReportFormat, "report_format"))
    cron: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recipients: Mapped[list[str]] = mapped_column(JSONB, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column()
    next_run_at: Mapped[datetime | None] = mapped_column(index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class RegulatoryLimit(UUIDPk, CreatedAt, Base):
    """MCL/MRDL configuration per parameter (Use Case 4: 'Configure MCL values per parameter')."""

    __tablename__ = "regulatory_limits"

    parameter: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    limit_min: Mapped[float | None] = mapped_column(Float)
    limit_max: Mapped[float | None] = mapped_column(Float)
    regulation: Mapped[str] = mapped_column(String(60), default="SDWA")
    required_samples_per_day: Mapped[int] = mapped_column(default=24)  # KPI 26 sample coverage
