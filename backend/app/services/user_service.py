"""User and API-key management (Table 7.2, Ch. 17.2.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.exceptions import AuthorizationError, ConflictError, ValidationError
from app.core.permissions import ALL_PERMISSIONS
from app.core.permissions import Role as RoleName
from app.core.security import generate_api_key, hash_password, verify_password
from app.models.user import ApiKey, User
from app.repositories.user_repository import ApiKeyRepository, RoleRepository, UserRepository
from app.schemas.user import ApiKeyCreate, SelfUpdate, UserCreate, UserUpdate
from app.services.audit_service import AuditService


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.roles = RoleRepository(session)
        self.keys = ApiKeyRepository(session)
        self.audit = AuditService(session)

    async def list(self, page: int, per_page: int, q: str | None, role: str | None,
                   active: bool | None) -> tuple[list[User], int]:
        filters: list[ColumnElement[bool]] = []
        if q:
            filters.append(User.email.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
        if role:
            r = await self.roles.get_by_name(role)
            filters.append(User.role_id == (r.id if r else uuid.uuid4()))
        if active is not None:
            filters.append(User.is_active.is_(active))
        return await self.users.list(*filters, page=page, per_page=per_page)

    async def create(self, data: UserCreate, actor: Principal) -> User:
        if await self.users.get_by_email(data.email):
            raise ConflictError(f"User {data.email} already exists")
        role = await self.roles.get_by_name(data.role)
        if role is None:
            raise ValidationError(f"Unknown role {data.role}")
        self._guard_super_admin(data.role, actor)
        user = await self.users.create(User(
            email=data.email.lower(), display_name=data.display_name, password_hash=hash_password(data.password),
            role_id=role.id, asset_scopes=data.asset_scopes, phone=data.phone,
        ))
        await self.session.refresh(user, ["role"])
        await self.audit.record("user.create", "user", user.id, principal=actor,
                                details={"email": user.email, "role": data.role})
        await self.session.commit()
        return user

    async def update(self, user_id: uuid.UUID, data: UserUpdate, actor: Principal) -> User:
        user = await self.users.get_or_404(user_id, "User")
        changes = data.model_dump(exclude_unset=True)
        for k, v in changes.items():
            setattr(user, k, v)
        await self.audit.record("user.update", "user", user.id, principal=actor, details=changes)
        await self.session.commit()
        return user

    async def deactivate(self, user_id: uuid.UUID, actor: Principal) -> None:
        if user_id == actor.id:
            raise ValidationError("You cannot deactivate your own account")
        user = await self.users.get_or_404(user_id, "User")
        user.is_active = False  # soft delete: audit history keeps referencing the user
        await self.audit.record("user.deactivate", "user", user.id, principal=actor)
        await self.session.commit()

    async def assign_role(self, user_id: uuid.UUID, role_name: str, actor: Principal) -> User:
        user = await self.users.get_or_404(user_id, "User")
        role = await self.roles.get_by_name(role_name)
        if role is None:
            raise ValidationError(f"Unknown role {role_name}")
        self._guard_super_admin(role_name, actor)
        old = user.role.name
        user.role_id = role.id
        await self.session.flush()
        await self.session.refresh(user, ["role"])
        await self.audit.record("user.role_assign", "user", user.id, principal=actor,
                                details={"from": old, "to": role_name})
        await self.session.commit()
        return user

    async def update_self(self, actor: Principal, data: SelfUpdate) -> User:
        user = await self.users.get_or_404(actor.id, "User")
        if data.new_password:
            if not data.current_password or not verify_password(data.current_password, user.password_hash):
                raise ValidationError("current_password is incorrect")
            user.password_hash = hash_password(data.new_password)
        if data.display_name:
            user.display_name = data.display_name
        if data.phone is not None:
            user.phone = data.phone
        await self.audit.record("user.update_self", "user", user.id, principal=actor,
                                details={"password_changed": bool(data.new_password)})
        await self.session.commit()
        return user

    @staticmethod
    def _guard_super_admin(role: str, actor: Principal) -> None:
        if role == RoleName.SUPER_ADMIN and actor.role != RoleName.SUPER_ADMIN:
            raise AuthorizationError("Only a super admin can grant the super_admin role")

    # ---- API keys --------------------------------------------------------------------------
    async def create_api_key(self, data: ApiKeyCreate, actor: Principal) -> tuple[ApiKey, str]:
        unknown = set(data.permissions) - set(ALL_PERMISSIONS)
        if unknown:
            raise ValidationError(f"Unknown permissions: {sorted(unknown)}")
        raw, prefix, hashed = generate_api_key()
        key = await self.keys.create(ApiKey(
            name=data.name, key_prefix=prefix, key_hash=hashed, permissions=data.permissions,
            asset_scopes=data.asset_scopes, created_by=actor.user_id,
            expires_at=datetime.now(UTC) + timedelta(days=data.expires_in_days),
        ))
        await self.audit.record("api_key.create", "api_key", key.id, principal=actor,
                                details={"name": data.name, "permissions": data.permissions})
        await self.session.commit()
        return key, raw

    async def revoke_api_key(self, key_id: uuid.UUID, actor: Principal) -> None:
        key = await self.keys.get_or_404(key_id, "API key")
        key.revoked = True
        await self.audit.record("api_key.revoke", "api_key", key.id, principal=actor)
        await self.session.commit()
