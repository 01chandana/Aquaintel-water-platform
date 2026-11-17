"""KPI computation engine (Ch. 11, roadmap week 7).

Each of the 30 catalogue KPIs is a registered function ``fn(ctx, start, end, asset) -> float | None``
evaluated over its rolling window. :class:`DataContext` loads telemetry and operational
records for one site **once** into pandas and slices them per window, so the same code
serves the hourly Celery job, on-demand ``POST /kpis/compute`` and historical backfill.

Results are written to ``kpi_values`` with a status (normal/warning/critical) and a 0-100
``normalized_value`` feeding the ``asset_health_scores`` view. Critical KPIs raise
``source='kpi'`` alerts, and a ``kpis.computed`` event is published (Table 5.2).
"""

from __future__ import annotations

import inspect
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.core.events import KPIS_COMPUTED, envelope, get_event_bus
from app.core.logging import get_logger
from app.core.metrics import kpi_computation_duration
from app.core.timeutil import local_hours
from app.models.alert import Alert
from app.models.asset import Asset, SparePart
from app.models.enums import WorkOrderType
from app.models.kpi import KPIDefinition, KPIValue
from app.models.report import RegulatoryLimit, Report
from app.models.system import SystemConfig
from app.models.work_order import WorkOrder
from app.services.kpi_catalog import KPI_BY_CODE

log = get_logger(__name__)
RHO_G = 9.81  # kN/m3 for water -> eta = 9.81 * Q[m3/s] * H[m] / P[kW]
BAR_TO_M = 10.197
THM_MCL = 80.0  # ug/L

DEFAULT_CONFIG: dict[str, Any] = {
    "energy.tariff": {"peak_hours": [17, 18, 19, 20, 21], "peak_rate": 0.21, "offpeak_rate": 0.09},
    "energy.contracted_demand_kw": 900.0,
    "energy.grid_emission_factor_kg_per_kwh": 0.71,
    "chemicals.prices_per_kg": {"coagulant_dose": 0.42, "chlorine_dose": 1.85},
    "production.daily_target_m3": 48000.0,
    "maintenance.cost_allocation": "completed_in_period",
}

KPIFunc = Callable[["DataContext", datetime, datetime, Asset | None], "float | None | Awaitable[float | None]"]
F = TypeVar("F", bound=Callable[..., Any])
REGISTRY: dict[str, KPIFunc] = {}


def kpi(code: str) -> Callable[[F], F]:
    """Register a KPI function (sync, or async when it needs to load data) under its catalogue code."""

    def deco(fn: F) -> F:
        REGISTRY[code] = fn
        return fn

    return deco


