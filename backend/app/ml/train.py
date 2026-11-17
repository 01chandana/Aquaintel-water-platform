"""Training pipeline orchestration (Ch. 10.6, roadmap weeks 9-10).

``python -m app.ml.train --model all`` (also run by the Celery ``retrain`` task and the
Airflow DAG): load data from TimescaleDB -> engineer features -> time-aware split ->
train -> evaluate vs acceptance criteria -> log to MLflow -> store artifact -> register
in ``ml_models`` at stage ``staging`` (or ``production`` when bootstrapping).
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import configure_logging, get_logger
from app.core.timeutil import local_hours
from app.db.session import session_scope
from app.ml import features as F
from app.ml import models as M
from app.ml.drift import REFERENCE_DAYS, baseline_profile
from app.ml.registry import log_to_mlflow, next_version, save_artifact
from app.models.asset import Asset
from app.models.enums import ModelStage
from app.models.ml_model import MLModel

log = get_logger(__name__)
MODEL_TYPES = {
    "pump_failure": "xgboost_classifier+logreg_ensemble",
    "demand_forecast": "lightgbm_recursive",
    "anomaly_detection": "isolation_forest",
    "chlorine_decay": "physics_informed_xgboost",
    "energy_optimization": "xgboost_regressor",
}
RETRAIN_WINDOW_DAYS = {"pump_failure": 180, "demand_forecast": 365, "anomaly_detection": 90,
                       "chlorine_decay": 180, "energy_optimization": 365}  # Table 10.2


async def _sites(session: AsyncSession) -> list[Asset]:
    return list((await session.execute(select(Asset).where(Asset.parent_id.is_(None)).order_by(Asset.path))).unique().scalars())


async def dataset(session: AsyncSession, name: str, start: datetime, end: datetime) -> pd.DataFrame:
    if name in ("pump_failure", "anomaly_detection"):
        df = await F.pump_features(session, start, end)
        if not df.empty:
            df["label"] = await F.failure_labels(session, df, 7 if name == "pump_failure" else 10)
        return df
    if name == "demand_forecast":
        frames = []
        for site in await _sites(session):
            s = await F.demand_series(session, site, start, end)
            if not s.empty:
                frames.append(F.demand_features(s).assign(site=site.external_id))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if name == "chlorine_decay":
        return await chlorine_dataset(session, start, end)
    if name == "energy_optimization":
        return await energy_dataset(session, start, end)
    raise ValueError(name)


async def chlorine_dataset(session: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    rows = []
    for site in await _sites(session):
        sh = await F.site_hourly(session, site, ["production_flow", "water_temperature", "toc"], start, end)
        if sh.empty:
            continue
        analyzer = (await session.execute(select(Asset).where(Asset.external_id == f"{site.external_id}_analyzer"))).unique().scalar_one_or_none()
        dmas = [a for a in (await session.execute(select(Asset).where(Asset.path.like(f"{site.path}/%")))).unique().scalars()
                if (a.metadata_ or {}).get("role") == "distribution_endpoint"]
        if analyzer is None:
            continue
        c0 = await F._wide(session, [analyzer.id], ["chlorine"], start, end)
        if c0.empty:
            continue
        c0 = c0[["time", "chlorine"]].rename(columns={"chlorine": "c0"})
        for dma in dmas:
            d = await F._wide(session, [dma.id], ["chlorine", "billed_flow"], start, end)
            if d.empty:
                continue
            d = d.rename(columns={"chlorine": "c"}).merge(c0, on="time").merge(sh, on="time")
            dma_flow = d["billed_flow"] / 0.8
            d["residence_h"] = float((dma.metadata_ or {}).get("pipe_volume_m3", 5000)) / dma_flow.clip(lower=50)
            d["flow_share"] = d["billed_flow"] / d["production_flow"].clip(lower=1)
            d["dma"] = dma.external_id
            rows.append(d)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


async def energy_dataset(session: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    from app.services.kpi_engine import DEFAULT_CONFIG

    peak = set(DEFAULT_CONFIG["energy.tariff"]["peak_hours"])
    frames = []
    for site in await _sites(session):
        sh = await F.site_hourly(session, site, ["power_kw", "production_flow", "run_status", "pump_speed", "tank_level"],
                                 start, end)
        if sh.empty:
            continue
        pumps = [a for a in (await session.execute(select(Asset).where(Asset.path.like(f"{site.path}/%")))).unique().scalars()
                 if a.asset_type.category == "pump"]
        cap = float(np.mean([(p.metadata_ or {}).get("rated_flow_m3h", 900) for p in pumps])) if pumps else 900
        sh = sh.rename(columns={"production_flow": "demand", "run_status": "pumps_running", "pump_speed": "avg_speed",
                                "tank_level": "tank_level"})
        sh["pumps_running"] = sh["pumps_running"].round()
        sh["sec"] = sh["power_kw"] / sh["demand"].clip(lower=1)
        sh["is_peak_tariff"] = local_hours(sh["time"]).isin(peak).astype(int)
        sh["pump_capacity"] = cap
        sh["load_per_pump"] = sh["demand"] / (sh["pumps_running"].clip(lower=1) * cap)  # flow-rate ratio (Ch. 10.4.2)
        sh["site"] = site.external_id
        frames.append(F._cyclical(sh))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _fit(name: str, df: pd.DataFrame) -> dict[str, Any]:
    if name == "pump_failure":
        return M.train_pump_failure(df)
    if name == "anomaly_detection":
        return M.train_anomaly(df, df.get("label"))
    if name == "demand_forecast":
        return M.train_demand(df)
    if name == "chlorine_decay":
        return M.train_chlorine(df)
    if name == "energy_optimization":
        return M.train_energy(df)
    raise ValueError(name)


def _latency_ms(name: str, bundle: dict[str, Any], df: pd.DataFrame) -> float:
    row = df.iloc[[len(df) // 2]]
    start = time.perf_counter()
    for _ in range(20):
        if name == "pump_failure":
            M.predict_pump_failure(bundle, row)
        elif name == "anomaly_detection":
            M.score_anomaly(bundle, row)
        elif name == "chlorine_decay":
            M.predict_chlorine(bundle, row)
        else:
            bundle["model"].predict(row[bundle["features"]])
    return round((time.perf_counter() - start) / 20 * 1000, 3)


def _reference_window(df: pd.DataFrame, end: datetime) -> pd.DataFrame:
    """Drift reference: the last REFERENCE_DAYS of the training data (falls back to all rows if too few)."""
    col = next((c for c in ("time", "hour", "ts") if c in df.columns), None)
    if col is None:
        return df
    recent = df[pd.to_datetime(df[col], utc=True) >= end - timedelta(days=REFERENCE_DAYS)]
    return recent if len(recent) >= 100 else df


async def train_model(name: str, *, end: datetime | None = None, days: int | None = None,
                      promote: bool = False, created_by: Any = None) -> MLModel | None:
    end = end or datetime.now(UTC)
    start = end - timedelta(days=days or RETRAIN_WINDOW_DAYS[name])
    async with session_scope() as session:
        df = await dataset(session, name, start, end)
        if df.empty or len(df) < 100:
            log.warning("training_skipped", model=name, rows=len(df))
            return None
        if name == "demand_forecast":
            # one global model across sites: train on the larger site, others share the pattern
            sizes = df.groupby("site")["demand"].mean().sort_values()
            df = df[df["site"] == sizes.index[-1]].reset_index(drop=True)
        t0 = time.perf_counter()
        bundle = await asyncio.to_thread(_fit, name, df)
        bundle["metrics"]["training_seconds"] = round(time.perf_counter() - t0, 2)
        bundle["metrics"]["inference_latency_ms"] = _latency_ms(name, bundle, df)
        bundle["metrics"]["training_rows"] = int(len(df))
        feats = bundle["features"]
        baseline = baseline_profile(_reference_window(df, end), feats)
        existing = tuple(v for (v,) in (await session.execute(select(MLModel.version).where(MLModel.name == name))).all())
        version = next_version(existing)
        bundle["name"], bundle["version"] = name, version
        run_id = await asyncio.to_thread(log_to_mlflow, name, f"{name}_v{version}", bundle.get("params", {}),
                                         {k: v for k, v in bundle["metrics"].items() if v is not None}, bundle)
        uri = await save_artifact(name, version, bundle)
        acc = M.acceptance(name, bundle["metrics"])
        stage = ModelStage.STAGING
        if promote:
            prod = (await session.execute(select(MLModel).where(MLModel.name == name, MLModel.stage == ModelStage.PRODUCTION))).scalars().all()
            for p in prod:
                p.stage, p.archived_at = ModelStage.ARCHIVED, datetime.now(UTC)
            stage = ModelStage.PRODUCTION
        model = MLModel(name=name, model_type=MODEL_TYPES[name], version=version, stage=stage, mlflow_run_id=run_id,
                        artifact_uri=uri, metrics=_jsonable(bundle["metrics"]), params=_jsonable(bundle.get("params", {})),
                        features=feats, baseline=baseline, acceptance=_jsonable(acc), created_by=created_by,
                        training_window={"start": start.isoformat(), "end": end.isoformat(), "rows": int(len(df))},
                        deployed_at=datetime.now(UTC) if promote else None)
        session.add(model)
        await session.flush()
        from app.services.audit_service import AuditService

        await AuditService(session).record("ml.model_trained", "ml_model", model.id,
                                           details={"name": name, "version": version, "stage": str(stage),
                                                    "acceptance_passed": acc["passed"]})
        log.info("model_trained", model=name, version=version, metrics=bundle["metrics"], acceptance=acc["passed"])
        return model


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    import json

    return json.loads(json.dumps(d, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o)))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Train AquaIntel ML models")
    parser.add_argument("--model", default="all", choices=["all", *MODEL_TYPES])
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--promote", action="store_true", help="register directly in Production (bootstrap only)")
    args = parser.parse_args()
    configure_logging("INFO")
    for name in (MODEL_TYPES if args.model == "all" else [args.model]):
        m = await train_model(name, days=args.days, promote=args.promote)
        print(f"{name}: {'skipped' if m is None else f'v{m.version} [{m.stage}] {m.metrics}'}")


if __name__ == "__main__":
    asyncio.run(main())
