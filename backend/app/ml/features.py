"""Feature engineering (Ch. 10.4) shared by training and online inference.

Using one function for both paths removes training/serving skew. Features:
* rolling statistics (mean/std/max over 6 h and 24 h), rate of change, lags
* cyclical calendar encodings (hour, day-of-week sin/cos, weekend flag)
* domain features: hydraulic efficiency vs BEP, specific energy, residence time,
  hours since last preventive maintenance
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import local_times
from app.models.asset import Asset, AssetType
from app.models.enums import WorkOrderType
from app.models.work_order import WorkOrder

PUMP_PARAMS = ["flow", "discharge_pressure", "power_kw", "power_factor", "vibration", "bearing_temperature",
               "motor_current", "run_status"]
LOOKBACK_H = 8 * 24  # covers the 7-day per-pump vibration baseline
PUMP_FEATURES = [
    "vibration_mean_6h", "vibration_std_6h", "vibration_max_24h", "vibration_trend_24h",
    "bearing_temperature_mean_6h", "bearing_temperature_roc_6h", "motor_current_mean_6h",
    "power_factor_mean_6h", "efficiency_index_6h", "flow_mean_6h", "runtime_frac_24h",
    "vibration_vs_baseline_7d", "hours_since_pm", "hour_sin", "hour_cos",
]
ANOMALY_FEATURES = ["vibration_mean_6h", "vibration_std_6h", "vibration_max_24h", "bearing_temperature_mean_6h",
                    "motor_current_mean_6h", "power_factor_mean_6h", "efficiency_index_6h", "flow_mean_6h",
                    "bearing_temperature_roc_6h"]


async def _wide(session: AsyncSession, asset_ids: list[uuid.UUID], params: list[str], start: datetime,
                end: datetime, freq: str = "1h") -> pd.DataFrame:
    sql = text("""
        SELECT date_trunc('hour', td.time) AS time, tt.asset_id, tt.parameter, avg(td.value) AS value
        FROM telemetry_data td JOIN telemetry_tags tt ON tt.id = td.tag_id
        WHERE tt.asset_id = ANY(:a) AND tt.parameter = ANY(:p) AND td.time >= :s AND td.time < :e AND td.status <> 'bad'
        GROUP BY 1, 2, 3""")
    rows = (await session.execute(sql, {"a": asset_ids, "p": params, "s": start, "e": end})).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time", "asset_id", "parameter", "value"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.pivot_table(index=["asset_id", "time"], columns="parameter", values="value").reset_index()


def _cyclical(df: pd.DataFrame) -> pd.DataFrame:
    local = local_times(df["time"])  # plant clock: demand, staffing and weekends follow local time
    h = local.dt.hour
    df["hour_sin"], df["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    dow = local.dt.dayofweek
    df["dow_sin"], df["dow_cos"] = np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7)
    df["is_weekend"] = (dow >= 5).astype(int)
    return df


async def pump_assets(session: AsyncSession, asset_id: uuid.UUID | None = None) -> list[Asset]:
    stmt = select(Asset).join(AssetType).where(AssetType.category == "pump")
    if asset_id:
        stmt = stmt.where(Asset.id == asset_id)
    return list((await session.execute(stmt)).unique().scalars())


async def pump_features(session: AsyncSession, start: datetime, end: datetime,
                        asset_id: uuid.UUID | None = None) -> pd.DataFrame:
    pumps = await pump_assets(session, asset_id)
    if not pumps:
        return pd.DataFrame()
    raw = await _wide(session, [p.id for p in pumps], PUMP_PARAMS, start - timedelta(hours=LOOKBACK_H), end)
    if raw.empty:
        return raw
    pms = (await session.execute(select(WorkOrder.asset_id, WorkOrder.completed_at).where(
        WorkOrder.wo_type == WorkOrderType.PREVENTIVE, WorkOrder.completed_at.is_not(None)))).all()
    bep = {p.id: float((p.metadata_ or {}).get("bep_efficiency", 0.82)) for p in pumps}
    frames = []
    for aid, g in raw.groupby("asset_id"):
        g = g.sort_values("time").set_index("time").asfreq("1h").reset_index()
        g["asset_id"] = aid
        for col in PUMP_PARAMS:
            if col not in g:
                g[col] = np.nan
        g[PUMP_PARAMS] = g[PUMP_PARAMS].ffill(limit=2)
        running = g["power_kw"].fillna(0) > 5
        eta = 9.81 * (g["flow"] / 3600) * (g["discharge_pressure"] * 10.197) / g["power_kw"].where(running)
        g["efficiency_index"] = (eta / bep[aid] * 100).clip(0, 130)
        # vibration / temperature only meaningful while running
        for col in ("vibration", "bearing_temperature", "motor_current", "power_factor", "flow"):
            g[col] = g[col].where(running)
        roll6 = g.rolling(6, min_periods=2)
        g["vibration_mean_6h"] = roll6["vibration"].mean()
        g["vibration_std_6h"] = roll6["vibration"].std()
        g["vibration_max_24h"] = g["vibration"].rolling(24, min_periods=3).max()
        g["vibration_trend_24h"] = g["vibration"].rolling(24, min_periods=6).mean() - g["vibration"].rolling(
            24, min_periods=6).mean().shift(24)
        # each pump against its own recent normal: early wear shows as a ratio before absolute limits are crossed
        vib24 = g["vibration"].rolling(24, min_periods=6).mean()
        g["vibration_vs_baseline_7d"] = vib24 / g["vibration"].rolling(168, min_periods=48).quantile(0.25).shift(24)
        g["bearing_temperature_mean_6h"] = roll6["bearing_temperature"].mean()
        g["bearing_temperature_roc_6h"] = g["bearing_temperature_mean_6h"].diff(6)
        g["motor_current_mean_6h"] = roll6["motor_current"].mean()
        g["power_factor_mean_6h"] = roll6["power_factor"].mean()
        g["efficiency_index_6h"] = roll6["efficiency_index"].mean()
        g["flow_mean_6h"] = roll6["flow"].mean()
        g["runtime_frac_24h"] = g["run_status"].rolling(24, min_periods=1).mean()
        last_pm = sorted(t for a, t in pms if a == aid)
        times = g["time"]
        g["hours_since_pm"] = [
            ((t - pd.Timestamp(max([p for p in last_pm if p <= t], default=t - pd.Timedelta(days=60)))).total_seconds() / 3600)
            for t in times]
        frames.append(g)
    df = _cyclical(pd.concat(frames, ignore_index=True))
    df = df[(df["time"] >= pd.Timestamp(start)) & (df["time"] < pd.Timestamp(end))]
    return df.dropna(subset=["vibration_mean_6h", "bearing_temperature_mean_6h"]).reset_index(drop=True)


async def failure_labels(session: AsyncSession, df: pd.DataFrame, horizon_days: int = 7) -> pd.Series:
    """Label = 1 if a corrective work order with a failure code starts within ``horizon_days``."""
    rows = (await session.execute(select(WorkOrder.asset_id, WorkOrder.started_at).where(
        WorkOrder.wo_type == WorkOrderType.CORRECTIVE, WorkOrder.failure_code.is_not(None),
        WorkOrder.started_at.is_not(None)))).all()
    failures: dict[uuid.UUID, list[pd.Timestamp]] = {}
    for aid, t in rows:
        failures.setdefault(aid, []).append(pd.Timestamp(t))
    h = pd.Timedelta(days=horizon_days)
    return pd.Series([int(any(0 <= (f - t).total_seconds() <= h.total_seconds() for f in failures.get(a, [])))
                      for a, t in zip(df["asset_id"], df["time"], strict=True)], index=df.index)


async def demand_series(session: AsyncSession, site: Asset, start: datetime, end: datetime) -> pd.DataFrame:
    sql = text("""
        SELECT date_trunc('hour', td.time) AS time, tt.parameter, avg(td.value) AS value
        FROM telemetry_data td JOIN telemetry_tags tt ON tt.id = td.tag_id JOIN assets a ON a.id = tt.asset_id
        WHERE (a.path = :p OR a.path LIKE :l) AND tt.parameter IN ('production_flow', 'ambient_temperature')
          AND td.time >= :s AND td.time < :e AND td.status <> 'bad'
        GROUP BY 1, 2""")
    rows = (await session.execute(sql, {"p": site.path, "l": f"{site.path}/%", "s": start, "e": end})).all()
    df = pd.DataFrame(rows, columns=["time", "parameter", "value"])
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"], utc=True)
    w = df.pivot_table(index="time", columns="parameter", values="value").asfreq("1h").interpolate(limit=3)
    return w.rename(columns={"production_flow": "demand", "ambient_temperature": "temperature"}).reset_index()


def demand_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Lags of a day or more only: the first 24 forecast steps then use observed values, and longer horizons
    # recurse in day-sized strides instead of compounding hour-on-hour errors.
    for lag in (24, 48, 168):
        df[f"lag_{lag}"] = df["demand"].shift(lag)
    df["rolling_24h"] = df["demand"].shift(24).rolling(24, min_periods=12).mean()
    df["rolling_7d"] = df["demand"].shift(24).rolling(168, min_periods=24).mean()
    df["same_hour_last_week"] = df["demand"].shift(168)
    # Relative inputs for the change-vs-last-week model: what has moved since last week, not absolute levels
    # (absolute levels let the model memorise the season it was trained in).
    df["level_change_vs_last_week"] = df["rolling_24h"] - df["rolling_24h"].shift(168)
    df["yesterday_change_vs_last_week"] = df["lag_24"] - df["lag_24"].shift(168)
    df["temp_change_vs_last_week"] = df["temperature"] - df["temperature"].shift(168)
    return _cyclical(df)


# The model predicts demand - lag_168 (see models.train_demand); lag_168 is the base, not a model input.
DEMAND_FEATURES = ["level_change_vs_last_week", "yesterday_change_vs_last_week", "temp_change_vs_last_week",
                   "temperature", "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend"]


async def site_hourly(session: AsyncSession, site: Asset, params: list[str], start: datetime,
                      end: datetime) -> pd.DataFrame:
    """Hourly site-level frame, summing additive quantities and averaging the rest."""
    additive = {"power_kw", "production_flow", "run_status"}
    sql = text("""
        SELECT date_trunc('hour', td.time) AS time, tt.parameter, tt.asset_id, avg(td.value) AS value
        FROM telemetry_data td JOIN telemetry_tags tt ON tt.id = td.tag_id JOIN assets a ON a.id = tt.asset_id
        WHERE (a.path = :p OR a.path LIKE :l) AND tt.parameter = ANY(:params) AND td.time >= :s AND td.time < :e
          AND td.status <> 'bad'
        GROUP BY 1, 2, 3""")
    rows = (await session.execute(sql, {"p": site.path, "l": f"{site.path}/%", "params": params, "s": start, "e": end})).all()
    df = pd.DataFrame(rows, columns=["time", "parameter", "asset_id", "value"])
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"], utc=True)
    parts = []
    for param, g in df.groupby("parameter"):
        agg = g.groupby("time")["value"].sum() if param in additive else g.groupby("time")["value"].mean()
        parts.append(agg.rename(param))
    return pd.concat(parts, axis=1).sort_index().reset_index()