@dataclass
class DataContext:
    session: AsyncSession
    site: Asset
    range_start: datetime
    range_end: datetime
    config: dict[str, Any] = field(default_factory=dict)
    _frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    assets: dict[uuid.UUID, Asset] = field(default_factory=dict)
    work_orders: list[WorkOrder] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    parts: list[SparePart] = field(default_factory=list)
    reports: list[Report] = field(default_factory=list)
    limits: dict[str, RegulatoryLimit] = field(default_factory=dict)

    @classmethod
    async def load(cls, session: AsyncSession, site: Asset, start: datetime, end: datetime) -> DataContext:
        ctx = cls(session, site, start, end)
        cfg = {r.key: r.value for r in (await session.execute(select(SystemConfig))).scalars()}
        ctx.config = {**DEFAULT_CONFIG, **cfg}
        subtree = (Asset.path == site.path) | Asset.path.like(f"{site.path}/%")
        ctx.assets = {a.id: a for a in (await session.execute(select(Asset).where(subtree))).unique().scalars()}
        ids = list(ctx.assets)
        ctx.work_orders = list((await session.execute(select(WorkOrder).where(
            WorkOrder.asset_id.in_(ids), WorkOrder.created_at >= end - timedelta(days=400)))).unique().scalars())
        ctx.alerts = list((await session.execute(select(Alert).where(
            Alert.asset_id.in_(ids), Alert.created_at >= start - timedelta(days=31)))).unique().scalars())
        ctx.parts = list((await session.execute(select(SparePart))).scalars())
        ctx.reports = list((await session.execute(select(Report).where(Report.due_at.is_not(None)))).scalars())
        ctx.limits = {r.parameter: r for r in (await session.execute(select(RegulatoryLimit))).scalars()}
        return ctx

    async def frame(self, parameter: str, lookback: timedelta = timedelta(days=7)) -> pd.DataFrame:
        """Telemetry for one parameter across the site, loaded once per context."""
        if parameter not in self._frames:
            sql = text("""
                SELECT td.time, td.value, td.status, tt.id AS tag_id, tt.asset_id, tt.design_value, tt.metadata
                FROM telemetry_data td JOIN telemetry_tags tt ON tt.id = td.tag_id
                JOIN assets a ON a.id = tt.asset_id
                WHERE tt.parameter = :p AND td.status <> 'bad' AND td.time >= :s AND td.time <= :e
                  AND (a.path = :path OR a.path LIKE :like)
                ORDER BY td.time""")
            rows = (await self.session.execute(sql, {
                "p": parameter, "s": self.range_start - lookback, "e": self.range_end,
                "path": self.site.path, "like": f"{self.site.path}/%"})).all()
            df = pd.DataFrame(rows, columns=["time", "value", "status", "tag_id", "asset_id", "design_value", "metadata"])
            if not df.empty:
                df["time"] = pd.to_datetime(df["time"], utc=True)
            self._frames[parameter] = df
        return self._frames[parameter]

    def cfg(self, key: str) -> Any:
        return self.config.get(key, DEFAULT_CONFIG.get(key))


