"""Test suite for AlertService business logic (mirrors spec Listing 16.1)."""

from __future__ import annotations

from app.services.alert_service import AlertService


class TestAlertService:
    async def test_evaluate_threshold_rule_triggers_alert(self, db) -> None:  # type: ignore[no-untyped-def]
        """Verify threshold crossing triggers alert generation."""
        result = await AlertService(db).evaluate_rule(rule_id="rule_001", telemetry_value=95.0, threshold=90.0,
                                                      operator="greater_than")
        assert result.triggered is True
        assert result.severity == "critical"

    async def test_evaluate_threshold_rule_no_trigger(self, db) -> None:  # type: ignore[no-untyped-def]
        """Verify normal values do not trigger alerts."""
        result = await AlertService(db).evaluate_rule(rule_id="rule_001", telemetry_value=85.0, threshold=90.0,
                                                      operator="greater_than")
        assert result.triggered is False

    async def test_alert_deduplication(self, db, world) -> None:  # type: ignore[no-untyped-def]
        """Verify duplicate alerts are suppressed within cooldown period."""
        svc = AlertService(db)
        asset_id = world["pumps"][0].id
        first = await svc.create_alert(asset_id=asset_id, rule_id="R001", title="Bearing hot", severity="major")
        duplicate = await svc.create_alert(asset_id=asset_id, rule_id="R001", title="Bearing hot",
                                           severity="major")
        assert first.created and first.suppressed is False
        assert duplicate.suppressed is True
        assert duplicate.alert.id == first.alert.id and duplicate.alert.occurrence_count == 2
