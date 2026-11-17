"""Async engine and session factory (Ch. 9.5: pooled connections, SQLAlchemy 2.0)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
timescale_enabled: bool = False


def build_engine(url: str | None = None, *, pooled: bool = True) -> AsyncEngine:
    s = get_settings()
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if pooled:
        kwargs.update(pool_size=s.database_pool_size, max_overflow=s.database_max_overflow)
    else:
        kwargs["poolclass"] = NullPool  # Celery workers: one event loop per task
    return create_async_engine(url or s.database_url, **kwargs)


def init_engine(url: str | None = None, *, pooled: bool = True) -> AsyncEngine:
    global _engine, _session_factory
    _engine = build_engine(url, pooled=pooled)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed by the service layer."""
    async with session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Unit-of-work for background jobs and the stream processor."""
    async with session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def detect_timescale() -> bool:
    global timescale_enabled
    async with get_engine().connect() as conn:
        row = await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"))
        timescale_enabled = row.first() is not None
    return timescale_enabled


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine, _session_factory = None, None
