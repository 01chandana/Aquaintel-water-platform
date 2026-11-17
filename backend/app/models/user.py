"""Identity models: Role, User, ApiKey (Table 6.1, Ch. 17.2-17.3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk


class Role(UUIDPk, CreatedAt, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="role")


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    # --- Table 6.1 columns -------------------------------------------------------------
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_login: Mapped[datetime | None] = mapped_column()
    # --- Supporting columns (Ch. 17.2.2 MFA, 17.3.2 ABAC, 17.5.3 lockout) --------------
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_backup_codes: Mapped[list[str] | None] = mapped_column(JSONB)
    asset_scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    phone: Mapped[str | None] = mapped_column(String(32))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column()

    role: Mapped[Role] = relationship(back_populates="users", lazy="joined")

    @property
    def permissions(self) -> list[str]:
        return list(self.role.permissions) if self.role else []


class ApiKey(UUIDPk, CreatedAt, Base):
    """Machine-to-machine credentials (Ch. 17.2.3): scoped, rate limited, rotated every 90 days."""

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    asset_scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column()
    last_used_at: Mapped[datetime | None] = mapped_column()
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
