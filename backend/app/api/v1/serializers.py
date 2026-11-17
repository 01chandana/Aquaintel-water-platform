"""Small ORM -> response helpers shared by routers."""

from __future__ import annotations

from typing import Any

from app.models.alert import Alert
from app.models.work_order import WorkOrder
from app.schemas.alert import AlertDetail, AlertOut, RuleOut
from app.schemas.work_order import WorkOrderOut


def alert_out(a: Alert) -> dict[str, Any]:
    out = AlertOut.model_validate(a).model_dump(mode="json")
    out["asset_name"] = a.asset.name if a.asset else None
    out["asset_path"] = a.asset.path if a.asset else None
    return out


def alert_detail(a: Alert) -> dict[str, Any]:
    out = AlertDetail.model_validate(a).model_dump(mode="json")
    out["asset_name"] = a.asset.name if a.asset else None
    out["asset_path"] = a.asset.path if a.asset else None
    out["rule"] = RuleOut.model_validate(a.rule).model_dump(mode="json") if a.rule else None
    return out


def wo_out(w: WorkOrder) -> dict[str, Any]:
    out = WorkOrderOut.model_validate(w).model_dump(mode="json")
    out["asset_name"] = w.asset.name if w.asset else None
    return out
