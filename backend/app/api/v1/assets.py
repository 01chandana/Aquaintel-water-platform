"""Asset management endpoints #17-30 (Table 7.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query, Response

from app.api.deps import DB, Pagination, Principal, require_permission
from app.api.v1.serializers import alert_out, wo_out
from app.core.responses import ok, paginated
from app.models.alert import Alert
from app.models.work_order import WorkOrder
from app.repositories.alert_repository import AlertRepository
from app.repositories.telemetry_repository import TagRepository, TelemetryRepository
from app.repositories.work_order_repository import WorkOrderRepository
from app.schemas.asset import AssetCreate, AssetOut, AssetTypeCreate, AssetTypeOut, AssetUpdate
from app.schemas.telemetry import TagOut
from app.services.asset_service import AssetService
from app.services.kpi_service import KPIService
from app.services.telemetry_service import TelemetryService, parse_interval

router = APIRouter(prefix="/assets", tags=["Assets"])
READ = require_permission("assets:read")
WRITE = require_permission("assets:write")


@router.get("", summary="#17 List assets (hierarchical)")
async def list_assets(db: DB, p: Pagination, principal: Principal = READ, view: Literal["flat", "tree"] = "flat",
                      status: str | None = None, type_id: uuid.UUID | None = None,
                      parent_id: uuid.UUID | None = None, sort: str | None = None) -> dict:
    svc = AssetService(db)
    if view == "tree":
        return ok(await svc.tree(principal))
    items, total = await svc.list(principal, p.page, p.per_page, status, type_id, parent_id, sort)
    return paginated([AssetOut.model_validate(a) for a in items], p.page, p.per_page, total)


@router.post("", status_code=201, summary="#18 Register new asset")
async def create_asset(body: AssetCreate, db: DB, principal: Principal = WRITE) -> dict:
    return ok(AssetOut.model_validate(await AssetService(db).create(body, principal)))


# static sub-paths before /{asset_id}
@router.get("/types", dependencies=[READ], summary="#28 List asset types")
async def list_types(db: DB) -> dict:
    return ok([AssetTypeOut.model_validate(t) for t in await AssetService(db).types.all()])


@router.post("/types", status_code=201, summary="#29 Create asset type")
async def create_type(body: AssetTypeCreate, db: DB, principal: Principal = WRITE) -> dict:
    return ok(AssetTypeOut.model_validate(await AssetService(db).create_type(body, principal)))


@router.get("/search", summary="#30 Search assets")
async def search(db: DB, principal: Principal = READ, q: str = Query(min_length=1, max_length=100)) -> dict:
    return ok([AssetOut.model_validate(a) for a in await AssetService(db).search(q, principal)])


@router.get("/{asset_id}", summary="#19 Get asset with metadata")
async def get_asset(asset_id: uuid.UUID, db: DB, principal: Principal = READ) -> dict:
    asset = await AssetService(db).get(asset_id, principal)
    tags = await TagRepository(db).for_asset(asset.id)
    return ok({**AssetOut.model_validate(asset).model_dump(mode="json"),
               "tags": [TagOut.model_validate(t).model_dump(mode="json") for t in tags]})


@router.put("/{asset_id}", summary="#20 Update asset")
async def update_asset(asset_id: uuid.UUID, body: AssetUpdate, db: DB, principal: Principal = WRITE) -> dict:
    return ok(AssetOut.model_validate(await AssetService(db).update(asset_id, body, principal)))


@router.delete("/{asset_id}", status_code=204, summary="#21 Remove asset")
async def delete_asset(asset_id: uuid.UUID, db: DB, principal: Principal = require_permission("assets:delete")) -> Response:
    await AssetService(db).delete(asset_id, principal)
    return Response(status_code=204)


@router.get("/{asset_id}/children", summary="#22 Get child assets")
async def children(asset_id: uuid.UUID, db: DB, principal: Principal = READ) -> dict:
    return ok([AssetOut.model_validate(a) for a in await AssetService(db).children(asset_id, principal)])


@router.get("/{asset_id}/telemetry", summary="#23 Get asset telemetry")
async def asset_telemetry(asset_id: uuid.UUID, db: DB, principal: Principal = require_permission("telemetry:read"),
                          start: datetime | None = None, end: datetime | None = None,
                          interval: str | None = Query(None, description="e.g. 15m, 1h; omit for raw"),
                          parameter: str | None = None) -> dict:
    asset = await AssetService(db).get(asset_id, principal)
    end = end or datetime.now(UTC)
    start = start or end - timedelta(hours=24)
    tags = [t for t in await TagRepository(db).for_asset(asset.id) if not parameter or t.parameter == parameter]
    repo = TelemetryRepository(db)
    ids = [t.id for t in tags]
    rows = await (repo.aggregate(ids, start, end, parse_interval(interval)) if interval else repo.query(ids, start, end))
    return ok({"asset_id": str(asset.id), "tags": [TagOut.model_validate(t).model_dump(mode="json") for t in tags],
               "points": rows}, {"start": start.isoformat(), "end": end.isoformat(), "count": len(rows)})


@router.get("/{asset_id}/telemetry/latest", summary="#24 Get latest values")
async def asset_latest(asset_id: uuid.UUID, db: DB, principal: Principal = require_permission("telemetry:read")) -> dict:
    asset = await AssetService(db).get(asset_id, principal)
    tags = await TagRepository(db).for_asset(asset.id)
    return ok(await TelemetryService(db).latest([t.id for t in tags]))


@router.get("/{asset_id}/kpis", summary="#25 Get asset KPIs")
async def asset_kpis(asset_id: uuid.UUID, db: DB, principal: Principal = require_permission("kpis:read")) -> dict:
    await AssetService(db).get(asset_id, principal)
    return ok(await KPIService(db).asset_kpis(asset_id))


@router.get("/{asset_id}/alerts", summary="#26 Get asset alerts")
async def asset_alerts(asset_id: uuid.UUID, db: DB, p: Pagination, principal: Principal = require_permission("alerts:read")) -> dict:
    asset = await AssetService(db).get(asset_id, principal)
    from app.repositories.asset_repository import AssetRepository

    ids = [a.id for a in await AssetRepository(db).subtree(asset.path)]
    items, total = await AlertRepository(db).list(Alert.asset_id.in_(ids), page=p.page, per_page=p.per_page)
    return paginated([alert_out(a) for a in items], p.page, p.per_page, total)


@router.get("/{asset_id}/work-orders", summary="#27 Get work orders")
async def asset_work_orders(asset_id: uuid.UUID, db: DB, p: Pagination, principal: Principal = require_permission("work_orders:read")) -> dict:
    await AssetService(db).get(asset_id, principal)
    items, total = await WorkOrderRepository(db).list(WorkOrder.asset_id == asset_id, page=p.page, per_page=p.per_page)
    return paginated([wo_out(w) for w in items], p.page, p.per_page, total)
