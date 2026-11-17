"""Optimization Service endpoints (Ch. 3.3.3, Use Cases 15 & 18, roadmap week 12)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import DB, Pagination, Principal, require_permission
from app.core.responses import ok, paginated
from app.models.system import Schedule
from app.repositories.system_repository import ScheduleRepository
from app.schemas.optimization import DosingRequest, PumpScheduleRequest, ScheduleOutModel
from app.services.optimization_service import OptimizationService

router = APIRouter(prefix="/optimization", tags=["Optimization"])
RUN = require_permission("optimization:run")


@router.post("/pump-schedule", status_code=201, summary="Optimize pump schedule (MILP, 24-48 h)")
async def pump_schedule(body: PumpScheduleRequest, db: DB, principal: Principal = RUN) -> dict:
    return ok(ScheduleOutModel.model_validate(await OptimizationService(db).pump_schedule(body, principal)))


@router.post("/dosing", status_code=201, summary="Recommend chemical dosing setpoints")
async def dosing(body: DosingRequest, db: DB, principal: Principal = RUN) -> dict:
    return ok(ScheduleOutModel.model_validate(await OptimizationService(db).dosing(body, principal)))


@router.get("/schedules", dependencies=[require_permission("kpis:read")], summary="List optimization plans")
async def schedules(db: DB, p: Pagination, schedule_type: str | None = None) -> dict:
    f = [Schedule.schedule_type == schedule_type] if schedule_type else []
    items, total = await ScheduleRepository(db).list(*f, page=p.page, per_page=p.per_page)
    return paginated([ScheduleOutModel.model_validate(s) for s in items], p.page, p.per_page, total)


@router.post("/schedules/{schedule_id}/approve", summary="Approve a proposed plan")
async def approve(schedule_id: uuid.UUID, db: DB, principal: Principal = RUN) -> dict:
    return ok(ScheduleOutModel.model_validate(await OptimizationService(db).approve(schedule_id, principal)))
