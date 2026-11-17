"""Work orders (Table 7.9) schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.enums import (
    Priority,
    WorkOrderStatus,
    WorkOrderType,
)
from app.schemas.common import APIModel, ORMModel


class WorkOrderCreate(APIModel):
    asset_id: uuid.UUID
    alert_id: uuid.UUID | None = None
    title: str = Field(min_length=3, max_length=250)
    description: str | None = Field(default=None, max_length=4000)
    wo_type: WorkOrderType = WorkOrderType.CORRECTIVE
    priority: Priority = Priority.MEDIUM
    due_date: datetime | None = None


class WorkOrderUpdate(APIModel):
    title: str | None = Field(default=None, min_length=3, max_length=250)
    description: str | None = Field(default=None, max_length=4000)
    priority: Priority | None = None
    status: Literal["open", "in_progress", "cancelled"] | None = None
    due_date: datetime | None = None


class WorkOrderAssign(APIModel):
    assigned_to: uuid.UUID


class WorkOrderComplete(APIModel):
    resolution_notes: str = Field(min_length=3, max_length=4000)
    labor_hours: float = Field(ge=0)
    cost: float | None = Field(default=None, ge=0)
    failure_code: str | None = Field(default=None, max_length=40)


class WorkOrderOut(ORMModel):
    id: uuid.UUID
    number: str
    asset_id: uuid.UUID
    alert_id: uuid.UUID | None
    title: str
    description: str | None
    wo_type: WorkOrderType
    priority: Priority
    status: WorkOrderStatus
    assigned_to: uuid.UUID | None
    created_by: uuid.UUID | None
    due_date: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    labor_hours: float | None
    cost: float | None
    failure_code: str | None
    resolution_notes: str | None
    created_at: datetime
    asset_name: str | None = None
