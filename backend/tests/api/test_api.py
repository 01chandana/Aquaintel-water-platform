"""API tests (Ch. 16.5): envelope contract, auth flows, RBAC/ABAC, end-to-end ingestion -> alert."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import PASSWORD, settle

pytestmark = pytest.mark.api


def assert_envelope(body: dict) -> None:
    assert body["status"] == "success" and "data" in body and body["request_id"].startswith("req_")


class TestHealthAndContract:
    async def test_health_contract(self, async_client) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.get("/health/ready")
        body = r.json()
        assert r.status_code == 200 and {"status", "version", "uptime_seconds", "checks"} <= set(body)
        assert {"database", "redis", "kafka", "minio"} <= set(body["checks"])

    async def test_request_id_and_rate_limit_headers(self, async_client, auth_headers) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.get("/v1/assets", headers={**auth_headers, "X-Request-ID": "req_custom"})
        assert r.headers["X-Request-ID"] == "req_custom"
        assert {"x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"} <= set(r.headers)

    async def test_unauthenticated_is_401_envelope(self, async_client) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.get("/v1/assets")
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


class TestAuth:
    async def test_login_refresh_rotation_logout(self, async_client, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/auth/login", json={"email": "admin@aquaintel.io", "password": PASSWORD})
        assert r.status_code == 200
        tokens = r.json()["data"]["tokens"]
        r2 = await async_client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r2.status_code == 200
        reuse = await async_client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert reuse.status_code == 401  # rotated refresh tokens are single-use
        new = r2.json()["data"]
        h = {"Authorization": f"Bearer {new['access_token']}"}
        assert (await async_client.get("/v1/users/me", headers=h)).status_code == 200
        await async_client.post("/v1/auth/logout", json={"refresh_token": new["refresh_token"]}, headers=h)
        assert (await async_client.get("/v1/users/me", headers=h)).status_code == 401  # blacklisted jti

    async def test_bad_password_and_login_rate_limit(self, async_client, world) -> None:  # type: ignore[no-untyped-def]
        codes = [(await async_client.post("/v1/auth/login", json={"email": "operator@aquaintel.io", "password": "wrong"})).status_code
                 for _ in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429  # 5 attempts/minute (Table 7.1)


class TestAssets:
    async def test_list_assets_pagination(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        """Verify asset listing with pagination (spec Listing 16.3)."""
        response = await async_client.get("/v1/assets?page=1&per_page=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "meta" in data and {"page", "per_page", "total", "total_pages"} <= set(data["meta"])

    async def test_create_asset_validation(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        """Verify 422 on invalid asset creation."""
        response = await async_client.post("/v1/assets", json={"name": ""}, headers=auth_headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_rbac_operator_cannot_create(self, async_client, headers_for, world) -> None:  # type: ignore[no-untyped-def]
        body = {"external_id": "new_pump", "name": "New", "asset_type_id": str(world["types"]["pump"].id)}
        r = await async_client.post("/v1/assets", json=body, headers=headers_for("operator"))
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
        ok = await async_client.post("/v1/assets", json=body, headers=headers_for("engineer"))
        assert ok.status_code == 201 and ok.json()["data"]["path"] == "new_pump"

    async def test_abac_asset_scope(self, async_client, headers_for, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.get("/v1/assets?per_page=100", headers=headers_for("operator_b"))
        paths = {a["path"] for a in r.json()["data"]}
        assert paths == {"plant_b"}
        denied = await async_client.get(f"/v1/assets/{world['pumps'][0].id}", headers=headers_for("operator_b"))
        assert denied.status_code == 403

    async def test_tree_and_move(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        tree = (await async_client.get("/v1/assets?view=tree", headers=auth_headers)).json()["data"]
        assert {n["external_id"] for n in tree} == {"plant_a", "plant_b"}
        r = await async_client.put(f"/v1/assets/{world['area'].id}", json={"parent_id": str(world["site_b"].id)},
                                   headers=auth_headers)
        assert r.status_code == 200 and r.json()["data"]["path"] == "plant_b/plant_a_pumping"
        pump = (await async_client.get(f"/v1/assets/{world['pumps'][0].id}", headers=auth_headers)).json()["data"]
        assert pump["path"].startswith("plant_b/plant_a_pumping/")  # subtree re-rooted


class TestEndToEnd:
    async def test_ingest_rule_alert_ack_resolve(self, async_client, headers_for, world, _infra) -> None:  # type: ignore[no-untyped-def]
        eng = headers_for("engineer")
        tag = world["tags"]["plant_a_pump_002_bearing_temperature"]
        rule = {"name": "Bearing high temp", "tag_id": str(tag.id), "rule_type": "threshold", "severity": "critical",
                "condition": {"operator": "greater_than", "value": 85, "sustained_seconds": 0}}
        r = await async_client.post("/v1/alerts/rules", json=rule, headers=eng)
        assert r.status_code == 201
        now = datetime.now(UTC)
        pts = [{"tag": tag.external_id, "time": (now - timedelta(minutes=3 - i)).isoformat(), "value": v}
               for i, v in enumerate([70, 88, 92])]
        ing = await async_client.post("/v1/telemetry/ingest", json={"source": "mqtt", "points": pts},
                                      headers={"X-API-Key": world["api_key"]})
        assert ing.status_code == 200 and ing.json()["data"]["accepted"] == 3
        await settle(_infra)
        alerts = (await async_client.get("/v1/alerts?open_only=true", headers=eng)).json()["data"]
        assert len(alerts) == 1 and alerts[0]["severity"] == "critical"
        aid = alerts[0]["id"]
        op = headers_for("operator")
        assert (await async_client.post(f"/v1/alerts/{aid}/acknowledge", json={}, headers=op)).status_code == 200
        res = await async_client.post(f"/v1/alerts/{aid}/resolve", json={"note": "fixed"}, headers=op)
        assert res.json()["data"]["status"] == "resolved"
        timeline = [e["to_status"] for e in res.json()["data"]["events"]]
        assert timeline == ["triggered", "acknowledged", "resolved"]

    async def test_unknown_tags_are_reported(self, async_client, world) -> None:  # type: ignore[no-untyped-def]
        pts = [{"tag": "does_not_exist", "time": datetime.now(UTC).isoformat(), "value": 1}]
        r = await async_client.post("/v1/telemetry/ingest", json={"points": pts}, headers={"X-API-Key": world["api_key"]})
        assert r.json()["data"]["rejected"] == 1 and r.json()["data"]["errors"][0]["code"] == "UNKNOWN_TAG"

    async def test_rule_test_endpoint(self, async_client, headers_for, world) -> None:  # type: ignore[no-untyped-def]
        tag = world["tags"]["plant_a_pump_001_vibration"]
        body = {"rule": {"name": "Vib", "tag_id": str(tag.id), "rule_type": "threshold", "severity": "major",
                         "condition": {"operator": "greater_than", "value": 7.1, "sustained_seconds": 120}},
                "values": [2, 8, 8, 8, 2, 9], "interval_seconds": 60}
        r = await async_client.post("/v1/alerts/rules/test", json=body, headers=headers_for("engineer"))
        assert r.json()["data"]["trigger_count"] == 1


class TestReportsAndAdmin:
    @pytest.mark.parametrize("fmt", ["pdf", "excel", "html"])
    async def test_generate_and_download(self, async_client, auth_headers, world, fmt) -> None:  # type: ignore[no-untyped-def]
        from app.workers.dispatch import drain

        r = await async_client.post("/v1/reports/generate", json={"report_type": "shift_handover", "format": fmt},
                                    headers=auth_headers)
        assert r.status_code == 202
        await drain()
        rid = r.json()["data"]["id"]
        dl = await async_client.get(f"/v1/reports/{rid}/download", headers=auth_headers)
        assert dl.status_code == 200 and len(dl.content) > 500
        magic = {"pdf": b"%PDF", "excel": b"PK", "html": b"<!DOCTYPE"}[fmt]
        assert dl.content.startswith(magic)

    async def test_audit_log_and_chain_verify(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        await async_client.put("/v1/admin/system-config", json={"values": {"energy.contracted_demand_kw": 950}},
                               headers=auth_headers)
        log = (await async_client.get("/v1/admin/audit-log", headers=auth_headers)).json()
        assert any(e["action"] == "system.config_update" for e in log["data"])
        v = (await async_client.get("/v1/admin/audit-log/verify", headers=auth_headers)).json()["data"]
        assert v["valid"] is True

    async def test_viewer_cannot_read_admin(self, async_client, headers_for, world) -> None:  # type: ignore[no-untyped-def]
        assert (await async_client.get("/v1/admin/metrics", headers=headers_for("viewer"))).status_code == 403

    async def test_api_key_lifecycle(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/admin/api-keys", json={"name": "scada-gw", "permissions": ["telemetry:ingest"]},
                                    headers=auth_headers)
        raw = r.json()["data"]["api_key"]
        assert raw.startswith("aq_")
        ok = await async_client.get("/v1/telemetry/tags", headers={"X-API-Key": raw})
        assert ok.status_code == 403  # key only has telemetry:ingest
        await async_client.delete(f"/v1/admin/api-keys/{r.json()['data']['id']}", headers=auth_headers)
        revoked = await async_client.post("/v1/telemetry/ingest", headers={"X-API-Key": raw},
                                          json={"points": [{"tag": "x", "time": datetime.now(UTC).isoformat(), "value": 1}]})
        assert revoked.status_code == 401


class TestMlGovernance:
    async def test_two_person_rule(self, async_client, headers_for, world) -> None:  # type: ignore[no-untyped-def]
        ds = headers_for("ds")
        body = {"name": "pump_failure", "model_type": "xgboost", "version": "9.0.0", "artifact_uri": "s3://m/x.pkl"}
        m = (await async_client.post("/v1/ml/models/register", json=body, headers=ds)).json()["data"]
        own = await async_client.post(f"/v1/ml/models/{m['id']}/deploy", json={"stage": "production"}, headers=ds)
        assert own.status_code == 403
        other = await async_client.post(f"/v1/ml/models/{m['id']}/deploy", json={"stage": "production"},
                                        headers=headers_for("admin"))
        assert other.status_code == 200 and other.json()["data"]["stage"] == "production"
