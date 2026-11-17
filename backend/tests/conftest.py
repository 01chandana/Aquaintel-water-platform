"""Shared fixtures (Ch. 16.4.2): real PostgreSQL test database, auto-cleaned state, factories.

Tests run against PostgreSQL (TimescaleDB in CI, plain PostgreSQL locally - migration 0002
degrades gracefully). Redis and Kafka are replaced by their in-process implementations so
the suite needs only a database: ``AQUAINTEL_TEST_DATABASE_URL`` (default ``test_aquaintel``).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio

TEST_DB = os.environ.get(
    "AQUAINTEL_TEST_DATABASE_URL", "postgresql+asyncpg://aquaintel:aquaintel@localhost:5432/test_aquaintel"
)
SEEDED_DB = TEST_DB.rsplit("/", 1)[0] + "/" + TEST_DB.rsplit("/", 1)[1] + "_seeded"
os.environ.update({
    "AQUAINTEL_DATABASE_URL": TEST_DB,
    "AQUAINTEL_ENVIRONMENT": "test",
    "AQUAINTEL_EVENT_BUS": "memory",
    "AQUAINTEL_TASK_MODE": "inline",
    "AQUAINTEL_RATE_LIMIT_ENABLED": "true",
    "AQUAINTEL_LOCAL_STORAGE_DIR": "/tmp/aquaintel-test-storage",
    "AQUAINTEL_SECRET_KEY": "test-secret-key-0123456789-abcdefghijklmnop",
})

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.cache import MemoryCache, set_cache  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.events import TELEMETRY_RAW, MemoryEventBus, set_event_bus  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.core.permissions import ROLE_PERMISSIONS  # noqa: E402
from app.core.security import create_token, generate_api_key, hash_password  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.models import ApiKey, Asset, AssetType, Role, TelemetryTag, User  # noqa: E402

PASSWORD = "Sup3rSecret!"
TABLES = [
    "notifications", "alert_events", "alerts", "incidents", "alert_rules", "predictions", "ml_models", "kpi_values",
    "kpi_definitions", "telemetry_data", "telemetry_tags", "work_orders", "dashboard_widgets", "dashboards", "reports",
    "report_schedules", "regulatory_limits", "schedules", "spare_parts", "system_config", "api_keys", "users", "roles",
    "assets", "asset_types",
]


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "app", "db", "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    get_settings.cache_clear()
    configure_logging("WARNING", json_output=False)
    _migrate()


@pytest.fixture(scope="session")
def seeded_database() -> str:
    """A database seeded once per session with 21 days of simulated plant history + trained models."""
    import subprocess
    import sys

    import psycopg

    base = SEEDED_DB.replace("+asyncpg", "").rsplit("/", 1)
    with psycopg.connect(base[0] + "/postgres", autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{base[1]}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{base[1]}"')
    env = {**os.environ, "AQUAINTEL_DATABASE_URL": SEEDED_DB, "AQUAINTEL_REDIS_URL": "redis://127.0.0.1:1/0",
           "AQUAINTEL_LOCAL_STORAGE_DIR": "/tmp/aquaintel-test-seeded",
           "AQUAINTEL_SIMULATOR_KEY_FILE": "/tmp/aquaintel-test-seeded/simulator_api_key.txt"}
    root = os.path.join(os.path.dirname(__file__), "..")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, check=True,
                   capture_output=True)
    subprocess.run([sys.executable, "scripts/seed_dev_data.py", "--days", "21", "--kpi-days", "2"], cwd=root,
                   env=env, check=True, capture_output=True)
    return SEEDED_DB


@pytest_asyncio.fixture(autouse=True)
async def _infra(request: pytest.FixtureRequest) -> AsyncIterator[MemoryEventBus]:
    seeded = request.node.get_closest_marker("seeded") is not None
    if seeded:
        os.environ["AQUAINTEL_LOCAL_STORAGE_DIR"] = "/tmp/aquaintel-test-seeded"
        get_settings.cache_clear()
        from app.core import storage

        storage._store = None
    db_session.init_engine(request.getfixturevalue("seeded_database") if seeded else TEST_DB, pooled=False)
    await db_session.detect_timescale()
    set_cache(MemoryCache())
    bus = MemoryEventBus()
    from app.services.telemetry_service import TelemetryPipeline

    bus.subscribe(TELEMETRY_RAW, TelemetryPipeline().handle_event)
    set_event_bus(bus)
    if seeded:
        yield bus
        await bus.drain()
        await db_session.dispose_engine()
        os.environ["AQUAINTEL_LOCAL_STORAGE_DIR"] = "/tmp/aquaintel-test-storage"
        get_settings.cache_clear()
        from app.core import storage

        storage._store = None
        return
    async with db_session.get_engine().begin() as conn:
        # audit_log is append-only by trigger; tests bypass it with session_replication_role
        await conn.execute(text("SET session_replication_role = replica"))
        await conn.execute(text("TRUNCATE audit_log RESTART IDENTITY CASCADE"))
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
        await conn.execute(text("SET session_replication_role = origin"))
    yield bus
    await bus.drain()
    await db_session.dispose_engine()


@pytest_asyncio.fixture
async def db() -> AsyncIterator:
    async with db_session.session_factory()() as session:
        yield session


@pytest_asyncio.fixture
async def world(db) -> dict:  # type: ignore[no-untyped-def]
    """Minimal plant: roles, three users, site -> area -> two pumps, one analyzer, tags."""
    roles = {}
    for name, perms in ROLE_PERMISSIONS.items():
        roles[name] = Role(name=name, permissions=sorted(perms))
        db.add(roles[name])
    await db.flush()
    users = {}
    for key, role, scopes in (("admin", "admin", []), ("engineer", "engineer", []), ("operator", "operator", ["plant_a/*"]),
                              ("operator_b", "operator", ["plant_b/*"]), ("viewer", "viewer", []), ("ds", "data_scientist", [])):
        users[key] = User(email=f"{key}@aquaintel.io", display_name=key.title(), password_hash=hash_password(PASSWORD),
                          role_id=roles[role].id, asset_scopes=scopes)
        db.add(users[key])
    types = {c: AssetType(name=n, category=c) for n, c in (("Plant", "site"), ("Area", "area"), ("Pump", "pump"),
                                                             ("Analyzer", "analyzer"))}
    db.add_all(types.values())
    await db.flush()
    site = Asset(external_id="plant_a", name="Plant A", asset_type_id=types["site"].id, path="plant_a")
    db.add(site)
    await db.flush()
    area = Asset(external_id="plant_a_pumping", name="Pumping", asset_type_id=types["area"].id, parent_id=site.id,
                 path="plant_a/plant_a_pumping")
    db.add(area)
    await db.flush()
    pumps = []
    for i in (1, 2):
        p = Asset(external_id=f"plant_a_pump_{i:03d}", name=f"Pump {i}", asset_type_id=types["pump"].id, parent_id=area.id,
                  path=f"plant_a/plant_a_pumping/plant_a_pump_{i:03d}", metadata_={"bep_efficiency": 0.82})
        db.add(p)
        pumps.append(p)
    site_b = Asset(external_id="plant_b", name="Plant B", asset_type_id=types["site"].id, path="plant_b")
    db.add(site_b)
    await db.flush()
    tags = {}
    for p in pumps:
        for param, unit, lo, hi in (("bearing_temperature", "degC", -5, 150), ("vibration", "mm/s", 0, 50), ("flow", "m3/h", 0, 2000)):
            t = TelemetryTag(asset_id=p.id, external_id=f"{p.external_id}_{param}", name=f"{p.name} {param}",
                             parameter=param, unit=unit, min_valid=lo, max_valid=hi)
            db.add(t)
            tags[t.external_id] = t
    await db.flush()
    raw, prefix, hashed = generate_api_key()
    db.add(ApiKey(name="test-adapter", key_prefix=prefix, key_hash=hashed,
                  permissions=["telemetry:ingest", "telemetry:read", "assets:read"]))
    await db.commit()
    return {"users": users, "roles": roles, "site": site, "site_b": site_b, "area": area, "pumps": pumps, "tags": tags,
            "types": types, "api_key": raw}


def token_for(user: User, role: str, scopes: list[str] | None = None) -> str:
    token, _ = create_token(subject=str(user.id), token_type="access", role=role,
                            permissions=sorted(ROLE_PERMISSIONS[role]), asset_scopes=scopes or [])
    return token


@pytest.fixture
def auth_headers(world) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {"Authorization": f"Bearer {token_for(world['users']['admin'], 'admin')}"}


@pytest.fixture
def headers_for(world):  # type: ignore[no-untyped-def]
    def _h(key: str) -> dict[str, str]:
        u = world["users"][key]
        role = {"admin": "admin", "engineer": "engineer", "operator": "operator", "operator_b": "operator",
                "viewer": "viewer", "ds": "data_scientist"}[key]
        return {"Authorization": f"Bearer {token_for(u, role, list(u.asset_scopes or []))}"}

    return _h


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def settle(bus: MemoryEventBus) -> None:
    """Wait for in-process event handlers (stream processor) to finish."""
    await asyncio.sleep(0)
    await bus.drain()


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


