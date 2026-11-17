from __future__ import annotations

from app.models.work_order import WorkOrder
from app.repositories.base import BaseRepository


class WorkOrderRepository(BaseRepository[WorkOrder]):
    model = WorkOrder
    default_order = (WorkOrder.created_at.desc(),)
    sortable = {"created_at": WorkOrder.created_at, "priority": WorkOrder.priority, "due_date": WorkOrder.due_date,
                "status": WorkOrder.status}
