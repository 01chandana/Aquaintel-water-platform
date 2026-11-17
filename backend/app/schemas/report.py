"""Reports & compliance (Table 7.8) schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.models.enums import (
    ReportFormat,
    ReportStatus,
)
from app.schemas.common import APIModel, ORMModel

ReportType = Literal[
    "shift_handover", "compliance_daily", "compliance_monthly", "kpi_summary", "alert_summary",
    "asset_performance", "custom",
]


class ReportGenerate(APIModel):
    report_type: ReportType
    format: ReportFormat = ReportFormat.PDF
    name: str | None = Field(default=None, min_length=3, max_length=200)
    start: datetime | None = None
    end: datetime | None = None
    site_id: uuid.UUID | None = None
    sections: list[str] | None = None  # Report Builder section order
    due_at: datetime | None = None


class ReportOut(ORMModel):
    id: uuid.UUID
    name: str
    report_type: str
    format: ReportFormat
    status: ReportStatus
    parameters: dict[str, Any] | None
    file_size: int | None
    due_at: datetime | None
    created_at: datetime
    completed_at: datetime | None
    error: str | None


class ScheduleCreate(APIModel):
    name: str = Field(min_length=3, max_length=200)
    report_type: ReportType
    format: ReportFormat = ReportFormat.PDF
    cron: str = Field(min_length=9, max_length=100)
    parameters: dict[str, Any] | None = None
    recipients: list[str] = []
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def _cron(cls, v: str) -> str:
        from croniter import croniter

        if not croniter.is_valid(v):
            raise ValueError("invalid cron expression")
        return v


class ScheduleOut(ORMModel):
    id: uuid.UUID
    name: str
    report_type: str
    format: ReportFormat
    cron: str
    parameters: dict[str, Any] | None
    recipients: list[str]
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
