"""Unit tests: security, permissions/ABAC, validation, KPI math, optimizer, drift, audit hashing."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyotp
import pytest

from app.core.exceptions import AuthenticationError
from app.core.permissions import ROLE_PERMISSIONS, asset_in_scope
from app.core.security import (
    create_token,
    decode_token,
    generate_api_key,
    generate_backup_codes,
    hash_password,
    verify_api_key,
    verify_password,
    verify_totp,
)
from app.integration.validation import iqr_bounds, validate_point
from app.ml.drift import baseline_profile, drift_report, psi
from app.optimization import pump_scheduler as ps
from app.services.audit_service import GENESIS, compute_hash
from app.services.kpi_engine import _integrate_m3, classify, normalize


class TestSecurity:
    def test_argon2_roundtrip(self) -> None:
        h = hash_password("CorrectHorse9")
        assert h.startswith("$argon2") and verify_password("CorrectHorse9", h) and not verify_password("nope", h)

    def test_token_claims_follow_listing_17_1(self) -> None:
        tok, claims = create_token(subject="u1", token_type="access", role="operator",
                                   permissions=["assets:read"], asset_scopes=["plant_a/*"])
        decoded = decode_token(tok)
        assert {"sub", "role", "permissions", "exp", "iat", "jti", "asset_scopes"} <= set(decoded)
        assert decoded["jti"] == claims["jti"]

    def test_wrong_token_type_rejected(self) -> None:
        tok, _ = create_token(subject="u1", token_type="refresh")
        with pytest.raises(AuthenticationError):
            decode_token(tok, "access")

    def test_expired_token_rejected(self) -> None:
        tok, _ = create_token(subject="u1", token_type="access", expires_delta=timedelta(seconds=-5))
        with pytest.raises(AuthenticationError, match="expired"):
            decode_token(tok)

    def test_api_key_hash_never_equals_key(self) -> None:
        raw, prefix, hashed = generate_api_key()
        assert raw.startswith("aq_") and prefix == raw[:11] and raw not in hashed
        assert verify_api_key(raw, hashed) and not verify_api_key(raw + "x", hashed)

    def test_totp_and_backup_codes(self) -> None:
        secret = pyotp.random_base32()
        assert verify_totp(secret, pyotp.TOTP(secret).now())
        plain, hashed = generate_backup_codes(4)
        assert len(plain) == len(hashed) == 4 and plain[0] not in hashed


class TestPermissions:
    def test_roles_are_cumulative(self) -> None:
        assert ROLE_PERMISSIONS["viewer"] < ROLE_PERMISSIONS["operator"] < ROLE_PERMISSIONS["engineer"]
        assert "users:manage" in ROLE_PERMISSIONS["admin"] and "users:manage" not in ROLE_PERMISSIONS["engineer"]

    @pytest.mark.parametrize(("path", "scopes", "ok"), [
        ("plant_a/pumping/pump_1", ["plant_a/*"], True), ("plant_b/x", ["plant_a/*"], False),
        ("plant_b/pumping/pump_007", ["plant_b/pumping/pump_*"], True), ("anything", [], True),
        ("plant_a", ["plant_a/*"], True),
    ])
    def test_asset_scope_globs(self, path: str, scopes: list[str], ok: bool) -> None:
        assert asset_in_scope(path, scopes) is ok


class TestValidation:
    def test_out_of_range_is_bad(self) -> None:
        assert validate_point(15.0, 192, "ph", None, None, None, None, 0).status == "bad"

    def test_low_quality_is_suspect(self) -> None:
        v = validate_point(7.2, 64, "ph", None, None, None, None, 0)
        assert v.status == "suspect" and "low_quality" in v.reasons

    def test_rate_of_change(self) -> None:
        v = validate_point(9.5, 192, "ph", None, None, None, (0.0, 7.0), 900.0)
        assert "rate_of_change" in v.reasons

    def test_z_score_outlier(self) -> None:
        hist = [7.0 + 0.01 * (i % 5) for i in range(50)]
        assert "z_score_outlier" in validate_point(8.0, 192, "ph", None, None, None, None, 0, hist).reasons

    def test_nan_is_bad(self) -> None:
        assert validate_point(float("nan"), 192, "flow", None, None, None, None, 0).status == "bad"

    def test_iqr_bounds(self) -> None:
        lo, hi = iqr_bounds([float(i) for i in range(100)])
        assert lo < 0 < 99 < hi


class TestKpiMath:
    kd = SimpleNamespace(threshold_warning=98.0, threshold_critical=95.0, higher_is_better=True, unit="%")
    kd_low = SimpleNamespace(threshold_warning=0.45, threshold_critical=0.55, higher_is_better=False, unit="kWh/m3")

    def test_classify_higher_is_better(self) -> None:
        assert [classify(self.kd, v) for v in (99, 96, 90)] == ["normal", "warning", "critical"]

    def test_classify_lower_is_better(self) -> None:
        assert [classify(self.kd_low, v) for v in (0.3, 0.5, 0.6)] == ["normal", "warning", "critical"]

    def test_normalize_is_monotonic_and_bounded(self) -> None:
        vals = [normalize(self.kd, v) for v in (80, 95, 97, 99, 100)]
        assert vals == sorted(vals) and all(0 <= v <= 100 for v in vals)
        low = [normalize(self.kd_low, v) for v in (0.7, 0.55, 0.5, 0.4)]
        assert low == sorted(low)

    def test_time_weighted_integration(self) -> None:
        t = pd.date_range("2026-01-01", periods=5, freq="15min", tz="UTC")
        df = pd.DataFrame({"time": t, "value": [100.0] * 5, "tag_id": ["a"] * 5})
        assert _integrate_m3(df) == pytest.approx(100.0)  # 100 m3/h for one hour


class TestPumpScheduler:
    pumps = [ps.PumpSpec(f"P{i}", 800, ps.pump_power(800, 48, 0.8)) for i in range(3)]
    demand = [1400 + 600 * np.sin(2 * np.pi * (h - 6) / 24) for h in range(24)]
    tariff = [0.21 if 17 <= h <= 21 else 0.09 for h in range(24)]

    def test_optimal_schedule_beats_follow_demand(self) -> None:
        res = ps.solve(self.pumps, self.demand, self.tariff, 20000, 60, 25, 95)
        assert res["status"] == "optimal"
        assert res["cost"] <= res["baseline"]["cost"] and res["savings_pct"] >= 0

    def test_tank_limits_respected(self) -> None:
        res = ps.solve(self.pumps, self.demand, self.tariff, 20000, 60, 25, 95)
        assert all(25 - 1e-6 <= h["level_pct"] <= 95 + 1e-6 for h in res["hours"])
        assert res["hours"][-1]["level_pct"] >= 60 - 1e-6  # no borrowing of stored water

    def test_infeasible_when_capacity_too_small(self) -> None:
        res = ps.solve(self.pumps[:1], [5000] * 6, [0.1] * 6, 1000, 50, 40, 60)
        assert res["status"] == "infeasible"

    def test_chlorine_setpoint_inverts_decay(self) -> None:
        c0 = ps.chlorine_setpoint(0.5, 0.05, 10, safety=1.0)
        assert c0 * np.exp(-0.05 * 10) == pytest.approx(0.5)


class TestDrift:
    def test_psi_zero_for_identical(self) -> None:
        assert psi(np.array([0.5, 0.5]), np.array([0.5, 0.5])) == pytest.approx(0)

    def test_shifted_distribution_detected(self) -> None:
        rng = np.random.default_rng(1)
        base = pd.DataFrame({"x": rng.normal(0, 1, 2000)})
        prof = baseline_profile(base, ["x"])
        same = drift_report(prof, pd.DataFrame({"x": rng.normal(0, 1, 2000)}))
        shifted = drift_report(prof, pd.DataFrame({"x": rng.normal(1.5, 1, 2000)}))
        assert not same["drift_detected"] and shifted["drift_detected"] and shifted["max_psi"] > 0.2

    def test_seasonal_shift_reported_but_not_alerted(self) -> None:
        rng = np.random.default_rng(2)
        base = pd.DataFrame({"water_temperature": rng.normal(16, 1, 2000), "vibration_mean_6h": rng.normal(3, 0.3, 2000)})
        prof = baseline_profile(base, list(base.columns))
        autumn = pd.DataFrame({"water_temperature": rng.normal(11, 1, 500), "vibration_mean_6h": rng.normal(3, 0.3, 500)})
        rep = drift_report(prof, autumn)
        temp = next(f for f in rep["features"] if f["feature"] == "water_temperature")
        assert temp["seasonal"] and temp["status"] == "significant"
        assert not rep["drift_detected"] and rep["retrain_recommended"] and rep["monitored_max_psi"] < 0.2


def test_audit_hash_chain_detects_tampering() -> None:
    e1 = {"action": "a", "details": {"x": 1}}
    h1 = compute_hash(GENESIS, e1)
    h2 = compute_hash(h1, {"action": "b"})
    assert compute_hash(GENESIS, {"action": "a", "details": {"x": 2}}) != h1
    assert compute_hash(h1, {"action": "b"}) == h2 and len(h2) == 64
