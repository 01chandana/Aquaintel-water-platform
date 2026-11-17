"""AquaIntel model-lifecycle DAGs (spec Ch. 14: "Airflow DAGs for scheduled retraining"; cadence Table 10.2).

Airflow decides *when*; the platform does the work. Every task calls the AquaIntel REST API with an
integration API key (Airflow Variables ``aquaintel_api_url`` / ``aquaintel_api_key``; the key needs
``ml:read``, ``ml:register`` and ``ml:performance``). Training runs on the Celery ``ml`` queue, so a sensor waits for the
new version to appear in the model registry. New versions land in ``staging``: promotion to production
stays a two-person decision in the UI (Ch. 10.11). The API runs with ``AQUAINTEL_ML_ORCHESTRATOR=airflow``
so Celery beat does not schedule the same retrains.

Table 10.2                   DAG
  Demand forecast  daily     aquaintel_retrain_daily
  Anomaly detection weekly   aquaintel_retrain_weekly (+ any model whose weekly drift check fails)
  Chlorine decay   weekly    aquaintel_retrain_weekly
  Pump failure     monthly   aquaintel_retrain_monthly
  Energy           monthly   aquaintel_retrain_monthly
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import requests
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.sensors.base import PokeReturnValue

DEFAULT_ARGS = {"owner": "ml-platform", "retries": 2, "retry_delay": timedelta(minutes=5)}
START = datetime(2026, 1, 1)


def _api(method: str, path: str, **kw: Any) -> Any:
    base = Variable.get("aquaintel_api_url", default_var="http://api:8000/v1")
    key = Variable.get("aquaintel_api_key")
    r = requests.request(method, f"{base}{path}", headers={"X-API-Key": key}, timeout=60, **kw)
    r.raise_for_status()
    return r.json()["data"]


def _latest_version(name: str) -> str | None:
    versions = [m["version"] for m in _api("GET", "/ml/models", params={"name": name})]
    return max(versions, default=None, key=lambda v: tuple(int(p) for p in v.split(".")))


@task
def trigger_retrain(name: str) -> dict[str, Any]:
    before = _latest_version(name)
    job = _api("POST", "/ml/models/train", params={"name": name})
    return {"model": name, "previous_version": before, "task_id": job["task_id"]}


@task.sensor(poke_interval=60, timeout=2 * 60 * 60, mode="reschedule")
def wait_for_new_version(request: dict[str, Any]) -> PokeReturnValue:
    current = _latest_version(request["model"])
    done = current is not None and current != request["previous_version"]
    return PokeReturnValue(is_done=done, xcom_value={**request, "new_version": current})


@task
def check_acceptance(result: dict[str, Any]) -> dict[str, Any]:
    """Surface the offline acceptance gate (Ch. 10.7.2) in the Airflow run; a failing version stays in staging."""
    new = next(m for m in _api("GET", "/ml/models", params={"name": result["model"]})
               if m["version"] == result["new_version"])
    acceptance = new.get("acceptance") or {}
    if not acceptance.get("passed"):
        print(f"{result['model']} v{new['version']} did not pass acceptance: {acceptance.get('checks')}")
    return {"model": result["model"], "version": new["version"], "stage": new["stage"],
            "passed": bool(acceptance.get("passed"))}


def _retrain(names: list[str]) -> None:
    for name in names:
        check_acceptance.override(task_id=f"check_{name}")(
            wait_for_new_version.override(task_id=f"wait_{name}")(
                trigger_retrain.override(task_id=f"retrain_{name}")(name)))


@dag(dag_id="aquaintel_retrain_daily", schedule="30 1 * * *", start_date=START, catchup=False,
     default_args=DEFAULT_ARGS, tags=["aquaintel", "ml"])
def retrain_daily() -> None:
    _retrain(["demand_forecast"])


@dag(dag_id="aquaintel_retrain_monthly", schedule="0 2 1 * *", start_date=START, catchup=False,
     default_args=DEFAULT_ARGS, tags=["aquaintel", "ml"])
def retrain_monthly() -> None:
    _retrain(["pump_failure", "energy_optimization"])


@dag(dag_id="aquaintel_retrain_weekly", schedule="0 3 * * 1", start_date=START, catchup=False,
     default_args=DEFAULT_ARGS, tags=["aquaintel", "ml", "drift"])
def retrain_weekly() -> None:
    @task
    def drift_triggered() -> list[str]:
        """Weekly drift check (Ch. 10.9.2): models with PSI > 0.2 on equipment/process features."""
        reports = _api("GET", "/ml/drift/report")
        scheduled = {"anomaly_detection", "chlorine_decay", "demand_forecast"}  # retrained anyway
        return [r["model"] for r in reports if r.get("drift_detected") and r["model"] not in scheduled]

    _retrain(["anomaly_detection", "chlorine_decay"])
    extra = trigger_retrain.override(task_id="retrain_drifted").expand(name=drift_triggered())
    check_acceptance.override(task_id="check_drifted").expand(
        result=wait_for_new_version.override(task_id="wait_drifted").expand(request=extra))


retrain_daily()
retrain_weekly()
retrain_monthly()
