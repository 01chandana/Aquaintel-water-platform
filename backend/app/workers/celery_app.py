"""Celery configuration (Ch. 9.8, Figure 9.2): Redis broker, dedicated queues, beat schedule.

Queues map to the worker pools of Figure 9.2: ``kpi``, ``alerts``, ``reports``, ``ml``.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aquaintel",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks.kpi_tasks",
        "app.workers.tasks.alert_tasks",
        "app.workers.tasks.report_tasks",
        "app.workers.tasks.ml_tasks",
    ],
)

# Model lifecycle cadence (Table 10.2). When Airflow is deployed (ml_orchestrator=airflow) the
# aquaintel_* DAGs own this calendar instead, so the same retrain never runs twice.
ML_LIFECYCLE_SCHEDULE = {
    "weekly-drift-check": {"task": "app.workers.tasks.ml_tasks.drift_check",
                           "schedule": crontab(minute=0, hour=3, day_of_week=1)},
    "daily-demand-retrain": {"task": "app.workers.tasks.ml_tasks.retrain",
                             "schedule": crontab(minute=30, hour=1), "args": ["demand_forecast"]},
    "weekly-anomaly-retrain": {"task": "app.workers.tasks.ml_tasks.retrain",
                               "schedule": crontab(minute=0, hour=4, day_of_week=1), "args": ["anomaly_detection"]},
    "weekly-chlorine-retrain": {"task": "app.workers.tasks.ml_tasks.retrain",
                                "schedule": crontab(minute=30, hour=4, day_of_week=1), "args": ["chlorine_decay"]},
    "monthly-pump-retrain": {"task": "app.workers.tasks.ml_tasks.retrain",
                             "schedule": crontab(minute=0, hour=2, day_of_month=1), "args": ["pump_failure"]},
    "monthly-energy-retrain": {"task": "app.workers.tasks.ml_tasks.retrain",
                               "schedule": crontab(minute=30, hour=2, day_of_month=1), "args": ["energy_optimization"]},
}

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.tz,
    enable_utc=True,
    task_acks_late=True,  # at-least-once: tasks are idempotent
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    result_expires=3600,
    task_default_retry_delay=10,
    task_routes={
        "app.workers.tasks.kpi_tasks.*": {"queue": "kpi"},
        "app.workers.tasks.alert_tasks.*": {"queue": "alerts"},
        "app.workers.tasks.report_tasks.*": {"queue": "reports"},
        "app.workers.tasks.ml_tasks.*": {"queue": "ml"},
    },
    beat_schedule={
        "compute-kpis-hourly": {"task": "app.workers.tasks.kpi_tasks.compute_kpis", "schedule": crontab(minute=5)},
        "refresh-daily-aggregates": {"task": "app.workers.tasks.kpi_tasks.refresh_daily_aggregates",
                                     "schedule": crontab(minute=20, hour=0)},
        "escalate-alerts": {"task": "app.workers.tasks.alert_tasks.escalate_alerts", "schedule": 60.0},
        "run-report-schedules": {"task": "app.workers.tasks.report_tasks.run_due_schedules", "schedule": 60.0},
        "batch-score-pumps": {"task": "app.workers.tasks.ml_tasks.batch_score", "schedule": crontab(minute="*/15")},
        **(ML_LIFECYCLE_SCHEDULE if settings.ml_orchestrator == "celery" else {}),
    },
)
