"""Synthetic historical data generator (spec Appendix A.4).

Usage::

    python scripts/generate_synthetic_data.py --days 60          # relative to now
    python scripts/generate_synthetic_data.py --start 2024-01-01 --end 2026-07-01   # Listing A.3 full range

Generates telemetry for every registered tag with the plant simulator (diurnal demand,
pump hydraulics, fault episodes, quality events), injects missing data and outliers,
validates each sample (Appendix A.3.4) and bulk-loads it into the ``telemetry_data``
hypertable with PostgreSQL COPY. It also derives the operational history that a real
plant would have: corrective work orders at each failure, monthly preventive maintenance,
audit findings, compliance report submissions, and historical alerts obtained by
replaying the configured rules over the generated series.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select, text

from app.core.logging import configure_logging, get_logger
from app.db import session as db_session
from app.integration.simulator import GENERATOR_CONFIG, PlantModel
from app.integration.validation import validate_point
from app.models import Alert, AlertEvent, AlertRule, Asset, Report, TelemetryTag, User, WorkOrder
from app.models.enums import (
    AlertStatus,
    Priority,
    ReportFormat,
    ReportStatus,
    RuleType,
    WorkOrderStatus,
    WorkOrderType,
)
from app.services import rules_engine

log = get_logger("generator")
STEP = timedelta(minutes=GENERATOR_CONFIG["frequency_minutes"])


async def generate(start: datetime, end: datetime, seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed)
    model = PlantModel(start, end, seed=seed)
    async with db_session.session_scope() as session:
        tags = {t.external_id: t for t in (await session.execute(select(TelemetryTag))).unique().scalars()}
        await session.execute(text("DELETE FROM telemetry_data WHERE time >= :s AND time <= :e"), {"s": start, "e": end})

    series: dict[str, list[tuple[float, float]]] = defaultdict(list)
    records: list[tuple[Any, ...]] = []
    t = start
    n_points = n_bad = 0
    engine = db_session.get_engine()
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        apg = raw.driver_connection
        while t <= end:
            values = model.corrupt(model.step(t), GENERATOR_CONFIG["missing_data_ratio"], GENERATOR_CONFIG["outlier_ratio"])
            for ext, value in values.items():
                tag = tags.get(ext)
                if tag is None or value is None:
                    continue
                quality = 192 if rng.random() > 0.003 else 64
                verdict = validate_point(value, quality, tag.parameter, tag.min_valid, tag.max_valid, None, None, 0)
                records.append((t, tag.id, float(value), quality, verdict.status, None, t))
                if verdict.status != "bad":
                    series[ext].append((t.timestamp(), float(value)))
                else:
                    n_bad += 1
            if len(records) >= 50_000:
                await apg.copy_records_to_table("telemetry_data", records=records, columns=[
                    "time", "tag_id", "value", "quality", "status", "annotations", "ingested_at"])
                n_points += len(records)
                records.clear()
            t += STEP
        if records:
            await apg.copy_records_to_table("telemetry_data", records=records, columns=[
                "time", "tag_id", "value", "quality", "status", "annotations", "ingested_at"])
            n_points += len(records)
        await conn.commit()
    log.info("telemetry_loaded", points=n_points, bad=n_bad, days=(end - start).days)

    async with db_session.session_scope() as session:
        await _work_orders(session, model, start, end, rng)
        await _audit_findings(session, end, rng)
        await _compliance_reports(session, end, rng)
        n_alerts = await _historical_alerts(session, series, tags, end, rng)
    async with engine.begin() as conn:
        await conn.execute(text("REFRESH MATERIALIZED VIEW telemetry_daily"))
    return {"points": n_points, "bad": n_bad, "faults": len(model.faults), "alerts": n_alerts}


async def _users(session: Any, role: str) -> list[User]:
    from app.models.user import Role

    return list((await session.execute(select(User).join(Role).where(Role.name == role))).unique().scalars())


async def _work_orders(session: Any, model: PlantModel, start: datetime, end: datetime, rng: random.Random) -> None:
    await session.execute(delete(WorkOrder))
    assets = {a.external_id: a for a in (await session.execute(select(Asset))).unique().scalars()}
    techs = await _users(session, "technician")
    engineers = await _users(session, "engineer")
    seq = 0

    def number() -> str:
        nonlocal seq
        seq += 1
        return f"WO-{end.year}-{seq:06d}"

    for f in model.faults:  # corrective WO at every failure -> MTBF / MTTR / ML labels
        if f.failure > end:
            continue
        a = assets[f.pump]
        done = f.failure + timedelta(hours=f.repair_hours)
        completed = done <= end
        session.add(WorkOrder(
            number=number(), asset_id=a.id, title=f"Pump failure - {f.code.replace('-', ' ').lower()}",
            description=f"Unplanned trip of {a.name}. Root cause: {f.code}.", wo_type=WorkOrderType.CORRECTIVE,
            priority=Priority.URGENT, status=WorkOrderStatus.COMPLETED if completed else WorkOrderStatus.IN_PROGRESS,
            assigned_to=rng.choice(techs).id if techs else None, created_by=engineers[0].id if engineers else None,
            started_at=f.failure, completed_at=done if completed else None, created_at=f.failure,
            labor_hours=round(f.repair_hours * rng.uniform(1.2, 2.2), 1) if completed else None,
            cost=round(rng.uniform(2500, 18000), 2) if completed else None, failure_code=f.code,
            resolution_notes="Replaced bearings and seal kit; realigned coupling." if completed else None,
            due_date=f.failure + timedelta(hours=24)))
    pumps = [a for a in assets.values() if a.asset_type.category == "pump"]
    d = start.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
    while d <= end + timedelta(days=20):  # monthly preventive maintenance
        for p in pumps:
            due = d + timedelta(days=rng.randint(5, 25))
            if due > end + timedelta(days=20):
                continue
            created = due - timedelta(days=14)
            late = rng.random() < 0.12
            completed_at = due + timedelta(days=rng.uniform(1, 6)) if late else due - timedelta(days=rng.uniform(0, 4))
            done = completed_at <= end
            session.add(WorkOrder(
                number=number(), asset_id=p.id, title=f"Monthly PM - {p.name}", wo_type=WorkOrderType.PREVENTIVE,
                description="Lubrication, vibration route, coupling and seal inspection.", priority=Priority.MEDIUM,
                status=WorkOrderStatus.COMPLETED if done else (WorkOrderStatus.ASSIGNED if created <= end else WorkOrderStatus.OPEN),
                assigned_to=rng.choice(techs).id if techs else None, created_at=min(created, end), due_date=due,
                started_at=completed_at - timedelta(hours=3) if done else None, completed_at=completed_at if done else None,
                labor_hours=round(rng.uniform(2, 5), 1) if done else None, cost=round(rng.uniform(150, 600), 2) if done else None,
                resolution_notes="PM completed per checklist." if done else None))
        d = (d + timedelta(days=32)).replace(day=1)


async def _audit_findings(session: Any, end: datetime, rng: random.Random) -> None:
    site = (await session.execute(select(Asset).where(Asset.parent_id.is_(None)).order_by(Asset.path).limit(1))).unique().scalar_one()
    findings = [("Chlorine analyzer calibration record missing", 21, True),
                ("Backflow prevention test overdue at DMA East", 34, True),
                ("Lockout/tagout signage incomplete at high-lift station", 12, False)]
    n = 900000
    for title, age_days, closed in findings:
        created = end - timedelta(days=age_days + (rng.randint(5, 20) if closed else 0))
        n += 1
        session.add(WorkOrder(number=f"AUD-{end.year}-{n}", asset_id=site.id, title=title, wo_type=WorkOrderType.AUDIT_FINDING,
                              priority=Priority.HIGH, status=WorkOrderStatus.COMPLETED if closed else WorkOrderStatus.IN_PROGRESS,
                              created_at=created, started_at=created, completed_at=created + timedelta(days=age_days) if closed else None,
                              resolution_notes="Corrective action verified by QA." if closed else None))


async def _compliance_reports(session: Any, end: datetime, rng: random.Random) -> None:
    await session.execute(delete(Report).where(Report.report_type == "compliance_daily", Report.file_key.is_(None)))
    for i in range(1, 31):
        day = (end - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        due = day + timedelta(days=1, hours=12)
        submitted = due - timedelta(hours=rng.uniform(1, 10)) if rng.random() > 0.04 else due + timedelta(hours=6)
        session.add(Report(name=f"Daily Compliance {day:%Y-%m-%d}", report_type="compliance_daily", format=ReportFormat.PDF,
                           status=ReportStatus.COMPLETED, parameters={"start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat()},
                           due_at=due, submitted_at=submitted, completed_at=submitted, created_at=day + timedelta(days=1)))


async def _historical_alerts(session: Any, series: dict[str, list[tuple[float, float]]], tags: dict[str, TelemetryTag],
                             end: datetime, rng: random.Random) -> int:
    await session.execute(delete(Alert))
    rules = list((await session.execute(select(AlertRule).where(
        AlertRule.rule_type.in_([RuleType.THRESHOLD, RuleType.RATE, RuleType.DEVIATION])))).unique().scalars())
    by_id = {t.id: t for t in tags.values()}
    operators = await _users(session, "operator") + await _users(session, "engineer")
    created = 0
    for rule in rules:
        tag = by_id.get(rule.tag_id)
        if tag is None or tag.external_id not in series:
            continue
        result = rules_engine.replay(str(rule.rule_type), rule.condition, series[tag.external_id])
        for ep in result["episodes"][-25:]:
            t0 = datetime.fromtimestamp(ep["start"], UTC)
            t1 = datetime.fromtimestamp(ep["end"], UTC) if ep["end"] else None
            recent_open = t1 is None or (end - t1) < timedelta(hours=2)
            ack_by = rng.choice(operators) if operators else None
            ack = t0 + timedelta(minutes=rng.uniform(2, 35 if rule.severity in ("critical", "major") else 180))
            status = AlertStatus.ACKNOWLEDGED if recent_open and ack <= end else (
                AlertStatus.TRIGGERED if recent_open else AlertStatus.CLOSED)
            alert = Alert(rule_id=rule.id, asset_id=tag.asset_id, tag_id=tag.id, severity=rule.severity, title=rule.name,
                          message=ep["message"], source="rule", trigger_value=ep["peak"], status=status,
                          threshold_value=rule.condition.get("value") or rule.condition.get("max_change_pct"),
                          occurrence_count=max(1, ep["samples"]), created_at=t0, updated_at=t1 or t0, last_triggered_at=t0,
                          acknowledged_at=ack if ack <= end else None, acknowledged_by=ack_by.id if ack_by and ack <= end else None,
                          resolved_at=None if recent_open else t1, closed_at=None if recent_open else t1,
                          is_false_positive=None if recent_open else rng.random() < 0.07,
                          context={"tag": tag.external_id, "parameter": tag.parameter, "historical": True})
            alert.events = [AlertEvent(from_status=None, to_status="triggered", actor="system", note=ep["message"], created_at=t0)]
            if alert.acknowledged_at:
                alert.events.append(AlertEvent(from_status="triggered", to_status="acknowledged", actor_id=ack_by.id,
                                               actor=ack_by.email, created_at=ack))
            if not recent_open:
                alert.events += [AlertEvent(from_status="acknowledged", to_status="resolved", actor="system",
                                            note="auto-resolved: condition cleared", created_at=t1),
                                 AlertEvent(from_status="resolved", to_status="closed", actor="system", created_at=t1)]
            session.add(alert)
            created += 1
    log.info("historical_alerts", count=created)
    return created


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    configure_logging("INFO", json_output=False)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC) if args.end else now - timedelta(minutes=now.minute % 15)
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC) if args.start else end - timedelta(days=args.days)
    db_session.init_engine()
    await db_session.detect_timescale()
    print(await generate(start, end, args.seed))
    await db_session.dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

