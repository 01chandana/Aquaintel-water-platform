"""Task dispatch: Celery in production, in-process asyncio in single-node development.

``task_mode=inline`` also starts :func:`run_scheduler`, an asyncio equivalent of the Celery
beat schedule, so escalation, KPI computation, scheduled reports and batch scoring keep
running when only ``uvicorn`` is started.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
INLINE_STATS: Counter[str] = Counter()
_inflight: set[asyncio.Task[Any]] = set()

CELERY_NAMES = {
    "compute_kpis": "app.workers.tasks.kpi_tasks.compute_kpis",
    "refresh_daily_aggregates": "app.workers.tasks.kpi_tasks.refresh_daily_aggregates",
    "escalate_alerts": "app.workers.tasks.alert_tasks.escalate_alerts",
    "generate_report": "app.workers.tasks.report_tasks.generate_report",
    "run_due_schedules": "app.workers.tasks.report_tasks.run_due_schedules",
    "batch_score": "app.workers.tasks.ml_tasks.batch_score",
    "drift_check": "app.workers.tasks.ml_tasks.drift_check",
    "retrain": "app.workers.tasks.ml_tasks.retrain",
}


async def _run_inline(name: str, *args: Any) -> Any:
    from app.workers.jobs import JOBS

    INLINE_STATS[f"{name}:started"] += 1
    try:
        result = await JOBS[name](*args)
        INLINE_STATS[f"{name}:succeeded"] += 1
        return result
    except Exception as exc:
        INLINE_STATS[f"{name}:failed"] += 1
        log.exception("inline_task_failed", task=name, error=str(exc))
        return None


async def dispatch(name: str, *args: Any) -> str:
    if get_settings().task_mode == "celery":
        from app.workers.celery_app import celery_app

        result = await asyncio.to_thread(celery_app.send_task, CELERY_NAMES[name], args=list(args))
        return str(result.id)
    task = asyncio.create_task(_run_inline(name, *args))
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)
    return f"inline-{id(task)}"


async def drain() -> None:
    while _inflight:
        await asyncio.gather(*list(_inflight), return_exceptions=True)


async def run_scheduler(stop: asyncio.Event) -> None:
    """In-process beat: same cadence as ``celery_app.conf.beat_schedule``."""
    last: dict[str, Any] = {}
    while not stop.is_set():
        now = datetime.now(UTC)
        minute_key = now.strftime("%Y%m%d%H%M")
        if last.get("minute") != minute_key:
            last["minute"] = minute_key
            await _run_inline("escalate_alerts")
            await _run_inline("run_due_schedules")
            if now.minute == 5 and last.get("kpi") != now.hour:
                last["kpi"] = now.hour
                await _run_inline("compute_kpis")
            if now.minute % 15 == 0:
                await _run_inline("batch_score")
            if now.hour == 0 and now.minute == 20:
                await _run_inline("refresh_daily_aggregates")
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except TimeoutError:
            pass