def _window(df: pd.DataFrame, start: datetime, end: datetime, asset: Asset | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    out = df[(df["time"] > pd.Timestamp(start)) & (df["time"] <= pd.Timestamp(end))]
    if asset is not None:
        out = out[out["asset_id"] == asset.id]
    return out


def _integrate_m3(df: pd.DataFrame) -> float:
    """Time-weighted integral of a flow series in m3/h -> m3 (per tag, then summed)."""
    total = 0.0
    for _, g in df.groupby("tag_id"):
        if len(g) < 2:
            continue
        hours = (g["time"].astype("int64").to_numpy() / 3.6e12)
        total += float(np.trapezoid(g["value"].to_numpy(), hours))
    return total


def _kwh(df: pd.DataFrame) -> float:
    return _integrate_m3(df)  # same trapezoid on kW -> kWh


def _pct(mask: pd.Series) -> float | None:
    return float(mask.mean() * 100) if len(mask) else None


def _volume(ctx: DataContext, df: pd.DataFrame) -> float:
    return _integrate_m3(df)


# ---- Operational --------------------------------------------------------------------------
@kpi("SYSTEM_AVAILABILITY")
def system_availability(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    pumps = [a for a in ctx.assets.values() if a.asset_type.category == "pump"]
    if not pumps:
        return None
    scheduled = len(pumps) * (end - start).total_seconds() / 3600
    down = 0.0
    for wo in ctx.work_orders:
        if wo.wo_type != WorkOrderType.CORRECTIVE or wo.asset_id not in {p.id for p in pumps} or not wo.started_at:
            continue
        s, e = max(wo.started_at, start), min(wo.completed_at or end, end)
        if e > s:
            down += (e - s).total_seconds() / 3600
    return max(0.0, (scheduled - down) / scheduled * 100)


async def _prod(ctx: DataContext, start: datetime, end: datetime) -> pd.DataFrame:
    return _window(await ctx.frame("production_flow"), start, end)


@kpi("PRODUCTION_VOLUME")
async def production_volume(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = await _prod(ctx, start, end)
    return _volume(ctx, df) if len(df) > 1 else None


@kpi("FLOW_RATE_EFFICIENCY")
async def flow_rate_efficiency(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = await _prod(ctx, start, end)
    if df.empty:
        return None
    design = df["design_value"].dropna()
    return float(df["value"].mean() / design.iloc[0] * 100) if len(design) else None


@kpi("PRESSURE_STABILITY_INDEX")
async def pressure_stability(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = _window(await ctx.frame("pressure"), start, end)
    vals = [1 - g["value"].std(ddof=0) / g["value"].mean() for _, g in df.groupby("tag_id") if len(g) > 2 and g["value"].mean()]
    return float(np.mean(vals)) if vals else None


@kpi("DISTRIBUTION_LOSS")
async def distribution_loss(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    produced = _volume(ctx, await _prod(ctx, start, end))
    billed = _integrate_m3(_window(await ctx.frame("billed_flow"), start, end))
    return (produced - billed) / produced * 100 if produced > 0 and billed > 0 else None


@kpi("PEAK_DEMAND_RATIO")
async def peak_demand_ratio(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = await _prod(ctx, start, end)
    if len(df) < 4:
        return None
    hourly = df.set_index("time")["value"].resample("1h").mean().dropna()
    return float(hourly.max() / hourly.mean()) if hourly.mean() else None


# ---- Quality ------------------------------------------------------------------------------
def _sub_chlorine(v: np.ndarray) -> np.ndarray:
    return np.where((v >= 0.5) & (v <= 4.0), 100, np.where(v < 0.5, np.clip(v / 0.5 * 100, 0, 100),
                                                            np.clip(100 - (v - 4) * 50, 0, 100)))


def _sub_turbidity(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.3, 100, np.clip(100 - (v - 0.3) / (5 - 0.3) * 100, 0, 100))


def _sub_ph(v: np.ndarray) -> np.ndarray:
    dist = np.where(v < 6.5, 6.5 - v, np.where(v > 8.5, v - 8.5, 0))
    return np.clip(100 - dist * 50, 0, 100)


@kpi("WATER_QUALITY_INDEX")
async def wqi(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    parts = []
    for param, fn, w in (("chlorine", _sub_chlorine, 0.40), ("turbidity", _sub_turbidity, 0.35), ("ph", _sub_ph, 0.25)):
        df = _window(await ctx.frame(param), start, end)
        if not df.empty:
            parts.append((float(fn(df["value"].to_numpy()).mean()), w))
    if not parts:
        return None
    return sum(q * w for q, w in parts) / sum(w for _, w in parts)


@kpi("CHLORINE_RESIDUAL_COMPLIANCE")
async def chlorine_compliance(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = _window(await ctx.frame("chlorine"), start, end)
    return _pct(df["value"].between(0.5, 4.0)) if not df.empty else None


@kpi("TURBIDITY_EXCEEDANCE_RATE")
async def turbidity_exceedance(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = _window(await ctx.frame("turbidity"), start, end)
    return _pct(df["value"] > 0.3) if not df.empty else None


@kpi("PH_STABILITY")
async def ph_stability(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = _window(await ctx.frame("ph"), start, end)
    return _pct(df["value"].between(6.5, 8.5)) if not df.empty else None


@kpi("DBP_RISK")
async def dbp_risk(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = _window(await ctx.frame("thm"), start, end)
    return float(df["value"].mean() / THM_MCL * 100) if not df.empty else None


@kpi("MICROBIAL_CONTAMINATION_INDEX")
async def microbial(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = _window(await ctx.frame("coliform_positive", timedelta(days=31)), start, end)
    return float((df["value"] >= 0.5).sum()) if not df.empty else None


# ---- Energy -------------------------------------------------------------------------------
@kpi("SPECIFIC_ENERGY_CONSUMPTION")
async def sec(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    kwh = _kwh(_window(await ctx.frame("power_kw"), start, end))
    vol = _volume(ctx, await _prod(ctx, start, end))
    return kwh / vol if vol > 0 else None


@kpi("PUMP_EFFICIENCY_INDEX")
async def pump_efficiency(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    flow = _window(await ctx.frame("flow"), start, end, asset)
    press = _window(await ctx.frame("discharge_pressure"), start, end, asset)
    power = _window(await ctx.frame("power_kw"), start, end, asset)
    if flow.empty or press.empty or power.empty:
        return None
    df = (flow[["time", "asset_id", "value"]].rename(columns={"value": "q"})
          .merge(press[["time", "asset_id", "value"]].rename(columns={"value": "p"}), on=["time", "asset_id"])
          .merge(power[["time", "asset_id", "value"]].rename(columns={"value": "kw"}), on=["time", "asset_id"]))
    df = df[(df["kw"] > 5) & (df["q"] > 1)]
    if df.empty:
        return None
    eta = RHO_G * (df["q"] / 3600) * (df["p"] * BAR_TO_M) / df["kw"]
    bep = {aid: float((ctx.assets[aid].metadata_ or {}).get("bep_efficiency", 0.82)) for aid in df["asset_id"].unique()}
    idx = eta / df["asset_id"].map(bep) * 100
    return float(idx.clip(0, 130).mean())


@kpi("MAXIMUM_DEMAND_UTILIZATION")
async def max_demand(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    df = _window(await ctx.frame("power_kw"), start, end)
    if df.empty:
        return None
    site_kw = df.set_index("time").groupby("tag_id")["value"].resample("15min").mean().groupby(level=1).sum()
    return float(site_kw.max() / float(ctx.cfg("energy.contracted_demand_kw")) * 100)


@kpi("POWER_FACTOR")
async def power_factor(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    pf = _window(await ctx.frame("power_factor"), start, end)
    kw = _window(await ctx.frame("power_kw"), start, end)
    if pf.empty:
        return None
    m = pf[["time", "asset_id", "value"]].merge(kw[["time", "asset_id", "value"]], on=["time", "asset_id"],
                                                 suffixes=("_pf", "_kw"))
    m = m[m["value_kw"] > 5]
    return float(np.average(m["value_pf"], weights=m["value_kw"])) if len(m) else float(pf["value"].mean())


def _tou_kwh(ctx: DataContext, df: pd.DataFrame) -> tuple[float, float]:
    tariff = ctx.cfg("energy.tariff")
    peak_hours = set(tariff["peak_hours"])
    peak = off = 0.0
    for _, g in df.groupby("tag_id"):
        g = g.sort_values("time")
        if len(g) < 2:
            continue
        dt_h = g["time"].diff().dt.total_seconds().fillna(0).to_numpy() / 3600
        kwh = g["value"].to_numpy() * dt_h
        is_peak = local_hours(g["time"]).isin(peak_hours).to_numpy()
        peak += float(kwh[is_peak].sum())
        off += float(kwh[~is_peak].sum())
    return peak, off


async def _energy_cost(ctx: DataContext, start: datetime, end: datetime) -> float:
    tariff = ctx.cfg("energy.tariff")
    peak, off = _tou_kwh(ctx, _window(await ctx.frame("power_kw"), start, end))
    return peak * float(tariff["peak_rate"]) + off * float(tariff["offpeak_rate"])


@kpi("ENERGY_COST_INTENSITY")
async def energy_cost_intensity(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    vol = _volume(ctx, await _prod(ctx, start, end))
    return await _energy_cost(ctx, start, end) / vol if vol > 0 else None


@kpi("PEAK_OFFPEAK_RATIO")
async def peak_offpeak(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    peak, off = _tou_kwh(ctx, _window(await ctx.frame("power_kw"), start, end))
    return peak / off if off > 0 else None


# ---- Maintenance --------------------------------------------------------------------------
def _pumps(ctx: DataContext, asset: Asset | None) -> list[Asset]:
    if asset is not None:
        return [asset]
    return [a for a in ctx.assets.values() if a.asset_type.category == "pump"]


@kpi("MTBF")
def mtbf(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    pumps = _pumps(ctx, asset)
    ids = {p.id for p in pumps}
    if not pumps:
        return None
    failures = [w for w in ctx.work_orders if w.asset_id in ids and w.wo_type == WorkOrderType.CORRECTIVE
                and w.failure_code and start <= w.created_at <= end]
    hours = 0.0
    for p in pumps:
        since = max(start, datetime.combine(p.commissioned_at, datetime.min.time(), UTC)) if p.commissioned_at else start
        hours += max(0.0, (end - since).total_seconds() / 3600)
    return hours / len(failures) if failures else hours


@kpi("MTTR")
def mttr(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    ids = {p.id for p in _pumps(ctx, asset)} if asset else set(ctx.assets)
    rep = [(w.completed_at - w.started_at).total_seconds() / 3600 for w in ctx.work_orders
           if w.asset_id in ids and w.wo_type == WorkOrderType.CORRECTIVE and w.started_at and w.completed_at
           and start <= w.completed_at <= end]
    return float(np.mean(rep)) if rep else None


@kpi("PM_COMPLIANCE")
def pm_compliance(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    due = [w for w in ctx.work_orders if w.wo_type == WorkOrderType.PREVENTIVE and w.due_date and start <= w.due_date <= end]
    if not due:
        return None
    on_time = [w for w in due if w.completed_at and w.due_date and w.completed_at <= w.due_date]
    return len(on_time) / len(due) * 100


@kpi("EQUIPMENT_HEALTH_SCORE")
async def health_score(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    pumps = _pumps(ctx, asset)
    scores = []
    vib, temp = await ctx.frame("vibration"), await ctx.frame("bearing_temperature")
    for p in pumps:
        score = 100.0
        v = _window(vib, start, end, p)
        if not v.empty:  # ISO 10816-3 zones (mm/s RMS)
            rms = float(v["value"].mean())
            score -= 0 if rms < 2.8 else 10 if rms < 4.5 else 25 if rms < 7.1 else 45
        t = _window(temp, start, end, p)
        if not t.empty:
            bt = float(t["value"].mean())
            score -= 0 if bt < 70 else 10 if bt < 80 else 25
        eff = await pump_efficiency(ctx, start, end, p)
        if eff is not None:
            score -= 0 if eff >= 85 else 8 if eff >= 75 else 15
        last_pm = max((w.completed_at for w in ctx.work_orders if w.asset_id == p.id and w.completed_at
                       and w.wo_type == WorkOrderType.PREVENTIVE), default=None)
        if last_pm and (end - last_pm).days > 180:
            score -= 5
        open_alerts = sum(1 for a in ctx.alerts if a.asset_id == p.id and a.status in (
            "triggered", "acknowledged", "investigating", "escalated"))
        score -= min(20, open_alerts * 5)
        scores.append(max(0.0, min(100.0, score)))
    return float(np.mean(scores)) if scores else None


@kpi("CRITICAL_ALERT_RATE")
def critical_alert_rate(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    equipment = [a for a in ctx.assets.values() if a.asset_type.category not in ("site", "area")]
    if not equipment:
        return None
    crit = [a for a in ctx.alerts if a.severity == "critical" and start <= a.created_at <= end]
    months = max((end - start).days / 30, 1)
    return len(crit) / len(equipment) / months


@kpi("SPARE_PARTS_AVAILABILITY")
def spare_parts(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    critical = [p for p in ctx.parts if p.critical]
    return sum(1 for p in critical if p.quantity_on_hand >= p.min_required) / len(critical) * 100 if critical else None


# ---- Compliance ---------------------------------------------------------------------------
async def _regulated(ctx: DataContext, start: datetime, end: datetime) -> list[tuple[RegulatoryLimit, pd.DataFrame]]:
    return [(lim, _window(await ctx.frame(param), start, end)) for param, lim in ctx.limits.items()]


@kpi("REGULATORY_COMPLIANCE_RATE")
async def regulatory_compliance(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    ok = total = 0
    for lim, df in await _regulated(ctx, start, end):
        if df.empty:
            continue
        v = df["value"]
        good = pd.Series(True, index=v.index)
        if lim.limit_min is not None:
            good &= v >= lim.limit_min
        if lim.limit_max is not None:
            good &= v <= lim.limit_max
        ok += int(good.sum())
        total += len(v)
    return ok / total * 100 if total else None


@kpi("SAMPLE_COLLECTION_COVERAGE")
async def sample_coverage(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    days = max((end - start).total_seconds() / 86400, 1 / 24)
    actual = required = 0.0
    for lim, df in await _regulated(ctx, start, end):
        tags = max(df["tag_id"].nunique(), 1) if not df.empty else 1
        req = lim.required_samples_per_day * days * tags
        required += req
        actual += min(len(df), req)
    return actual / required * 100 if required else None


@kpi("REPORT_SUBMISSION_TIMELINESS")
def report_timeliness(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    due = [(r, r.due_at) for r in ctx.reports if r.due_at and start <= r.due_at <= end]
    if not due:
        return None
    on_time = [r for r, deadline in due if (done := r.submitted_at or r.completed_at) is not None and done <= deadline]
    return len(on_time) / len(due) * 100


@kpi("AUDIT_FINDING_RESOLUTION_TIME")
def audit_resolution(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    findings = [w for w in ctx.work_orders if w.wo_type == WorkOrderType.AUDIT_FINDING and w.created_at >= start]
    if not findings:
        return None
    return float(np.mean([((w.completed_at or end) - w.created_at).total_seconds() / 86400 for w in findings]))


# ---- Financial ----------------------------------------------------------------------------
async def _chemical_cost(ctx: DataContext, start: datetime, end: datetime) -> float:
    total = 0.0
    for param, price in ctx.cfg("chemicals.prices_per_kg").items():
        total += _integrate_m3(_window(await ctx.frame(param), start, end)) * float(price)
    return total


@kpi("OM_COST_PER_UNIT")
async def om_cost(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    vol = _volume(ctx, await _prod(ctx, start, end))
    if vol <= 0:
        return None
    maint = sum(w.cost or 0 for w in ctx.work_orders if w.completed_at and start <= w.completed_at <= end)
    labour = sum((w.labor_hours or 0) * 55 for w in ctx.work_orders if w.completed_at and start <= w.completed_at <= end)
    return (await _energy_cost(ctx, start, end) + await _chemical_cost(ctx, start, end) + maint + labour) / vol


@kpi("CHEMICAL_COST_INTENSITY")
async def chemical_cost(ctx: DataContext, start: datetime, end: datetime, asset: Asset | None) -> float | None:
    vol = _volume(ctx, await _prod(ctx, start, end))
    return await _chemical_cost(ctx, start, end) / vol if vol > 0 else None


# ---- Custom KPIs created through POST /kpis -------------------------------------------------
CUSTOM_FORMULA = re.compile(r"^\s*(avg|min|max|sum|count|time_weighted)\(\s*([a-z_]+)\s*\)\s*$")


async def custom_kpi(ctx: DataContext, kd: KPIDefinition, start: datetime, end: datetime) -> float | None:
    """User-defined KPI whose formula is ``<aggregation>(<telemetry parameter>)``, e.g. ``avg(ph)``."""
    match = CUSTOM_FORMULA.match(kd.formula)
    if not match:
        return None
    agg, param = match.groups()
    df = _window(await ctx.frame(param), start, end)
    if df.empty:
        return None
    if agg == "time_weighted":
        return _integrate_m3(df) / max((end - start).total_seconds() / 3600, 1e-9)
    return float(getattr(df["value"], {"avg": "mean"}.get(agg, agg))())


# ---- status & normalisation ----------------------------------------------------------------
def classify(kd: KPIDefinition, value: float) -> str:
    w, c = kd.threshold_warning, kd.threshold_critical
    if kd.higher_is_better:
        if c is not None and value < c:
            return "critical"
        if w is not None and value < w:
            return "warning"
    else:
        if c is not None and value > c:
            return "critical"
        if w is not None and value > w:
            return "warning"
    return "normal"


def normalize(kd: KPIDefinition, value: float) -> float | None:
    """Map a KPI value to 0-100 (100 = best) so heterogeneous KPIs can be averaged."""
    w, c = kd.threshold_warning, kd.threshold_critical
    if w is None or c is None or w == c:
        return 100.0 if kd.unit == "%" and value >= 100 else (float(np.clip(value, 0, 100)) if kd.unit == "%" else None)
    span = abs(w - c)
    sign = 1 if kd.higher_is_better else -1
    d_w = sign * (value - w)
    if d_w >= 0:
        score = 70 + 30 * min(1.0, d_w / span)
    else:
        d_c = sign * (value - c)
        score = 40 + 30 * (d_c / span) if d_c >= 0 else 40 * max(0.0, 1 + d_c / span)
    return float(np.clip(score, 0, 100))


class KPIEngine:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compute_site(self, site: Asset, at: datetime, ctx: DataContext | None = None,
                           codes: list[str] | None = None, raise_alerts: bool = True) -> list[dict[str, Any]]:
        defs = list((await self.session.execute(select(KPIDefinition))).scalars())
        if codes:
            defs = [d for d in defs if d.code in codes]
        ctx = ctx or await DataContext.load(self.session, site, at - timedelta(days=31), at)
        rows: list[dict[str, Any]] = []
        for kd in defs:
            meta = KPI_BY_CODE.get(kd.code, {})
            window = timedelta(hours=meta.get("window_h", max(1, int(kd.computation_interval.total_seconds() // 3600))))
            start = at - window
            targets: list[Asset | None] = [None]
            if meta.get("scope") == "asset":
                targets += [a for a in ctx.assets.values() if a.asset_type.category == "pump"]
            for target in targets:
                with kpi_computation_duration.labels(kd.category).time():
                    try:
                        fn = REGISTRY.get(kd.code)
                        if fn is None:
                            value = await custom_kpi(ctx, kd, start, at)
                        else:
                            result = fn(ctx, start, at, target)
                            value = await result if inspect.isawaitable(result) else result
                    except Exception as exc:  # noqa: BLE001 - one KPI must not stop the batch
                        log.warning("kpi_failed", kpi=kd.code, error=str(exc))
                        value = None
                if value is None or not np.isfinite(value):
                    continue
                rows.append({"time": at, "kpi_id": kd.id, "asset_id": (target or site).id, "value": round(float(value), 6),
                             "normalized_value": normalize(kd, value), "status": classify(kd, value),
                             "period_start": start, "_kd": kd, "_target": target})
        if rows:
            stmt = insert(KPIValue).values([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
            stmt = stmt.on_conflict_do_update(index_elements=["time", "kpi_id", "asset_id"], set_={
                "value": stmt.excluded.value, "normalized_value": stmt.excluded.normalized_value,
                "status": stmt.excluded.status})
            await self.session.execute(stmt)
        if raise_alerts:
            await self._alert_on_critical(site, [r for r in rows if r["status"] == "critical"])
        return rows

    async def _alert_on_critical(self, site: Asset, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        from app.services.alert_service import AlertService

        svc = AlertService(self.session)
        for r in rows:
            kd: KPIDefinition = r["_kd"]
            target: Asset | None = r["_target"]
            await svc.raise_alert(rule=None, asset=target or site, title=f"KPI critical: {kd.name}",
                                  severity="major", source="kpi", trigger_value=r["value"],
                                  threshold_value=kd.threshold_critical,
                                  message=f"{kd.name} = {r['value']:.3f} {kd.unit} breached critical threshold "
                                          f"{kd.threshold_critical}. {kd.alert_condition or ''}",
                                  context={"kpi_code": kd.code})

    async def run(self, at: datetime | None = None, codes: list[str] | None = None) -> int:
        at = (at or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
        sites = list((await self.session.execute(select(Asset).where(Asset.parent_id.is_(None)))).unique().scalars())
        total = 0
        for site in sites:
            rows = await self.compute_site(site, at, codes=codes)
            total += len(rows)
            await get_event_bus().publish(KPIS_COMPUTED, envelope("kpis.computed", {
                "site_id": str(site.id), "time": at.isoformat(), "count": len(rows)}), key=str(site.id))
        await get_cache().delete_pattern("kpi:*")  # Table 9.1 write-invalidate on recompute
        await self.session.commit()
        return total

    async def backfill(self, site: Asset, start: datetime, end: datetime, step: timedelta = timedelta(hours=1)) -> int:
        ctx = await DataContext.load(self.session, site, start - timedelta(days=31), end)
        t = start.replace(minute=0, second=0, microsecond=0)
        n = 0
        while t <= end:
            n += len(await self.compute_site(site, t, ctx=ctx, raise_alerts=False))
            t += step
        await self.session.commit()
        return n
