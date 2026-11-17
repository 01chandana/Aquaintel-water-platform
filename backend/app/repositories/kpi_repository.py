from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.kpi import KPIDefinition, KPIValue
from app.repositories.base import BaseRepository


class KPIRepository(BaseRepository[KPIDefinition]):
    model = KPIDefinition
    default_order = (KPIDefinition.number.asc().nulls_last(), KPIDefinition.name.asc())

    async def by_code(self, code: str) -> KPIDefinition | None:
        return (await self.session.execute(select(KPIDefinition).where(KPIDefinition.code == code))).scalar_one_or_none()

    async def values(self, kpi_id: uuid.UUID, start: datetime, end: datetime,
                     asset_id: uuid.UUID | None = None, limit: int = 5000) -> list[KPIValue]:
        stmt = select(KPIValue).where(KPIValue.kpi_id == kpi_id, KPIValue.time >= start, KPIValue.time <= end)
        if asset_id:
            stmt = stmt.where(KPIValue.asset_id == asset_id)
        stmt = stmt.order_by(KPIValue.time.asc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest_values(self, kpi_id: uuid.UUID, asset_id: uuid.UUID | None, n: int = 2) -> list[KPIValue]:
        stmt = select(KPIValue).where(KPIValue.kpi_id == kpi_id)
        if asset_id:
            stmt = stmt.where(KPIValue.asset_id == asset_id)
        stmt = stmt.order_by(KPIValue.time.desc()).limit(n)
        return list((await self.session.execute(stmt)).scalars().all())
