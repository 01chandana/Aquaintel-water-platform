"""ML (Table 7.10) schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.models.enums import (
    ModelStage,
)
from app.schemas.common import APIModel, ORMModel


class ModelRegister(APIModel):
    name: str = Field(min_length=3, max_length=60)
    model_type: str = Field(min_length=2, max_length=60)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    artifact_uri: str = Field(min_length=3, max_length=500)
    mlflow_run_id: str | None = None
    metrics: dict[str, float] = {}
    params: dict[str, Any] = {}
    features: list[str] = []


class ModelDeploy(APIModel):
    stage: Literal["staging", "production", "archived"] = "production"
    note: str | None = Field(default=None, max_length=2000)


class PredictRequest(APIModel):
    asset_id: uuid.UUID | None = None
    features: dict[str, float] | None = None
    horizon_hours: int = Field(24, ge=1, le=72)  # forecasting models
    explain: bool = True


class ModelOut(ORMModel):
    id: uuid.UUID
    name: str
    model_type: str
    version: str
    stage: ModelStage
    mlflow_run_id: str | None
    artifact_uri: str
    metrics: dict[str, Any]
    params: dict[str, Any]
    features: list[str]
    acceptance: dict[str, Any] | None
    training_window: dict[str, Any] | None
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    deployed_at: datetime | None
    created_at: datetime
