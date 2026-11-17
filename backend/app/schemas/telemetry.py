"""Telemetry schemas (Table 7.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.common import APIModel, ORMModel


class TelemetryPoint(APIModel):
    """One sample. Either ``tag_id`` (UUID) or ``tag`` (SCADA external id) must be supplied.

    Non-finite values parse here on purpose: the service rejects them *per point* (``NON_FINITE_VALUE``)
    so one bad sample from a PLC does not discard the rest of its batch.
    """

    model_config = ConfigDict(allow_inf_nan=True)

    tag_id: uuid.UUID | None = None
    tag: str | None = Field(default=None, max_length=150)
    time: datetime
    value: float
    quality: int = Field(192, ge=0, le=255)
    annotations: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_ref(self) -> TelemetryPoint:
        if not (self.tag_id or self.tag):
            raise ValueError("tag_id or tag is required")
        return self


class IngestRequest(APIModel):
    source: str = Field("rest", max_length=40)  # mqtt | opcua | modbus | rest | csv
    points: list[TelemetryPoint] = Field(min_length=1, max_length=10_000)


class IngestResponse(APIModel):
    accepted: int
    rejected: int
    errors: list[dict[str, Any]] = []
    mode: str


class TagCreate(APIModel):
    asset_id: uuid.UUID
    external_id: str = Field(min_length=2, max_length=150)
    name: str = Field(min_length=1, max_length=200)
    parameter: str = Field(min_length=1, max_length=60)
    unit: str = Field(min_length=1, max_length=30)
    min_valid: float | None = None
    max_valid: float | None = None
    max_delta_per_hour: float | None = None
    design_value: float | None = None
    source_protocol: Literal["mqtt", "opcua", "modbus", "rest", "csv"] = "mqtt"


class TagOut(ORMModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    external_id: str
    name: str
    parameter: str
    unit: str
    min_valid: float | None
    max_valid: float | None
    max_delta_per_hour: float | None
    design_value: float | None
    source_protocol: str


class TelemetryRow(APIModel):
    time: datetime
    tag_id: uuid.UUID
    value: float
    quality: int
    status: str


class AggregateRow(APIModel):
    bucket: datetime
    tag_id: uuid.UUID
    avg_value: float | None
    min_value: float | None
    max_value: float | None
    count: int


class LatestValue(APIModel):
    tag_id: str
    tag: str | None = None
    asset_id: str | None = None
    parameter: str | None = None
    unit: str | None = None
    time: datetime | str
    value: float
    quality: int = 192
    status: str = "good"
