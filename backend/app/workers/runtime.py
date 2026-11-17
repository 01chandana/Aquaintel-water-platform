"""Bootstraps infrastructure for code running outside the API process (Celery workers, CLIs)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from app.core.cache import init_cache
from app.core.config import get_settings
from app.core.events import init_event_bus
from app.db import session as db_session

T = TypeVar("T")


async def bootstrap(pooled: bool = False) -> None:
    s = get_settings()
    db_session.init_engine(pooled=pooled)
    await db_session.detect_timescale()
    await init_cache(s.redis_url)
    init_event_bus(s.event_bus, s.kafka_bootstrap_servers)


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine in a fresh event loop (Celery prefork workers are synchronous)."""

    async def _wrapped() -> T:
        await bootstrap(pooled=False)
        try:
            return await coro
        finally:
            await db_session.dispose_engine()

    return asyncio.run(_wrapped())
