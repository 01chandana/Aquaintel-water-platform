"""KPI API operations (Table 7.6) with Redis caching (Table 9.1: 5 min, write-invalidate)."""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.cache import TTL_KPI_VALUES, get_cache
from app.core.exceptions import ConflictError, ValidationError
from app.models.asset import Asset
from app.models.kpi import KPIDefinition, KPIValue
from app.repositories.kpi_repository import KPIRepository
from app.schemas.kpi import KPICreate, KPIOut
from app.services.audit_service import AuditService
from app.services.kpi_catalog import CATEGORIES
from app.services.kpi_engine import CUSTOM_FORMULA

DASHBOARD_SETS: dict[str, list[str]] = {
    "executive": ["SYSTEM_AVAILABILITY", "PRODUCTION_VOLUME", "WATER_QUALITY_INDEX", "SPECIFIC_ENERGY_CONSUMPTION",
                  "REGULATORY_COMPLIANCE_RATE", "OM_COST_PER_UNIT", "DISTRIBUTION_LOSS", "CRITICAL_ALERT_RATE"],
    "operations": ["SYSTEM_AVAILABILITY", "PRODUCTION_VOLUME", "FLOW_RATE_EFFICIENCY", "PRESSURE_STABILITY_INDEX",
                   "PEAK_DEMAND_RATIO", "DISTRIBUTION_LOSS"],
    "energy": ["SPECIFIC_ENERGY_CONSUMPTION", "PUMP_EFFICIENCY_INDEX", "MAXIMUM_DEMAND_UTILIZATION", "POWER_FACTOR",
               "ENERGY_COST_INTENSITY", "PEAK_OFFPEAK_RATIO"],
    "quality": ["WATER_QUALITY_INDEX", "CHLORINE_RESIDUAL_COMPLIANCE", "TURBIDITY_EXCEEDANCE_RATE", "PH_STABILITY",
                "DBP_RISK", "MICROBIAL_CONTAMINATION_INDEX"],
    "maintenance": ["MTBF", "MTTR", "PM_COMPLIANCE", "EQUIPMENT_HEALTH_SCORE", "CRITICAL_ALERT_RATE",
                    "SPARE_PARTS_AVAILABILITY"],
    "compliance": ["REGULATORY_COMPLIANCE_RATE", "SAMPLE_COLLECTION_COVERAGE", "REPORT_SUBMISSION_TIMELINESS",
                   "AUDIT_FINDING_RESOLUTION_TIME"],
}


