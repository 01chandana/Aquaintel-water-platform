"""Admin & system endpoints #86-95 (Table 7.11) plus API-key management (Ch. 17.2.3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse

from app.api.deps import DB, Pagination, Principal, require_permission
from app.core.responses import ok, paginated
from app.repositories.user_repository import ApiKeyRepository
from app.schemas.admin import ConfigUpdate
from app.schemas.user import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services.admin_service import AdminService, health
from app.services.audit_service import AuditService
from app.services.user_service import UserService

health_router = APIRouter(tags=["Health"])
router = APIRouter(prefix="/admin", tags=["Admin"])
ADMIN = require_permission("admin:read")


# ---- health (Ch. 19.5.1) — no authentication -------------------------------------------
@health_router.get("/health", summary="#86 Basic health check")
async def basic_health() -> dict:
    return await health(None, deep=False)


@health_router.get("/health/ready", summary="#87 Readiness probe (dependencies)")
async def ready() -> JSONResponse:
    body = await health(None, deep=True)
    return JSONResponse(body, status_code=503 if body["status"] == "unhealthy" else 200)


@health_router.get("/health/live", summary="#88 Liveness probe")
async def live() -> dict:
    return {"status": "healthy"}


# ---- admin -------------------------------------------------------------------------------
@router.get("/metrics", dependencies=[ADMIN], summary="#89 System metrics")
async def metrics(db: DB) -> dict:
    return ok(await AdminService(db).metrics())


@router.get("/logs", dependencies=[ADMIN], summary="#90 Recent system logs")
async def logs(level: str | None = None, q: str | None = None, limit: int = Query(200, ge=1, le=500)) -> dict:
    return ok(AdminService.logs(level, limit, q))


@router.get("/audit-log", dependencies=[require_permission("audit:read")], summary="#91 Query audit log")
async def audit_log(db: DB, p: Pagination, user_id: uuid.UUID | None = None, entity_type: str | None = None,
                    action: str | None = None, start: datetime | None = None, end: datetime | None = None) -> dict:
    rows, total = await AdminService(db).audit_log(p.page, p.per_page, user_id, entity_type, action, start, end)
    items = [{"id": r.id, "created_at": r.created_at.isoformat(), "actor": r.actor, "user_id": str(r.user_id) if r.user_id else None,
              "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
              "source_ip": str(r.source_ip) if r.source_ip else None, "details": r.details, "hash": r.hash,
              "prev_hash": r.prev_hash} for r in rows]
    return paginated(items, p.page, p.per_page, total)


@router.get("/audit-log/verify", dependencies=[require_permission("audit:read")],
            summary="Verify the tamper-evident hash chain (Ch. 17.7)")
async def verify_audit(db: DB) -> dict:
    return ok(await AuditService(db).verify_chain())


@router.get("/queue-status", dependencies=[ADMIN], summary="#92 Task queue status")
async def queue_status(db: DB) -> dict:
    return ok(await AdminService(db).queue_status())


@router.get("/system-config", dependencies=[require_permission("system:config")], summary="#93 System configuration")
async def get_config(db: DB) -> dict:
    return ok(await AdminService(db).get_config())


@router.put("/system-config", summary="#94 Update configuration")
async def put_config(body: ConfigUpdate, db: DB, principal: Principal = require_permission("system:config")) -> dict:
    return ok(await AdminService(db).update_config(body.values, principal))


@router.get("/usage-stats", dependencies=[ADMIN], summary="#95 System usage statistics")
async def usage(db: DB) -> dict:
    return ok(await AdminService(db).usage_stats())


@router.get("/api-keys", dependencies=[require_permission("api_keys:manage")], summary="List integration API keys")
async def list_keys(db: DB, p: Pagination) -> dict:
    items, total = await ApiKeyRepository(db).list(page=p.page, per_page=p.per_page)
    return paginated([ApiKeyOut.model_validate(k) for k in items], p.page, p.per_page, total)


@router.post("/api-keys", status_code=201, summary="Create API key (plaintext shown once)")
async def create_key(body: ApiKeyCreate, db: DB, principal: Principal = require_permission("api_keys:manage")) -> dict:
    key, raw = await UserService(db).create_api_key(body, principal)
    return ok(ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), api_key=raw))


@router.delete("/api-keys/{key_id}", status_code=204, summary="Revoke API key")
async def revoke_key(key_id: uuid.UUID, db: DB, principal: Principal = require_permission("api_keys:manage")) -> Response:
    await UserService(db).revoke_api_key(key_id, principal)
    return Response(status_code=204)
