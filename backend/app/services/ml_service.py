"""ML lifecycle service (Table 7.10, Ch. 10.8-10.11, 14.7-14.8).

* Registry: register -> staging -> production -> archived, with a **two-person rule** for
  production (approver must differ from the model's creator, Ch. 14.8).
* Serving: real-time REST inference (< 100 ms, in-process model cache), batch scoring via
  Celery, and predictive rules evaluated on every score (Ch. 13.2.3).
* Champion/challenger: when a staging model exists it is scored in **shadow mode** next to
  the production champion; both predictions are stored for comparison.
* Explainability: TreeSHAP contributions stored with each XGBoost prediction.
* Monitoring: PSI/KL/KS drift report; significant drift raises an alert and a retrain flag.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.cache import get_cache
from app.core.events import ML_INFERENCE_RESULT, envelope, get_event_bus
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.metrics import ml_feature_drift_psi, ml_inference_latency, ml_predictions_total
from app.ml import features as F
from app.ml import models as M
from app.ml.drift import MIN_ROWS, PSI_ALERT, drift_report
from app.ml.registry import load_artifact
from app.models.alert import AlertRule
from app.models.asset import Asset
from app.models.enums import ModelStage, RuleType
from app.models.ml_model import MLModel, Prediction
from app.repositories.ml_repository import MLModelRepository
from app.schemas.ml import ModelRegister, PredictRequest
from app.services import rules_engine
from app.services.audit_service import AuditService

log = get_logger(__name__)
TABULAR = {"energy_optimization", "chlorine_decay"}


class MLService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.models = MLModelRepository(session)

    # ---- registry -------------------------------------------------------------------------
    async def register(self, data: ModelRegister, principal: Principal) -> MLModel:
        if (await self.session.execute(select(MLModel).where(MLModel.name == data.name, MLModel.version == data.version))).first():
            raise ConflictError(f"{data.name} v{data.version} already registered")
        m = await self.models.create(MLModel(**data.model_dump(), stage=ModelStage.NONE, created_by=principal.user_id))
        await AuditService(self.session).record("ml.model_registered", "ml_model", m.id, principal=principal,
                                                details={"name": m.name, "version": m.version})
        await self.session.commit()
        return m

    async def deploy(self, model_id: uuid.UUID, stage: str, principal: Principal, note: str | None) -> MLModel:
        m = await self.models.get_or_404(model_id, "Model")
        target = ModelStage(stage)
        if target == ModelStage.PRODUCTION:
            if m.created_by and m.created_by == principal.user_id:
                raise AuthorizationError("Two-person rule: a model cannot be promoted to production by its creator")
            if m.acceptance and not m.acceptance.get("passed", True) and not note:
                raise ValidationError("Model failed acceptance criteria; provide an override note to deploy")
            for champion in await self.models.all(MLModel.name == m.name, MLModel.stage == ModelStage.PRODUCTION):
                champion.stage, champion.archived_at = ModelStage.ARCHIVED, datetime.now(UTC)  # kept 30 d for rollback
            m.approved_by, m.deployed_at = principal.user_id, datetime.now(UTC)
        elif target == ModelStage.ARCHIVED:
            m.archived_at = datetime.now(UTC)
        m.stage = target
        await AuditService(self.session).record("ml.model_stage_change", "ml_model", m.id, principal=principal,
                                                details={"name": m.name, "version": m.version, "stage": str(target),
                                                         "note": note})
        await self.session.commit()
        return m

    async def production(self, name: str) -> MLModel:
        m = await self.models.in_stage(name, ModelStage.PRODUCTION)
        if m is None:
            raise NotFoundError(f"No production model for {name}")
        return m

    # ---- inference --------------------------------------------------------------------------
    async def predict(self, model_id: uuid.UUID, req: PredictRequest, principal: Principal | None = None,
                      mode: str = "realtime") -> dict[str, Any]:
        m = await self.models.get_or_404(model_id, "Model")
        bundle = await load_artifact(m.name, m.version)
        start = time.perf_counter()
        result = await self._score(m, bundle, req)
        latency = (time.perf_counter() - start) * 1000
        ml_inference_latency.labels(m.name).observe(latency / 1000)
        ml_predictions_total.labels(m.name, mode).inc()
        result.update({"model": m.name, "version": m.version, "stage": str(m.stage), "latency_ms": round(latency, 2)})

        # champion/challenger shadow scoring (never returned to callers, only stored)
        if m.stage == ModelStage.PRODUCTION:
            challenger = await self.models.in_stage(m.name, ModelStage.STAGING)
            if challenger is not None:
                try:
                    shadow = await self._score(challenger, await load_artifact(challenger.name, challenger.version), req,
                                               shadow=True)
                    result["shadow"] = {"version": challenger.version, "value": shadow.get("value")}
                except Exception as exc:  # noqa: BLE001
                    log.warning("shadow_scoring_failed", error=str(exc))
        await self.session.commit()
        await get_event_bus().publish(ML_INFERENCE_RESULT, envelope("ml.inference.result", {
            "model": m.name, "version": m.version, "asset_id": str(req.asset_id) if req.asset_id else None,
            "value": result.get("value")}), key=str(req.asset_id) if req.asset_id else m.name)
        return result

    async def _store(self, m: MLModel, asset_id: uuid.UUID | None, value: float, label: str | None,
                     confidence: float | None, features: dict[str, Any] | None, explanation: dict[str, Any] | None,
                     horizon: str | None = None, shadow: bool = False) -> None:
        self.session.add(Prediction(time=datetime.now(UTC), id=uuid.uuid4(), model_id=m.id, asset_id=asset_id,
                                    value=float(value), label=label, confidence=confidence, horizon=horizon,
                                    is_shadow=shadow, features=_clean(features), explanation=_clean(explanation)))

    async def _score(self, m: MLModel, bundle: dict[str, Any], req: PredictRequest, shadow: bool = False) -> dict[str, Any]:
        now = datetime.now(UTC)
        if m.name in ("pump_failure", "anomaly_detection"):
            if req.features:
                X = pd.DataFrame([req.features])
                asset_id = req.asset_id
            else:
                if not req.asset_id:
                    raise ValidationError("asset_id (pump) or features required")
                df = await F.pump_features(self.session, now - timedelta(hours=48), now + timedelta(hours=1), req.asset_id)
                if df.empty:
                    raise ValidationError("Not enough recent telemetry to build features for this asset")
                X = df.iloc[[-1]]
                asset_id = req.asset_id
            if m.name == "pump_failure":
                p = float(M.predict_pump_failure(bundle, X)[0])
                label = "failure_risk" if p >= bundle["threshold"] else "normal"
                expl = None
                if req.explain:
                    contrib = M.shap_contributions(bundle["model"], X[bundle["features"]])[0]
                    expl = dict(sorted(contrib.items(), key=lambda kv: -abs(kv[1]))[:8])
                feats = X[bundle["features"]].iloc[0].to_dict()
                await self._store(m, asset_id, p, label, abs(p - 0.5) * 2, feats, expl, "7d", shadow)
                if not shadow:
                    await self._predictive_rules(m.name, asset_id, {"failure_probability": p, "value": p})
                rul = max(0.0, 30 * (1 - p)) if p > 0.2 else None
                return {"value": round(p, 4), "label": label, "failure_probability": round(p, 4),
                        "decision_threshold": bundle["threshold"], "remaining_useful_life_days": round(rul, 1) if rul else None,
                        "explanation": expl, "features": _clean(feats),
                        "recommendation": "Schedule inspection at next planned shutdown; inspect bearings and lubrication"
                        if label == "failure_risk" else "No action required"}
            if {"flow_mean_6h", "runtime_frac_24h"} <= set(X.columns) and not bool(M.running_mask(X).iloc[0]):
                return {"value": 0.0, "label": "idle", "anomaly_score": 0.0, "threshold": round(bundle["threshold"], 4),
                        "note": "pump not in steady-state operation; anomaly scoring skipped"}
            score = float(M.score_anomaly(bundle, X)[0])
            label = "anomaly" if score >= bundle["threshold"] else "normal"
            feats = X[bundle["features"]].iloc[0].to_dict()
            await self._store(m, asset_id, score, label, score, feats, None, None, shadow)
            if not shadow:
                await self._predictive_rules(m.name, asset_id, {"anomaly_score": score, "value": score})
            return {"value": round(score, 4), "label": label, "anomaly_score": round(score, 4),
                    "threshold": round(bundle["threshold"], 4), "features": _clean(feats)}

        if m.name == "demand_forecast":
            site = await self._site(req.asset_id)
            hist = await F.demand_series(self.session, site, now - timedelta(days=10), now + timedelta(hours=1))
            if len(hist) < 200:
                raise ValidationError("Not enough demand history (need ~8 days)")
            fc = M.forecast_demand(bundle, hist, req.horizon_hours, temperature=hist.set_index("time")["temperature"])
            total = sum(f["value"] for f in fc)
            await self._store(m, site.id, total, "forecast_total_m3", None, {"horizon_h": req.horizon_hours}, None,
                              f"t+{req.horizon_hours}h", shadow)
            peak = max(fc, key=lambda f: f["value"])
            return {"value": round(total, 1), "site_id": str(site.id), "forecast": fc,
                    "peak": {"time": peak["time"], "value": peak["value"]}, "unit": "m3/h"}

        if m.name == "chlorine_decay":
            if req.features:
                X = pd.DataFrame([req.features])
                pred = float(M.predict_chlorine(bundle, X)[0])
                await self._store(m, req.asset_id, pred, "residual_mg_l", None, req.features, None, None, shadow)
                return {"value": round(pred, 3), "unit": "mg/L"}
            from app.ml.train import chlorine_dataset

            df = await chlorine_dataset(self.session, now - timedelta(hours=6), now + timedelta(hours=1))
            if df.empty:
                raise ValidationError("Not enough recent data")
            latest = df.sort_values("time").groupby("dma").tail(1)
            preds = M.predict_chlorine(bundle, latest)
            out = []
            for (_, row), p in zip(latest.iterrows(), preds, strict=True):
                k = float(M.physics_k(bundle, np.array([row["water_temperature"]]), np.array([row["toc"]]))[0])
                out.append({"dma": row["dma"], "predicted_mg_l": round(float(p), 3), "measured_mg_l": round(float(row["c"]), 3),
                            "residence_h": round(float(row["residence_h"]), 2), "decay_k_per_h": round(k, 4),
                            "status": "low" if p < 0.2 else "watch" if p < 0.5 else "ok"})
            await self._store(m, req.asset_id, float(np.mean(preds)), "network_mean_mg_l", None, None, None, None, shadow)
            return {"value": round(float(np.mean(preds)), 3), "unit": "mg/L", "endpoints": out,
                    "recommendation": "Increase plant chlorine setpoint or flush mains for endpoints marked 'low'"
                    if any(o["status"] == "low" for o in out) else "Residual within operating range"}

        if m.name == "energy_optimization":
            feats = req.features
            if not feats:
                from app.ml.train import energy_dataset

                df = await energy_dataset(self.session, now - timedelta(hours=3), now + timedelta(hours=1))
                if df.empty:
                    raise ValidationError("Not enough recent data")
                feats = df.sort_values("time").iloc[-1].to_dict()
            row = pd.DataFrame([feats])
            sec = float(bundle["model"].predict(row[bundle["features"]].astype(float))[0])
            options = []
            for n in range(1, bundle.get("max_pumps", 4) + 1):
                if float(feats.get("demand", 0)) <= n * float(feats.get("pump_capacity", 900)) * 0.98:
                    cand = row.assign(pumps_running=n, load_per_pump=float(feats.get("demand", 0)) / (
                        n * float(feats.get("pump_capacity", 900))))
                    options.append({"pumps_running": n, "predicted_sec": round(float(bundle["model"].predict(
                        cand[bundle["features"]].astype(float))[0]), 4)})
            best = min(options, key=lambda o: o["predicted_sec"]) if options else None
            await self._store(m, req.asset_id, sec, "sec_kwh_m3", None, {k: feats.get(k) for k in bundle["features"]},
                              None, None, shadow)
            return {"value": round(sec, 4), "unit": "kWh/m3", "options": options, "recommended": best,
                    "estimated_savings_pct": round((sec - best["predicted_sec"]) / sec * 100, 2) if best and sec else None}
        raise ValidationError(f"Unsupported model {m.name}")

    async def _site(self, asset_id: uuid.UUID | None) -> Asset:
        if asset_id:
            a = await self.session.get(Asset, asset_id)
            if a is None:
                raise NotFoundError("Asset not found")
            root = a.path.split("/")[0]
            return (await self.session.execute(select(Asset).where(Asset.external_id == root))).unique().scalar_one()
        return (await self.session.execute(select(Asset).where(Asset.parent_id.is_(None)).order_by(Asset.path).limit(1))).unique().scalar_one()

    async def _predictive_rules(self, model_name: str, asset_id: uuid.UUID | None, outputs: dict[str, float]) -> None:
        """Evaluate predictive rules (Ch. 13.2.3) -> predictive-maintenance alert (Ch. 5.3.2 step 4)."""
        from app.services.alert_service import AlertService

        rules = (await self.session.execute(select(AlertRule).where(AlertRule.rule_type == RuleType.PREDICTIVE,
                                                                    AlertRule.enabled.is_(True)))).unique().scalars()
        asset = await self.session.get(Asset, asset_id) if asset_id else None
        for rule in rules:
            cond = rule.condition
            if cond.get("model") != model_name or (rule.asset_id and rule.asset_id != asset_id):
                continue
            value = outputs.get(cond.get("metric", "value"), outputs["value"])
            key = f"rule_state:{rule.id}:{asset_id}"
            state = await get_cache().get_json(key) or {}
            res = rules_engine.evaluate_predictive(cond, value, time.time(), state)
            await get_cache().set_json(key, res.state, 86400)
            if res.triggered:
                await AlertService(self.session).raise_alert(
                    rule=rule, asset=asset, title=f"{rule.name}: {asset.name if asset else ''}".strip(": "),
                    severity=rule.severity, source="ml", trigger_value=value, threshold_value=cond["value"],
                    fault_code="PRED-FAILURE" if model_name == "pump_failure" else "ANOMALY", message=res.message,
                    context={"model": model_name})

    async def batch_score(self) -> dict[str, int]:
        """Celery task body: score every pump with the production failure & anomaly models."""
        counts: dict[str, int] = {}
        pumps = await F.pump_assets(self.session)
        for name in ("pump_failure", "anomaly_detection"):
            try:
                m = await self.production(name)
            except NotFoundError:
                continue
            n = 0
            for p in pumps:
                try:
                    await self.predict(m.id, PredictRequest(asset_id=p.id, explain=name == "pump_failure"), mode="batch")
                    n += 1
                except ValidationError:
                    continue
            counts[name] = n
        return counts

    # ---- monitoring ---------------------------------------------------------------------------
    async def performance(self, model_id: uuid.UUID) -> dict[str, Any]:
        m = await self.models.get_or_404(model_id, "Model")
        since = datetime.now(UTC) - timedelta(days=7)
        day = func.date_trunc("day", Prediction.time).label("day")
        rows = (await self.session.execute(
            select(day, Prediction.is_shadow, func.count(), func.avg(Prediction.value))
            .where(Prediction.model_id == m.id, Prediction.time >= since)
            .group_by(day, Prediction.is_shadow).order_by(day))).all()
        champion_vs_challenger = None
        challenger = await self.models.in_stage(m.name, ModelStage.STAGING) if m.stage == ModelStage.PRODUCTION else None
        if challenger:
            a = (await self.session.execute(select(func.avg(Prediction.value)).where(
                Prediction.model_id == m.id, Prediction.time >= since))).scalar()
            b = (await self.session.execute(select(func.avg(Prediction.value)).where(
                Prediction.model_id == challenger.id, Prediction.is_shadow.is_(True), Prediction.time >= since))).scalar()
            champion_vs_challenger = {"challenger_version": challenger.version, "champion_mean": a, "challenger_mean": b,
                                      "challenger_metrics": challenger.metrics}
        return {"model": {"id": str(m.id), "name": m.name, "version": m.version, "stage": str(m.stage)},
                "offline_metrics": m.metrics, "acceptance": m.acceptance, "params": m.params,
                "training_window": m.training_window,
                "prediction_volume": [{"day": d.isoformat(), "shadow": s, "count": c, "mean_value": round(v or 0, 4)}
                                      for d, s, c, v in rows],
                "champion_vs_challenger": champion_vs_challenger}

    async def drift(self, name: str | None) -> list[dict[str, Any]]:
        from app.ml.train import dataset

        out = []
        models = [await self.production(name)] if name else await self.models.all(MLModel.stage == ModelStage.PRODUCTION)
        now = datetime.now(UTC)
        for m in models:
            if not m.baseline:
                continue
            # Only score data the model has not been trained on: the window starts at training end at the earliest.
            trained_to = datetime.fromisoformat(m.training_window["end"]) if m.training_window else now - timedelta(days=7)
            window_start = max(now - timedelta(days=7), trained_to)
            current = await dataset(self.session, m.name, window_start, now)
            meta = {"model": m.name, "version": m.version, "window_start": window_start.isoformat(),
                    "window_end": now.isoformat(), "rows": int(len(current))}
            if len(current) < MIN_ROWS:
                out.append({**meta, "status": "collecting", "features": [], "max_psi": None,
                            "monitored_max_psi": None, "drift_detected": False, "retrain_recommended": False})
                continue
            rep = drift_report(m.baseline, current)
            ml_feature_drift_psi.labels(m.name).set(rep["monitored_max_psi"])
            if rep["drift_detected"]:
                from app.services.alert_service import AlertService

                await AlertService(self.session).raise_alert(
                    rule=None, asset=None, title=f"Model drift detected: {m.name} v{m.version}", severity="minor",
                    source="ml", trigger_value=rep["monitored_max_psi"], threshold_value=PSI_ALERT,
                    message=f"Max PSI {rep['monitored_max_psi']} on equipment/process features > {PSI_ALERT} "
                            "- retraining recommended", context={"model": m.name})
            out.append({**meta, "status": "drift" if rep["drift_detected"] else "ok", **rep})
        await self.session.commit()
        return out


def _clean(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if d is None:
        return None
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (np.floating, float)):
            out[k] = None if not np.isfinite(v) else round(float(v), 5)
        elif isinstance(v, (np.integer, int)):
            out[k] = int(v)
        elif isinstance(v, (str, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out
