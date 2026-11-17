"""Admin (Table 7.11) schemas."""

from __future__ import annotations

from typing import Any

from app.schemas.common import APIModel


class ConfigUpdate(APIModel):
    values: dict[str, Any]
