"""Time-series data access.

The aggregate query router picks the cheapest source for a requested interval:

* interval >= 1 hour  -> ``telemetry_hourly`` continuous aggregate (pre-computed)
* interval <  1 hour  -> ``time_bucket`` on the raw hypertable (TimescaleDB) or
  ``date_bin`` (plain PostgreSQL 14+) when the extension is unavailable
* ``gapfill=True``    -> ``time_bucket_gapfill`` + ``locf`` (Ch. 4.4.2 gap-filling)
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.db import session as db_session
from app.models.asset import Asset
from app.models.telemetry import TelemetryData, TelemetryTag
from app.repositories.base import BaseRepository


class TagRepository(BaseRepository[TelemetryTag]):
    model = TelemetryTag
    default_order = (TelemetryTag.external_id.asc(),)

    async def by_external_ids(self, ids: Sequence[str]) -> dict[str, TelemetryTag]:
        if not ids:
            return {}
        rows = (await self.session.execute(select(TelemetryTag).where(TelemetryTag.external_id.in_(set(ids))))).unique().scalars()
        return {t.external_id: t for t in rows}

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, TelemetryTag]:
        if not ids:
            return {}
        rows = (await self.session.execute(select(TelemetryTag).where(TelemetryTag.id.in_(set(ids))))).unique().scalars()
        return {t.id: t for t in rows}

    async def for_asset(self, asset_id: uuid.UUID) -> list[TelemetryTag]:
        return await self.all(TelemetryTag.asset_id == asset_id)

    async def for_assets(self, asset_ids: Sequence[uuid.UUID]) -> list[TelemetryTag]:
        return await self.all(TelemetryTag.asset_id.in_(list(asset_ids)))

    async def by_parameter(self, parameter: str, path_prefix: str | None = None) -> list[TelemetryTag]:
        stmt = select(TelemetryTag).join(Asset, Asset.id == TelemetryTag.asset_id).where(
            TelemetryTag.parameter == parameter
        )
        if path_prefix:
            stmt = stmt.where((Asset.path == path_prefix) | Asset.path.like(f"{path_prefix}/%"))
        return list((await self.session.execute(stmt)).unique().scalars().all())


class TelemetryRepository:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def bulk_insert(self, rows: list[dict[str, Any]]) -> int:
        """Idempotent batch insert: duplicate (time, tag_id) points from at-least-once delivery are ignored."""
        if not rows:
            return 0
        total = 0
        for start in range(0, len(rows), 5000):
            stmt = insert(TelemetryData).values(rows[start:start + 5000]).on_conflict_do_nothing(
                index_elements=["time", "tag_id"]
            )
            result = await self.session.execute(stmt)
            total += result.rowcount or 0
        return total

    async def query(
        self, tag_ids: Sequence[uuid.UUID], start: datetime, end: datetime, limit: int = 10_000
    ) -> list[dict[str, Any]]:
        stmt = (
            select(TelemetryData.time, TelemetryData.tag_id, TelemetryData.value, TelemetryData.quality,
                   TelemetryData.status)
            .where(TelemetryData.tag_id.in_(list(tag_ids)), TelemetryData.time >= start, TelemetryData.time <= end)
            .order_by(TelemetryData.time.asc())
            .limit(limit)
        )
        return [dict(r._mapping) for r in await self.session.execute(stmt)]

    async def aggregate(
        self,
        tag_ids: Sequence[uuid.UUID],
        start: datetime,
        end: datetime,
        interval: timedelta,
        gapfill: bool = False,
    ) -> list[dict[str, Any]]:
        params = {"tags": list(tag_ids), "start": start, "end": end, "interval": interval}
        ts = db_session.timescale_enabled
        if ts and gapfill:
            sql = """
                SELECT time_bucket_gapfill(:interval, time) AS bucket, tag_id,
                       locf(avg(value)) AS avg_value, min(value) AS min_value, max(value) AS max_value,
                       count(value) AS count
                FROM telemetry_data
                WHERE tag_id = ANY(:tags) AND time >= :start AND time < :end AND status <> 'bad'
                GROUP BY bucket, tag_id ORDER BY bucket"""
        elif interval >= timedelta(hours=1) and interval % timedelta(hours=1) == timedelta(0):
            bucket = "time_bucket(:interval, bucket)" if ts else "date_bin(:interval, bucket, TIMESTAMPTZ '2000-01-01')"
            sql = f"""
                SELECT {bucket} AS b, tag_id,
                       sum(avg_value * count) / NULLIF(sum(count), 0) AS avg_value,
                       min(min_value) AS min_value, max(max_value) AS max_value, sum(count)::bigint AS count
                FROM telemetry_hourly
                WHERE tag_id = ANY(:tags) AND bucket >= :start AND bucket < :end
                GROUP BY b, tag_id ORDER BY b"""
        else:
            bucket = "time_bucket(:interval, time)" if ts else "date_bin(:interval, time, TIMESTAMPTZ '2000-01-01')"
            sql = f"""
                SELECT {bucket} AS b, tag_id, avg(value) AS avg_value, min(value) AS min_value,
                       max(value) AS max_value, count(*) AS count
                FROM telemetry_data
                WHERE tag_id = ANY(:tags) AND time >= :start AND time < :end AND status <> 'bad'
                GROUP BY b, tag_id ORDER BY b"""
        rows = await self.session.execute(text(sql), params)
        out = []
        for r in rows:
            m = dict(r._mapping)
            m["bucket"] = m.pop("b", m.get("bucket"))
            out.append(m)
        return out

    async def latest(self, tag_ids: Sequence[uuid.UUID] | None = None) -> list[dict[str, Any]]:
        where = "WHERE td.time > NOW() - INTERVAL '7 days'"
        params: dict[str, Any] = {}
        if tag_ids is not None:
            where += " AND td.tag_id = ANY(:tags)"
            params["tags"] = list(tag_ids)
        sql = f"""
            SELECT DISTINCT ON (td.tag_id) td.tag_id, td.time, td.value, td.quality, td.status
            FROM telemetry_data td {where}
            ORDER BY td.tag_id, td.time DESC"""
        return [dict(r._mapping) for r in await self.session.execute(text(sql), params)]

    async def recent_values(self, tag_id: uuid.UUID, limit: int) -> list[tuple[datetime, float]]:
        stmt = (select(TelemetryData.time, TelemetryData.value)
                .where(TelemetryData.tag_id == tag_id, TelemetryData.status != "bad")
                .order_by(TelemetryData.time.desc()).limit(limit))
        return [(r.time, r.value) for r in await self.session.execute(stmt)][::-1]

    async def count_since(self, since: datetime) -> int:
        row = await self.session.execute(text("SELECT count(*) FROM telemetry_data WHERE time >= :s"), {"s": since})
        return int(row.scalar_one())
