"""Alembic environment (async, URL from settings)."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  - registers all tables on Base.metadata
from app.core.config import get_settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# Views / continuous aggregates created in 0002 are not ORM-managed.
EXCLUDE_TABLES = {"telemetry_hourly", "telemetry_daily", "kpi_daily"}


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    return not (type_ == "table" and name in EXCLUDE_TABLES)


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
