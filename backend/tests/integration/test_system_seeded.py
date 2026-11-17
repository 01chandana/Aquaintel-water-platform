"""System tests against a seeded plant (21 days of simulated history, 5 trained models).

Covers the analytics stack end to end: KPI engine, compliance, reports, ML inference
(SHAP, predictive rules, drift), optimization, dashboards, work orders and admin.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import create_token
from app.models import Asset, KPIValue, MLModel, User

pytestmark = [pytest.mark.seeded, pytest.mark.integration]


async def _headers(db, email: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    u = (await db.execute(select(User).where(User.email == email))).unique().scalar_one()
    tok, _ = create_token(subject=str(u.id), token_type="access", role=u.role.name,
                          permissions=sorted(ROLE_PERMISSIONS[u.role.name]), asset_scopes=list(u.asset_scopes or []))
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
async def admin(db) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return await _headers(db, "admin@aquaintel.io")


@pytest.fixture
async def engineer(db) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return await _headers(db, "engineer@aquaintel.io")


async def _model_id(db, name: str) -> str:  # type: ignore[no-untyped-def]
    m = (await db.execute(select(MLModel).where(MLModel.name == name, MLModel.stage == "production"))).scalar_one()
    return str(m.id)


async def _asset(db, ext: str) -> Asset:  # type: ignore[no-untyped-def]
    return (await db.execute(select(Asset).where(Asset.external_id == ext))).unique().scalar_one()


class TestKpis:
    async def test_all_thirty_kpis_have_values(self, db) -> None:  # type: ignore[no-untyped-def]
        from app.models import KPIDefinition

        n = (await db.execute(select(func.count(func.distinct(KPIValue.kpi_id))))).scalar_one()
        total = (await db.execute(select(func.count()).select_from(KPIDefinition))).scalar_one()
        assert total == 30 and n >= 28  # timeliness/audit KPIs depend on history windows

    async def test_kpi_api(self, async_client, admin) -> None:  # type: ignore[no-untyped-def]
        kpis = (await async_client.get("/v1/kpis?category=energy", headers=admin)).json()["data"]
        assert {k["code"] for k in kpis} >= {"SPECIFIC_ENERGY_CONSUMPTION", "POWER_FACTOR"}
        kid = kpis[0]["id"]
        cur = (await async_client.get(f"/v1/kpis/{kid}/current", headers=admin)).json()["data"]
        assert cur["value"] is not None and cur["status"] in ("normal", "warning", "critical")
        vals = await async_client.get(f"/v1/kpis/{kid}/values?bucket=day", headers=admin)
        assert vals.status_code == 200 and len(vals.json()["data"]) >= 1
        dash = (await async_client.get("/v1/kpis/dashboard?view=maintenance", headers=admin)).json()["data"]
        assert len(dash) == 6 and "sparkline" in dash[0]
        assert (await async_client.get("/v1/kpis/categories", headers=admin)).json()["data"][0] == "operational"
        heat = (await async_client.get("/v1/kpis/health-heatmap", headers=admin)).json()["data"]
        assert heat and {"asset", "category", "value"} <= set(heat[0])

    async def test_custom_kpi_and_recompute(self, async_client, engineer, db) -> None:  # type: ignore[no-untyped-def]
        body = {"code": "AVG_PH_TEST", "name": "Average pH", "formula": "x", "unit": "pH", "category": "quality",
                "source_parameter": "ph", "aggregation_type": "avg"}
        r = await async_client.post("/v1/kpis", json=body, headers=engineer)
        assert r.status_code == 201 and r.json()["data"]["formula"] == "avg(ph)"
        from app.services.kpi_engine import KPIEngine

        site = await _asset(db, "plant_a")
        rows = await KPIEngine(db).compute_site(site, datetime.now(UTC), codes=["AVG_PH_TEST", "MTBF", "SAMPLE_COLLECTION_COVERAGE"])
        assert {r["_kd"].code for r in rows} >= {"AVG_PH_TEST", "MTBF"}
        await db.rollback()


class TestComplianceAndReports:
    async def test_compliance_endpoints(self, async_client, engineer) -> None:  # type: ignore[no-untyped-def]
        daily = (await async_client.get("/v1/compliance/summary/daily", headers=engineer)).json()["data"]
        assert daily["parameters"] and daily["overall_compliance_pct"] is not None
        monthly = (await async_client.get("/v1/compliance/summary/monthly", headers=engineer)).json()["data"]
        assert {p["parameter"] for p in monthly["parameters"]} >= {"chlorine", "ph", "turbidity"}
        ex = await async_client.get("/v1/compliance/exceedances?parameter=turbidity", headers=engineer)
        assert ex.status_code == 200

    @pytest.mark.parametrize("rtype", ["compliance_monthly", "asset_performance", "alert_summary", "kpi_summary"])
    async def test_report_types(self, async_client, admin, rtype) -> None:  # type: ignore[no-untyped-def]
        from app.workers.dispatch import drain

        r = await async_client.post("/v1/reports/generate", json={"report_type": rtype, "format": "html"}, headers=admin)
        await drain()
        rep = (await async_client.get(f"/v1/reports/{r.json()['data']['id']}", headers=admin)).json()["data"]
        assert rep["status"] == "completed", rep["error"]
        preview = await async_client.post("/v1/reports/preview", json={"report_type": rtype}, headers=admin)
        assert preview.status_code == 200 and b"<table>" in preview.content

    async def test_schedules(self, async_client, engineer) -> None:  # type: ignore[no-untyped-def]
        s = await async_client.post("/v1/reports/schedules", headers=engineer, json={
            "name": "Test weekly", "report_type": "kpi_summary", "cron": "0 6 * * 1"})
        assert s.status_code == 201
        bad = await async_client.post("/v1/reports/schedules", headers=engineer, json={
            "name": "Bad", "report_type": "kpi_summary", "cron": "not a cron"})
        assert bad.status_code == 422
        listed = (await async_client.get("/v1/reports/schedules", headers=engineer)).json()["data"]
        assert any(x["name"] == "Shift handover report" for x in listed)
        assert (await async_client.delete(f"/v1/reports/schedules/{s.json()['data']['id']}", headers=engineer)).status_code == 204


class TestMachineLearning:
    async def test_models_registered_in_production(self, async_client, admin) -> None:  # type: ignore[no-untyped-def]
        models = (await async_client.get("/v1/ml/models?stage=production", headers=admin)).json()["data"]
        assert {m["name"] for m in models} == {"pump_failure", "demand_forecast", "anomaly_detection", "chlorine_decay",
                                               "energy_optimization"}
        assert all(m["acceptance"] and "checks" in m["acceptance"] for m in models)

    async def test_pump_failure_inference_with_shap(self, async_client, admin, db) -> None:  # type: ignore[no-untyped-def]
        pump = await _asset(db, "plant_a_pump_002")
        mid = await _model_id(db, "pump_failure")
        r = await async_client.post(f"/v1/ml/models/{mid}/predict", json={"asset_id": str(pump.id)}, headers=admin)
        body = r.json()["data"]
        assert r.status_code == 200 and 0 <= body["failure_probability"] <= 1
        assert body["explanation"] and body["latency_ms"] < 1000

    async def test_forecast_chlorine_energy_anomaly(self, async_client, admin, db) -> None:  # type: ignore[no-untyped-def]
        site = await _asset(db, "plant_a")
        fc = (await async_client.post(f"/v1/ml/models/{await _model_id(db, 'demand_forecast')}/predict",
                                      json={"asset_id": str(site.id), "horizon_hours": 24}, headers=admin)).json()["data"]
        assert len(fc["forecast"]) == 24 and fc["forecast"][0]["lower"] <= fc["forecast"][0]["value"]
        cl = (await async_client.post(f"/v1/ml/models/{await _model_id(db, 'chlorine_decay')}/predict", json={},
                                      headers=admin)).json()["data"]
        assert cl["endpoints"] and cl["unit"] == "mg/L"
        en = (await async_client.post(f"/v1/ml/models/{await _model_id(db, 'energy_optimization')}/predict", json={},
                                      headers=admin)).json()["data"]
        assert en["value"] > 0 and en["options"]
        pump = await _asset(db, "plant_b_pump_001")
        an = await async_client.post(f"/v1/ml/models/{await _model_id(db, 'anomaly_detection')}/predict",
                                     json={"asset_id": str(pump.id)}, headers=admin)
        assert an.status_code == 200 and an.json()["data"]["label"] in ("normal", "anomaly", "idle")

    async def test_performance_predictions_drift(self, async_client, admin, db) -> None:  # type: ignore[no-untyped-def]
        mid = await _model_id(db, "pump_failure")
        perf = (await async_client.get(f"/v1/ml/models/{mid}/performance", headers=admin)).json()["data"]
        assert perf["offline_metrics"]["f1"] is not None
        preds = (await async_client.get(f"/v1/ml/predictions?model_id={mid}", headers=admin)).json()
        assert preds["meta"]["total"] >= 1
        # trained up to "now": there is no unseen data yet, so the monitor reports that instead of a fake drift score
        drift = (await async_client.get("/v1/ml/drift/report?model=pump_failure", headers=admin)).json()["data"]
        assert drift[0]["status"] == "collecting" and drift[0]["features"] == []

        # pretend the model went live four days ago: those four days are now unseen data to compare with training
        model = await db.get(MLModel, uuid.UUID(mid))
        original = dict(model.training_window)
        model.training_window = {**original, "end": (datetime.now(UTC) - timedelta(days=4)).isoformat()}
        await db.commit()
        try:
            drift = (await async_client.get("/v1/ml/drift/report?model=pump_failure", headers=admin)).json()["data"]
            rep = drift[0]
            assert rep["status"] in ("ok", "drift") and rep["rows"] >= 20 and rep["features"]
            assert {f["feature"] for f in rep["features"] if f["seasonal"]} <= {"hours_since_pm"}
            assert rep["drift_detected"] == (rep["monitored_max_psi"] > 0.2)
        finally:
            model.training_window = original
            await db.commit()


class TestOptimization:
    async def test_pump_schedule_and_dosing(self, async_client, engineer) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/optimization/pump-schedule", json={"horizon_hours": 24}, headers=engineer)
        plan = r.json()["data"]
        # "feasible" = solver time limit reached with a valid schedule (happens on a loaded CI runner)
        assert r.status_code == 201 and plan["solver_status"] in ("optimal", "feasible")
        assert plan["estimated_cost"] <= plan["baseline_cost"] and len(plan["plan"]["hours"]) == 24
        d = (await async_client.post("/v1/optimization/dosing", json={"target_residual_mg_l": 0.8}, headers=engineer)).json()["data"]
        assert d["plan"]["chlorine"]["plant_setpoint_mg_l"] > 0.8 and d["plan"]["coagulant"]["dose_mg_l"] > 0
        approved = await async_client.post(f"/v1/optimization/schedules/{plan['id']}/approve", headers=engineer)
        assert approved.json()["data"]["status"] == "approved"
        assert (await async_client.get("/v1/optimization/schedules", headers=engineer)).json()["meta"]["total"] >= 2


class TestOperationsApis:
    async def test_assets_telemetry_alerts(self, async_client, admin, db) -> None:  # type: ignore[no-untyped-def]
        pump = await _asset(db, "plant_a_pump_001")
        detail = (await async_client.get(f"/v1/assets/{pump.id}", headers=admin)).json()["data"]
        assert len(detail["tags"]) == 9
        tel = await async_client.get(f"/v1/assets/{pump.id}/telemetry?interval=1h&parameter=vibration", headers=admin)
        assert tel.json()["meta"]["count"] > 10
        latest = (await async_client.get(f"/v1/assets/{pump.id}/telemetry/latest", headers=admin)).json()["data"]
        assert len(latest) == 9
        tag_ids = [t["id"] for t in detail["tags"][:2]]
        agg = await async_client.get("/v1/telemetry/query/aggregate", params={"tag_ids": tag_ids, "interval": "15m"},
                                     headers=admin)
        assert agg.status_code == 200 and agg.json()["data"]
        raw = await async_client.get("/v1/telemetry/query", params={"tag_ids": tag_ids}, headers=admin)
        assert raw.json()["meta"]["count"] > 0
        assert (await async_client.get(f"/v1/telemetry/tags/{tag_ids[0]}", headers=admin)).json()["data"]["latest"]
        for path in (f"/v1/assets/{pump.id}/kpis", f"/v1/assets/{pump.id}/alerts", f"/v1/assets/{pump.id}/work-orders",
                     f"/v1/assets/{pump.id}/children", "/v1/assets/search?q=pump", "/v1/assets/types",
                     "/v1/telemetry/latest?parameter=chlorine", "/v1/alerts/analytics?days=30", "/v1/alerts/incidents",
                     "/v1/alerts/rules?rule_type=threshold"):
            assert (await async_client.get(path, headers=admin)).status_code == 200, path
        alerts = (await async_client.get("/v1/alerts?per_page=5", headers=admin)).json()
        assert alerts["meta"]["total"] > 0
        a = (await async_client.get(f"/v1/alerts/{alerts['data'][0]['id']}", headers=admin)).json()["data"]
        assert a["events"]

    async def test_rule_simulation(self, async_client, engineer) -> None:  # type: ignore[no-untyped-def]
        rules = (await async_client.get("/v1/alerts/rules?q=vibration&per_page=1", headers=engineer)).json()["data"]
        end = datetime.now(UTC)
        r = await async_client.post(f"/v1/alerts/rules/{rules[0]['id']}/simulate", headers=engineer,
                                    json={"start": (end - timedelta(days=20)).isoformat(), "end": end.isoformat()})
        assert r.status_code == 200 and r.json()["data"]["points_evaluated"] > 100

    async def test_work_order_flow(self, async_client, engineer, db) -> None:  # type: ignore[no-untyped-def]
        pump = await _asset(db, "plant_b_pump_003")
        tech = (await db.execute(select(User).where(User.email == "technician@aquaintel.io"))).unique().scalar_one()
        wo = (await async_client.post("/v1/work-orders", headers=engineer, json={
            "asset_id": str(pump.id), "title": "Inspect coupling", "wo_type": "predictive", "priority": "high"})).json()["data"]
        assert wo["number"].startswith("WO-")
        await async_client.post(f"/v1/work-orders/{wo['id']}/assign", headers=engineer, json={"assigned_to": str(tech.id)})
        upd = await async_client.put(f"/v1/work-orders/{wo['id']}", headers=engineer, json={"status": "in_progress"})
        assert upd.json()["data"]["started_at"]
        done = await async_client.post(f"/v1/work-orders/{wo['id']}/complete", headers=engineer, json={
            "resolution_notes": "Coupling replaced", "labor_hours": 2.5, "cost": 300})
        assert done.json()["data"]["status"] == "completed"
        again = await async_client.post(f"/v1/work-orders/{wo['id']}/complete", headers=engineer, json={
            "resolution_notes": "again", "labor_hours": 1})
        assert again.status_code == 422
        listed = await async_client.get("/v1/work-orders?status=completed&wo_type=corrective", headers=engineer)
        assert listed.json()["meta"]["total"] >= 1

    async def test_dashboards(self, async_client, engineer) -> None:  # type: ignore[no-untyped-def]
        tpls = (await async_client.get("/v1/dashboards/templates", headers=engineer)).json()["data"]
        assert len(tpls) == 5
        d = (await async_client.post("/v1/dashboards", headers=engineer, json={"name": "Mine", "template_id": tpls[0]["id"]})).json()["data"]
        assert len(d["widgets"]) == len(tpls[0]["widgets"])
        w = (await async_client.post(f"/v1/dashboards/{d['id']}/widgets", headers=engineer, json={
            "widget_type": "gauge", "title": "PF", "config": {"kpi": "POWER_FACTOR"}})).json()["data"]
        order = [w["id"]] + [x["id"] for x in d["widgets"]]
        upd = (await async_client.put(f"/v1/dashboards/{d['id']}", headers=engineer, json={"widget_order": order})).json()["data"]
        assert upd["widgets"][0]["id"] == w["id"] and upd["version"] > d["version"]
        await async_client.put(f"/v1/dashboards/{d['id']}/widgets/{w['id']}", headers=engineer,
                               json={"widget_type": "kpi_card", "title": "PF card", "config": {}})
        assert (await async_client.get(f"/v1/dashboards/{d['id']}", headers=engineer)).status_code == 200
        assert (await async_client.delete(f"/v1/dashboards/{d['id']}/widgets/{w['id']}", headers=engineer)).status_code == 204
        assert (await async_client.delete(f"/v1/dashboards/{d['id']}", headers=engineer)).status_code == 204

    async def test_users_and_admin(self, async_client, admin) -> None:  # type: ignore[no-untyped-def]
        u = await async_client.post("/v1/users", headers=admin, json={
            "email": "new.operator@aquaintel.io", "display_name": "New Op", "password": "Welcome12345A", "role": "operator"})
        assert u.status_code == 201
        uid = u.json()["data"]["id"]
        weak = await async_client.post("/v1/users", headers=admin, json={
            "email": "weak@aquaintel.io", "display_name": "W", "password": "short", "role": "operator"})
        assert weak.status_code == 422
        assert (await async_client.put(f"/v1/users/{uid}/role", headers=admin, json={"role": "engineer"})).json()["data"]["role"] == "engineer"
        perms = (await async_client.get(f"/v1/users/{uid}/permissions", headers=admin)).json()["data"]
        assert "alerts:rules" in perms["permissions"]
        assert (await async_client.put(f"/v1/users/{uid}", headers=admin, json={"phone": "+1555"})).status_code == 200
        assert (await async_client.delete(f"/v1/users/{uid}", headers=admin)).status_code == 204
        assert (await async_client.get("/v1/users?role=operator", headers=admin)).json()["meta"]["total"] >= 2
        for path in ("/v1/admin/metrics", "/v1/admin/logs", "/v1/admin/queue-status", "/v1/admin/system-config",
                     "/v1/admin/usage-stats", "/v1/admin/api-keys", "/v1/users/me", "/v1/docs/changelog"):
            assert (await async_client.get(path, headers=admin)).status_code == 200, path
        bad = await async_client.put("/v1/admin/system-config", headers=admin, json={"values": {"nope": 1}})
        assert bad.status_code == 422

    async def test_jobs(self, db) -> None:  # type: ignore[no-untyped-def]
        from app.workers import jobs

        assert await jobs.escalate_alerts() >= 0
        assert await jobs.run_due_schedules() >= 0
        await jobs.refresh_daily_aggregates()
        assert await jobs.compute_kpis(["POWER_FACTOR"]) >= 1
