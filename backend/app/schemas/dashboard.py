"""Dashboards (Table 7.7) schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import APIModel, ORMModel

WidgetType = Literal["kpi_card", "trend_chart", "gauge", "alert_list", "telemetry_table", "heatmap", "bar_chart", "asset_tree"]


class WidgetIn(APIModel):
    widget_type: WidgetType
    title: str = Field(min_length=1, max_length=150)
    config: dict[str, Any] = {}
    position_index: int = 0
    width: int = Field(4, ge=2, le=12)


class WidgetOut(ORMModel):
    id: uuid.UUID
    widget_type: str
    title: str
    config: dict[str, Any]
    position_index: int
    width: int


class DashboardIn(APIModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    layout: dict[str, Any] | None = None
    filters: dict[str, Any] | None = None
    is_shared: bool = False
    template_id: uuid.UUID | None = None  # clone widgets from a template


class DashboardUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    layout: dict[str, Any] | None = None
    filters: dict[str, Any] | None = None
    is_shared: bool | None = None
    widget_order: list[uuid.UUID] | None = None  # drag-and-drop reorder


class DashboardOut(ORMModel):
    id: uuid.UUID
    owner_id: uuid.UUID | None
    name: str
    description: str | None
    layout: dict[str, Any] | None
    filters: dict[str, Any] | None
    is_template: bool
    is_shared: bool
    version: int
    widgets: list[WidgetOut] = []
    created_at: datetime
    updated_at: datetime
