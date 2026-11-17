"""Alert lifecycle, fatigue prevention, correlation and escalation (Ch. 13.4-13.8).

Lifecycle state machine (Figure 13.1)::

    triggered -> acknowledged -> investigating -> resolved -> closed
        |             |               |              ^
        +-> escalated-+---------------+--------------+
        +-> resolved (auto-resolve when the condition clears)

Fatigue controls (13.7): dedup of open alerts, post-resolution cooldown (flapping), flood
control (max 10 alerts/asset/hour), maintenance-mode suppression, silent hours and
suppression of lower-severity alerts when a higher one is already open on the asset.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.core.events import ALERTS_ACKNOWLEDGED, ALERTS_GENERATED, envelope, get_event_bus
from app.core.exceptions import InvalidStateTransition, NotFoundError
from app.core.logging import get_logger
from app.core.metrics import alert_generation_rate, alert_suppressed_total
from app.core.timeutil import local_hour
from app.models.alert import Alert, AlertEvent, AlertRule, Incident
from app.models.asset import Asset
from app.models.enums import OPEN_ALERT_STATUSES, SEVERITY_RANK, AlertStatus, AssetStatus, Severity
from app.repositories.alert_repository import AlertRepository, AlertRuleRepository, IncidentRepository
from app.services import rules_engine
from app.services.notification_service import NotificationService, broadcast

log = get_logger(__name__)

ALLOWED_TRANSITIONS: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.TRIGGERED: {AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED, AlertStatus.RESOLVED},
    AlertStatus.ACKNOWLEDGED: {AlertStatus.INVESTIGATING, AlertStatus.ESCALATED, AlertStatus.RESOLVED},
    AlertStatus.INVESTIGATING: {AlertStatus.ESCALATED, AlertStatus.RESOLVED},
    AlertStatus.ESCALATED: {AlertStatus.ACKNOWLEDGED, AlertStatus.INVESTIGATING, AlertStatus.RESOLVED},
    AlertStatus.RESOLVED: {AlertStatus.CLOSED, AlertStatus.TRIGGERED},  # re-trigger after resolve
    AlertStatus.CLOSED: set(),
}

# Table 13.1 escalation matrix: minutes after trigger at which each level is notified
ESCALATION_MATRIX: dict[str, list[int]] = {
    Severity.CRITICAL: [5, 5 + 15, 5 + 15 + 30],
    Severity.MAJOR: [15, 15 + 30, 15 + 30 + 60],
    Severity.MINOR: [60, 60 + 120],
    Severity.WARNING: [240],
    Severity.INFO: [],
}
FLOOD_LIMIT_PER_ASSET_HOUR = 10
CORRELATION_WINDOW = timedelta(minutes=10)


@dataclass
class AlertOutcome:
    alert: Alert | None
    created: bool
    suppressed: bool = False
    reason: str | None = None


@dataclass
class RuleEvaluation:
    triggered: bool
    severity: str
    message: str


def _now() -> datetime:
    return datetime.now(UTC)


class AlertService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.alerts = AlertRepository(session)
        self.rules = AlertRuleRepository(session)
        self.incidents = IncidentRepository(session)
        self.cache = get_cache()

    # ---- convenience API mirrored from the spec's unit test (Listing 16.1) --------------
    async def evaluate_rule(self, rule_id: str, telemetry_value: float, threshold: float,
                            operator: str, severity: str = "critical") -> RuleEvaluation:
        result = rules_engine.evaluate_threshold({"operator": operator, "value": threshold},
                                                 telemetry_value, _now().timestamp(), {})
        return RuleEvaluation(result.triggered, severity, result.message)

    async def create_alert(self, asset_id: Any, rule_id: Any, **kwargs: Any) -> AlertOutcome:
        rule = await self.rules.get(rule_id) if isinstance(rule_id, uuid.UUID) else None
        asset = await self.session.get(Asset, asset_id) if isinstance(asset_id, uuid.UUID) else None
        return await self.raise_alert(
            rule=rule, asset=asset, title=kwargs.get("title") or (rule.name if rule else "Manual alert"),
            severity=kwargs.get("severity") or (rule.severity if rule else Severity.WARNING),
            message=kwargs.get("message"), source=kwargs.get("source", "manual"),
            asset_id_override=None if asset else asset_id,
            context=None if rule else {"rule_ref": str(rule_id)},
        )

    # ---- creation with fatigue controls ---------------------------------------------------
    async def raise_alert(
        self,
        *,
        rule: AlertRule | None,
        asset: Asset | None,
        title: str,
        severity: Severity | str,
        message: str | None = None,
        source: str = "rule",
        tag_id: uuid.UUID | None = None,
        trigger_value: float | None = None,
        threshold_value: float | None = None,
        fault_code: str | None = None,
        context: dict[str, Any] | None = None,
        asset_id_override: Any = None,
        rule_id_override: Any = None,
    ) -> AlertOutcome:
        severity = Severity(severity)
        asset_id = asset.id if asset else asset_id_override
        rule_id = rule.id if rule else rule_id_override
        suppression = (rule.suppression if rule else None) or {}
        now = _now()

        # 1) maintenance mode
        if asset is not None and asset.status == AssetStatus.MAINTENANCE and suppression.get(
                "suppress_if_asset_in_maintenance", True):
            alert_suppressed_total.labels("maintenance").inc()
            return AlertOutcome(None, False, True, "asset_in_maintenance")

        # 2) dedup against an open alert for the same rule/asset
        dedup_key = f"dedup:{rule_id}:{asset_id}:{source}"
        existing = await self._open_alert(rule_id, asset_id, source, title)
        if existing is None and await self.cache.exists(dedup_key):
            existing = await self._open_alert(rule_id, asset_id, source, title)
        if existing is not None:
            existing.occurrence_count += 1
            existing.last_triggered_at = now
            if trigger_value is not None:
                existing.trigger_value = trigger_value
            await self.session.flush()
            alert_suppressed_total.labels("dedup").inc()
            return AlertOutcome(existing, False, True, "duplicate")

        # 3) cooldown after resolution (flapping protection)
        cooldown = (rule.cooldown_minutes if rule else 15) or 0
        if cooldown and await self.cache.exists(f"cooldown:{rule_id}:{asset_id}"):
            alert_suppressed_total.labels("cooldown").inc()
            return AlertOutcome(None, False, True, "cooldown")

        # 4) flood control
        hour_key = f"flood:{asset_id}:{now:%Y%m%d%H}"
        if await self.cache.incr(hour_key, 3600) > FLOOD_LIMIT_PER_ASSET_HOUR:
            alert_suppressed_total.labels("flood").inc()
            return AlertOutcome(None, False, True, "flood_control")

        alert = Alert(
            rule_id=rule_id, asset_id=asset_id, tag_id=tag_id, severity=severity, title=title[:250],
            message=message, source=source, trigger_value=trigger_value, threshold_value=threshold_value,
            fault_code=fault_code, context=context, last_triggered_at=now,
            status=AlertStatus.TRIGGERED, events=[AlertEvent(from_status=None, to_status="triggered", actor="system",
                                                             note=message)],
        )
        self.session.add(alert)
        await self.session.flush()
        await self.cache.set_json(dedup_key, str(alert.id), 120)

        # 5) suppress lower-severity alerts when a higher one is already open (13.2.4)
        skip_external = False
        if asset_id is not None:
            open_sev = [a.severity for a in await self.alerts.all(
                Alert.asset_id == asset_id, Alert.id != alert.id, Alert.status.in_(OPEN_ALERT_STATUSES))]
            if open_sev and max(SEVERITY_RANK[Severity(s)] for s in open_sev) > SEVERITY_RANK[severity]:
                alert.suppressed = True
                skip_external = True
        if suppression.get("suppress_during_silent_hours") and await self._in_silent_hours(now):
            skip_external = True

        # 6) correlation into incidents (Use Case 6)
        if asset is not None:
            await self._correlate(alert, asset)

        alert_generation_rate.labels(severity=str(severity), rule_type=str(rule.rule_type) if rule else source).inc()
        await get_event_bus().publish(ALERTS_GENERATED, envelope("alert.generated", {
            "alert_id": str(alert.id), "asset_id": str(asset_id) if asset_id else None,
            "severity": str(severity), "title": alert.title, "source": source}, source="alert-service"),
            key=str(asset_id) if asset_id else None)
        await NotificationService(self.session).dispatch(alert, rule, level=0, skip_external=skip_external)
        return AlertOutcome(alert, True, alert.suppressed, "lower_severity" if alert.suppressed else None)

    async def _open_alert(self, rule_id: Any, asset_id: Any, source: str, title: str) -> Alert | None:
        if rule_id is None:
            stmt = select(Alert).where(Alert.asset_id == asset_id, Alert.rule_id.is_(None), Alert.title == title[:250],
                                       Alert.status.in_(OPEN_ALERT_STATUSES))
            return (await self.session.execute(stmt.limit(1))).unique().scalar_one_or_none()
        return await self.alerts.open_for(rule_id, asset_id, None)

    async def _in_silent_hours(self, now: datetime) -> bool:
        from app.models.system import SystemConfig

        cfg = await self.session.get(SystemConfig, "alerts.silent_hours")
        if not cfg or not cfg.value:
            return False
        start, end = int(cfg.value.get("start_hour", 0)), int(cfg.value.get("end_hour", 0))
        h = local_hour(now)
        return start <= h < end if start < end else (h >= start or h < end)

    async def _correlate(self, alert: Alert, asset: Asset) -> None:
        """Group temporally and spatially related alerts (same asset or same parent) into an incident."""
        if asset.parent_id is None:
            return
        siblings = select(Asset.id).where((Asset.parent_id == asset.parent_id) | (Asset.id == asset.parent_id))
        related = await self.alerts.all(
            Alert.asset_id.in_(siblings), Alert.id != alert.id, Alert.status.in_(OPEN_ALERT_STATUSES),
            Alert.created_at >= _now() - CORRELATION_WINDOW,
        )
        if not related:
            return
        incident_id = next((a.incident_id for a in related if a.incident_id), None)
        if incident_id:
            incident = await self.incidents.get_or_404(incident_id)
            incident.alert_count += 1
            if SEVERITY_RANK[Severity(alert.severity)] > SEVERITY_RANK[Severity(incident.severity)]:
                incident.severity = alert.severity
        else:
            first = min(related, key=lambda a: a.created_at)
            incident = Incident(
                title=f"Correlated alerts under {asset.path.rsplit('/', 1)[0]}",
                root_asset_id=asset.parent_id, severity=max(
                    [alert.severity, *[a.severity for a in related]], key=lambda s: SEVERITY_RANK[Severity(s)]),
                alert_count=len(related) + 1,
                root_cause_hint=f"Earliest event: '{first.title}' at {first.created_at:%H:%M:%S} "
                                f"on asset {first.asset_id}; downstream alerts likely consequential.",
            )
            self.session.add(incident)
            await self.session.flush()
            for a in related:
                a.incident_id = incident.id
        alert.incident_id = incident.id

    # ---- lifecycle --------------------------------------------------------------------------
    async def transition(self, alert: Alert, to: AlertStatus, actor: Any = None, note: str | None = None) -> Alert:
        current = AlertStatus(alert.status)
        if to not in ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransition(f"Cannot move alert from {current} to {to}")
        now = _now()
        actor_id = getattr(actor, "user_id", None)
        if to == AlertStatus.ACKNOWLEDGED and not alert.acknowledged_at:
            alert.acknowledged_at, alert.acknowledged_by = now, actor_id
        if to == AlertStatus.RESOLVED:
            alert.resolved_at, alert.resolved_by = now, actor_id
            cooldown = (alert.rule.cooldown_minutes if alert.rule else 15) or 0
            if cooldown:
                await self.cache.set_json(f"cooldown:{alert.rule_id}:{alert.asset_id}", True, cooldown * 60)
        if to == AlertStatus.CLOSED:
            alert.closed_at = now
        if to == AlertStatus.TRIGGERED:
            alert.resolved_at = None
        alert.status = to
        alert.events.append(AlertEvent(from_status=str(current), to_status=str(to), actor_id=actor_id,
                                       actor=getattr(actor, "name", None) or "system", note=note))
        await self.session.flush()
        if to == AlertStatus.ACKNOWLEDGED:
            await get_event_bus().publish(ALERTS_ACKNOWLEDGED, envelope("alert.acknowledged", {
                "alert_id": str(alert.id), "by": getattr(actor, "name", None)}), key=str(alert.asset_id))
        await broadcast("alert_update", {"alert_id": str(alert.id), "status": str(to), "severity": str(alert.severity)})
        return alert

    async def get(self, alert_id: uuid.UUID) -> Alert:
        alert = await self.alerts.get(alert_id)
        if not alert:
            raise NotFoundError(f"Alert {alert_id} not found")
        return alert

    async def acknowledge(self, alert_id: uuid.UUID, actor: Any, note: str | None = None) -> Alert:
        return await self.transition(await self.get(alert_id), AlertStatus.ACKNOWLEDGED, actor, note)

    async def resolve(self, alert_id: uuid.UUID, actor: Any, note: str | None = None,
                      false_positive: bool = False, close: bool = False) -> Alert:
        alert = await self.get(alert_id)
        alert.is_false_positive = false_positive
        await self.transition(alert, AlertStatus.RESOLVED, actor, note)
        if close:
            await self.transition(alert, AlertStatus.CLOSED, actor, "closed on resolve")
        return alert

    async def escalate(self, alert_id: uuid.UUID, actor: Any, note: str | None = None) -> Alert:
        alert = await self.get(alert_id)
        alert.escalation_level = min(3, alert.escalation_level + 1)
        if AlertStatus(alert.status) != AlertStatus.ESCALATED:
            await self.transition(alert, AlertStatus.ESCALATED, actor, note or "manual escalation")
        await NotificationService(self.session).dispatch(alert, alert.rule, level=alert.escalation_level)
        return alert

    async def auto_resolve(self, alert: Alert, cleared_for_s: float) -> None:
        if AlertStatus(alert.status) in (AlertStatus.RESOLVED, AlertStatus.CLOSED):
            return
        await self.transition(alert, AlertStatus.RESOLVED, None, f"auto-resolved: condition clear for {int(cleared_for_s)}s")

    async def escalate_due(self) -> int:
        """Celery beat job: notify the next level when an alert stays unacknowledged (Table 13.1)."""
        now = _now()
        pending = await self.alerts.all(Alert.status.in_([AlertStatus.TRIGGERED, AlertStatus.ESCALATED]),
                                        Alert.acknowledged_at.is_(None), Alert.suppressed.is_(False))
        escalated = 0
        for alert in pending:
            schedule = list(ESCALATION_MATRIX.get(Severity(alert.severity), []))
            if alert.rule and alert.rule.escalation and alert.rule.escalation.get("escalation_intervals"):
                esc = alert.rule.escalation
                initial = int(esc.get("initial_delay_minutes") or (schedule[0] if schedule else 5))
                schedule = [initial]
                for step in esc["escalation_intervals"]:
                    schedule.append(schedule[-1] + int(step))
                schedule = schedule[: {"operator": 1, "supervisor": 2, "manager": 3}.get(
                    esc.get("max_escalation_level", "manager"), 3)]
            elapsed = (now - alert.created_at).total_seconds() / 60
            due_level = sum(1 for m in schedule if elapsed >= m)
            if due_level > alert.escalation_level:
                alert.escalation_level = due_level
                if due_level >= 2 and AlertStatus(alert.status) == AlertStatus.TRIGGERED:
                    await self.transition(alert, AlertStatus.ESCALATED, None, f"auto-escalated to level {due_level}")
                await NotificationService(self.session).dispatch(alert, alert.rule, level=due_level)
                escalated += 1
        return escalated

    # ---- analytics (13.8) -------------------------------------------------------------------
    async def analytics(self, start: datetime, end: datetime) -> dict[str, Any]:
        alerts = await self.alerts.all(Alert.created_at >= start, Alert.created_at <= end)
        ack = [(a.acknowledged_at - a.created_at).total_seconds() / 60 for a in alerts if a.acknowledged_at]
        res = [(a.resolved_at - a.created_at).total_seconds() / 60 for a in alerts if a.resolved_at]
        reviewed = [a for a in alerts if a.is_false_positive is not None]
        volume: dict[str, Counter[str]] = defaultdict(Counter)
        for a in alerts:
            volume[a.created_at.date().isoformat()][str(a.severity)] += 1
        by_asset = Counter((a.asset.name if a.asset else "unassigned") for a in alerts)
        by_type = Counter(str(a.rule.rule_type) if a.rule else a.source for a in alerts)
        responders: dict[str, list[float]] = defaultdict(list)
        names = {}
        if any(a.acknowledged_by for a in alerts):
            from app.models.user import User

            ids = {a.acknowledged_by for a in alerts if a.acknowledged_by}
            names = {u.id: u.display_name for u in (await self.session.execute(select(User).where(User.id.in_(ids)))).unique().scalars()}
        for a in alerts:
            if a.acknowledged_by and a.acknowledged_at:
                responders[names.get(a.acknowledged_by, str(a.acknowledged_by))].append(
                    (a.acknowledged_at - a.created_at).total_seconds() / 60)
        return {
            "total": len(alerts),
            "open": sum(1 for a in alerts if a.status in OPEN_ALERT_STATUSES),
            "mean_time_to_acknowledge_min": round(fmean(ack), 2) if ack else None,
            "mean_time_to_resolve_min": round(fmean(res), 2) if res else None,
            "false_positive_rate_pct": round(100 * sum(1 for a in reviewed if a.is_false_positive) / len(reviewed), 2)
            if reviewed else None,
            "suppressed": sum(1 for a in alerts if a.suppressed),
            "by_severity": dict(Counter(str(a.severity) for a in alerts)),
            "volume_trend": [{"date": d, **dict(c)} for d, c in sorted(volume.items())],
            "pareto_by_asset": [{"name": k, "count": v} for k, v in by_asset.most_common(10)],
            "pareto_by_rule_type": [{"name": k, "count": v} for k, v in by_type.most_common()],
            "operator_response": [{"operator": k, "acknowledged": len(v), "avg_ack_min": round(fmean(v), 2)}
                                  for k, v in sorted(responders.items(), key=lambda kv: fmean(kv[1]))],
        }
