"""Admin & system operations (Table 7.11) and the health contract (Ch. 19.5.1)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from prometheus_client import REGISTRY
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.events import get_event_bus
from app.core.logging import RECENT_LOGS
from app.core.resilience import breaker_states
from app.core.storage import get_store
from app.db import session as db_session
from app.models.alert import Alert
from app.models.asset import Asset
from app.models.audit import AuditLog
from app.models.enums import OPEN_ALERT_STATUSES
from app.models.ml_model import MLModel
from app.models.report import Report
from app.models.system import SystemConfig
from app.models.user import User
from app.services.audit_service import AuditService

STARTED_AT = time.time()

# Settings that may be changed at runtime through PUT /admin/system-config
EDITABLE_CONFIG = {
    "energy.tariff": "Time-of-use tariff: peak hours and $/kWh rates",
    "energy.contracted_demand_kw": "Contracted electrical demand (kW) for KPI 15",
    "energy.grid_emission_factor_kg_per_kwh": "Scope 2 emission factor (Use Case 20)",
    "chemicals.prices_per_kg": "Chemical unit prices for KPIs 29-30",
    "production.daily_target_m3": "Daily production target for KPI 2",
    "alerts.silent_hours": "Quiet period for non-critical external notifications {start_hour, end_hour}",
    "alerts.flood_limit_per_asset_hour": "Flood-control cap (Ch. 13.7)",
    "features.ml_inference_enabled": "Feature flag: graceful degradation switch for ML scoring",
    "features.optimization_enabled": "Feature flag for the optimization engine",
}


async def health(session: AsyncSession | None, deep: bool) -> dict[str, Any]:
    s = get_settings()
    checks: dict[str, Any] = {}
    status = "healthy"
    if deep:
        start = time.perf_counter()
        try:
            async with db_session.get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = {"status": "healthy", "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                                  "timescaledb": db_session.timescale_enabled}
        except Exception as exc:  # noqa: BLE001
            checks["database"] = {"status": "unhealthy", "error": str(exc)[:200]}
            status = "unhealthy"
        cache = get_cache()
        try:
            checks["redis"] = {"status": "healthy" if cache.name == "redis" else "degraded", "backend": cache.name,
                               "latency_ms": round(await cache.ping(), 2)}
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = {"status": "unhealthy", "error": str(exc)[:200]}
        checks["kafka"] = await get_event_bus().health()
        checks["minio"] = await get_store().health()
        if status == "healthy" and any(c.get("status") in ("degraded", "unhealthy") for c in checks.values()):
            status = "degraded"
    return {"status": status, "version": s.version, "environment": s.environment,
            "uptime_seconds": int(time.time() - STARTED_AT), "checks": checks}


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def metrics(self) -> dict[str, Any]:
        wanted = {"http_requests_total", "telemetry_ingestion_rate", "alert_generation_rate", "alert_suppressed_total",
                  "ml_predictions_total", "notifications_sent_total", "events_published_total", "websocket_connections",
                  "telemetry_rejected_total"}
        out: dict[str, Any] = {}
        for metric in REGISTRY.collect():
            if metric.name in wanted or metric.name.removesuffix("_total") in {w.removesuffix("_total") for w in wanted}:
                total = sum(s.value for s in metric.samples if s.name.endswith(("_total", "")) and not s.name.endswith("_created"))
                out[metric.name] = round(total, 2)
        pool = db_session.get_engine().pool
        out["db_pool"] = {"size": getattr(pool, "size", lambda: None)(), "checked_out": getattr(pool, "checkedout", lambda: None)()}
        out["cache"] = await get_cache().info()
        out["event_bus"] = get_event_bus().name
        out["circuit_breakers"] = breaker_states()
        return out

    @staticmethod
    def logs(level: str | None, limit: int, q: str | None) -> list[dict[str, Any]]:
        items = list(RECENT_LOGS)[::-1]
        if level:
            items = [i for i in items if str(i.get("level", "")).upper() == level.upper()]
        if q:
            items = [i for i in items if q.lower() in str(i).lower()]
        return items[:limit]

    async def audit_log(self, page: int, per_page: int, user_id: Any, entity_type: str | None, action: str | None,
                        start: datetime | None, end: datetime | None) -> tuple[list[AuditLog], int]:
        stmt = select(AuditLog)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if entity_type:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if action:
            stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
        if start:
            stmt = stmt.where(AuditLog.created_at >= start)
        if end:
            stmt = stmt.where(AuditLog.created_at <= end)
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.session.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * per_page).limit(per_page))).scalars()
        return list(rows), total

    async def queue_status(self) -> dict[str, Any]:
        s = get_settings()
        if s.task_mode == "inline":
            from app.workers.dispatch import INLINE_STATS

            return {"mode": "inline", "workers": 0, "stats": dict(INLINE_STATS)}
        from app.workers.celery_app import celery_app

        def _inspect() -> dict[str, Any]:
            insp = celery_app.control.inspect(timeout=1.5)
            active, scheduled, reserved = insp.active() or {}, insp.scheduled() or {}, insp.reserved() or {}
            return {"mode": "celery", "workers": len(active), "active": {k: len(v) for k, v in active.items()},
                    "scheduled": {k: len(v) for k, v in scheduled.items()}, "reserved": {k: len(v) for k, v in reserved.items()}}

        import asyncio

        try:
            data = await asyncio.wait_for(asyncio.to_thread(_inspect), timeout=3)
        except Exception as exc:  # noqa: BLE001
            data = {"mode": "celery", "workers": 0, "error": str(exc)}
        try:
            import redis

            r = redis.Redis.from_url(s.celery_broker_url)
            data["queue_depth"] = {q: r.llen(q) for q in ("celery", "kpi", "alerts", "reports", "ml")}
        except Exception as exc:  # noqa: BLE001 - broker unreachable: report it rather than fail the page
            data["queue_depth_error"] = str(exc)
        return data

    async def get_config(self) -> list[dict[str, Any]]:
        stored = {r.key: r for r in (await self.session.execute(select(SystemConfig))).scalars()}
        from app.services.kpi_engine import DEFAULT_CONFIG

        out = []
        for key, desc in EDITABLE_CONFIG.items():
            row = stored.get(key)
            out.append({"key": key, "value": row.value if row else DEFAULT_CONFIG.get(key), "description": desc,
                        "updated_at": row.updated_at.isoformat() if row else None})
        s = get_settings()
        out.append({"key": "runtime", "readonly": True, "description": "Environment-sourced settings (12-factor)",
                    "value": {"environment": s.environment, "event_bus": get_event_bus().name, "cache": get_cache().name,
                              "task_mode": s.task_mode, "timescaledb": db_session.timescale_enabled,
                              "jwt_expiry_minutes": s.jwt_expiry_minutes, "rate_limit_enabled": s.rate_limit_enabled,
                              "object_store": get_store().backend, "mlflow": bool(s.mlflow_tracking_uri)}})
        return out

    async def update_config(self, values: dict[str, Any], principal: Principal) -> list[dict[str, Any]]:
        from app.core.exceptions import ValidationError

        unknown = set(values) - set(EDITABLE_CONFIG)
        if unknown:
            raise ValidationError(f"Unknown or read-only config keys: {sorted(unknown)}")
        for key, value in values.items():
            row = await self.session.get(SystemConfig, key)
            if row is None:
                self.session.add(SystemConfig(key=key, value=value, description=EDITABLE_CONFIG[key], updated_by=principal.user_id))
            else:
                row.value, row.updated_by = value, principal.user_id
        await AuditService(self.session).record("system.config_update", "system_config", ",".join(values),
                                                principal=principal, details=values)
        await self.session.commit()
        await get_cache().delete_pattern("kpi:*")
        return await self.get_config()

    async def usage_stats(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        day = now - timedelta(days=1)
        q = lambda stmt: self.session.execute(stmt)  # noqa: E731
        users = (await q(select(func.count()).select_from(User))).scalar_one()
        active_users = (await q(select(func.count()).select_from(User).where(User.last_login >= now - timedelta(days=7)))).scalar_one()
        points = (await self.session.execute(text("SELECT count(*) FROM telemetry_data WHERE time >= :d"),
                                             {"d": day})).scalar_one()
        return {
            "users": {"total": users, "active_7d": active_users,
                      "active_sessions": await get_cache().count_keys("refresh:*")},
            "assets": (await q(select(func.count()).select_from(Asset))).scalar_one(),
            "telemetry_points_24h": points,
            "alerts": {"open": (await q(select(func.count()).select_from(Alert).where(Alert.status.in_(OPEN_ALERT_STATUSES)))).scalar_one(),
                       "last_24h": (await q(select(func.count()).select_from(Alert).where(Alert.created_at >= day))).scalar_one()},
            "reports_generated_30d": (await q(select(func.count()).select_from(Report).where(
                Report.created_at >= now - timedelta(days=30)))).scalar_one(),
            "models_in_production": (await q(select(func.count()).select_from(MLModel).where(MLModel.stage == "production"))).scalar_one(),
            "api_calls_by_endpoint": _top_endpoints(),
        }


def _top_endpoints(n: int = 10) -> list[dict[str, Any]]:
    counts: dict[str, float] = {}
    for metric in REGISTRY.collect():
        if metric.name == "http_requests":
            for s in metric.samples:
                if s.name == "http_requests_total":
                    key = f"{s.labels['method']} {s.labels['endpoint']}"
                    counts[key] = counts.get(key, 0) + s.value
    return [{"endpoint": k, "calls": int(v)} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:n]]
