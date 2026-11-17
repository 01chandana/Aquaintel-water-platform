"""Telemetry ingestion, the stream-processing pipeline and query services (Ch. 5.3.1).

Real-time flow (spec steps 1-10)::

    adapter/API -> telemetry.raw -> TelemetryPipeline.process()
        -> validate & normalize -> TimescaleDB -> latest-value cache (write-through)
        -> telemetry.processed -> rules engine -> alerts.generated -> notifications
        -> WebSocket push to dashboards
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import TTL_ALERT_RULES, TTL_LATEST_TELEMETRY, get_cache
from app.core.events import TELEMETRY_PROCESSED, TELEMETRY_RAW, envelope, get_event_bus
from app.core.exceptions import AuthorizationError, ValidationError
from app.core.logging import get_logger
from app.core.metrics import telemetry_ingestion_lag_seconds, telemetry_ingestion_rate, telemetry_rejected_total
from app.db.session import session_scope
from app.integration.validation import validate_point
from app.models.alert import Alert, AlertRule
from app.models.asset import Asset
from app.models.enums import OPEN_ALERT_STATUSES, RuleType
from app.models.telemetry import TelemetryTag
from app.repositories.alert_repository import AlertRuleRepository
from app.repositories.telemetry_repository import TagRepository, TelemetryRepository
from app.schemas.telemetry import IngestRequest, IngestResponse
from app.services import rules_engine
from app.services.notification_service import broadcast

log = get_logger(__name__)
LATEST_KEY = "telemetry:latest"
HISTORY_LEN = 200


def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class TelemetryService:
    """Synchronous API-facing operations (ingest endpoint, queries, latest values)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tags = TagRepository(session)
        self.repo = TelemetryRepository(session)

    async def ingest(self, req: IngestRequest, principal: Any) -> IngestResponse:
        """Resolve tags, enforce asset scope and publish to ``telemetry.raw`` (step 2)."""
        by_ext = await self.tags.by_external_ids([p.tag for p in req.points if p.tag and not p.tag_id])
        by_id = await self.tags.by_ids([p.tag_id for p in req.points if p.tag_id])
        accepted: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for i, p in enumerate(req.points):
            tag = by_id.get(p.tag_id) if p.tag_id else by_ext.get(p.tag or "")
            if tag is None:
                errors.append({"index": i, "code": "UNKNOWN_TAG", "message": f"tag {p.tag_id or p.tag} not registered"})
                continue
            if principal is not None and not principal.can_access(tag.asset.path):
                errors.append({"index": i, "code": "OUT_OF_SCOPE", "message": "tag outside API key asset scope"})
                continue
            if not math.isfinite(p.value):  # AQ-008: never store inf / NaN
                errors.append({"index": i, "code": "NON_FINITE_VALUE", "message": "value must be a finite number"})
                continue
            if p.time > now + timedelta(minutes=5):
                errors.append({"index": i, "code": "FUTURE_TIMESTAMP", "message": "timestamp is in the future"})
                continue
            accepted.append({"tag_id": str(tag.id), "asset_id": str(tag.asset_id), "time": p.time.isoformat(),
                             "value": p.value, "quality": p.quality, "annotations": p.annotations})
        if errors:
            telemetry_rejected_total.labels("ingest_validation").inc(len(errors))
        if not accepted:
            if errors and len(errors) == len(req.points) and all(e["code"] == "OUT_OF_SCOPE" for e in errors):
                raise AuthorizationError("All points are outside the caller's asset scope")
            return IngestResponse(accepted=0, rejected=len(errors), errors=errors[:100], mode=get_event_bus().name)

        bus = get_event_bus()
        by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for point in accepted:
            by_asset[point["asset_id"]].append(point)
        for asset_id, points in by_asset.items():  # key = asset id -> per-asset ordering (Ch. 5.4.1)
            await bus.publish(TELEMETRY_RAW, envelope("telemetry.raw", {"source": req.source, "points": points},
                                                       source=req.source), key=asset_id)
        return IngestResponse(accepted=len(accepted), rejected=len(errors), errors=errors[:100], mode=bus.name)

    async def latest(self, tag_ids: list[uuid.UUID] | None = None) -> list[dict[str, Any]]:
        """Read-through: Redis write-through cache first, TimescaleDB ``DISTINCT ON`` fallback."""
        cached = await get_cache().hgetall_json(LATEST_KEY)
        wanted = {str(t) for t in tag_ids} if tag_ids is not None else None
        result = {k: v for k, v in cached.items() if wanted is None or k in wanted}
        missing = (wanted - set(result)) if wanted is not None else (set() if result else None)
        if missing is None or missing:
            ids = [uuid.UUID(m) for m in missing] if missing else None
            rows = await self.repo.latest(ids)
            tags = await self.tags.by_ids([r["tag_id"] for r in rows])
            for r in rows:
                t = tags.get(r["tag_id"])
                result[str(r["tag_id"])] = {
                    "tag_id": str(r["tag_id"]), "tag": t.external_id if t else None,
                    "asset_id": str(t.asset_id) if t else None, "parameter": t.parameter if t else None,
                    "unit": t.unit if t else None, "time": r["time"].isoformat(), "value": r["value"],
                    "quality": r["quality"], "status": r["status"]}
        return sorted(result.values(), key=lambda v: v.get("tag") or "")


