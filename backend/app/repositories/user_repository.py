from __future__ import annotations

from sqlalchemy import func, select

from app.models.user import ApiKey, Role, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User
    default_order = (User.display_name.asc(),)
    sortable = {"email": User.email, "display_name": User.display_name, "created_at": User.created_at,
                "last_login": User.last_login}

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()


class RoleRepository(BaseRepository[Role]):
    model = Role
    default_order = (Role.name.asc(),)

    async def get_by_name(self, name: str) -> Role | None:
        return (await self.session.execute(select(Role).where(Role.name == name))).scalar_one_or_none()


class ApiKeyRepository(BaseRepository[ApiKey]):
    model = ApiKey
    default_order = (ApiKey.created_at.desc(),)

    async def by_prefix(self, prefix: str) -> list[ApiKey]:
        stmt = select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.revoked.is_(False))
        return list((await self.session.execute(stmt)).scalars().all())
