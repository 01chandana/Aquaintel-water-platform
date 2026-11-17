"""ML tasks (ML worker, Figure 9.2): batch inference, drift checks, scheduled retraining (Table 10.2)."""

from __future__ import annotations

from typing import Any

from app.workers import jobs
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async


@celery_app.task(time_limit=300)
def batch_score() -> dict[str, int]:
    return run_async(jobs.batch_score())


@celery_app.task(time_limit=900)
def drift_check() -> list[dict[str, Any]]:
    return run_async(jobs.drift_check())


@celery_app.task(time_limit=3600)
def retrain(name: str) -> str | None:
    return run_async(jobs.retrain(name))
