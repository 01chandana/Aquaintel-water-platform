"""Asset management schemas (Table 7.3)."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator

from app.models.enums import AssetStatus
from app.schemas.common import APIModel, ORMModel

_EXTERNAL_ID = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,99}$")


class GeoPoint(APIModel):
    """GeoJSON Point (Table 6.2 ``location``)."""

    type: str = "Point"
    coordinates: list[float] = Field(min_length=2, max_length=3)  # [lon, lat]


class AssetTypeCreate(APIModel):
    name: str = Field(min_length=2, max_length=100)
    category: str = Field(min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    criticality: int = Field(3, ge=1, le=5)
    default_tags: list[dict[str, Any]] | None = None


class AssetTypeOut(ORMModel):
    id: uuid.UUID
    name: str
    category: str
    description: str | None
    criticality: int
    default_tags: list[dict[str, Any]] | None = None


class AssetBase(APIModel):
    name: str = Field(min_length=1, max_length=200)
    location: GeoPoint | None = None
    metadata: dict[str, Any] | None = None
    status: AssetStatus = AssetStatus.ACTIVE
    commissioned_at: date | None = None
    warranty_until: date | None = None


class AssetCreate(AssetBase):
    external_id: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    asset_type_id: uuid.UUID
    parent_id: uuid.UUID | None = None

    @field_validator("external_id")
    @classmethod
    def _ext(cls, v: str) -> str:
        if not _EXTERNAL_ID.match(v):
            raise ValueError("external_id must be lowercase alphanumeric with _ or - (SCADA tag style)")
        return v


class AssetUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location: GeoPoint | None = None
    metadata: dict[str, Any] | None = None
    status: AssetStatus | None = None
    parent_id: uuid.UUID | None = None
    commissioned_at: date | None = None
    warranty_until: date | None = None


class AssetOut(ORMModel):
    id: uuid.UUID
    external_id: str
    name: str
    asset_type_id: uuid.UUID
    asset_type: AssetTypeOut | None = None
    parent_id: uuid.UUID | None
    path: str
    location: dict[str, Any] | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    status: AssetStatus
    commissioned_at: date | None
    warranty_until: date | None
    created_at: datetime


class AssetNode(AssetOut):
    children: list[AssetNode] = []
    open_alerts: int = 0


AssetNode.model_rebuild()
