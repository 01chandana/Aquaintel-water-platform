"""FastAPI application factory and entrypoint (Ch. 4.2.1, 9.x).

Start-up wires the infrastructure with graceful degradation (design principle 4):

* PostgreSQL/TimescaleDB is mandatory (readiness fails without it).
* Redis -> in-memory cache fallback.
* Kafka -> in-process event bus fallback; the stream processor is then subscribed
  in-process so ingestion -> rules -> alerts -> WebSocket still works end to end.
* Celery -> ``task_mode=inline`` runs jobs and an asyncio beat schedule in-process.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1.router import api_router
from app.api.v1.websocket import manager
from app.api.v1.websocket import router as ws_router
from app.core.cache import init_cache
from app.core.config import get_settings
from app.core.events import TELEMETRY_RAW, MemoryEventBus, get_event_bus, init_event_bus
from app.core.logging import configure_logging, get_logger
from app.core.metrics import refresh_resource_gauges
from app.core.responses import register_exception_handlers
from app.db import session as db_session
from app.middleware.cors import add_cors
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.timing import BodySizeLimitMiddleware, TimingMiddleware

log = get_logger(__name__)

OPENAPI_TAGS = [
    {"name": "Authentication", "description": "JWT login, refresh rotation, MFA (Table 7.1)"},
    {"name": "Users", "description": "User management and RBAC (Table 7.2)"},
    {"name": "Assets", "description": "Asset registry & hierarchy / digital twin (Table 7.3)"},
    {"name": "Telemetry", "description": "Ingestion and time-series queries (Table 7.4)"},
    {"name": "Alerts", "description": "Rules engine and alert lifecycle (Table 7.5)"},
    {"name": "KPIs & Analytics", "description": "30-KPI catalogue and analytics (Table 7.6)"},
    {"name": "Dashboards", "description": "Self-service dashboard builder (Table 7.7)"},
    {"name": "Reports & Compliance", "description": "PDF/Excel/HTML reports and compliance (Table 7.8)"},
    {"name": "Work Orders", "description": "Maintenance work orders (Table 7.9)"},
    {"name": "Machine Learning", "description": "Model registry, inference and drift (Table 7.10)"},
    {"name": "Optimization", "description": "Pump scheduling and dosing optimisation"},
    {"name": "Admin", "description": "System administration (Table 7.11)"},
    {"name": "Health", "description": "Liveness/readiness probes (Ch. 19.5)"},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level, json_output=s.environment != "test")
    if s.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=s.sentry_dsn, environment=s.environment, traces_sample_rate=0.1)
    db_session.init_engine()
    await db_session.detect_timescale()
    await init_cache(s.redis_url)
    bus = init_event_bus(s.event_bus, s.kafka_bootstrap_servers)
    if isinstance(bus, MemoryEventBus):
        from app.services.telemetry_service import TelemetryPipeline

        bus.subscribe(TELEMETRY_RAW, TelemetryPipeline().handle_event)  # in-process stream processor
    manager.start()
    stop = asyncio.Event()
    scheduler = None
    if s.task_mode == "inline" and s.environment != "test":
        from app.workers.dispatch import run_scheduler

        scheduler = asyncio.create_task(run_scheduler(stop))
    log.info("startup_complete", environment=s.environment, timescaledb=db_session.timescale_enabled,
             event_bus=bus.name, task_mode=s.task_mode)
    try:
        yield
    finally:
        stop.set()
        if scheduler:
            scheduler.cancel()
        await manager.stop()
        await get_event_bus().close()
        from app.core.cache import get_cache

        await get_cache().close()
        await db_session.dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=s.app_name,
        version=s.version,
        description="AquaIntel Operations Platform - enterprise water infrastructure intelligence & analytics. "
                    "All responses use the standard envelope `{status, data, meta, request_id}` (Ch. 7.2.3).",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    # Middleware executes bottom-up: request-id first so every log line carries it.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=s.max_request_body_mb * 1024 * 1024)
    add_cors(app, s)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    app.include_router(api_router, prefix=s.api_prefix)
    from app.api.v1.admin import health_router

    app.include_router(health_router)  # also at the root for k8s probes (/health, /health/ready, /health/live)
    app.include_router(ws_router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        await refresh_resource_gauges()
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get(f"{s.api_prefix}/docs/changelog", tags=["Health"], summary="API changelog (Ch. 7.14)")
    async def changelog() -> dict:
        return {"versions": [{"version": "v1", "status": "current", "released": "2026-07-26",
                              "notes": "Initial release: 95 endpoints across 12 domains"}]}

    return app


app = create_app()
