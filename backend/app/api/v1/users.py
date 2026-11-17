"""User management endpoints #8-16 (Table 7.2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from app.api.deps import DB, CurrentUser, Pagination, Principal, require_permission
from app.core.responses import ok, paginated
from app.repositories.user_repository import UserRepository
from app.schemas.user import PermissionsOut, RoleAssign, SelfUpdate, UserCreate, UserOut, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])
ADMIN = require_permission("users:manage")


# /users/me must be declared before /users/{id}
@router.get("/me", summary="#15 Get current user profile")
async def me(principal: CurrentUser) -> dict:
    return ok({**UserOut.model_validate(principal.user).model_dump(mode="json"),
               "permissions": sorted(principal.permissions)})


@router.put("/me", summary="#16 Update own profile")
async def update_me(body: SelfUpdate, principal: CurrentUser, db: DB) -> dict:
    return ok(UserOut.model_validate(await UserService(db).update_self(principal, body)))


@router.get("", dependencies=[ADMIN], summary="#8 List users (paginated)")
async def list_users(db: DB, p: Pagination, q: str | None = None, role: str | None = None,
                     active: bool | None = Query(None)) -> dict:
    users, total = await UserService(db).list(p.page, p.per_page, q, role, active)
    return paginated([UserOut.model_validate(u) for u in users], p.page, p.per_page, total)


@router.post("", status_code=201, summary="#9 Create new user")
async def create_user(body: UserCreate, db: DB, principal: Principal = ADMIN) -> dict:
    return ok(UserOut.model_validate(await UserService(db).create(body, principal)))


@router.get("/{user_id}", dependencies=[ADMIN], summary="#10 Get user details")
async def get_user(user_id: uuid.UUID, db: DB) -> dict:
    return ok(UserOut.model_validate(await UserRepository(db).get_or_404(user_id, "User")))


@router.put("/{user_id}", summary="#11 Update user")
async def update_user(user_id: uuid.UUID, body: UserUpdate, db: DB, principal: Principal = ADMIN) -> dict:
    return ok(UserOut.model_validate(await UserService(db).update(user_id, body, principal)))


@router.delete("/{user_id}", status_code=204, summary="#12 Deactivate user")
async def delete_user(user_id: uuid.UUID, db: DB, principal: Principal = ADMIN) -> Response:
    await UserService(db).deactivate(user_id, principal)
    return Response(status_code=204)


@router.get("/{user_id}/permissions", dependencies=[ADMIN], summary="#13 Get user permissions")
async def user_permissions(user_id: uuid.UUID, db: DB) -> dict:
    u = await UserRepository(db).get_or_404(user_id, "User")
    return ok(PermissionsOut(user_id=u.id, role=u.role.name, permissions=sorted(u.role.permissions),
                             asset_scopes=list(u.asset_scopes or [])))


@router.put("/{user_id}/role", summary="#14 Assign role")
async def assign_role(user_id: uuid.UUID, body: RoleAssign, db: DB, principal: Principal = ADMIN) -> dict:
    return ok(UserOut.model_validate(await UserService(db).assign_role(user_id, body.role, principal)))
