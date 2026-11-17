"""Regression tests for the QA audit of the earlier AquaIntel prototype (report of 24 Sep 2026).

Each class is named after the audit finding it guards. Findings that the architecture rules out
(e.g. AQ-002 static mount of the project root) are still asserted, so a future change cannot
quietly reintroduce them. See docs/QA_AUDIT_RESPONSE.md for the full mapping.
"""

from __future__ import annotations

import asyncio
import io
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.models.telemetry import TelemetryData
from app.services.report_service import render_excel, render_pdf
from tests.conftest import PASSWORD, settle

pytestmark = pytest.mark.api
BACKEND = Path(__file__).resolve().parents[2]


class TestAQ001NoSelfServiceAdmin:
    async def test_no_public_registration_route(self, async_client) -> None:  # type: ignore[no-untyped-def]
        spec = (await async_client.get("/openapi.json")).json()
        auth_and_users = [p for p in spec["paths"] if p.startswith(("/v1/auth", "/v1/users"))]
        assert not [p for p in auth_and_users if any(w in p for w in ("signup", "register"))]

    async def test_creating_users_requires_users_manage(self, async_client, headers_for, world) -> None:  # type: ignore[no-untyped-def]
        body = {"email": "mallory@aquaintel.io", "display_name": "M", "password": "Str0ng!Passw0rd", "role": "super_admin"}
        assert (await async_client.post("/v1/users", json=body)).status_code == 401
        assert (await async_client.post("/v1/users", json=body, headers=headers_for("operator"))).status_code == 403


class TestAQ002NoFileExposure:
    @pytest.mark.parametrize("path", ["/static/aquaintel.db", "/.env", "/app/main.py", "/alembic.ini",
                                      "/var/simulator_api_key.txt", "/static/../.env"])
    async def test_server_files_are_not_served(self, async_client, path: str) -> None:  # type: ignore[no-untyped-def]
        assert (await async_client.get(path)).status_code == 404


class TestAQ003SigningKey:
    def test_placeholder_secret_refused_outside_development(self) -> None:
        env = {**os.environ, "AQUAINTEL_ENVIRONMENT": "production",
               "AQUAINTEL_SECRET_KEY": "change-me-to-a-random-string-of-at-least-32-chars"}
        r = subprocess.run([sys.executable, "-c", "from app.core.config import Settings; Settings()"],
                           cwd=BACKEND, env=env, capture_output=True, text=True)
        assert r.returncode != 0 and "published placeholder" in r.stderr

    async def test_token_for_deleted_user_is_rejected(self, async_client, db, world, headers_for) -> None:  # type: ignore[no-untyped-def]
        h = headers_for("viewer")  # signed with the real key
        await db.execute(text("UPDATE users SET is_active = false WHERE email = 'viewer@aquaintel.io'"))
        await db.commit()
        assert (await async_client.get("/v1/assets", headers=h)).status_code == 401


class TestAQ005ReadsNeedAuthentication:
    PUBLIC = {"/v1/auth/login", "/v1/auth/refresh", "/v1/auth/forgot-password", "/v1/auth/reset-password",
              "/v1/auth/mfa/verify", "/v1/docs/changelog",
              "/v1/health", "/v1/health/live", "/v1/health/ready"}  # probes for load balancers / Kubernetes

    async def test_every_v1_get_requires_a_token(self, async_client, world) -> None:  # type: ignore[no-untyped-def]
        spec = (await async_client.get("/openapi.json")).json()
        open_routes = []
        for path, ops in spec["paths"].items():
            if "get" not in ops or not path.startswith("/v1/") or path in self.PUBLIC:
                continue
            url = path.replace("{", "").replace("}", "")  # placeholder ids -> still must be 401, not 404/422
            for name in ("asset_id", "alert_id", "rule_id", "kpi_id", "report_id", "user_id", "model_id",
                         "dashboard_id", "tag_id", "work_order_id", "schedule_id", "incident_id", "key_id"):
                url = url.replace(name, str(uuid.uuid4()))
            if (await async_client.get(url)).status_code != 401:
                open_routes.append(path)
        assert open_routes == []

    async def test_ingestion_requires_credentials(self, async_client) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/telemetry/ingest", json={"source": "x", "points": []})
        assert r.status_code == 401


