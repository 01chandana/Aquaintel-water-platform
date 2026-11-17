"""Seed a complete development environment (spec Ch. 22.1.3 ``python scripts/seed_dev_data.py``).

Idempotent reference data + generated history:

1. RBAC roles (Table 17.1) and one demo user per role
2. Asset types, two treatment plants (~44 assets, ~128 tags) with GeoJSON locations
3. The 30-KPI catalogue, regulatory limits (SDWA), system configuration, spare parts
4. Alert rules covering every rule family (threshold / rate / deviation / composite / predictive)
5. Dashboard templates (Executive, Operations, Energy, Quality, Maintenance) and report schedules
6. An integration API key for the protocol-adapter simulator
7. ``--days`` of synthetic telemetry + work orders + historical alerts (generate_synthetic_data)
8. KPI backfill, ML training (5 models, bootstrapped to Production) and a batch scoring pass
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.logging import configure_logging
from app.core.permissions import INTEGRATION_PERMISSIONS, ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from app.core.security import generate_api_key, hash_password
from app.core.timeutil import to_plant
from app.db import session as db_session
from app.integration.simulator import SITES, asset_blueprint
from app.models import (
    AlertRule,
    ApiKey,
    Asset,
    AssetType,
    Dashboard,
    DashboardWidget,
    KPIDefinition,
    RegulatoryLimit,
    ReportSchedule,
    Role,
    SparePart,
    SystemConfig,
    TelemetryTag,
    User,
)
from app.models.enums import AggregationType, ReportFormat, RuleType, Severity
from app.services.kpi_catalog import KPI_CATALOG
from app.services.kpi_engine import DEFAULT_CONFIG

DEMO_PASSWORD = "AquaIntel!2026"
DEMO_USERS = [  # email, name, role, scopes, phone
    ("superadmin@aquaintel.io", "Sam Super", "super_admin", [], "+15550000001"),
    ("admin@aquaintel.io", "Alex Admin", "admin", [], "+15550000002"),
    ("engineer@aquaintel.io", "Erin Engineer", "engineer", [], "+15550000003"),
    ("datascience@aquaintel.io", "Dana Scientist", "data_scientist", [], None),
    ("operator@aquaintel.io", "Omar Operator", "operator", ["plant_a/*"], "+15550000004"),
    ("operator.b@aquaintel.io", "Olivia Operator", "operator", ["plant_b/*"], "+15550000005"),
    ("technician@aquaintel.io", "Tariq Technician", "technician", [], "+15550000006"),
    ("viewer@aquaintel.io", "Vera Viewer", "viewer", ["plant_a/*"], None),
]
ASSET_TYPES = [  # name, category, criticality
    ("Treatment Plant", "site", 5), ("Process Area", "area", 4), ("Analyzer", "analyzer", 4),
    ("Dosing Unit", "dosing", 4), ("Storage Tank", "tank", 4), ("Centrifugal Pump", "pump", 5),
    ("Flow Meter", "meter", 3), ("District Metered Area", "dma", 3), ("Motorized Valve", "valve", 3),
]
REG_LIMITS = [  # parameter, display, unit, min, max, regulation, samples/day
    ("chlorine", "Free Chlorine Residual", "mg/L", 0.2, 4.0, "SDWA MRDL", 96),
    ("turbidity", "Turbidity (combined filter effluent)", "NTU", None, 1.0, "SDWA SWTR", 96),
    ("ph", "pH", "pH", 6.5, 8.5, "EPA Secondary", 96),
    ("thm", "Total Trihalomethanes", "ug/L", None, 80.0, "SDWA Stage 2 DBPR", 96),
    ("coliform_positive", "Total Coliform", "positive", None, 0.0, "SDWA RTCR", 1),
]


async def seed_reference(session) -> dict[str, str]:  # type: ignore[no-untyped-def]
    roles = {}
    for name, perms in ROLE_PERMISSIONS.items():
        r = (await session.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
        if r is None:
            r = Role(name=name)
            session.add(r)
        r.permissions, r.description = sorted(perms), ROLE_DESCRIPTIONS[name]
        roles[name] = r
    await session.flush()
    for email, display, role, scopes, phone in DEMO_USERS:
        u = (await session.execute(select(User).where(User.email == email))).unique().scalar_one_or_none()
        if u is None:
            session.add(User(email=email, display_name=display, password_hash=hash_password(DEMO_PASSWORD),
                             role_id=roles[role].id, asset_scopes=scopes, phone=phone,
                             last_login=datetime.now(UTC) - timedelta(days=1)))
    types = {}
    for name, cat, crit in ASSET_TYPES:
        t = (await session.execute(select(AssetType).where(AssetType.name == name))).scalar_one_or_none()
        if t is None:
            t = AssetType(name=name, category=cat, criticality=crit, description=f"{name} ({cat})")
            session.add(t)
        types[name] = t
    await session.flush()

    by_ext: dict[str, Asset] = {a.external_id: a for a in (await session.execute(select(Asset))).unique().scalars()}
    for bp in asset_blueprint():
        parent = by_ext.get(bp["parent"]) if bp["parent"] else None
        a = by_ext.get(bp["external_id"])
        if a is None:
            a = Asset(external_id=bp["external_id"], name=bp["name"], asset_type_id=types[bp["type"]].id,
                      parent_id=parent.id if parent else None, path=f"{parent.path}/{bp['external_id']}" if parent else bp["external_id"],
                      location=bp["location"], metadata_=bp["metadata"], commissioned_at=date(2016, 5, 1),
                      warranty_until=date(2027, 5, 1))
            session.add(a)
            await session.flush()
            by_ext[a.external_id] = a
        for suffix, param, unit, lo, hi in bp["tags"]:
            ext = f"{bp['external_id']}_{suffix}"
            if (await session.execute(select(TelemetryTag.id).where(TelemetryTag.external_id == ext))).first():
                continue
            design = None
            if param == "production_flow":
                design = next(s.design_flow for s in SITES if s.code == bp["site"])
            elif param == "flow" and bp["type"] == "Centrifugal Pump":
                design = bp["metadata"]["rated_flow_m3h"]
            session.add(TelemetryTag(asset_id=a.id, external_id=ext, name=f"{bp['name']} {param.replace('_', ' ')}",
                                     parameter=param, unit=unit, min_valid=lo, max_valid=hi, design_value=design,
                                     source_protocol="opcua" if bp["type"] in ("Centrifugal Pump", "Flow Meter") else "mqtt"))
    await session.flush()

    for k in KPI_CATALOG:
        if (await session.execute(select(KPIDefinition.id).where(KPIDefinition.code == k["code"]))).first():
            continue
        session.add(KPIDefinition(
            code=k["code"], number=k["number"], name=k["name"], formula=k["formula"], unit=k["unit"], category=k["category"],
            threshold_warning=k["warn"], threshold_critical=k["crit"], aggregation_type=AggregationType(k["agg"]),
            computation_interval=timedelta(hours=1), higher_is_better=k["hib"], visualization=k["viz"],
            alert_condition=k["alert"], scope=k.get("scope", "site"), health_category=k.get("health"),
            description=f"KPI {k['number']} - {k['name']} ({k['category']}). Rolling window {k['window_h']} h.",
            target=DEFAULT_CONFIG.get(k.get("target_key", ""), None)))
    for p, disp, unit, lo, hi, reg, spd in REG_LIMITS:
        if not (await session.execute(select(RegulatoryLimit.id).where(RegulatoryLimit.parameter == p))).first():
            session.add(RegulatoryLimit(parameter=p, display_name=disp, unit=unit, limit_min=lo, limit_max=hi, regulation=reg,
                                        required_samples_per_day=spd))
    for key, value in DEFAULT_CONFIG.items():
        if await session.get(SystemConfig, key) is None:
            session.add(SystemConfig(key=key, value=value))
    if await session.get(SystemConfig, "alerts.silent_hours") is None:
        session.add(SystemConfig(key="alerts.silent_hours", value={"start_hour": 23, "end_hour": 5}))
    pump_type = types["Centrifugal Pump"]
    for pn, name, qty, minimum, crit, cost in [
        ("BRG-6312-C3", "Pump drive-end bearing 6312 C3", 6, 4, True, 420.0),
        ("BRG-6310-C3", "Pump non-drive-end bearing 6310", 5, 4, True, 360.0),
        ("SEAL-MECH-60", "Mechanical seal kit 60 mm", 1, 2, True, 1250.0),  # below minimum -> KPI 24 < 100 %
        ("IMP-GP900", "Impeller GP-900", 1, 1, True, 6400.0),
        ("CPL-ELEM-90", "Coupling elastomer element", 9, 4, False, 85.0),
        ("CL2-SENSOR", "Free chlorine sensor cartridge", 3, 2, True, 690.0),
        ("TURB-LAMP", "Turbidimeter lamp assembly", 4, 2, False, 210.0),
        ("VLV-ACT-GB", "Valve actuator gearbox", 1, 1, True, 3100.0),
    ]:
        if not (await session.execute(select(SparePart.id).where(SparePart.part_number == pn))).first():
            session.add(SparePart(part_number=pn, name=name, asset_type_id=pump_type.id if pn.startswith(("BRG", "SEAL", "IMP", "CPL")) else None,
                                  quantity_on_hand=qty, min_required=minimum, critical=crit, unit_cost=cost))
    await session.flush()
    return {k: str(v.id) for k, v in by_ext.items()}


def _rule(name: str, tag: TelemetryTag | None, rtype: RuleType, sev: Severity, cond: dict, **kw) -> AlertRule:  # type: ignore[no-untyped-def]
    return AlertRule(name=name, tag_id=tag.id if tag else None, asset_id=tag.asset_id if tag else kw.pop("asset_id", None),
                     rule_type=rtype, severity=sev, condition=cond, **kw)


async def seed_rules(session) -> int:  # type: ignore[no-untyped-def]
    if (await session.execute(select(AlertRule.id).limit(1))).first():
        return 0
    tags = {t.external_id: t for t in (await session.execute(select(TelemetryTag))).unique().scalars()}
    rules: list[AlertRule] = []
    crit_escalation = {"initial_delay_minutes": 5, "escalation_intervals": [15, 30], "max_escalation_level": "manager"}
    for s in SITES:
        c = s.code
        for i in range(1, s.n_pumps + 1):
            p = f"{c}_pump_{i:03d}"
            rules.append(_rule(f"Pump bearing high temperature ({p})", tags[f"{p}_tbrg"], RuleType.THRESHOLD, Severity.CRITICAL,
                               {"operator": "greater_than", "value": 85.0, "unit": "degC", "sustained_seconds": 300, "hysteresis": 2.0},
                               escalation=crit_escalation,
                               notification={"channels": ["dashboard", "email", "sms"], "recipients": ["operator_shift", "maintenance_lead"],
                                             "repeat_interval_minutes": 60},
                               suppression={"suppress_if_asset_in_maintenance": True, "suppress_during_silent_hours": False,
                                            "auto_resolve_seconds": 900}, description="Listing 13.1 reference rule"))
            rules.append(_rule(f"Pump vibration above ISO 10816 zone C ({p})", tags[f"{p}_vib"], RuleType.THRESHOLD, Severity.MAJOR,
                               {"operator": "greater_than", "value": 7.1, "unit": "mm/s", "sustained_seconds": 900, "hysteresis": 0.5},
                               notification={"channels": ["dashboard", "email"], "recipients": ["maintenance_lead"]}))
        for dma in ("north", "south", "east"):
            d = f"{c}_dma_{dma}"
            rules.append(_rule(f"Rapid pressure drop >15% in 5 min ({d})", tags[f"{d}_p"], RuleType.RATE, Severity.MAJOR,
                               {"window_seconds": 900, "max_change_pct": 15, "direction": "drop"}, description="KPI 4 alert condition"))
            rules.append(_rule(f"Abnormal DMA pressure - possible burst/leak ({d})", tags[f"{d}_p"], RuleType.DEVIATION, Severity.MINOR,
                               {"method": "sigma", "window_points": 96, "n_sigma": 4.0}, description="Use Case 23 anomaly in network"))
            rules.append(_rule(f"Chlorine residual below 0.2 mg/L ({d})", tags[f"{d}_cl"], RuleType.THRESHOLD, Severity.CRITICAL,
                               {"operator": "less_than", "value": 0.2, "unit": "mg/L", "sustained_seconds": 0, "hysteresis": 0.05},
                               description="KPI 8 alert condition", escalation=crit_escalation,
                               notification={"channels": ["dashboard", "email", "sms"], "recipients": ["operator_shift", "quality_team"]}))
        a = f"{c}_analyzer"
        rules += [
            _rule(f"Turbidity > 1.0 NTU ({a})", tags[f"{a}_turb"], RuleType.THRESHOLD, Severity.CRITICAL,
                  {"operator": "greater_than", "value": 1.0, "unit": "NTU"}, description="KPI 9 alert condition"),
            _rule(f"Turbidity > 0.3 NTU for two consecutive samples ({a})", tags[f"{a}_turb"], RuleType.THRESHOLD, Severity.MAJOR,
                  {"operator": "greater_than", "value": 0.3, "unit": "NTU", "sustained_seconds": 900}),
            _rule(f"pH outside 6.5-8.5 ({a})", tags[f"{a}_ph"], RuleType.THRESHOLD, Severity.MAJOR,
                  {"operator": "outside_range", "low": 6.5, "high": 8.5, "hysteresis": 0.05}, description="KPI 10 alert condition"),
            _rule(f"THM approaching 80% of MCL ({a})", tags[f"{a}_thm"], RuleType.THRESHOLD, Severity.WARNING,
                  {"operator": "greater_than", "value": 64.0, "unit": "ug/L", "sustained_seconds": 3600}, description="KPI 11"),
            _rule(f"Total coliform positive sample ({a})", tags[f"{a}_coliform"], RuleType.THRESHOLD, Severity.CRITICAL,
                  {"operator": "greater_equal", "value": 1.0}, description="KPI 12: immediate investigation"),
            _rule(f"Service reservoir low level ({c})", tags[f"{c}_reservoir_level"], RuleType.THRESHOLD, Severity.MAJOR,
                  {"operator": "less_than", "value": 25.0, "unit": "%", "sustained_seconds": 600}),
            _rule(f"Valve actuator torque drift ({c}_valve_001)", tags[f"{c}_valve_001_torque"], RuleType.THRESHOLD, Severity.MINOR,
                  {"operator": "greater_than", "value": 70.0, "unit": "Nm", "sustained_seconds": 3600}, description="Use Case 9"),
            _rule(f"Pump running with low flow ({c}_pump_001)", None, RuleType.COMPOSITE, Severity.MAJOR,
                  {"logic": "and", "sustained_seconds": 600, "terms": [
                      {"tag_id": str(tags[f"{c}_pump_001_run"].id), "operator": "equals", "value": 1},
                      {"tag_id": str(tags[f"{c}_pump_001_flow"].id), "operator": "less_than", "value": 150}]},
                  asset_id=tags[f"{c}_pump_001_flow"].asset_id, description="Conditional logic / correlation rule (13.2.4)"),
        ]
    rules.append(AlertRule(name="Predicted pump failure within 7 days", rule_type=RuleType.PREDICTIVE, severity=Severity.MAJOR,
                           condition={"model": "pump_failure", "metric": "failure_probability", "operator": "greater_than", "value": 0.7},
                           description="Predictive maintenance workflow (Ch. 5.3.2)",
                           notification={"channels": ["dashboard", "email"], "recipients": ["maintenance_lead"]}, cooldown_minutes=720))
    rules.append(AlertRule(name="Multivariate anomaly on pump", rule_type=RuleType.PREDICTIVE, severity=Severity.MINOR,
                           condition={"model": "anomaly_detection", "metric": "anomaly_score", "operator": "greater_than", "value": 0.85},
                           cooldown_minutes=240))
    session.add_all(rules)
    return len(rules)


TEMPLATES = {
    "Executive Dashboard": [("kpi_card", "System Availability", {"kpi": "SYSTEM_AVAILABILITY"}, 3),
                            ("kpi_card", "Water Quality Index", {"kpi": "WATER_QUALITY_INDEX"}, 3),
                            ("kpi_card", "Specific Energy", {"kpi": "SPECIFIC_ENERGY_CONSUMPTION"}, 3),
                            ("kpi_card", "O&M Cost / m3", {"kpi": "OM_COST_PER_UNIT"}, 3),
                            ("trend_chart", "Production Volume (7 d)", {"kpi": "PRODUCTION_VOLUME", "days": 7}, 8),
                            ("alert_list", "Critical Alerts", {"severity": "critical,major", "limit": 8}, 4)],
    "Operations Dashboard": [("gauge", "Flow Rate Efficiency", {"kpi": "FLOW_RATE_EFFICIENCY"}, 4),
                             ("gauge", "Pressure Stability", {"kpi": "PRESSURE_STABILITY_INDEX"}, 4),
                             ("kpi_card", "Peak Demand Ratio", {"kpi": "PEAK_DEMAND_RATIO"}, 4),
                             ("telemetry_table", "Live Telemetry", {"parameter": "flow"}, 8),
                             ("alert_list", "Active Alerts", {"limit": 10}, 4)],
    "Energy Dashboard": [("kpi_card", "SEC", {"kpi": "SPECIFIC_ENERGY_CONSUMPTION"}, 4),
                         ("kpi_card", "Power Factor", {"kpi": "POWER_FACTOR"}, 4),
                         ("kpi_card", "Max Demand Utilization", {"kpi": "MAXIMUM_DEMAND_UTILIZATION"}, 4),
                         ("trend_chart", "Energy Cost Intensity", {"kpi": "ENERGY_COST_INTENSITY", "days": 14}, 12)],
    "Quality Dashboard": [("kpi_card", "Chlorine Compliance", {"kpi": "CHLORINE_RESIDUAL_COMPLIANCE"}, 4),
                          ("kpi_card", "Turbidity Exceedance", {"kpi": "TURBIDITY_EXCEEDANCE_RATE"}, 4),
                          ("kpi_card", "DBP Risk", {"kpi": "DBP_RISK"}, 4),
                          ("trend_chart", "Water Quality Index", {"kpi": "WATER_QUALITY_INDEX", "days": 7}, 12)],
    "Maintenance Dashboard": [("kpi_card", "MTBF", {"kpi": "MTBF"}, 3), ("kpi_card", "MTTR", {"kpi": "MTTR"}, 3),
                              ("kpi_card", "PM Compliance", {"kpi": "PM_COMPLIANCE"}, 3),
                              ("kpi_card", "Spare Parts", {"kpi": "SPARE_PARTS_AVAILABILITY"}, 3),
                              ("heatmap", "Equipment Health Heat Map", {"kpi": "EQUIPMENT_HEALTH_SCORE"}, 12)],
}


async def seed_dashboards_schedules(session) -> str:  # type: ignore[no-untyped-def]
    if not (await session.execute(select(Dashboard.id).where(Dashboard.is_template.is_(True)))).first():
        for name, widgets in TEMPLATES.items():
            session.add(Dashboard(name=name, is_template=True, is_shared=True, description=f"Template: {name}",
                                  widgets=[DashboardWidget(widget_type=w, title=t, config=c, width=wd, position_index=i)
                                           for i, (w, t, c, wd) in enumerate(widgets)]))
    from croniter import croniter

    for name, rtype, fmt, cron in [("Shift handover report", "shift_handover", ReportFormat.PDF, "30 5,13,21 * * *"),
                                   ("Daily compliance report", "compliance_daily", ReportFormat.PDF, "0 1 * * *"),
                                   ("Monthly compliance workbook", "compliance_monthly", ReportFormat.EXCEL, "0 2 1 * *")]:
        if not (await session.execute(select(ReportSchedule.id).where(ReportSchedule.name == name))).first():
            session.add(ReportSchedule(name=name, report_type=rtype, format=fmt, cron=cron, recipients=["operations@aquaintel.io"],
                                       next_run_at=croniter(cron, to_plant(datetime.now(UTC))).get_next(datetime)))
    import os

    from app.core.security import verify_api_key

    key_file = Path(os.environ.get("AQUAINTEL_SIMULATOR_KEY_FILE")
                    or Path(__file__).resolve().parents[1] / "var" / "simulator_api_key.txt")
    existing = (await session.execute(select(ApiKey).where(ApiKey.name == "plant-simulator", ApiKey.revoked.is_(False)))).scalar_one_or_none()
    if existing and key_file.exists() and verify_api_key(key_file.read_text().strip(), existing.key_hash):
        return key_file.read_text().strip()
    if existing:
        existing.revoked = True  # file lost or belongs to another database: rotate
    raw, prefix, hashed = generate_api_key()
    session.add(ApiKey(name="plant-simulator", key_prefix=prefix, key_hash=hashed, permissions=sorted(INTEGRATION_PERMISSIONS),
                       expires_at=datetime.now(UTC) + timedelta(days=90)))
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(raw)
    return raw


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed AquaIntel development data")
    parser.add_argument("--days", type=int, default=60, help="days of synthetic history")
    parser.add_argument("--kpi-days", type=int, default=14, help="days of hourly KPI backfill")
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--skip-ml", action="store_true")
    args = parser.parse_args()
    configure_logging("INFO", json_output=False)
    from app.workers.runtime import bootstrap

    await bootstrap(pooled=True)
    async with db_session.session_scope() as session:
        await seed_reference(session)
        n_rules = await seed_rules(session)
        api_key = await seed_dashboards_schedules(session)
    print(f"[seed] reference data ready ({n_rules} new rules)")

    if not args.skip_history:
        from generate_synthetic_data import generate

        now = datetime.now(UTC).replace(second=0, microsecond=0)
        end = now - timedelta(minutes=now.minute % 15)
        stats = await generate(end - timedelta(days=args.days), end)
        print(f"[seed] history generated: {stats}")

        from app.services.kpi_engine import KPIEngine

        async with db_session.session_scope() as session:
            sites = list((await session.execute(select(Asset).where(Asset.parent_id.is_(None)))).unique().scalars())
            for site in sites:
                n = await KPIEngine(session).backfill(site, end - timedelta(days=args.kpi_days), end)
                print(f"[seed] KPI backfill {site.external_id}: {n} values")

    if not args.skip_ml and not args.skip_history:
        from app.ml.train import MODEL_TYPES, train_model

        for name in MODEL_TYPES:
            m = await train_model(name, end=end, days=args.days, promote=True)
            print(f"[seed] model {name}: " + (f"v{m.version} {m.metrics}" if m else "skipped"))
        from app.workers.jobs import batch_score

        print(f"[seed] batch scoring: {await batch_score()}")

    print(f"\nDemo users (password for all: {DEMO_PASSWORD})")
    for email, _, role, scopes, _ in DEMO_USERS:
        print(f"  {role:15s} {email:32s} scopes={scopes or 'all'}")
    print(f"\nSimulator API key (saved to backend/var/simulator_api_key.txt): {api_key}")
    await db_session.dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
