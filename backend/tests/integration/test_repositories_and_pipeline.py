"""Integration tests: router -> service -> repository -> PostgreSQL (Ch. 16.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.cache import get_cache
from app.core.exceptions import InvalidStateTransition
from app.models import Alert, AlertRule, Asset, TelemetryData
from app.models.enums import AlertStatus, AssetStatus, RuleType, Severity
from app.repositories.asset_repository import AssetRepository
from app.services.alert_service import AlertService
from app.services.audit_service import AuditService
from app.services.telemetry_service import LATEST_KEY, TelemetryPipeline

pytestmark = pytest.mark.integration


class TestAssetRepository:
    async def test_create_and_retrieve_asset(self, db, world) -> None:  # type: ignore[no-untyped-def]
        """Verify asset CRUD through repository layer (spec Listing 16.2)."""
        repo = AssetRepository(db)
        created = await repo.create(Asset(external_id="test_pump", name="Test Pump", path="test_pump",
                                          asset_type_id=world["types"]["pump"].id))
        assert created.id is not None
        retrieved = await repo.get(created.id)
        assert retrieved.name == "Test Pump"
        assert retrieved.status == AssetStatus.ACTIVE

    async def test_asset_hierarchy(self, db, world) -> None:  # type: ignore[no-untyped-def]
        repo = AssetRepository(db)
        children = await repo.get_children(world["area"].id)
        assert {c.id for c in children} == {p.id for p in world["pumps"]}
        subtree = await repo.subtree("plant_a")
        assert len(subtree) == 4  # site + area + 2 pumps


async def _rule(db, world, **kw) -> AlertRule:  # type: ignore[no-untyped-def]
    tag = world["tags"]["plant_a_pump_001_bearing_temperature"]
    rule = AlertRule(name="Bearing hot", tag_id=tag.id, asset_id=tag.asset_id, rule_type=RuleType.THRESHOLD,
                     severity=kw.pop("severity", Severity.CRITICAL),
                     condition=kw.pop("condition", {"operator": "greater_than", "value": 85.0}),
                     suppression={"auto_resolve_seconds": 60}, **kw)
    db.add(rule)
    await db.commit()
    return rule


def _points(tag, values, start=None, step=60):  # type: ignore[no-untyped-def]
    start = start or datetime.now(UTC) - timedelta(minutes=len(values))
    return [{"tag_id": str(tag.id), "time": (start + timedelta(seconds=i * step)).isoformat(), "value": v, "quality": 192}
            for i, v in enumerate(values)]


class TestTelemetryPipeline:
    async def test_process_stores_validates_and_caches(self, db, world) -> None:  # type: ignore[no-untyped-def]
        tag = world["tags"]["plant_a_pump_001_vibration"]
        inserted = await TelemetryPipeline().process(_points(tag, [2.0, 2.1, 999.0]))
        assert inserted == 3
        rows = (await db.execute(select(TelemetryData).where(TelemetryData.tag_id == tag.id))).scalars().all()
        assert sorted(r.status for r in rows) == ["bad", "good", "good"]  # 999 mm/s is out of range
        latest = await get_cache().hgetall_json(LATEST_KEY)
        assert latest[str(tag.id)]["value"] == 999.0

    async def test_ingestion_is_idempotent(self, db, world) -> None:  # type: ignore[no-untyped-def]
        tag = world["tags"]["plant_a_pump_001_vibration"]
        pts = _points(tag, [1.0, 1.1])
        assert await TelemetryPipeline().process(pts) == 2
        assert await TelemetryPipeline().process(pts) == 0  # at-least-once redelivery is harmless

    async def test_threshold_rule_raises_and_auto_resolves(self, db, world) -> None:  # type: ignore[no-untyped-def]
        rule = await _rule(db, world)
        rule_id = rule.id
        tag = world["tags"]["plant_a_pump_001_bearing_temperature"]
        start = datetime.now(UTC) - timedelta(minutes=30)
        await TelemetryPipeline().process(_points(tag, [70, 90, 91], start))
        alert = (await db.execute(select(Alert).where(Alert.rule_id == rule_id))).unique().scalar_one()
        assert alert.status == AlertStatus.TRIGGERED and alert.occurrence_count == 2  # second breach deduplicated
        await TelemetryPipeline().process(_points(tag, [70, 70, 70], start + timedelta(minutes=5)))
        db.expire_all()
        alert = (await db.execute(select(Alert).where(Alert.rule_id == rule_id))).unique().scalar_one()
        assert alert.status == AlertStatus.RESOLVED


class TestAlertLifecycle:
    async def test_state_machine(self, db, world) -> None:  # type: ignore[no-untyped-def]
        svc = AlertService(db)
        out = await svc.raise_alert(rule=None, asset=world["pumps"][0], title="Manual", severity="major")
        alert = out.alert
        await svc.acknowledge(alert.id, None)
        await svc.transition(alert, AlertStatus.INVESTIGATING)
        await svc.resolve(alert.id, None, close=True)
        assert alert.status == AlertStatus.CLOSED
        assert [e.to_status for e in (await svc.get(alert.id)).events][:1] == ["triggered"]
        with pytest.raises(InvalidStateTransition):
            await svc.transition(alert, AlertStatus.ACKNOWLEDGED)

    async def test_maintenance_mode_suppresses(self, db, world) -> None:  # type: ignore[no-untyped-def]
        pump = world["pumps"][0]
        pump.status = AssetStatus.MAINTENANCE
        out = await AlertService(db).raise_alert(rule=None, asset=pump, title="x", severity="critical")
        assert out.alert is None and out.reason == "asset_in_maintenance"

    async def test_flood_control(self, db, world) -> None:  # type: ignore[no-untyped-def]
        svc = AlertService(db)
        outcomes = [await svc.raise_alert(rule=None, asset=world["pumps"][1], title=f"a{i}", severity="minor")
                    for i in range(12)]
        assert sum(o.created for o in outcomes) == 10
        assert outcomes[-1].reason == "flood_control"

    async def test_lower_severity_suppressed_and_correlated(self, db, world) -> None:  # type: ignore[no-untyped-def]
        svc = AlertService(db)
        p1, p2 = world["pumps"]
        await svc.raise_alert(rule=None, asset=p1, title="critical one", severity="critical")
        low = await svc.raise_alert(rule=None, asset=p1, title="minor one", severity="minor")
        assert low.suppressed and low.reason == "lower_severity"
        sibling = await svc.raise_alert(rule=None, asset=p2, title="sibling", severity="major")
        assert sibling.alert.incident_id is not None  # spatial/temporal correlation -> incident

    async def test_escalation_matrix(self, db, world) -> None:  # type: ignore[no-untyped-def]
        svc = AlertService(db)
        out = await svc.raise_alert(rule=None, asset=world["pumps"][0], title="old critical", severity="critical")
        out.alert.created_at = datetime.now(UTC) - timedelta(minutes=25)  # past 5 and 5+15 min marks
        await db.flush()
        assert await svc.escalate_due() == 1
        assert out.alert.escalation_level == 2 and out.alert.status == AlertStatus.ESCALATED


class TestAuditChain:
    async def test_chain_verifies_and_is_append_only(self, db, world) -> None:  # type: ignore[no-untyped-def]
        audit = AuditService(db)
        for i in range(3):
            await audit.record(f"test.action{i}", "test", i, details={"i": i})
        await db.commit()
        result = await audit.verify_chain()
        assert result["valid"] and result["checked"] == 3
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text("UPDATE audit_log SET action = 'tampered' WHERE id = 1"))
        await db.rollback()
