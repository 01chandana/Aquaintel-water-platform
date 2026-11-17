"""Asset registry, hierarchy and digital-twin metadata (Table 7.3, Ch. 3.3.3)."""

from __future__ import annotations

import builtins
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.cache import TTL_ASSET_METADATA, get_cache
from app.core.events import ASSETS_CHANGED, envelope, get_event_bus
from app.core.exceptions import ConflictError, ValidationError
from app.models.alert import Alert
from app.models.asset import Asset, AssetType
from app.models.enums import OPEN_ALERT_STATUSES
from app.repositories.asset_repository import AssetRepository, AssetTypeRepository
from app.schemas.asset import AssetCreate, AssetNode, AssetOut, AssetTypeCreate, AssetUpdate
from app.services.audit_service import AuditService
from app.services.telemetry_service import assert_scope

TREE_CACHE_KEY = "assets:tree"


class AssetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.assets = AssetRepository(session)
        self.types = AssetTypeRepository(session)
        self.audit = AuditService(session)
        self.cache = get_cache()

    async def get(self, asset_id: uuid.UUID, principal: Principal | None = None) -> Asset:
        asset = await self.assets.get_or_404(asset_id, "Asset")
        assert_scope(principal, asset)
        return asset

    async def list(self, principal: Principal, page: int, per_page: int, status: str | None,
                   type_id: uuid.UUID | None, parent_id: uuid.UUID | None, sort: str | None) -> tuple[list[Asset], int]:
        filters: list[Any] = []
        if status:
            filters.append(Asset.status == status)
        if type_id:
            filters.append(Asset.asset_type_id == type_id)
        if parent_id:
            filters.append(Asset.parent_id == parent_id)
        if principal.asset_scopes:  # ABAC asset scope (Ch. 17.3.2)
            from sqlalchemy import or_

            clauses = []
            for scope in principal.asset_scopes:
                prefix = scope.rstrip("*").rstrip("/")
                clauses.append(or_(Asset.path == prefix, Asset.path.like(f"{prefix}/%"),
                                   Asset.path.like(scope.replace("*", "%"))))
            filters.append(or_(*clauses))
        return await self.assets.list(*filters, page=page, per_page=per_page, sort=sort)

    async def tree(self, principal: Principal) -> builtins.list[dict[str, Any]]:
        """Hierarchical view (endpoint #17 ``?view=tree``) with open-alert counts, cached 5 min."""
        cached = await self.cache.get_json(TREE_CACHE_KEY)
        if cached is None:
            assets = await self.assets.all()
            counts: dict[uuid.UUID | None, int] = {aid: n for aid, n in (await self.session.execute(
                select(Alert.asset_id, func.count()).where(Alert.status.in_(OPEN_ALERT_STATUSES)).group_by(Alert.asset_id)
            )).all()}
            nodes = {a.id: AssetNode.model_validate(a).model_copy(update={"open_alerts": counts.get(a.id, 0)})
                     for a in assets}
            roots: list[AssetNode] = []
            for a in assets:
                node = nodes[a.id]
                if a.parent_id and a.parent_id in nodes:
                    nodes[a.parent_id].children.append(node)
                else:
                    roots.append(node)

            def rollup(n: AssetNode) -> int:
                n.open_alerts += sum(rollup(c) for c in n.children)
                return n.open_alerts

            for r in roots:
                rollup(r)
            cached = [r.model_dump(mode="json") for r in roots]
            await self.cache.set_json(TREE_CACHE_KEY, cached, TTL_ASSET_METADATA)
        if not principal.asset_scopes:
            return cached

        def prune(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = []
            for n in nodes:
                if principal.can_access(n["path"]):
                    out.append(n)
                else:
                    kids = prune(n["children"])
                    if kids:
                        out.append({**n, "children": kids})
            return out

        return prune(cached)

    async def _path_for(self, external_id: str, parent_id: uuid.UUID | None) -> str:
        if parent_id is None:
            return external_id
        parent = await self.assets.get_or_404(parent_id, "Parent asset")
        return f"{parent.path}/{external_id}"

    async def create(self, data: AssetCreate, principal: Principal) -> Asset:
        if await self.assets.get_by_external_id(data.external_id):
            raise ConflictError(f"Asset {data.external_id} already exists")
        await self.types.get_or_404(data.asset_type_id, "Asset type")
        path = await self._path_for(data.external_id, data.parent_id)
        if data.parent_id and not principal.can_access(path):
            raise ValidationError("Parent asset is outside your scope")
        asset = await self.assets.create(Asset(
            external_id=data.external_id, name=data.name, asset_type_id=data.asset_type_id, parent_id=data.parent_id,
            location=data.location.model_dump() if data.location else None, metadata_=data.metadata,
            status=data.status, commissioned_at=data.commissioned_at, warranty_until=data.warranty_until, path=path,
        ))
        await self._changed("asset.created", asset, principal)
        await self.session.commit()
        return asset

    async def update(self, asset_id: uuid.UUID, data: AssetUpdate, principal: Principal) -> Asset:
        asset = await self.get(asset_id, principal)
        changes = data.model_dump(exclude_unset=True)
        if "parent_id" in changes and changes["parent_id"] != asset.parent_id:
            new_parent = changes["parent_id"]
            if new_parent == asset.id:
                raise ValidationError("An asset cannot be its own parent")
            new_path = await self._path_for(asset.external_id, new_parent)
            if new_path.startswith(asset.path + "/"):
                raise ValidationError("Cannot move an asset under its own descendant")
            old_path = asset.path
            for d in await self.assets.subtree(old_path):  # re-root the materialized paths
                d.path = new_path + d.path[len(old_path):]
            asset.parent_id = new_parent
        for field in ("name", "status", "commissioned_at", "warranty_until"):
            if field in changes:
                setattr(asset, field, changes[field])
        if "location" in changes:
            asset.location = data.location.model_dump() if data.location else None
        if "metadata" in changes:
            asset.metadata_ = {**(asset.metadata_ or {}), **(data.metadata or {})}
        await self._changed("asset.updated", asset, principal, {k: str(v) for k, v in changes.items()})
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def delete(self, asset_id: uuid.UUID, principal: Principal) -> None:
        asset = await self.get(asset_id, principal)
        if await self.assets.count(Asset.parent_id == asset.id):
            raise ConflictError("Asset has child assets; move or delete them first")
        await self._changed("asset.deleted", asset, principal)
        await self.assets.delete(asset)
        await self.session.commit()

    async def children(self, asset_id: uuid.UUID, principal: Principal) -> builtins.list[Asset]:
        await self.get(asset_id, principal)
        return [a for a in await self.assets.get_children(asset_id) if principal.can_access(a.path)]

    async def search(self, q: str, principal: Principal) -> builtins.list[Asset]:
        return [a for a in await self.assets.search(q) if principal.can_access(a.path)]

    async def create_type(self, data: AssetTypeCreate, principal: Principal) -> AssetType:
        if await self.types.get_by_name(data.name):
            raise ConflictError(f"Asset type {data.name} already exists")
        t = await self.types.create(AssetType(**data.model_dump()))
        await self.audit.record("asset_type.created", "asset_type", t.id, principal=principal, details={"name": t.name})
        await self.session.commit()
        return t

    async def _changed(self, action: str, asset: Asset, principal: Principal,
                       details: dict[str, Any] | None = None) -> None:
        await self.cache.delete(TREE_CACHE_KEY)  # Table 9.1: flush asset metadata on update
        await self.audit.record(action, "asset", asset.id, principal=principal,
                                details={"external_id": asset.external_id, **(details or {})})
        await get_event_bus().publish(ASSETS_CHANGED, envelope(action, {
            "asset_id": str(asset.id), "external_id": asset.external_id, "path": asset.path}), key=str(asset.id))


def asset_out(asset: Asset) -> dict[str, Any]:
    return AssetOut.model_validate(asset).model_dump(mode="json")
