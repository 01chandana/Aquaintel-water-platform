"""Work order management (Table 7.9) closing the predictive-maintenance loop (Ch. 5.3.2 step 7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.exceptions import InvalidStateTransition, ValidationError
from app.models.alert import Alert
from app.models.enums import AlertStatus, AssetStatus, WorkOrderStatus, WorkOrderType
from app.models.user import User
from app.models.work_order import WorkOrder
from app.repositories.work_order_repository import WorkOrderRepository
from app.schemas.work_order import WorkOrderAssign, WorkOrderComplete, WorkOrderCreate, WorkOrderUpdate
from app.services.audit_service import AuditService

TERMINAL = {WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED}


class WorkOrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WorkOrderRepository(session)
        self.audit = AuditService(session)

    async def _next_number(self) -> str:
        year = datetime.now(UTC).year
        n = (await self.session.execute(select(func.count()).select_from(WorkOrder))).scalar_one()
        return f"WO-{year}-{n + 1:06d}"

    async def list(self, page: int, per_page: int, status: str | None, asset_id: uuid.UUID | None,
                   assigned_to: uuid.UUID | None, wo_type: str | None, sort: str | None) -> tuple[list[WorkOrder], int]:
        filters: list[Any] = []
        if status:
            filters.append(WorkOrder.status.in_(status.split(",")))
        if asset_id:
            filters.append(WorkOrder.asset_id == asset_id)
        if assigned_to:
            filters.append(WorkOrder.assigned_to == assigned_to)
        if wo_type:
            filters.append(WorkOrder.wo_type == wo_type)
        return await self.repo.list(*filters, page=page, per_page=per_page, sort=sort)

    async def create(self, data: WorkOrderCreate, principal: Principal) -> WorkOrder:
        alert = await self.session.get(Alert, data.alert_id) if data.alert_id else None
        if data.alert_id and alert is None:
            raise ValidationError("alert_id does not exist")
        wo = await self.repo.create(WorkOrder(number=await self._next_number(), created_by=principal.user_id,
                                              status=WorkOrderStatus.OPEN, **data.model_dump()))
        if alert is not None and alert.status == AlertStatus.ACKNOWLEDGED:
            from app.services.alert_service import AlertService

            await AlertService(self.session).transition(alert, AlertStatus.INVESTIGATING, principal,
                                                        f"work order {wo.number} created")
        await self.audit.record("work_order.create", "work_order", wo.id, principal=principal,
                                details={"number": wo.number, "alert_id": str(data.alert_id) if data.alert_id else None})
        await self.session.commit()
        await self.session.refresh(wo)
        return wo

    async def update(self, wo_id: uuid.UUID, data: WorkOrderUpdate, principal: Principal) -> WorkOrder:
        wo = await self.repo.get_or_404(wo_id, "Work order")
        if wo.status in TERMINAL:
            raise InvalidStateTransition(f"Work order is {wo.status}")
        changes = data.model_dump(exclude_unset=True)
        if changes.get("status") == "in_progress":
            wo.started_at = wo.started_at or datetime.now(UTC)
            if wo.wo_type in (WorkOrderType.CORRECTIVE, WorkOrderType.PREVENTIVE):
                wo.asset.status = AssetStatus.MAINTENANCE  # suppress alerts while the asset is worked on
        for k, v in changes.items():
            setattr(wo, k, v)
        await self.audit.record("work_order.update", "work_order", wo.id, principal=principal,
                                details={k: str(v) for k, v in changes.items()})
        await self.session.commit()
        return wo

    async def assign(self, wo_id: uuid.UUID, data: WorkOrderAssign, principal: Principal) -> WorkOrder:
        wo = await self.repo.get_or_404(wo_id, "Work order")
        if wo.status in TERMINAL:
            raise InvalidStateTransition(f"Work order is {wo.status}")
        tech = await self.session.get(User, data.assigned_to)
        if tech is None or not tech.is_active:
            raise ValidationError("Assignee not found or inactive")
        wo.assigned_to = tech.id
        if wo.status == WorkOrderStatus.OPEN:
            wo.status = WorkOrderStatus.ASSIGNED
        await self.audit.record("work_order.assign", "work_order", wo.id, principal=principal,
                                details={"assigned_to": tech.email})
        await self.session.commit()
        return wo

    async def complete(self, wo_id: uuid.UUID, data: WorkOrderComplete, principal: Principal) -> WorkOrder:
        wo = await self.repo.get_or_404(wo_id, "Work order")
        if wo.status in TERMINAL:
            raise InvalidStateTransition(f"Work order is already {wo.status}")
        now = datetime.now(UTC)
        wo.status = WorkOrderStatus.COMPLETED
        wo.completed_at = now
        wo.started_at = wo.started_at or now
        wo.resolution_notes, wo.labor_hours, wo.cost = data.resolution_notes, data.labor_hours, data.cost
        if data.failure_code:
            wo.failure_code = data.failure_code  # labelled outcome feeds monthly retraining (Ch. 5.3.2 step 9)
        if wo.asset.status == AssetStatus.MAINTENANCE:
            wo.asset.status = AssetStatus.ACTIVE
        if wo.alert_id:
            alert = await self.session.get(Alert, wo.alert_id)
            if alert and alert.status not in (AlertStatus.RESOLVED, AlertStatus.CLOSED):
                from app.services.alert_service import AlertService

                await AlertService(self.session).resolve(alert.id, principal, f"resolved by {wo.number}")
        await self.audit.record("work_order.complete", "work_order", wo.id, principal=principal,
                                details={"labor_hours": data.labor_hours, "failure_code": data.failure_code})
        await self.session.commit()
        return wo
