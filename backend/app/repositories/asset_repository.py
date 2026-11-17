from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select

from app.models.asset import Asset, AssetType
from app.repositories.base import BaseRepository


class AssetRepository(BaseRepository[Asset]):
    model = Asset
    default_order = (Asset.path.asc(),)
    sortable = {"name": Asset.name, "path": Asset.path, "created_at": Asset.created_at, "status": Asset.status}

    async def get_by_external_id(self, external_id: str) -> Asset | None:
        return (await self.session.execute(select(Asset).where(Asset.external_id == external_id))).scalar_one_or_none()

    async def get_children(self, parent_id: uuid.UUID) -> list[Asset]:
        return await self.all(Asset.parent_id == parent_id)

    async def subtree(self, path: str) -> list[Asset]:
        """All descendants using the materialized path (no recursive CTE needed)."""
        return await self.all(or_(Asset.path == path, Asset.path.like(f"{path}/%")))

    async def sites(self) -> list[Asset]:
        return await self.all(Asset.parent_id.is_(None))

    async def search(self, q: str, limit: int = 25) -> list[Asset]:
        pattern = f"%{q.lower()}%"
        stmt = (
            select(Asset)
            .where(or_(func.lower(Asset.name).like(pattern), func.lower(Asset.external_id).like(pattern),
                       func.lower(Asset.path).like(pattern)))
            .order_by(Asset.path)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).unique().scalars().all())

    async def site_of(self, asset: Asset) -> Asset:
        root = asset.path.split("/", 1)[0]
        site = await self.get_by_external_id(root)
        return site or asset


class AssetTypeRepository(BaseRepository[AssetType]):
    model = AssetType
    default_order = (AssetType.category.asc(), AssetType.name.asc())

    async def get_by_name(self, name: str) -> AssetType | None:
        return (await self.session.execute(select(AssetType).where(AssetType.name == name))).scalar_one_or_none()
