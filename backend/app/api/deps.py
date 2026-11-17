"""Dependency injection (spec Listing 9.2): DB session, cache, current principal and RBAC.

A *principal* is either a human user (JWT bearer token) or an integration (``X-API-Key``).
Routers declare what they need with ``Depends(require_permission("alerts:acknowledge"))``;
the ``require_role`` factory from the spec listing is kept for role-specific routes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Query, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend, get_redis
from app.core.context import user_id_var
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.permissions import asset_in_scope
from app.core.security import API_KEY_PREFIX, decode_token, verify_api_key
from app.db.session import get_async_session
from app.models.user import User
from app.repositories.user_repository import ApiKeyRepository, UserRepository
from app.schemas.common import PageParams

bearer = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

DB = Annotated[AsyncSession, Depends(get_async_session)]
Cache = Annotated[CacheBackend, Depends(get_redis)]


@dataclass
class Principal:
    id: uuid.UUID
    kind: str  # "user" | "api_key"
    name: str
    role: str
    permissions: set[str]
    asset_scopes: list[str] = field(default_factory=list)
    jti: str | None = None
    exp: int | None = None
    user: User | None = None

    def has(self, *perms: str) -> bool:
        return all(p in self.permissions for p in perms)

    def can_access(self, asset_path: str | None) -> bool:
        return asset_in_scope(asset_path, self.asset_scopes)

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.id if self.kind == "user" else None


async def _principal_from_api_key(raw: str, db: AsyncSession) -> Principal:
    if not raw.startswith(API_KEY_PREFIX):
        raise AuthenticationError("Invalid API key")
    repo = ApiKeyRepository(db)
    for key in await repo.by_prefix(raw[:11]):
        if verify_api_key(raw, key.key_hash):
            if key.expires_at and key.expires_at < datetime.now(UTC):
                raise AuthenticationError("API key expired")
            key.last_used_at = datetime.now(UTC)
            await db.commit()
            return Principal(id=key.id, kind="api_key", name=key.name, role="integration",
                             permissions=set(key.permissions), asset_scopes=list(key.asset_scopes or []))
    raise AuthenticationError("Invalid API key")


async def get_current_principal(
    db: DB,
    cache: Cache,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    api_key: str | None = Depends(api_key_header),
) -> Principal:
    """Validate JWT (or API key) and return the calling principal."""
    if api_key:
        principal = await _principal_from_api_key(api_key, db)
    elif credentials:
        claims = decode_token(credentials.credentials)
        if await cache.exists(f"blacklist:{claims['jti']}"):
            raise AuthenticationError("Token revoked")
        user = await UserRepository(db).get(uuid.UUID(claims["sub"]))
        if user is None or not user.is_active:
            raise AuthenticationError("User inactive or not found")
        principal = Principal(
            id=user.id, kind="user", name=user.email, role=user.role.name,
            permissions=set(user.role.permissions), asset_scopes=list(user.asset_scopes or []),
            jti=claims["jti"], exp=claims["exp"], user=user,
        )
    else:
        raise AuthenticationError("Missing bearer token or API key")
    user_id_var.set(str(principal.id))
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


async def get_current_user(principal: CurrentPrincipal) -> Principal:
    if principal.kind != "user":
        raise AuthorizationError("This endpoint requires an interactive user session")
    return principal


CurrentUser = Annotated[Principal, Depends(get_current_user)]


def require_permission(*perms: str) -> Any:
    """Dependency factory for permission-based RBAC (Table 17.1)."""

    async def checker(principal: CurrentPrincipal) -> Principal:
        if not principal.has(*perms):
            raise AuthorizationError(f"Insufficient permissions: requires {', '.join(perms)}")
        return principal

    return Depends(checker)


def require_role(*roles: str) -> Any:
    """Dependency factory for role-based checks (spec Listing 9.2)."""

    async def role_checker(principal: CurrentPrincipal) -> Principal:
        if principal.role not in roles and principal.role != "super_admin":
            raise AuthorizationError("Insufficient permissions")
        return principal

    return Depends(role_checker)


def pagination(page: int = Query(1, ge=1, le=1_000_000), per_page: int = Query(50, ge=1, le=500)) -> PageParams:
    return PageParams(page=page, per_page=per_page)


Pagination = Annotated[PageParams, Depends(pagination)]


def client_context(request: Request) -> dict[str, str | None]:
    from app.middleware.request_id import client_ip

    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent")}
