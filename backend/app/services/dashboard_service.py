"""Self-service dashboard builder (Table 7.7, roadmap week 8)."""

from __future__ import annotations

import builtins
import uuid

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.cache import TTL_DASHBOARD, get_cache
from app.core.exceptions import AuthorizationError, NotFoundError
from app.models.dashboard import Dashboard, DashboardWidget
from app.repositories.dashboard_repository import DashboardRepository
from app.schemas.dashboard import DashboardIn, DashboardOut, DashboardUpdate, WidgetIn
from app.services.audit_service import AuditService


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DashboardRepository(session)
        self.cache = get_cache()

    async def _bump(self, d: Dashboard) -> None:
        d.version += 1  # Table 9.1: dashboard config cache uses a version key
        await self.cache.delete(f"dashboard:{d.id}")

    async def list(self, principal: Principal) -> list[Dashboard]:
        return await self.repo.all(Dashboard.is_template.is_(False),
                                   or_(Dashboard.owner_id == principal.id, Dashboard.is_shared.is_(True)))

    async def templates(self) -> builtins.list[Dashboard]:
        return await self.repo.all(Dashboard.is_template.is_(True))

    async def get(self, dashboard_id: uuid.UUID, principal: Principal) -> dict:
        cached = await self.cache.get_json(f"dashboard:{dashboard_id}")
        if cached and (cached["owner_id"] == str(principal.id) or cached["is_shared"] or cached["is_template"]):
            return cached
        d = await self.repo.get_or_404(dashboard_id, "Dashboard")
        if not (d.owner_id == principal.id or d.is_shared or d.is_template):
            raise NotFoundError(f"Dashboard {dashboard_id} not found")
        out = DashboardOut.model_validate(d).model_dump(mode="json")
        await self.cache.set_json(f"dashboard:{d.id}", out, TTL_DASHBOARD)
        return out

    async def _owned(self, dashboard_id: uuid.UUID, principal: Principal) -> Dashboard:
        d = await self.repo.get_or_404(dashboard_id, "Dashboard")
        if d.owner_id != principal.id and principal.role not in ("admin", "super_admin"):
            raise AuthorizationError("Only the dashboard owner can modify it")
        return d

    async def create(self, data: DashboardIn, principal: Principal) -> Dashboard:
        d = Dashboard(owner_id=principal.id, name=data.name, description=data.description, layout=data.layout,
                      filters=data.filters, is_shared=data.is_shared)
        if data.template_id:
            tpl = await self.repo.get_or_404(data.template_id, "Template")
            d.widgets = [DashboardWidget(widget_type=w.widget_type, title=w.title, config=dict(w.config),
                                         position_index=w.position_index, width=w.width) for w in tpl.widgets]
            d.layout = d.layout or tpl.layout
        self.session.add(d)
        await self.session.flush()
        await AuditService(self.session).record("dashboard.create", "dashboard", d.id, principal=principal)
        await self.session.commit()
        await self.session.refresh(d, ["widgets"])
        return d

    async def update(self, dashboard_id: uuid.UUID, data: DashboardUpdate, principal: Principal) -> Dashboard:
        d = await self._owned(dashboard_id, principal)
        for k, v in data.model_dump(exclude_unset=True, exclude={"widget_order"}).items():
            setattr(d, k, v)
        if data.widget_order:
            order = {wid: i for i, wid in enumerate(data.widget_order)}
            for w in d.widgets:
                w.position_index = order.get(w.id, w.position_index)
        await self._bump(d)
        await self.session.commit()
        await self.session.refresh(d, ["widgets"])
        return d

    async def delete(self, dashboard_id: uuid.UUID, principal: Principal) -> None:
        d = await self._owned(dashboard_id, principal)
        await self.cache.delete(f"dashboard:{d.id}")
        await self.repo.delete(d)
        await self.session.commit()

    async def add_widget(self, dashboard_id: uuid.UUID, data: WidgetIn, principal: Principal) -> DashboardWidget:
        d = await self._owned(dashboard_id, principal)
        w = DashboardWidget(dashboard_id=d.id, **data.model_dump())
        if not data.position_index:
            w.position_index = len(d.widgets)
        self.session.add(w)
        await self._bump(d)
        await self.session.commit()
        return w

    async def update_widget(self, dashboard_id: uuid.UUID, widget_id: uuid.UUID, data: WidgetIn,
                            principal: Principal) -> DashboardWidget:
        d = await self._owned(dashboard_id, principal)
        w = next((w for w in d.widgets if w.id == widget_id), None)
        if w is None:
            raise NotFoundError(f"Widget {widget_id} not found")
        for k, v in data.model_dump().items():
            setattr(w, k, v)
        await self._bump(d)
        await self.session.commit()
        return w

    async def delete_widget(self, dashboard_id: uuid.UUID, widget_id: uuid.UUID, principal: Principal) -> None:
        d = await self._owned(dashboard_id, principal)
        w = next((w for w in d.widgets if w.id == widget_id), None)
        if w is None:
            raise NotFoundError(f"Widget {widget_id} not found")
        d.widgets.remove(w)
        await self._bump(d)
        await self.session.commit()
