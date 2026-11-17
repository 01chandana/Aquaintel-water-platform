"""SQLAlchemy declarative base and shared column helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Every timestamp is TIMESTAMPTZ (Ch. 6.3); application code uses timezone-aware UTC datetimes.
    type_annotation_map = {datetime: DateTime(timezone=True)}


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Timestamps(CreatedAt):
    # Client-side onupdate keeps the value known to the ORM after flush (no expired-attribute
    # reload, which would require implicit IO under asyncio).
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=utcnow, onupdate=utcnow, nullable=False
    )
