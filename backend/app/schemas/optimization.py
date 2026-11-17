"""Optimization (Ch. 12.5 Use Cases 15, 18) schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel, ORMModel


class PumpScheduleRequest(APIModel):
    site_id: uuid.UUID | None = None
    horizon_hours: int = Field(24, ge=6, le=48)
    initial_level_pct: float | None = Field(default=None, ge=0, le=100)
    min_level_pct: float = Field(25, ge=0, le=100)
    max_level_pct: float = Field(95, ge=0, le=100)
    use_forecast: bool = True


class DosingRequest(APIModel):
    site_id: uuid.UUID | None = None
    target_residual_mg_l: float = Field(0.8, ge=0.2, le=4.0)
    raw_turbidity_ntu: float | None = None
    water_temperature_c: float | None = None
    flow_m3h: float | None = None


class ScheduleOutModel(ORMModel):
    id: uuid.UUID
    name: str
    schedule_type: str
    site_id: uuid.UUID | None
    horizon_hours: int
    status: str
    solver_status: str | None
    inputs: dict[str, Any]
    plan: dict[str, Any]
    estimated_cost: float | None
    baseline_cost: float | None
    savings_pct: float | None
    created_at: datetime
