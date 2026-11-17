"""Compliance engine (Ch. 3.3.3, Use Case 4, endpoints #70-72).

Compares regulated parameters with ``regulatory_limits`` (MCL/MRDL per SDWA) and
summarises daily / monthly compliance, sample coverage and exceedances.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.report_repository import RegulatoryLimitRepository


class ComplianceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, start: datetime, end: datetime, bucket: str = "day") -> dict[str, Any]:
        limits = {r.parameter: r for r in await RegulatoryLimitRepository(self.session).all()}
        if not limits:
            return {"period": {"start": start, "end": end}, "parameters": [], "overall_compliance_pct": None}
        trunc = "day" if bucket == "day" else "month"
        sql = text(f"""
            SELECT date_trunc('{trunc}', td.time) AS period, tt.parameter,
                   count(*) AS samples, min(td.value) AS min_value, max(td.value) AS max_value,
                   avg(td.value) AS avg_value,
                   count(*) FILTER (WHERE (rl.limit_max IS NOT NULL AND td.value > rl.limit_max)
                                       OR (rl.limit_min IS NOT NULL AND td.value < rl.limit_min)) AS exceedances,
                   count(*) FILTER (WHERE td.quality < 192) AS suspect_readings
            FROM telemetry_data td
            JOIN telemetry_tags tt ON tt.id = td.tag_id
            JOIN regulatory_limits rl ON rl.parameter = tt.parameter
            WHERE td.time >= :s AND td.time < :e AND td.status <> 'bad'
            GROUP BY 1, 2 ORDER BY 1, 2""")
        rows = [dict(r._mapping) for r in await self.session.execute(sql, {"s": start, "e": end})]
        days = max((end - start).total_seconds() / 86400, 1)
        params: dict[str, dict[str, Any]] = {}
        for r in rows:
            p = params.setdefault(r["parameter"], {
                "parameter": r["parameter"], "display_name": limits[r["parameter"]].display_name,
                "unit": limits[r["parameter"]].unit, "limit_min": limits[r["parameter"]].limit_min,
                "limit_max": limits[r["parameter"]].limit_max, "regulation": limits[r["parameter"]].regulation,
                "samples": 0, "exceedances": 0, "suspect_readings": 0, "min_value": None, "max_value": None,
                "series": []})
            p["samples"] += r["samples"]
            p["exceedances"] += r["exceedances"]
            p["suspect_readings"] += r["suspect_readings"]
            p["min_value"] = r["min_value"] if p["min_value"] is None else min(p["min_value"], r["min_value"])
            p["max_value"] = r["max_value"] if p["max_value"] is None else max(p["max_value"], r["max_value"])
            p["series"].append({"period": r["period"].isoformat(), "samples": r["samples"],
                                "exceedances": r["exceedances"], "avg_value": round(r["avg_value"], 4)})
        total = sum(p["samples"] for p in params.values())
        exceed = sum(p["exceedances"] for p in params.values())
        for p in params.values():
            lim = limits[p["parameter"]]
            required = lim.required_samples_per_day * days
            p["compliance_pct"] = round((1 - p["exceedances"] / p["samples"]) * 100, 3) if p["samples"] else None
            p["coverage_pct"] = round(min(100.0, p["samples"] / required * 100), 2) if required else None
            p["status"] = "compliant" if p["exceedances"] == 0 else "exceedance"
        return {
            "period": {"start": start.isoformat(), "end": end.isoformat(), "bucket": bucket},
            "overall_compliance_pct": round((1 - exceed / total) * 100, 3) if total else None,
            "total_samples": total, "total_exceedances": exceed, "parameters": list(params.values()),
        }

    async def daily(self, day: date | None = None) -> dict[str, Any]:
        day = day or datetime.now(UTC).date()
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        return await self.summary(start, start + timedelta(days=1), "day")

    async def monthly(self, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        now = datetime.now(UTC)
        y, m = year or now.year, month or now.month
        start = datetime(y, m, 1, tzinfo=UTC)
        end = datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=UTC)
        return await self.summary(start, end, "day")

    async def exceedances(self, start: datetime, end: datetime, parameter: str | None = None,
                          limit: int = 500) -> list[dict[str, Any]]:
        sql = text("""
            SELECT td.time, td.value, td.quality, tt.external_id AS tag, tt.parameter, tt.unit,
                   a.id AS asset_id, a.name AS asset_name, a.path,
                   rl.limit_min, rl.limit_max, rl.regulation,
                   CASE WHEN rl.limit_max IS NOT NULL AND td.value > rl.limit_max THEN 'above_max' ELSE 'below_min' END AS type
            FROM telemetry_data td
            JOIN telemetry_tags tt ON tt.id = td.tag_id
            JOIN assets a ON a.id = tt.asset_id
            JOIN regulatory_limits rl ON rl.parameter = tt.parameter
            WHERE td.time >= :s AND td.time < :e AND td.status <> 'bad'
              AND ((rl.limit_max IS NOT NULL AND td.value > rl.limit_max)
                OR (rl.limit_min IS NOT NULL AND td.value < rl.limit_min))
              AND (CAST(:p AS text) IS NULL OR tt.parameter = :p)
            ORDER BY td.time DESC LIMIT :lim""")
        rows = await self.session.execute(sql, {"s": start, "e": end, "p": parameter, "lim": limit})
        return [dict(r._mapping) for r in rows]
