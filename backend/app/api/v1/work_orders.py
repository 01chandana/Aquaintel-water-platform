"""Work order endpoints #73-78 (Table 7.9)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import DB, Pagination, Principal, require_permission
from app.api.v1.serializers import wo_out
from app.core.responses import ok, paginated
from app.repositories.work_order_repository import WorkOrderRepository
from app.schemas.work_order import WorkOrderAssign, WorkOrderComplete, WorkOrderCreate, WorkOrderUpdate
from app.services.work_order_service import WorkOrderService

router = APIRouter(prefix="/work-orders", tags=["Work Orders"])
READ = require_permission("work_orders:read")
WRITE = require_permission("work_orders:write")


@router.get("", dependencies=[READ], summary="#73 List work orders")
async def list_work_orders(db: DB, p: Pagination, status: str | None = None, asset_id: uuid.UUID | None = None,
                           assigned_to: uuid.UUID | None = None, wo_type: str | None = None,
                           sort: str | None = "-created_at") -> dict:
    items, total = await WorkOrderService(db).list(p.page, p.per_page, status, asset_id, assigned_to, wo_type, sort)
    return paginated([wo_out(w) for w in items], p.page, p.per_page, total)


@router.post("", status_code=201, summary="#74 Create work order")
async def create(body: WorkOrderCreate, db: DB, principal: Principal = WRITE) -> dict:
    return ok(wo_out(await WorkOrderService(db).create(body, principal)))


@router.get("/{wo_id}", dependencies=[READ], summary="#75 Get work order")
async def get(wo_id: uuid.UUID, db: DB) -> dict:
    return ok(wo_out(await WorkOrderRepository(db).get_or_404(wo_id, "Work order")))


@router.put("/{wo_id}", summary="#76 Update work order")
async def update(wo_id: uuid.UUID, body: WorkOrderUpdate, db: DB, principal: Principal = WRITE) -> dict:
    return ok(wo_out(await WorkOrderService(db).update(wo_id, body, principal)))


@router.post("/{wo_id}/assign", summary="#77 Assign technician")
async def assign(wo_id: uuid.UUID, body: WorkOrderAssign, db: DB,
                 principal: Principal = require_permission("work_orders:assign")) -> dict:
    return ok(wo_out(await WorkOrderService(db).assign(wo_id, body, principal)))


@router.post("/{wo_id}/complete", summary="#78 Mark complete")
async def complete(wo_id: uuid.UUID, body: WorkOrderComplete, db: DB,
                   principal: Principal = require_permission("work_orders:complete")) -> dict:
    return ok(wo_out(await WorkOrderService(db).complete(wo_id, body, principal)))
