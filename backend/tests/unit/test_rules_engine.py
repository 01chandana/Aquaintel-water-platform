"""Unit tests for the stateless rule evaluators (Ch. 13.2)."""

from __future__ import annotations

import pytest

from app.services import rules_engine as re


class TestThreshold:
    def test_single_threshold_triggers(self) -> None:
        r = re.evaluate_threshold({"operator": "greater_than", "value": 90.0}, 95.0, 0, {})
        assert r.triggered and r.breaching

    def test_normal_value_does_not_trigger(self) -> None:
        r = re.evaluate_threshold({"operator": "greater_than", "value": 90.0}, 85.0, 0, {})
        assert not r.triggered

    def test_sustained_seconds_requires_duration(self) -> None:
        cond = {"operator": "greater_than", "value": 85, "sustained_seconds": 300}
        state: dict = {}
        assert not re.evaluate_threshold(cond, 90, 0, state).triggered
        assert not re.evaluate_threshold(cond, 90, 200, state).triggered
        assert re.evaluate_threshold(cond, 90, 300, state).triggered

    def test_sustain_resets_when_condition_clears(self) -> None:
        cond = {"operator": "greater_than", "value": 85, "sustained_seconds": 300}
        state: dict = {}
        re.evaluate_threshold(cond, 90, 0, state)
        re.evaluate_threshold(cond, 80, 100, state)
        assert not re.evaluate_threshold(cond, 90, 350, state).triggered

    def test_hysteresis_prevents_chattering(self) -> None:
        cond = {"operator": "greater_than", "value": 85, "hysteresis": 2.0}
        state: dict = {}
        assert re.evaluate_threshold(cond, 86, 0, state).triggered
        # 84 is below 85 but above the 83 clear point -> still active
        assert re.evaluate_threshold(cond, 84, 60, state).triggered
        assert not re.evaluate_threshold(cond, 82.5, 120, state).triggered

    @pytest.mark.parametrize(("op", "value", "expected"), [
        ("outside_range", 6.0, True), ("outside_range", 7.0, False), ("inside_range", 7.0, True),
        ("less_equal", 6.5, True), ("not_equals", 7.0, True), ("equals", 7.0, False),
    ])
    def test_operators(self, op: str, value: float, expected: bool) -> None:
        assert re.compare(op, value, 6.5 if op in ("less_equal", "not_equals", "equals") else None, 6.5, 8.5) is expected

    def test_cleared_duration_feeds_auto_resolve(self) -> None:
        cond = {"operator": "greater_than", "value": 85}
        state: dict = {}
        re.evaluate_threshold(cond, 90, 0, state)
        re.evaluate_threshold(cond, 80, 60, state)
        assert re.evaluate_threshold(cond, 80, 400, state).cleared_for_s == pytest.approx(340)


class TestRateAndStatistical:
    def test_rapid_pressure_drop(self) -> None:
        cond = {"window_seconds": 300, "max_change_pct": 15, "direction": "drop"}
        hist = [(0, 4.0), (60, 3.98), (120, 3.9)]
        assert re.evaluate_rate(cond, hist, 3.2, 240, {}).triggered
        assert not re.evaluate_rate(cond, hist, 3.8, 240, {}).triggered

    def test_rise_direction_ignores_drop(self) -> None:
        cond = {"window_seconds": 300, "max_change_abs": 1.0, "direction": "rise"}
        assert not re.evaluate_rate(cond, [(0, 10.0)], 5.0, 60, {}).triggered

    def test_sigma_deviation(self) -> None:
        hist = [10.0 + (i % 5) * 0.1 for i in range(100)]
        cond = {"method": "sigma", "window_points": 96, "n_sigma": 3}
        assert re.evaluate_deviation(cond, hist, 15.0, 0, {}).triggered
        assert not re.evaluate_deviation(cond, hist, 10.2, 0, {}).triggered

    def test_ewma_updates_state(self) -> None:
        state: dict = {}
        hist = [5.0 + (i % 3) * 0.05 for i in range(50)]
        re.evaluate_deviation({"method": "ewma", "alpha": 0.3, "n_sigma": 3}, hist, 5.05, 0, state)
        assert "ewma" in state and "ewvar" in state

    def test_moving_average_warmup(self) -> None:
        assert re.evaluate_deviation({"method": "moving_average"}, [1.0, 2.0], 50.0, 0, {}).message == "warming up"


class TestCompositeAndPredictive:
    def test_composite_and(self) -> None:
        cond = {"logic": "and", "terms": [{"tag_id": "a", "operator": "equals", "value": 1},
                                          {"tag_id": "b", "operator": "less_than", "value": 150}]}
        assert re.evaluate_composite(cond, {"a": 1.0, "b": 100.0}, 0, {}).triggered
        assert not re.evaluate_composite(cond, {"a": 1.0, "b": 500.0}, 0, {}).triggered

    def test_composite_or_missing_tag(self) -> None:
        cond = {"logic": "or", "terms": [{"tag_id": "a", "operator": "greater_than", "value": 1},
                                         {"tag_id": "zz", "operator": "greater_than", "value": 1}]}
        assert re.evaluate_composite(cond, {"a": 2.0}, 0, {}).triggered

    def test_predictive_failure_probability(self) -> None:
        cond = {"model": "pump_failure", "metric": "failure_probability", "operator": "greater_than", "value": 0.7}
        assert re.evaluate_predictive(cond, 0.82, 0, {}).triggered
        assert not re.evaluate_predictive(cond, 0.4, 0, {}).triggered


def test_replay_returns_episodes() -> None:
    series = [(i * 60.0, 95.0 if 10 <= i < 20 else 70.0) for i in range(40)]
    out = re.replay("threshold", {"operator": "greater_than", "value": 90}, series)
    assert out["trigger_count"] == 1
    ep = out["episodes"][0]
    assert ep["start"] == 600 and ep["end"] == 1200 and ep["peak"] == 95.0


def test_replay_rejects_composite() -> None:
    with pytest.raises(ValueError):
        re.replay("composite", {}, [])