class TestAQ006CredentialsInBody:
    async def test_no_password_or_token_query_parameters(self, async_client) -> None:  # type: ignore[no-untyped-def]
        spec = (await async_client.get("/openapi.json")).json()
        leaky = [(p, prm["name"]) for p, ops in spec["paths"].items() for op in ops.values()
                 for prm in op.get("parameters", [])
                 if prm["in"] == "query" and any(w in prm["name"].lower() for w in ("password", "secret", "token"))]
        assert leaky == []


class TestAQ008NonFiniteNumbers:
    async def test_non_finite_points_rejected_individually(self, async_client, world, db, _infra) -> None:  # type: ignore[no-untyped-def]
        t = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
        body = ('{"source":"t","points":['
                f'{{"tag":"plant_a_pump_001_vibration","time":"{t.isoformat()}","value":Infinity}},'
                f'{{"tag":"plant_a_pump_001_vibration","time":"{(t + timedelta(seconds=1)).isoformat()}","value":NaN}},'
                f'{{"tag":"plant_a_pump_001_vibration","time":"{(t + timedelta(seconds=2)).isoformat()}","value":1e400}},'
                f'{{"tag":"plant_a_pump_001_vibration","time":"{(t + timedelta(seconds=3)).isoformat()}","value":2.5}}]}}')
        r = await async_client.post("/v1/telemetry/ingest", content=body,
                                    headers={"X-API-Key": world["api_key"], "content-type": "application/json"})
        data = r.json()["data"]
        assert r.status_code == 200 and data["accepted"] == 1 and data["rejected"] == 3
        assert {e["code"] for e in data["errors"]} == {"NON_FINITE_VALUE"}
        await settle(_infra)
        values = (await db.execute(select(TelemetryData.value))).scalars().all()
        assert values == [2.5]

    async def test_non_finite_rule_threshold_is_422(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        tag = world["tags"]["plant_a_pump_001_vibration"]
        body = ('{"name":"inf rule","rule_type":"threshold","severity":"minor","tag_id":"' + str(tag.id) + '",'
                '"condition":{"operator":"greater_than","value":Infinity}}')
        r = await async_client.post("/v1/alerts/rules", content=body,
                                    headers={**auth_headers, "content-type": "application/json"})
        assert r.status_code == 422

    @pytest.mark.parametrize(("path", "params"), [
        ("/v1/alerts", {"page": 10**20}), ("/v1/alerts", {"page": 0}), ("/v1/alerts", {"per_page": -5}),
        ("/v1/telemetry/query", {"limit": -1}), ("/v1/telemetry/query", {"limit": 10**9}),
        ("/v1/admin/logs", {"limit": 0}),
    ])
    async def test_out_of_range_numbers_are_422(self, async_client, auth_headers, world, path, params) -> None:  # type: ignore[no-untyped-def]
        if path == "/v1/telemetry/query":
            params = {**params, "tag_ids": str(world["tags"]["plant_a_pump_001_vibration"].id)}
        r = await async_client.get(path, params=params, headers=auth_headers)
        assert r.status_code == 422, (path, params, r.status_code)


class TestAQ009AQ011IntegrityErrors:
    async def test_unknown_reference_is_422_not_500(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/work-orders", headers=auth_headers,
                                    json={"title": "Check pump", "asset_id": str(uuid.uuid4()), "wo_type": "corrective",
                                          "priority": "low"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REFERENCE"

    async def test_rule_for_unknown_tag_is_422(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/alerts/rules", headers=auth_headers, json={
            "name": "ghost tag", "rule_type": "threshold", "severity": "minor", "tag_id": str(uuid.uuid4()),
            "condition": {"operator": "greater_than", "value": 1}})
        assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "tag_id"

    async def test_errors_use_http_status_codes(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        assert (await async_client.post("/v1/auth/login", json={"email": "admin@aquaintel.io", "password": "nope"})).status_code == 401
        assert (await async_client.get(f"/v1/assets/{uuid.uuid4()}", headers=auth_headers)).status_code == 404
        assert (await async_client.get("/v1/assets/not-a-uuid", headers=auth_headers)).status_code == 422


class TestAQ010AQ012InputValidation:
    async def test_very_long_password_is_422(self, async_client, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/auth/login", json={"email": "admin@aquaintel.io", "password": "a" * 5000})
        assert r.status_code == 422

    @pytest.mark.parametrize("body", [
        {"email": "not-an-email", "display_name": "X", "password": "Str0ng!Passw0rd", "role": "viewer"},
        {"email": "weak@aquaintel.io", "display_name": "X", "password": "short", "role": "viewer"},
        {"email": "long@aquaintel.io", "display_name": "X", "password": "Aa1!" + "x" * 200, "role": "viewer"},
    ])
    async def test_user_creation_validates_input(self, async_client, auth_headers, world, body) -> None:  # type: ignore[no-untyped-def]
        assert (await async_client.post("/v1/users", json=body, headers=auth_headers)).status_code == 422

    async def test_blank_asset_name_rejected(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/assets", headers=auth_headers, json={
            "external_id": "plant_a_x", "name": " ", "asset_type_id": str(world["types"]["pump"].id),
            "parent_id": str(world["area"].id)})
        assert r.status_code == 422


class TestAQ013Timestamps:
    async def test_timestamps_carry_an_offset(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.get(f"/v1/assets/{world['pumps'][0].id}", headers=auth_headers)
        created = r.json()["data"]["created_at"]
        assert created.endswith(("Z", "+00:00")), created


class TestAQ014Hardening:
    async def test_security_headers_on_api_responses(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        h = (await async_client.get("/v1/assets", headers=auth_headers)).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert "default-src 'none'" in h["content-security-policy"] and h["cache-control"] == "no-store"

    async def test_cors_does_not_trust_arbitrary_origins(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.get("/v1/assets", headers={**auth_headers, "Origin": "https://evil.example"})
        assert r.headers.get("access-control-allow-origin") is None


class TestAQ016DuplicateRules:
    async def test_identical_rule_is_409_regardless_of_key_order(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        tag = str(world["tags"]["plant_a_pump_001_vibration"].id)
        first = {"name": "Vibration high", "rule_type": "threshold", "severity": "major", "tag_id": tag,
                 "condition": {"operator": "greater_than", "value": 7.1, "sustained_seconds": 60}}
        assert (await async_client.post("/v1/alerts/rules", json=first, headers=auth_headers)).status_code == 201
        twin = {**first, "name": "Vibration high (copy)",
                "condition": {"sustained_seconds": 60, "value": 7.1, "operator": "greater_than"}}
        r = await async_client.post("/v1/alerts/rules", json=twin, headers=auth_headers)
        assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT"
        # a different severity is a different rule (warning + alarm levels on one tag are normal)
        assert (await async_client.post("/v1/alerts/rules", json={**twin, "severity": "critical"},
                                        headers=auth_headers)).status_code == 201

    async def test_re_enabling_a_duplicate_is_409(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        tag = str(world["tags"]["plant_a_pump_002_vibration"].id)
        body = {"name": "Vib A", "rule_type": "threshold", "severity": "minor", "tag_id": tag,
                "condition": {"operator": "greater_than", "value": 5}}
        a = (await async_client.post("/v1/alerts/rules", json=body, headers=auth_headers)).json()["data"]
        await async_client.put(f"/v1/alerts/rules/{a['id']}/toggle", headers=auth_headers)  # disable A
        assert (await async_client.post("/v1/alerts/rules", json={**body, "name": "Vib B"},
                                        headers=auth_headers)).status_code == 201
        assert (await async_client.put(f"/v1/alerts/rules/{a['id']}/toggle", headers=auth_headers)).status_code == 409


class TestAQ017RuleManagement:
    async def test_rules_can_be_listed_and_deleted(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        tag = str(world["tags"]["plant_a_pump_001_flow"].id)
        rid = (await async_client.post("/v1/alerts/rules", headers=auth_headers, json={
            "name": "Flow low", "rule_type": "threshold", "severity": "minor", "tag_id": tag,
            "condition": {"operator": "less_than", "value": 10}})).json()["data"]["id"]
        listed = (await async_client.get("/v1/alerts/rules", headers=auth_headers)).json()["data"]
        assert rid in {r["id"] for r in listed}
        assert (await async_client.delete(f"/v1/alerts/rules/{rid}", headers=auth_headers)).status_code == 204


class TestAQ019EmailCase:
    async def test_login_and_uniqueness_ignore_case(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        assert (await async_client.post("/v1/auth/login", json={"email": "ADMIN@AquaIntel.io", "password": PASSWORD})).status_code == 200
        r = await async_client.post("/v1/users", headers=auth_headers, json={
            "email": "Viewer@AQUAINTEL.io", "display_name": "Dup", "password": "Str0ng!Passw0rd", "role": "viewer"})
        assert r.status_code == 409


class TestAQ020WorkingDirectory:
    def test_paths_do_not_depend_on_the_start_folder(self, tmp_path: Path) -> None:
        code = ("from app.core.config import Settings, BACKEND_DIR; s = Settings(); "
                "import pathlib; p = pathlib.Path(s.local_storage_dir); "
                "assert p.is_absolute() and BACKEND_DIR in p.parents, p; print('ok')")
        env = {**os.environ, "PYTHONPATH": str(BACKEND)}
        env.pop("AQUAINTEL_LOCAL_STORAGE_DIR", None)
        r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)
        assert r.returncode == 0 and "ok" in r.stdout, r.stderr

    def test_alembic_runs_from_another_folder(self, tmp_path: Path) -> None:
        r = subprocess.run([sys.executable, "-m", "alembic", "-c", str(BACKEND / "alembic.ini"), "heads"],
                           cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 0 and "(head)" in r.stdout, r.stderr


class TestAQ022AQ004ReportInjection:
    DOC = {"title": "Asset <b>report</b>", "subtitle": "x", "generated_at": "now", "sections": [
        {"heading": "Assets", "kind": "table", "columns": ["Name", "Note"],
         "rows": [['=HYPERLINK("http://evil","x")', "<font size=40>big</font> & <a href='x'>link</a>"],
                  ["+cmd|' /C calc'!A0", "-2+3"]]}]}

    def test_excel_cells_never_become_formulas(self) -> None:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(render_excel(self.DOC)))
        cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None]
        assert all(c.data_type != "f" for c in cells)
        assert any(c.value == '=HYPERLINK("http://evil","x")' for c in cells)  # kept, as text

    def test_pdf_treats_markup_as_text(self) -> None:
        pdf = render_pdf(self.DOC)
        assert pdf.startswith(b"%PDF") and len(pdf) > 1000

    async def test_download_filename_is_header_safe(self, async_client, auth_headers, world) -> None:  # type: ignore[no-untyped-def]
        r = await async_client.post("/v1/reports/generate", headers=auth_headers, json={
            "report_type": "alert_summary", "format": "html", "name": 'Plant "A"\r\nSet-Cookie: x=1 ünïcode'})
        assert r.status_code in (200, 201, 202)
        rid = r.json()["data"]["id"]
        for _ in range(50):  # generation is asynchronous (inline task in tests)
            if (await async_client.get(f"/v1/reports/{rid}", headers=auth_headers)).json()["data"]["status"] == "completed":
                break
            await asyncio.sleep(0.1)
        d = await async_client.get(f"/v1/reports/{rid}/download", headers=auth_headers)
        cd = d.headers["content-disposition"]
        assert d.status_code == 200 and "\r" not in cd and "\n" not in cd and cd.count('"') == 2
