"""KPI & analytics endpoints #48-54 (Table 7.6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query

from app.api.deps import DB, Principal, require_permission
from app.core.responses import ok
from app.schemas.kpi import KPICreate, KPIOut
from app.services.kpi_service import DASHBOARD_SETS, KPIService
from app.workers.dispatch import dispatch

router = APIRouter(prefix="/kpis", tags=["KPIs & Analytics"])
READ = require_permission("kpis:read")


@router.get("", dependencies=[READ], summary="#48 List KPI definitions")
async def list_kpis(db: DB, category: str | None = None, q: str | None = None) -> dict:
    return ok([KPIOut.model_validate(k) for k in await KPIService(db).list(category, q)])


@router.post("", status_code=201, summary="#49 Create KPI definition",
             description="Custom KPIs aggregate one telemetry parameter, e.g. formula `avg(ph)` or "
                         "`source_parameter: ph` + `aggregation_type: avg`.")
async def create_kpi(body: KPICreate, db: DB, principal: Principal = require_permission("kpis:write")) -> dict:
    return ok(KPIOut.model_validate(await KPIService(db).create(body, principal)))


@router.get("/dashboard", dependencies=[READ], summary="#53 Get dashboard KPIs")
async def dashboard_kpis(db: DB, site_id: uuid.UUID | None = None,
                         view: str = Query("executive", pattern=f"^({'|'.join(DASHBOARD_SETS)})$")) -> dict:
    return ok(await KPIService(db).dashboard(view, site_id))


@router.get("/categories", dependencies=[READ], summary="#54 List KPI categories")
async def categories() -> dict:
    return ok(KPIService.categories())


@router.get("/health-heatmap", dependencies=[READ], summary="Equipment Health Score heat map data (KPI 22)")
async def health_heatmap(db: DB) -> dict:
    return ok(await KPIService(db).health_heatmap())


@router.post("/compute", summary="Trigger on-demand KPI computation (KPI engine)")
async def compute(codes: list[str] | None = Query(None),
                  principal: Principal = require_permission("kpis:write")) -> dict:
    task_id = await dispatch("compute_kpis", codes)
    return ok({"task_id": task_id, "requested_by": principal.name})


@router.get("/{kpi_id}", dependencies=[READ], summary="#50 Get KPI definition")
async def get_kpi(kpi_id: uuid.UUID, db: DB) -> dict:
    return ok(KPIOut.model_validate(await KPIService(db).repo.get_or_404(kpi_id, "KPI")))


@router.get("/{kpi_id}/values", dependencies=[READ], summary="#51 Get KPI time-series")
async def kpi_values(kpi_id: uuid.UUID, db: DB, start: datetime | None = None, end: datetime | None = None,
                     asset_id: uuid.UUID | None = None, bucket: Literal["hour", "day"] | None = None) -> dict:
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=7)
    rows = await KPIService(db).values(kpi_id, start, end, asset_id, bucket)
    return ok(rows, {"count": len(rows), "start": start.isoformat(), "end": end.isoformat()})


@router.get("/{kpi_id}/current", dependencies=[READ], summary="#52 Get current KPI value")
async def kpi_current(kpi_id: uuid.UUID, db: DB, asset_id: uuid.UUID | None = None) -> dict:
    return ok(await KPIService(db).current(kpi_id, asset_id))
