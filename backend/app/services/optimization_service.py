"""Optimization Service (Ch. 3.3.3): pump scheduling and chemical dosing recommendations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.core.timeutil import local_hour, local_hours
from app.ml import features as F
from app.models.asset import Asset
from app.models.system import Schedule, SystemConfig
from app.optimization import pump_scheduler as ps
from app.schemas.optimization import DosingRequest, PumpScheduleRequest
from app.services.audit_service import AuditService
from app.services.kpi_engine import DEFAULT_CONFIG

log = get_logger(__name__)


class OptimizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _site(self, site_id: uuid.UUID | None) -> Asset:
        stmt = select(Asset).where(Asset.parent_id.is_(None))
        stmt = stmt.where(Asset.id == site_id) if site_id else stmt.order_by(Asset.path).limit(1)
        site = (await self.session.execute(stmt)).unique().scalar_one_or_none()
        if site is None:
            raise ValidationError("Site not found")
        return site

    async def _cfg(self, key: str) -> Any:
        row = await self.session.get(SystemConfig, key)
        return row.value if row else DEFAULT_CONFIG[key]

    async def _children(self, site: Asset) -> list[Asset]:
        return list((await self.session.execute(select(Asset).where(Asset.path.like(f"{site.path}/%")))).unique().scalars())

    async def _demand(self, site: Asset, horizon: int, use_forecast: bool) -> tuple[list[float], str]:
        now = datetime.now(UTC)
        if use_forecast:
            try:
                from app.schemas.ml import PredictRequest
                from app.services.ml_service import MLService

                svc = MLService(self.session)
                m = await svc.production("demand_forecast")
                res = await svc.predict(m.id, PredictRequest(asset_id=site.id, horizon_hours=horizon, explain=False))
                return [f["value"] for f in res["forecast"]], f"demand_forecast v{m.version}"
            except Exception as exc:  # noqa: BLE001 - fall back to the historical profile
                log.warning("demand_forecast_unavailable", error=str(exc))
        hist = await F.demand_series(self.session, site, now - timedelta(days=7), now)
        if hist.empty:
            raise ValidationError("No demand history available for this site")
        profile = hist.assign(h=local_hours(hist["time"])).groupby("h")["demand"].mean()
        start_h = local_hour(now + timedelta(hours=1))
        return [float(profile.get((start_h + i) % 24, profile.mean())) for i in range(horizon)], "7-day hourly profile"

    async def pump_schedule(self, req: PumpScheduleRequest, principal: Principal) -> Schedule:
        site = await self._site(req.site_id)
        children = await self._children(site)
        pumps_assets = [a for a in children if a.asset_type.category == "pump" and str(a.status) != "maintenance"]
        reservoir = next((a for a in children if a.external_id.endswith("_reservoir")), None)
        if not pumps_assets:
            raise ValidationError("No available pumps at this site")
        demand, source = await self._demand(site, req.horizon_hours, req.use_forecast)
        tariff_cfg = await self._cfg("energy.tariff")
        start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        tariff = [float(tariff_cfg["peak_rate"] if local_hour(start + timedelta(hours=i)) in tariff_cfg["peak_hours"]
                        else tariff_cfg["offpeak_rate"]) for i in range(req.horizon_hours)]
        pumps = []
        for a in sorted(pumps_assets, key=lambda a: a.external_id):
            md = a.metadata_ or {}
            q = float(md.get("rated_flow_m3h", 900)) * 0.92
            pumps.append(ps.PumpSpec(a.name, q, ps.pump_power(q, float(md.get("rated_head_m", 48)),
                                                              float(md.get("bep_efficiency", 0.82)) * 0.97)))
        capacity = float((reservoir.metadata_ or {}).get("capacity_m3", 20000)) if reservoir else 20000.0
        level = req.initial_level_pct
        if level is None and reservoir is not None:
            from app.repositories.telemetry_repository import TagRepository
            from app.services.telemetry_service import TelemetryService

            tags = await TagRepository(self.session).for_asset(reservoir.id)
            latest = await TelemetryService(self.session).latest([t.id for t in tags])
            level = float(latest[0]["value"]) if latest else 60.0
        level = float(np.clip(level or 60.0, req.min_level_pct, req.max_level_pct))
        contracted = float(await self._cfg("energy.contracted_demand_kw"))
        result = ps.solve(pumps, demand, tariff, capacity, level, req.min_level_pct, req.max_level_pct, contracted)
        for i, h in enumerate(result.get("hours", [])):
            h["time"] = (start + timedelta(hours=i)).isoformat()
        sched = Schedule(
            name=f"Pump schedule {site.name} {start:%Y-%m-%d %H:00}", schedule_type="pump", site_id=site.id,
            horizon_hours=req.horizon_hours, status="proposed", solver_status=str(result["status"]),
            inputs={"demand_source": source, "demand_m3h": [round(d, 1) for d in demand], "tariff": tariff,
                    "initial_level_pct": level, "min_level_pct": req.min_level_pct, "max_level_pct": req.max_level_pct,
                    "reservoir_capacity_m3": capacity, "contracted_demand_kw": contracted,
                    "pumps": [p.__dict__ for p in pumps]},
            plan=result, estimated_cost=result.get("cost"), baseline_cost=result["baseline"]["cost"],
            savings_pct=result.get("savings_pct"), created_by=principal.user_id)
        self.session.add(sched)
        await self.session.flush()
        await AuditService(self.session).record("optimization.pump_schedule", "schedule", sched.id, principal=principal,
                                                details={"savings_pct": result.get("savings_pct")})
        await self.session.commit()
        return sched

    async def dosing(self, req: DosingRequest, principal: Principal) -> Schedule:
        site = await self._site(req.site_id)
        now = datetime.now(UTC)
        sh = await F.site_hourly(self.session, site, ["raw_turbidity", "water_temperature", "toc", "production_flow",
                                                      "coagulant_dose", "chlorine_dose"], now - timedelta(days=14), now)
        if sh.empty:
            raise ValidationError("Not enough process history")
        last = sh.dropna().iloc[-1]
        raw_turb = req.raw_turbidity_ntu if req.raw_turbidity_ntu is not None else float(last["raw_turbidity"])
        temp = req.water_temperature_c if req.water_temperature_c is not None else float(last["water_temperature"])
        flow = req.flow_m3h if req.flow_m3h is not None else float(last["production_flow"])
        toc = float(last["toc"])
        # ML part: refit the coagulant dose curve (mg/L vs raw turbidity) on recent plant history
        hist = sh.dropna()
        mg_l = hist["coagulant_dose"] / hist["production_flow"].clip(lower=1) * 1000
        slope, intercept = np.polyfit(hist["raw_turbidity"], mg_l, 1) if len(hist) > 24 else (1.15, 9.0)
        coag = ps.coagulant_dose_mg_l(raw_turb, float(slope), float(intercept)) * 0.95  # 5% trim vs historical practice
        # physics part: chlorine setpoint so the worst DMA keeps the target residual
        children = await self._children(site)
        dmas = [a for a in children if (a.metadata_ or {}).get("role") == "distribution_endpoint"]
        worst_res = max((float((d.metadata_ or {}).get("pipe_volume_m3", 5000)) / max(flow * 0.3, 50) for d in dmas), default=3.0)
        k = 0.055 * 1.065 ** (temp - 20) * (1 + 0.08 * (toc - 2.6))
        try:
            from app.ml.models import physics_k
            from app.ml.registry import load_artifact
            from app.services.ml_service import MLService

            m = await MLService(self.session).production("chlorine_decay")
            bundle = await load_artifact(m.name, m.version)
            k = float(physics_k(bundle, np.array([temp]), np.array([toc]))[0])
            k_source = f"chlorine_decay v{m.version}"
        except Exception:  # noqa: BLE001
            k_source = "default kinetics"
        cl_setpoint = ps.chlorine_setpoint(req.target_residual_mg_l, k, worst_res)
        prices = await self._cfg("chemicals.prices_per_kg")
        current_coag = float(last["coagulant_dose"])
        current_cl = float(last["chlorine_dose"])
        rec_coag_kgh = coag * flow / 1000
        rec_cl_kgh = (cl_setpoint + 0.6 + 0.08 * toc) * flow / 1000
        cur_cost = current_coag * prices["coagulant_dose"] + current_cl * prices["chlorine_dose"]
        new_cost = rec_coag_kgh * prices["coagulant_dose"] + rec_cl_kgh * prices["chlorine_dose"]
        plan = {
            "conditions": {"raw_turbidity_ntu": round(raw_turb, 2), "water_temperature_c": round(temp, 2), "toc_mg_l": round(toc, 2),
                           "flow_m3h": round(flow, 1), "worst_residence_h": round(worst_res, 2), "decay_k_per_h": round(k, 4),
                           "decay_source": k_source},
            "coagulant": {"dose_mg_l": round(coag, 2), "rate_kg_h": round(rec_coag_kgh, 2), "current_kg_h": round(current_coag, 2),
                          "curve": {"slope": round(float(slope), 4), "intercept": round(float(intercept), 3)}},
            "chlorine": {"plant_setpoint_mg_l": round(cl_setpoint, 3), "target_endpoint_mg_l": req.target_residual_mg_l,
                         "rate_kg_h": round(rec_cl_kgh, 2), "current_kg_h": round(current_cl, 2)},
            "cost_per_hour": {"current": round(cur_cost, 2), "recommended": round(new_cost, 2)},
            "valid_for_minutes": 15,
        }
        savings = (cur_cost - new_cost) / cur_cost * 100 if cur_cost else None
        sched = Schedule(name=f"Dosing setpoints {site.name} {now:%Y-%m-%d %H:%M}", schedule_type="dosing", site_id=site.id,
                         horizon_hours=1, status="proposed", solver_status="ok", inputs=req.model_dump(mode="json"),
                         plan=plan, estimated_cost=round(new_cost, 2), baseline_cost=round(cur_cost, 2),
                         savings_pct=round(savings, 2) if savings is not None else None, created_by=principal.user_id)
        self.session.add(sched)
        await self.session.flush()
        await AuditService(self.session).record("optimization.dosing", "schedule", sched.id, principal=principal)
        await self.session.commit()
        return sched

    async def approve(self, schedule_id: uuid.UUID, principal: Principal) -> Schedule:
        s = await self.session.get(Schedule, schedule_id)
        if s is None:
            raise ValidationError("Schedule not found")
        s.status = "approved"
        await AuditService(self.session).record("optimization.approve", "schedule", s.id, principal=principal)
        await self.session.commit()
        return s

