"""Tamper-evident audit log (Ch. 17.7).

Each row stores ``prev_hash`` and ``hash = SHA-256(prev_hash || canonical(row))``. Any edit
or deletion of a historical row breaks the chain, which ``GET /admin/audit-log/verify``
detects. A database trigger (migration 0002) also rejects UPDATE/DELETE: append-only.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt


class AuditLog(CreatedAt, Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    actor: Mapped[str | None] = mapped_column(String(255))  # email or api-key name
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    source_ip: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (
        Index("ix_audit_log_user_created", "user_id", "created_at"),  # Table 6.7
        Index("ix_audit_log_entity", "entity_type", "entity_id"),  # Table 6.7
    )
