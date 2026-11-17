"""ML model registry mirror and prediction history (Ch. 10.11, Table 6.7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPk
from app.models.enums import ModelStage, pg_enum


class MLModel(UUIDPk, CreatedAt, Base):
    __tablename__ = "ml_models"

    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # pump_failure, demand_forecast...
    model_type: Mapped[str] = mapped_column(String(60), nullable=False)  # xgboost_classifier, lightgbm, ...
    version: Mapped[str] = mapped_column(String(20), nullable=False)  # semantic version (Ch. 10.11)
    stage: Mapped[ModelStage] = mapped_column(pg_enum(ModelStage, "model_stage"), default=ModelStage.NONE)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64))
    artifact_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    features: Mapped[list[str]] = mapped_column(JSONB, default=list)
    baseline: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # training feature histograms for PSI
    acceptance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # Ch. 10.7.2 checks
    training_window: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    deployed_at: Mapped[datetime | None] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (UniqueConstraint("name", "version", name="uq_ml_models_name_version"),)


class Prediction(Base):
    __tablename__ = "predictions"

    time: Mapped[datetime] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ml_models.id", ondelete="CASCADE"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"))
    value: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str | None] = mapped_column(String(60))
    confidence: Mapped[float | None] = mapped_column(Float)
    horizon: Mapped[str | None] = mapped_column(String(30))  # e.g. "7d", "t+24h"
    is_shadow: Mapped[bool] = mapped_column(Boolean, default=False)  # challenger in shadow mode
    features: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # SHAP contributions (Ch. 14.8)

    __table_args__ = (
        Index("ix_predictions_model_time", "model_id", time.desc()),  # Table 6.7
        Index("ix_predictions_asset_time", "asset_id", time.desc()),  # Table 6.7
    )
