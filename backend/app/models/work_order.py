"""Work orders (Ch. 7.11): corrective, preventive, predictive, inspection and audit findings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import Priority, WorkOrderStatus, WorkOrderType, pg_enum


class WorkOrder(UUIDPk, Timestamps, Base):
    __tablename__ = "work_orders"

    number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)  # WO-2026-000123
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    wo_type: Mapped[WorkOrderType] = mapped_column(pg_enum(WorkOrderType, "work_order_type"))
    priority: Mapped[Priority] = mapped_column(pg_enum(Priority, "priority"), default=Priority.MEDIUM)
    status: Mapped[WorkOrderStatus] = mapped_column(pg_enum(WorkOrderStatus, "work_order_status"), default=WorkOrderStatus.OPEN)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    due_date: Mapped[datetime | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    labor_hours: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float)
    failure_code: Mapped[str | None] = mapped_column(String(50))  # set on corrective WOs -> MTBF/labels
    resolution_notes: Mapped[str | None] = mapped_column(Text)

    asset = relationship("Asset", lazy="joined")

    __table_args__ = (
        Index("ix_work_orders_asset_created", "asset_id", "created_at"),  # Table 6.7
        Index("ix_work_orders_status_assigned", "status", "assigned_to"),  # Table 6.7
    )
