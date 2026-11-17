"""KPI definitions (Table 6.6) and KPI values (time-series, hypertable in 0002)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, Interval, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPk
from app.models.enums import AggregationType, pg_enum


class KPIDefinition(UUIDPk, CreatedAt, Base):
    __tablename__ = "kpi_definitions"

    # --- Table 6.6 columns -------------------------------------------------------------
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    threshold_warning: Mapped[float | None] = mapped_column(Float)
    threshold_critical: Mapped[float | None] = mapped_column(Float)
    computation_interval: Mapped[timedelta] = mapped_column(Interval, server_default=text("'1 hour'"))
    aggregation_type: Mapped[AggregationType] = mapped_column(pg_enum(AggregationType, "aggregation_type"))
    # --- Catalogue metadata (Ch. 11.3) ------------------------------------------------------
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)  # engine function key
    number: Mapped[int | None] = mapped_column(Integer)  # 1..30 in the spec catalogue
    description: Mapped[str | None] = mapped_column(Text)
    higher_is_better: Mapped[bool] = mapped_column(Boolean, default=True)
    target: Mapped[float | None] = mapped_column(Float)
    visualization: Mapped[str | None] = mapped_column(String(100))
    alert_condition: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20), default="site")  # site | asset
    health_category: Mapped[str | None] = mapped_column(String(30))  # reliability/efficiency/quality (view 6.5)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)


class KPIValue(Base):
    __tablename__ = "kpi_values"

    time: Mapped[datetime] = mapped_column(primary_key=True)
    kpi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kpi_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    # NULL asset_id would break the composite PK, so site-wide values use the site asset id.
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_value: Mapped[float | None] = mapped_column(Float)  # 0..100 score used by health view
    status: Mapped[str] = mapped_column(String(20), default="normal")  # normal | warning | critical
    period_start: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        Index("ix_kpi_values_kpi_time", "kpi_id", time.desc()),  # Table 6.7
        Index("ix_kpi_values_asset_time", "asset_id", time.desc()),  # Table 6.7
    )
