"""Shared schema primitives."""

from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

T = TypeVar("T")


class APIModel(BaseModel):
    """Base for request bodies.

    * ``Infinity``/``NaN`` are rejected with 422 (QA audit AQ-008): Python's JSON parser accepts them
      (and ``1e400`` overflows to ``inf``), but they poison averages and cannot be serialised back.
    * Surrounding whitespace is trimmed, so ``"  "`` fails a ``min_length`` check instead of becoming
      a blank asset or rule name (AQ-012). Passwords opt out via :data:`Secret`.
    """

    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)


# Passwords and tokens are compared byte-for-byte: never trim them.
Secret = Annotated[str, StringConstraints(strip_whitespace=False)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=500)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class Envelope(BaseModel, Generic[T]):
    """Documented shape of the Ch. 7.2.3 envelope (used for OpenAPI response models)."""

    status: str = "success"
    data: T
    meta: dict[str, Any] | None = None
    request_id: str


class Message(BaseModel):
    message: str
