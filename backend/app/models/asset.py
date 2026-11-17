"""Asset registry: AssetType, Asset (Table 6.2), SparePart (KPI 24)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPk
from app.models.enums import AssetStatus, pg_enum


class AssetType(UUIDPk, CreatedAt, Base):
    __tablename__ = "asset_types"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)  # site/area/pump/valve/...
    description: Mapped[str | None] = mapped_column(Text)
    criticality: Mapped[int] = mapped_column(Integer, default=3, server_default="3")  # 1 low .. 5 critical
    default_tags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)


class Asset(UUIDPk, CreatedAt, Base):
    __tablename__ = "assets"

    # --- Table 6.2 columns -------------------------------------------------------------
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("asset_types.id"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL")
    )
    location: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # GeoJSON Point
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    status: Mapped[AssetStatus] = mapped_column(
        pg_enum(AssetStatus, "asset_status"), default=AssetStatus.ACTIVE, server_default="active"
    )
    commissioned_at: Mapped[date | None] = mapped_column(Date)
    warranty_until: Mapped[date | None] = mapped_column(Date)
    # --- Materialized hierarchy path (e.g. "plant_a/pumping/pump_001") used for ABAC
    #     asset-scope matching (Ch. 17.3.2) and subtree queries without recursion.
    path: Mapped[str] = mapped_column(String(500), index=True, nullable=False)

    asset_type: Mapped[AssetType] = relationship(lazy="joined")
    parent: Mapped[Asset | None] = relationship(remote_side="Asset.id", lazy="raise")

    __table_args__ = (Index("ix_assets_parent", "parent_id"),)


class SparePart(UUIDPk, CreatedAt, Base):
    __tablename__ = "spare_parts"

    part_number: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("asset_types.id"))
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    min_required: Mapped[int] = mapped_column(Integer, default=1)
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    unit_cost: Mapped[float | None] = mapped_column()
