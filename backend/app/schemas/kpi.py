"""KPIs (Table 7.6) schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from pydantic import Field

from app.models.enums import (
    AggregationType,
)
from app.schemas.common import APIModel, ORMModel


class KPICreate(APIModel):
    code: str = Field(pattern=r"^[A-Z0-9_]{2,40}$")
    name: str = Field(min_length=3, max_length=200)
    formula: str = Field(min_length=1, max_length=500)
    unit: str = Field(min_length=1, max_length=20)
    category: str = Field(min_length=2, max_length=40)
    threshold_warning: float | None = None
    threshold_critical: float | None = None
    computation_interval: timedelta = timedelta(hours=1)
    aggregation_type: AggregationType = AggregationType.AVG
    description: str | None = Field(default=None, max_length=2000)
    higher_is_better: bool = True
    target: float | None = None
    visualization: str | None = Field(default=None, max_length=40)
    # Custom KPIs: aggregate of one telemetry parameter (e.g. avg of 'ph' for a site)
    source_parameter: str | None = Field(default=None, max_length=60)


class KPIOut(ORMModel):
    id: uuid.UUID
    code: str
    number: int | None
    name: str
    formula: str
    unit: str
    category: str
    threshold_warning: float | None
    threshold_critical: float | None
    computation_interval: timedelta
    aggregation_type: AggregationType
    description: str | None
    higher_is_better: bool
    target: float | None
    visualization: str | None
    alert_condition: str | None
    scope: str
    is_builtin: bool


class KPIValueOut(APIModel):
    time: datetime
    asset_id: uuid.UUID
    value: float
    normalized_value: float | None
    status: str


class KPICurrent(APIModel):
    kpi: KPIOut
    asset_id: uuid.UUID | None
    value: float | None
    status: str
    time: datetime | None
    previous_value: float | None = None
    trend_pct: float | None = None