class KPIService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = KPIRepository(session)
        self.cache = get_cache()

    async def _site_id(self, site_id: uuid.UUID | None) -> uuid.UUID | None:
        if site_id:
            return site_id
        row = (await self.session.execute(select(Asset.id).where(Asset.parent_id.is_(None)).order_by(Asset.path).limit(1))).scalar()
        return row

    async def list(self, category: str | None, q: str | None) -> list[KPIDefinition]:
        filters = []
        if category:
            filters.append(KPIDefinition.category == category)
        if q:
            filters.append(KPIDefinition.name.ilike(f"%{q}%") | KPIDefinition.code.ilike(f"%{q}%"))
        return await self.repo.all(*filters)

    async def create(self, data: KPICreate, principal: Principal) -> KPIDefinition:
        if await self.repo.by_code(data.code):
            raise ConflictError(f"KPI {data.code} already exists")
        payload = data.model_dump(exclude={"source_parameter"})
        if data.source_parameter:
            payload["formula"] = f"{data.aggregation_type}({data.source_parameter})"
        if not CUSTOM_FORMULA.match(payload["formula"]):
            raise ValidationError("Custom KPI formula must be '<avg|min|max|sum|count|time_weighted>(<parameter>)'")
        kd = await self.repo.create(KPIDefinition(**payload, is_builtin=False, scope="site"))
        await AuditService(self.session).record("kpi.create", "kpi", kd.id, principal=principal,
                                                details={"code": kd.code, "formula": kd.formula})
        await self.session.commit()
        return kd

    async def values(self, kpi_id: uuid.UUID, start: datetime, end: datetime, asset_id: uuid.UUID | None,
                     bucket: str | None) -> builtins.list[dict[str, Any]]:
        kd = await self.repo.get_or_404(kpi_id, "KPI")
        asset_id = asset_id or await self._site_id(None)
        key = f"kpi:values:{kd.id}:{asset_id}:{start:%Y%m%d%H}:{end:%Y%m%d%H}:{bucket}"
        if (cached := await self.cache.get_json(key)) is not None:
            return cached
        rows = await self.repo.values(kd.id, start, end, asset_id)
        out = [{"time": r.time.isoformat(), "asset_id": str(r.asset_id), "value": r.value,
                "normalized_value": r.normalized_value, "status": r.status} for r in rows]
        if bucket == "day" and out:
            import pandas as pd

            df = pd.DataFrame(out)
            df["time"] = pd.to_datetime(df["time"])
            g = df.set_index("time").resample("1D")["value"].mean().dropna()
            out = [{"time": t.isoformat(), "asset_id": str(asset_id), "value": float(v), "normalized_value": None,
                    "status": "normal"} for t, v in g.items()]
        await self.cache.set_json(key, out, TTL_KPI_VALUES)
        return out

    async def current(self, kpi_id: uuid.UUID, asset_id: uuid.UUID | None) -> dict[str, Any]:
        kd = await self.repo.get_or_404(kpi_id, "KPI")
        return await self._current(kd, asset_id or await self._site_id(None))

    async def _current(self, kd: KPIDefinition, asset_id: uuid.UUID | None) -> dict[str, Any]:
        latest = await self.repo.latest_values(kd.id, asset_id, 25)
        cur = latest[0] if latest else None
        prev = next((v for v in latest[1:] if cur and v.time <= cur.time - timedelta(hours=23)), latest[-1] if len(latest) > 1 else None)
        trend = ((cur.value - prev.value) / abs(prev.value) * 100) if cur and prev and prev.value else None
        return {"kpi": KPIOut.model_validate(kd).model_dump(mode="json"), "asset_id": str(asset_id) if asset_id else None,
                "value": cur.value if cur else None, "status": cur.status if cur else "no_data",
                "time": cur.time.isoformat() if cur else None, "previous_value": prev.value if prev else None,
                "trend_pct": round(trend, 2) if trend is not None else None}

    async def dashboard(self, view: str, site_id: uuid.UUID | None) -> builtins.list[dict[str, Any]]:
        site = await self._site_id(site_id)
        key = f"kpi:dashboard:{view}:{site}"
        if (cached := await self.cache.get_json(key)) is not None:
            return cached
        codes = DASHBOARD_SETS.get(view, DASHBOARD_SETS["executive"])
        defs = {d.code: d for d in await self.repo.all(KPIDefinition.code.in_(codes))}
        out = []
        for code in codes:
            if code in defs:
                item = await self._current(defs[code], site)
                hist = await self.repo.values(defs[code].id, datetime.now(UTC) - timedelta(days=7), datetime.now(UTC), site)
                item["sparkline"] = [round(v.value, 4) for v in hist[-48:]]
                out.append(item)
        await self.cache.set_json(key, out, TTL_KPI_VALUES)
        return out

    async def asset_kpis(self, asset_id: uuid.UUID) -> builtins.list[dict[str, Any]]:
        rows = (await self.session.execute(
            select(KPIValue, KPIDefinition).join(KPIDefinition, KPIDefinition.id == KPIValue.kpi_id)
            .where(KPIValue.asset_id == asset_id, KPIValue.time >= datetime.now(UTC) - timedelta(days=2))
            .order_by(KPIValue.time.desc()))).all()
        seen: dict[str, dict[str, Any]] = {}
        for v, d in rows:
            if d.code not in seen:
                seen[d.code] = {"code": d.code, "name": d.name, "unit": d.unit, "category": d.category,
                                "value": v.value, "status": v.status, "time": v.time.isoformat(),
                                "threshold_warning": d.threshold_warning, "threshold_critical": d.threshold_critical}
        return list(seen.values())

    async def health_heatmap(self) -> builtins.list[dict[str, Any]]:
        kd = await self.repo.by_code("EQUIPMENT_HEALTH_SCORE")
        if not kd:
            return []
        rows = (await self.session.execute(
            select(KPIValue, Asset).join(Asset, Asset.id == KPIValue.asset_id)
            .where(KPIValue.kpi_id == kd.id, KPIValue.time >= datetime.now(UTC) - timedelta(days=7),
                   Asset.parent_id.is_not(None)).order_by(KPIValue.time))).unique().all()
        return [{"asset_id": str(a.id), "asset": a.name, "category": a.asset_type.category,
                 "time": v.time.isoformat(), "value": round(v.value, 1)} for v, a in rows]

    @staticmethod
    def categories() -> builtins.list[str]:
        return CATEGORIES
