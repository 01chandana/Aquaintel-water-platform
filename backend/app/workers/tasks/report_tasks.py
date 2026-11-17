"""Report generation tasks (Report worker, Figure 9.2)."""

from __future__ import annotations

from app.workers import jobs
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async


@celery_app.task(bind=True, max_retries=2, autoretry_for=(Exception,), retry_backoff=True, time_limit=600)
def generate_report(self, report_id: str) -> str:  # type: ignore[no-untyped-def]
    return run_async(jobs.generate_report(report_id))


@celery_app.task
def run_due_schedules() -> int:
    return run_async(jobs.run_due_schedules())
