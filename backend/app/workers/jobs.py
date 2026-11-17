"""Async job bodies shared by Celery tasks and the in-process scheduler.

Keeping the business logic here (and not inside Celery decorators) means the exact same
code runs under ``task_mode=celery`` in Kubernetes and ``task_mode=inline`` on a laptop.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text

from app.core.cache import get_cache
from app.core.logging import get_logger
from app.db.session import get_engine, session_scope

log = get_logger(__name__)


async def compute_kpis(codes: list[str] | None = None) -> int:
    from app.services.kpi_engine import KPIEngine

    # one KPI run at a time across workers: the hourly beat job and a manual "Recompute" can overlap
    async with get_cache().lock("kpi-compute", ttl_seconds=900), session_scope() as session:
        n = await KPIEngine(session).run(codes=codes)
    log.info("kpis_computed", values=n)
    return n


async def refresh_daily_aggregates() -> None:
    async with get_engine().begin() as conn:
        await conn.execute(text("REFRESH MATERIALIZED VIEW telemetry_daily"))


async def escalate_alerts() -> int:
    from app.services.alert_service import AlertService

    async with session_scope() as session:
        return await AlertService(session).escalate_due()


async def generate_report(report_id: str) -> str:
    from app.services.report_service import ReportService

    async with session_scope() as session:
        report = await ReportService(session).generate(uuid.UUID(report_id))
        return str(report.status)


async def run_due_schedules() -> int:
    from app.services.report_service import ReportService
    from app.workers.dispatch import dispatch

    async with session_scope() as session:
        reports = await ReportService(session).due_schedules()
    for r in reports:
        await dispatch("generate_report", str(r.id))
    return len(reports)


async def batch_score() -> dict[str, int]:
    from app.services.ml_service import MLService

    async with session_scope() as session:
        return await MLService(session).batch_score()


async def drift_check() -> list[dict[str, Any]]:
    from app.services.ml_service import MLService

    async with session_scope() as session:
        return await MLService(session).drift(None)


async def retrain(name: str) -> str | None:
    from app.ml.train import train_model

    model = await train_model(name)
    return model.version if model else None


JOBS: dict[str, Callable[..., Awaitable[Any]]] = {
    "compute_kpis": compute_kpis, "refresh_daily_aggregates": refresh_daily_aggregates,
    "escalate_alerts": escalate_alerts, "generate_report": generate_report, "run_due_schedules": run_due_schedules,
    "batch_score": batch_score, "drift_check": drift_check, "retrain": retrain,
}
