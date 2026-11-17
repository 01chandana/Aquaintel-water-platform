"""KPI computation tasks (KPI worker, Figure 9.2)."""

from __future__ import annotations

from app.workers import jobs
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async


@celery_app.task(bind=True, max_retries=3, autoretry_for=(Exception,), retry_backoff=True)
def compute_kpis(self, codes: list[str] | None = None) -> int:  # type: ignore[no-untyped-def]
    return run_async(jobs.compute_kpis(codes))


@celery_app.task
def refresh_daily_aggregates() -> None:
    run_async(jobs.refresh_daily_aggregates())
