"""Dashboard endpoints #55-63 (Table 7.7)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import DB, CurrentPrincipal, Principal, require_permission
from app.core.responses import ok
from app.schemas.dashboard import DashboardIn, DashboardOut, DashboardUpdate, WidgetIn, WidgetOut
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboards", tags=["Dashboards"])
WRITE = require_permission("dashboards:write")


@router.get("", summary="#55 List user dashboards")
async def list_dashboards(db: DB, principal: CurrentPrincipal) -> dict:
    return ok([DashboardOut.model_validate(d) for d in await DashboardService(db).list(principal)])


@router.post("", status_code=201, summary="#56 Create dashboard")
async def create_dashboard(body: DashboardIn, db: DB, principal: Principal = WRITE) -> dict:
    return ok(DashboardOut.model_validate(await DashboardService(db).create(body, principal)))


@router.get("/templates", summary="#63 List dashboard templates")
async def templates(db: DB, principal: CurrentPrincipal) -> dict:
    return ok([DashboardOut.model_validate(d) for d in await DashboardService(db).templates()])


@router.get("/{dashboard_id}", summary="#57 Get dashboard config")
async def get_dashboard(dashboard_id: uuid.UUID, db: DB, principal: CurrentPrincipal) -> dict:
    return ok(await DashboardService(db).get(dashboard_id, principal))


@router.put("/{dashboard_id}", summary="#58 Update dashboard (owner)")
async def update_dashboard(dashboard_id: uuid.UUID, body: DashboardUpdate, db: DB, principal: Principal = WRITE) -> dict:
    return ok(DashboardOut.model_validate(await DashboardService(db).update(dashboard_id, body, principal)))


@router.delete("/{dashboard_id}", status_code=204, summary="#59 Delete dashboard (owner)")
async def delete_dashboard(dashboard_id: uuid.UUID, db: DB, principal: Principal = WRITE) -> Response:
    await DashboardService(db).delete(dashboard_id, principal)
    return Response(status_code=204)


@router.post("/{dashboard_id}/widgets", status_code=201, summary="#60 Add widget")
async def add_widget(dashboard_id: uuid.UUID, body: WidgetIn, db: DB, principal: Principal = WRITE) -> dict:
    return ok(WidgetOut.model_validate(await DashboardService(db).add_widget(dashboard_id, body, principal)))


@router.put("/{dashboard_id}/widgets/{widget_id}", summary="#61 Update widget")
async def update_widget(dashboard_id: uuid.UUID, widget_id: uuid.UUID, body: WidgetIn, db: DB,
                        principal: Principal = WRITE) -> dict:
    return ok(WidgetOut.model_validate(await DashboardService(db).update_widget(dashboard_id, widget_id, body, principal)))


@router.delete("/{dashboard_id}/widgets/{widget_id}", status_code=204, summary="#62 Remove widget")
async def delete_widget(dashboard_id: uuid.UUID, widget_id: uuid.UUID, db: DB, principal: Principal = WRITE) -> Response:
    await DashboardService(db).delete_widget(dashboard_id, widget_id, principal)
    return Response(status_code=204)
