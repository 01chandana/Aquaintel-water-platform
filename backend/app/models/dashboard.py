"""Dashboard builder persistence: Dashboard, DashboardWidget."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk


class Dashboard(UUIDPk, Timestamps, Base):
    __tablename__ = "dashboards"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)  # cache version key (Table 9.1)

    widgets: Mapped[list[DashboardWidget]] = relationship(
        back_populates="dashboard", cascade="all, delete-orphan", lazy="selectin",
        order_by="DashboardWidget.position_index",
    )


class DashboardWidget(UUIDPk, CreatedAt, Base):
    __tablename__ = "dashboard_widgets"

    dashboard_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("dashboards.id", ondelete="CASCADE"), index=True)
    widget_type: Mapped[str] = mapped_column(String(40), nullable=False)  # kpi_card/trend_chart/gauge/alert_list/table/heatmap
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    position_index: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=4)  # grid columns out of 12

    dashboard: Mapped[Dashboard] = relationship(back_populates="widgets")