class TelemetryPipeline:
    """Stream processor: consumes ``telemetry.raw`` events (Kafka consumer or in-process bus)."""

    def __init__(self) -> None:
        self.cache = get_cache()

    async def handle_event(self, event: dict[str, Any]) -> int:
        payload = event.get("payload", event)
        return await self.process(payload.get("points", []), payload.get("source", "rest"))

    async def process(self, points: list[dict[str, Any]], source: str = "rest") -> int:
        if not points:
            return 0
        async with session_scope() as session:
            tags = await TagRepository(session).by_ids([uuid.UUID(p["tag_id"]) for p in points])
            rows: list[dict[str, Any]] = []
            processed: list[dict[str, Any]] = []
            for p in sorted(points, key=lambda x: x["time"]):
                tag = tags.get(uuid.UUID(p["tag_id"]))
                if tag is None or not math.isfinite(float(p["value"])):  # other Kafka producers bypass the API check
                    if tag is not None:
                        telemetry_rejected_total.labels("non_finite").inc()
                    continue
                t = _ts(p["time"])
                hist = await self._history(tag.id)
                prev = hist[-1] if hist else None
                verdict = validate_point(float(p["value"]), int(p.get("quality", 192)), tag.parameter,
                                         tag.min_valid, tag.max_valid, tag.max_delta_per_hour,
                                         prev, t.timestamp(), [v for _, v in hist[-96:]])
                if verdict.status == "bad":
                    telemetry_rejected_total.labels("out_of_range").inc()
                annotations = p.get("annotations") or None
                if verdict.reasons:
                    annotations = {**(annotations or {}), "validation": verdict.reasons}
                rows.append({"time": t, "tag_id": tag.id, "value": float(p["value"]),
                             "quality": int(p.get("quality", 192)), "status": verdict.status,
                             "annotations": annotations})
                item: dict[str, Any] = {"tag_id": str(tag.id), "tag": tag.external_id, "asset_id": str(tag.asset_id),
                        "parameter": tag.parameter, "unit": tag.unit, "time": t.isoformat(),
                        "value": float(p["value"]), "quality": int(p.get("quality", 192)), "status": verdict.status}
                processed.append(item)
                if verdict.status != "bad":
                    await self._push_history(tag.id, t.timestamp(), float(p["value"]), hist)
            inserted = await TelemetryRepository(session).bulk_insert(rows)
            for item in processed:  # write-through latest cache (Table 9.1, 30 s TTL)
                await self.cache.hset_json(LATEST_KEY, item["tag_id"], item, TTL_LATEST_TELEMETRY)
            telemetry_ingestion_rate.labels(source=source, asset_type="mixed").inc(len(rows))
            if processed:
                newest = max(datetime.fromisoformat(i["time"]) for i in processed)
                telemetry_ingestion_lag_seconds.labels(source=source).observe(
                    max(0.0, (datetime.now(UTC) - newest).total_seconds()))

            await get_event_bus().publish(TELEMETRY_PROCESSED, envelope("telemetry.processed", {
                "count": len(processed), "points": processed[-500:]}, source="stream-processor"),
                key=processed[0]["asset_id"] if processed else None)
            await self._evaluate_rules(session, [i for i in processed if i["status"] != "bad"], tags)
        await broadcast("telemetry", processed[-500:])
        return inserted

    # ---- tag history ring buffer (for rate/deviation rules and z-score validation) -------
    async def _history(self, tag_id: uuid.UUID) -> list[tuple[float, float]]:
        data = await self.cache.get_json(f"hist:{tag_id}")
        return [tuple(x) for x in data] if data else []  # type: ignore[misc]

    async def _push_history(self, tag_id: uuid.UUID, ts: float, value: float, hist: list[tuple[float, float]]) -> None:
        hist.append((ts, value))
        await self.cache.set_json(f"hist:{tag_id}", hist[-HISTORY_LEN:], 86400)

    async def _rules_for(self, session: AsyncSession, tag_id: uuid.UUID) -> list[AlertRule]:
        key = f"rules:tag:{tag_id}"
        cached = await self.cache.get_json(key)
        if cached is not None:
            ids = [uuid.UUID(i) for i in cached]
            return [r for r in [await session.get(AlertRule, i) for i in ids] if r is not None and r.enabled]
        rules = await AlertRuleRepository(session).enabled_for_tag(tag_id)
        await self.cache.set_json(key, [str(r.id) for r in rules], TTL_ALERT_RULES)
        return rules

    async def _evaluate_rules(self, session: AsyncSession, items: list[dict[str, Any]],
                              tags: dict[uuid.UUID, TelemetryTag]) -> None:
        from app.services.alert_service import AlertService

        alerts = AlertService(session)
        latest_values = {i["tag_id"]: i["value"] for i in items}
        touched_tags = set(latest_values)
        for item in items:
            tag = tags[uuid.UUID(item["tag_id"])]
            for rule in await self._rules_for(session, tag.id):
                await self._apply_rule(session, alerts, rule, tag, item)
        # composite / correlation rules spanning several tags
        composite = await AlertRuleRepository(session).enabled_of_type(RuleType.COMPOSITE)
        if composite:
            cached_latest = await self.cache.hgetall_json(LATEST_KEY)
            snapshot = {k: v["value"] for k, v in cached_latest.items()} | latest_values
            for rule in composite:
                term_tags = {str(t["tag_id"]) for t in rule.condition.get("terms", [])}
                if term_tags & touched_tags:
                    ts = datetime.now(UTC).timestamp()
                    state = await self.cache.get_json(f"rule_state:{rule.id}") or {}
                    res = rules_engine.evaluate_composite(rule.condition, snapshot, ts, state)
                    await self._act(session, alerts, rule, None, res, f"rule_state:{rule.id}")

    async def _apply_rule(self, session: AsyncSession, alerts: Any, rule: AlertRule, tag: TelemetryTag,
                          item: dict[str, Any]) -> None:
        key = f"rule_state:{rule.id}:{tag.asset_id}"
        state = await self.cache.get_json(key) or {}
        ts = _ts(item["time"]).timestamp()
        value = item["value"]
        hist = await self._history(tag.id)
        prior = [h for h in hist if h[0] < ts]
        if rule.rule_type == RuleType.THRESHOLD:
            res = rules_engine.evaluate_threshold(rule.condition, value, ts, state)
        elif rule.rule_type == RuleType.RATE:
            res = rules_engine.evaluate_rate(rule.condition, prior, value, ts, state)
        elif rule.rule_type == RuleType.DEVIATION:
            res = rules_engine.evaluate_deviation(rule.condition, [v for _, v in prior], value, ts, state)
        else:
            return
        await self._act(session, alerts, rule, tag, res, key)

    async def _act(self, session: AsyncSession, alerts: Any, rule: AlertRule, tag: TelemetryTag | None,
                   res: rules_engine.EvalResult, state_key: str) -> None:
        asset = await session.get(Asset, tag.asset_id if tag else rule.asset_id) if (tag or rule.asset_id) else None
        if res.triggered:
            outcome = await alerts.raise_alert(
                rule=rule, asset=asset, title=rule.name, severity=rule.severity, message=res.message,
                source="rule", tag_id=tag.id if tag else None, trigger_value=res.value, threshold_value=res.threshold,
                context={"tag": tag.external_id if tag else None, "parameter": tag.parameter if tag else None},
            )
            if outcome.alert is not None:
                res.state["alert_open"] = True
        elif res.state.get("alert_open"):
            auto_s = int(((rule.suppression or {}).get("auto_resolve_seconds")) or 300)
            if res.cleared_for_s >= auto_s:
                from sqlalchemy import select

                open_alert = (await session.execute(select(Alert).where(
                    Alert.rule_id == rule.id, Alert.asset_id == (asset.id if asset else None),
                    Alert.status.in_(OPEN_ALERT_STATUSES)).limit(1))).unique().scalar_one_or_none()
                if open_alert:
                    await alerts.auto_resolve(open_alert, res.cleared_for_s)
                res.state["alert_open"] = False
        await self.cache.set_json(state_key, res.state, 7 * 86400)


async def invalidate_rule_cache(tag_id: uuid.UUID | None) -> None:
    if tag_id:
        await get_cache().delete(f"rules:tag:{tag_id}")


def assert_scope(principal: Any, asset: Asset) -> None:
    if principal is not None and not principal.can_access(asset.path):
        raise AuthorizationError("Asset outside your assigned scope")


def parse_interval(value: str) -> timedelta:
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    try:
        return timedelta(**{units[value[-1]]: int(value[:-1])})
    except (KeyError, ValueError) as exc:
        raise ValidationError("interval must look like 30s, 5m, 1h or 1d") from exc
