"""Main v1 router aggregating all sub-routers (Listing 9.1)."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    alerts,
    assets,
    auth,
    dashboards,
    kpis,
    ml,
    optimization,
    reports,
    telemetry,
    users,
    work_orders,
)

api_router = APIRouter()
for module in (auth, users, assets, telemetry, alerts, kpis, dashboards, reports, work_orders, ml, optimization, admin):
    api_router.include_router(module.router)
api_router.include_router(admin.health_router)
