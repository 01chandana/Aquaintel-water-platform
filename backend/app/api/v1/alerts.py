"""Alert & rule endpoints #38-47 (Table 7.5) plus Rule Manager test/simulate and analytics."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import or_

from app.api.deps import DB, Pagination, Principal, require_permission
from app.api.v1.serializers import alert_detail, alert_out
from app.core.exceptions import ValidationError
from app.core.responses import ok, paginated
from app.models.alert import Alert, AlertRule, Incident
from app.models.asset import Asset
from app.models.enums import OPEN_ALERT_STATUSES, RuleType
from app.repositories.alert_repository import AlertRepository, AlertRuleRepository, IncidentRepository
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas.alert import (
    AlertAction,
    BulkAction,
    ResolveAction,
    RuleCreate,
    RuleOut,
    RuleSimulateRequest,
    RuleTestRequest,
    RuleUpdate,
)
from app.services import rules_engine
from app.services.alert_service import AlertService
from app.services.audit_service import AuditService
from app.services.rule_service import RuleService

router = APIRouter(prefix="/alerts", tags=["Alerts"])
READ = require_permission("alerts:read")
RULES = require_permission("alerts:rules")


# ---- static paths first -------------------------------------------------------------------
@router.get("/rules", dependencies=[RULES], summary="#43 List alert rules")
async def list_rules(db: DB, p: Pagination, asset_id: uuid.UUID | None = None, rule_type: RuleType | None = None,
                     enabled: bool | None = None, q: str | None = None) -> dict:
    f: list[Any] = []
    if asset_id:
        f.append(AlertRule.asset_id == asset_id)
    if rule_type:
        f.append(AlertRule.rule_type == rule_type)
    if enabled is not None:
        f.append(AlertRule.enabled.is_(enabled))
    if q:
        f.append(AlertRule.name.ilike(f"%{q}%"))
    items, total = await AlertRuleRepository(db).list(*f, page=p.page, per_page=p.per_page)
    return paginated([RuleOut.model_validate(r) for r in items], p.page, p.per_page, total)


@router.post("/rules", status_code=201, summary="#44 Create alert rule")
async def create_rule(body: RuleCreate, db: DB, principal: Principal = RULES) -> dict:
    return ok(RuleOut.model_validate(await RuleService(db).create(body, principal)))


@router.post("/rules/test", dependencies=[RULES], summary="Rule Manager: test a rule against sample values")
async def test_rule(body: RuleTestRequest) -> dict:
    series = [(float(i * body.interval_seconds), v) for i, v in enumerate(body.values)]
    return ok(rules_engine.replay(str(body.rule.rule_type), body.rule.condition, series))


@router.get("/analytics", dependencies=[READ], summary="Alert analytics (Ch. 13.8): MTTA, MTTR, Pareto, FPR")
async def analytics(db: DB, days: int = Query(30, ge=1, le=365)) -> dict:
    end = datetime.now(UTC)
    return ok(await AlertService(db).analytics(end - timedelta(days=days), end))


@router.get("/incidents", dependencies=[READ], summary="Correlated incidents (Use Case 6)")
async def incidents(db: DB, p: Pagination, status: str | None = "open") -> dict:
    items, total = await IncidentRepository(db).list(*([Incident.status == status] if status else []),
                                                     page=p.page, per_page=p.per_page)
    out = []
    for inc in items:
        alerts = await AlertRepository(db).all(Alert.incident_id == inc.id)
        out.append({"id": str(inc.id), "title": inc.title, "severity": str(inc.severity), "status": inc.status,
                    "alert_count": inc.alert_count, "root_cause_hint": inc.root_cause_hint,
                    "created_at": inc.created_at.isoformat(), "alerts": [alert_out(a) for a in alerts]})
    return paginated(out, p.page, p.per_page, total)


@router.post("/bulk", summary="Alert Center bulk acknowledge/resolve")
async def bulk(body: BulkAction, db: DB, principal: Principal = require_permission("alerts:acknowledge")) -> dict:
    svc = AlertService(db)
    done, failed = [], []
    for aid in body.alert_ids:
        try:
            if body.action == "acknowledge":
                await svc.acknowledge(aid, principal, body.note)
            else:
                await svc.resolve(aid, principal, body.note)
            done.append(str(aid))
        except Exception as exc:  # noqa: BLE001 - report per-item failures
            failed.append({"id": str(aid), "error": str(exc)})
    await AuditService(db).record(f"alert.bulk_{body.action}", "alert", None, principal=principal,
                                  details={"count": len(done)})
    await db.commit()
    return ok({"succeeded": done, "failed": failed})


@router.put("/rules/{rule_id}", summary="#45 Update rule")
async def update_rule(rule_id: uuid.UUID, body: RuleUpdate, db: DB, principal: Principal = RULES) -> dict:
    return ok(RuleOut.model_validate(await RuleService(db).update(rule_id, body, principal)))


@router.delete("/rules/{rule_id}", status_code=204, summary="#46 Delete rule")
async def delete_rule(rule_id: uuid.UUID, db: DB, principal: Principal = require_permission("alerts:rules:delete")) -> Response:
    await RuleService(db).delete(rule_id, principal)
    return Response(status_code=204)


@router.put("/rules/{rule_id}/toggle", summary="#47 Enable/disable rule")
async def toggle_rule(rule_id: uuid.UUID, db: DB, principal: Principal = RULES) -> dict:
    return ok(RuleOut.model_validate(await RuleService(db).toggle(rule_id, principal)))


@router.post("/rules/{rule_id}/simulate", dependencies=[RULES], summary="Rule Manager: replay history through a rule")
async def simulate_rule(rule_id: uuid.UUID, body: RuleSimulateRequest, db: DB) -> dict:
    rule = await AlertRuleRepository(db).get_or_404(rule_id, "Rule")
    if not rule.tag_id:
        raise ValidationError("Only single-tag rules can be simulated against history")
    if body.end - body.start > timedelta(days=90):
        raise ValidationError("Simulation window is limited to 90 days")
    rows = await TelemetryRepository(db).query([rule.tag_id], body.start, body.end, 100_000)
    series = [(r["time"].timestamp(), r["value"]) for r in rows if r["status"] != "bad"]
    result = rules_engine.replay(str(rule.rule_type), rule.condition, series)
    for ep in result["episodes"]:
        ep["start"] = datetime.fromtimestamp(ep["start"], UTC).isoformat()
        ep["end"] = datetime.fromtimestamp(ep["end"], UTC).isoformat() if ep["end"] else None
    return ok({**result, "points_evaluated": len(series)})


# ---- alert collection & items ---------------------------------------------------------------
@router.get("", summary="#38 List alerts with filters")
async def list_alerts(db: DB, p: Pagination, principal: Principal = READ, status: str | None = None,
                      severity: str | None = None, asset_id: uuid.UUID | None = None, source: str | None = None,
                      open_only: bool = False, q: str | None = None, sort: str | None = "-created_at",
                      start: datetime | None = None, end: datetime | None = None) -> dict:
    f: list[Any] = []
    if status:
        f.append(Alert.status.in_(status.split(",")))
    if open_only:
        f.append(Alert.status.in_(OPEN_ALERT_STATUSES))
    if severity:
        f.append(Alert.severity.in_(severity.split(",")))
    if asset_id:
        f.append(Alert.asset_id == asset_id)
    if source:
        f.append(Alert.source == source)
    if q:
        f.append(Alert.title.ilike(f"%{q}%"))
    if start:
        f.append(Alert.created_at >= start)
    if end:
        f.append(Alert.created_at <= end)
    if principal.asset_scopes:
        from sqlalchemy import select

        clauses = [Asset.path.like(s.replace("*", "%")) for s in principal.asset_scopes]
        f.append(Alert.asset_id.in_(select(Asset.id).where(or_(*clauses))))
    items, total = await AlertRepository(db).list(*f, page=p.page, per_page=p.per_page, sort=sort)
    return paginated([alert_out(a) for a in items], p.page, p.per_page, total)


@router.get("/{alert_id}", summary="#39 Get alert details")
async def get_alert(alert_id: uuid.UUID, db: DB, principal: Principal = READ) -> dict:
    alert = await AlertService(db).get(alert_id)
    if alert.asset is not None and not principal.can_access(alert.asset.path):
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"Alert {alert_id} not found")
    out = alert_detail(alert)
    if alert.tag_id:  # related telemetry around the trigger (Alert Detail page)
        t0 = alert.created_at
        out["related_telemetry"] = await TelemetryRepository(db).query([alert.tag_id], t0 - timedelta(hours=6),
                                                                      t0 + timedelta(hours=2), 2000)
    return ok(out)


@router.post("/{alert_id}/acknowledge", summary="#40 Acknowledge alert")
async def acknowledge(alert_id: uuid.UUID, body: AlertAction, db: DB,
                      principal: Principal = require_permission("alerts:acknowledge")) -> dict:
    alert = await AlertService(db).acknowledge(alert_id, principal, body.note)
    await AuditService(db).record("alert.acknowledge", "alert", alert.id, principal=principal)
    await db.commit()
    return ok(alert_detail(alert))


@router.post("/{alert_id}/resolve", summary="#41 Resolve alert")
async def resolve(alert_id: uuid.UUID, body: ResolveAction, db: DB,
                  principal: Principal = require_permission("alerts:resolve")) -> dict:
    alert = await AlertService(db).resolve(alert_id, principal, body.note, body.is_false_positive, body.close)
    await AuditService(db).record("alert.resolve", "alert", alert.id, principal=principal,
                                  details={"false_positive": body.is_false_positive})
    await db.commit()
    return ok(alert_detail(alert))


@router.post("/{alert_id}/escalate", summary="#42 Escalate alert")
async def escalate(alert_id: uuid.UUID, body: AlertAction, db: DB,
                   principal: Principal = require_permission("alerts:escalate")) -> dict:
    alert = await AlertService(db).escalate(alert_id, principal, body.note)
    await AuditService(db).record("alert.escalate", "alert", alert.id, principal=principal,
                                  details={"level": alert.escalation_level})
    await db.commit()
    return ok(alert_detail(alert))
