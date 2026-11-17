"""Telemetry tags and the TimescaleDB hypertable (Table 6.3).

``telemetry_data`` is converted into a hypertable in migration 0002:
RANGE(time) 7-day chunks, HASH(tag_id) x4 space partitions, compression after 30 days,
retention 2 years, plus the ``telemetry_hourly`` continuous aggregate (Table 6.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPk

GOOD_QUALITY = 192  # OPC-UA "Good"


class TelemetryTag(UUIDPk, CreatedAt, Base):
    __tablename__ = "telemetry_tags"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)  # SCADA tag
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parameter: Mapped[str] = mapped_column(String(60), index=True, nullable=False)  # flow, pressure, ph...
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    min_valid: Mapped[float | None] = mapped_column(Float)  # Appendix A.3.4 range checks
    max_valid: Mapped[float | None] = mapped_column(Float)
    max_delta_per_hour: Mapped[float | None] = mapped_column(Float)
    design_value: Mapped[float | None] = mapped_column(Float)  # e.g. design flow for KPI 3
    source_protocol: Mapped[str] = mapped_column(String(20), default="mqtt")  # mqtt/opcua/modbus/rest
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    asset = relationship("Asset", lazy="joined")


class TelemetryData(Base):
    __tablename__ = "telemetry_data"

    time: Mapped[datetime] = mapped_column(primary_key=True, nullable=False)
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telemetry_tags.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[int] = mapped_column(SmallInteger, default=GOOD_QUALITY, server_default="192")
    status: Mapped[str] = mapped_column(String(20), default="good", server_default="good")
    annotations: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        # Table 6.7 B-tree (tag_id, time DESC); BRIN and HASH indexes are created in 0002.
        Index("ix_telemetry_tag_time", "tag_id", time.desc()),
    )
