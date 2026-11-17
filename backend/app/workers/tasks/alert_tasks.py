"""Alert escalation tasks (Alert worker, Figure 9.2; escalation matrix Table 13.1)."""

from __future__ import annotations

from app.workers import jobs
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async


@celery_app.task(bind=True, max_retries=3, autoretry_for=(Exception,), retry_backoff=True)
def escalate_alerts(self) -> int:  # type: ignore[no-untyped-def]
    return run_async(jobs.escalate_alerts())
