"""Redis client wrapper (Ch. 4.4.3, Table 9.1) with an in-memory fallback.

Redis serves five roles in AquaIntel: response/metadata cache, latest-telemetry
write-through cache, sliding-window rate-limit counters (sorted sets), token
blacklist / refresh-token store, and pub/sub fan-out for WebSocket dashboards.

Design principle 4 (graceful degradation): if Redis is unreachable at start-up the
platform keeps running on :class:`MemoryCache`, which implements the same interface
in-process. Behaviour is identical for a single API instance; multi-instance
deployments must run Redis (enforced by the readiness probe in production).
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

import redis.asyncio as aioredis

from app.core.logging import get_logger

log = get_logger(__name__)

# Cache TTLs in seconds (Table 9.1)
TTL_SESSION = 24 * 3600
TTL_ASSET_METADATA = 300
TTL_LATEST_TELEMETRY = 30
TTL_KPI_VALUES = 300
TTL_ALERT_RULES = 600
TTL_DASHBOARD = 60

REALTIME_CHANNEL = "aquaintel:realtime"


class CacheBackend(Protocol):
    name: str

    async def ping(self) -> float: ...
    async def get_json(self, key: str) -> Any: ...
    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None: ...
    async def delete(self, *keys: str) -> None: ...
    async def delete_pattern(self, pattern: str) -> int: ...
    async def exists(self, key: str) -> bool: ...
    async def incr(self, key: str, ttl: int) -> int: ...
    async def sliding_window(self, key: str, limit: int, window_s: int) -> tuple[bool, int, int]: ...
    async def hset_json(self, key: str, field: str, value: Any, ttl: int | None = None) -> None: ...
    async def hgetall_json(self, key: str) -> dict[str, Any]: ...
    async def publish(self, channel: str, message: dict[str, Any]) -> None: ...
    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]: ...
    async def info(self) -> dict[str, Any]: ...
    async def count_keys(self, pattern: str) -> int: ...
    async def close(self) -> None: ...


class RedisCache:
    name = "redis"

    def __init__(self, url: str) -> None:
        self._r = aioredis.from_url(url, decode_responses=True, health_check_interval=30)

    async def ping(self) -> float:
        start = time.perf_counter()
        await self._r.ping()
        return (time.perf_counter() - start) * 1000

    async def memory_bytes(self) -> int:
        return int((await self._r.info("memory")).get("used_memory", 0))

    async def get_json(self, key: str) -> Any:
        raw = await self._r.get(key)
        return json.loads(raw) if raw is not None else None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self._r.set(key, json.dumps(value, default=str), ex=ttl)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._r.delete(*keys)

    async def delete_pattern(self, pattern: str) -> int:
        n = 0
        async for key in self._r.scan_iter(match=pattern, count=500):
            await self._r.delete(key)
            n += 1
        return n

    async def exists(self, key: str) -> bool:
        return bool(await self._r.exists(key))

    async def incr(self, key: str, ttl: int) -> int:
        async with self._r.pipeline(transaction=True) as p:
            p.incr(key)
            p.expire(key, ttl, nx=True)
            value, _ = await p.execute()
        return int(value)

    async def sliding_window(self, key: str, limit: int, window_s: int) -> tuple[bool, int, int]:
        """Sliding-window log using a sorted set (Table 9.1 "Redis Sorted Set")."""
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex[:6]}"
        async with self._r.pipeline(transaction=True) as p:
            p.zremrangebyscore(key, 0, now - window_s)
            p.zadd(key, {member: now})
            p.zcard(key)
            p.zrange(key, 0, 0, withscores=True)
            p.expire(key, window_s)
            _, _, count, oldest, _ = await p.execute()
        reset = int((oldest[0][1] if oldest else now) + window_s)
        allowed = count <= limit
        if not allowed:
            await self._r.zrem(key, member)
        return allowed, max(0, limit - count), reset

    async def hset_json(self, key: str, field: str, value: Any, ttl: int | None = None) -> None:
        await self._r.hset(key, field, json.dumps(value, default=str))
        if ttl:
            await self._r.expire(key, ttl)

    async def hgetall_json(self, key: str) -> dict[str, Any]:
        raw = await self._r.hgetall(key)
        return {k: json.loads(v) for k, v in raw.items()}

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._r.publish(channel, json.dumps(message, default=str))

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        pubsub = self._r.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    yield json.loads(msg["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def info(self) -> dict[str, Any]:
        info = await self._r.info(section="memory")
        return {"backend": "redis", "used_memory_bytes": info.get("used_memory"),
                "used_memory_human": info.get("used_memory_human")}

    async def count_keys(self, pattern: str) -> int:
        return sum([1 async for _ in self._r.scan_iter(match=pattern, count=500)])

    @asynccontextmanager
    async def lock(self, name: str, ttl_seconds: int = 30) -> AsyncIterator[None]:
        """Distributed lock for critical sections (Ch. 4.4.3); auto-expires after ``ttl_seconds``."""
        async with self._r.lock(f"lock:{name}", timeout=ttl_seconds):
            yield

    async def close(self) -> None:
        await self._r.aclose()


class MemoryCache:
    """In-process implementation of :class:`CacheBackend` used when Redis is unavailable."""

    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._zsets: dict[str, list[float]] = defaultdict(list)
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _alive(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        if item[1] is not None and item[1] < time.time():
            self._data.pop(key, None)
            return False
        return True

    async def ping(self) -> float:
        return 0.0

    async def get_json(self, key: str) -> Any:
        return self._data[key][0] if self._alive(key) else None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._data[key] = (json.loads(json.dumps(value, default=str)), time.time() + ttl if ttl else None)

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._data.pop(k, None)

    async def delete_pattern(self, pattern: str) -> int:
        keys = [k for k in list(self._data) if fnmatch.fnmatch(k, pattern)]
        await self.delete(*keys)
        return len(keys)

    async def exists(self, key: str) -> bool:
        return self._alive(key)

    async def incr(self, key: str, ttl: int) -> int:
        value = (await self.get_json(key) or 0) + 1
        expiry = self._data[key][1] if self._alive(key) else time.time() + ttl
        self._data[key] = (value, expiry)
        return int(value)

    async def sliding_window(self, key: str, limit: int, window_s: int) -> tuple[bool, int, int]:
        now = time.time()
        hits = [t for t in self._zsets[key] if t > now - window_s]
        allowed = len(hits) < limit
        if allowed:
            hits.append(now)
        self._zsets[key] = hits
        reset = int((hits[0] if hits else now) + window_s)
        return allowed, max(0, limit - len(hits)), reset

    async def hset_json(self, key: str, field: str, value: Any, ttl: int | None = None) -> None:
        current = await self.get_json(key) or {}
        current[field] = value
        await self.set_json(key, current, ttl)

    async def hgetall_json(self, key: str) -> dict[str, Any]:
        return dict(await self.get_json(key) or {})

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        for q in list(self._subscribers[channel]):
            if q.qsize() < 1000:
                q.put_nowait(message)

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[channel].add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers[channel].discard(q)

    async def info(self) -> dict[str, Any]:
        return {"backend": "memory", "keys": len(self._data)}

    async def count_keys(self, pattern: str) -> int:
        return len([k for k in list(self._data) if self._alive(k) and fnmatch.fnmatch(k, pattern)])

    @asynccontextmanager
    async def lock(self, name: str, ttl_seconds: int = 30) -> AsyncIterator[None]:
        async with self._locks[name]:
            yield

    async def close(self) -> None:
        self._data.clear()


_cache: RedisCache | MemoryCache | None = None


async def init_cache(url: str, allow_fallback: bool = True) -> RedisCache | MemoryCache:
    global _cache
    candidate = RedisCache(url)
    try:
        await asyncio.wait_for(candidate.ping(), timeout=2)
        _cache = candidate
        log.info("cache_connected", backend="redis")
    except Exception as exc:
        if not allow_fallback:
            raise
        log.warning("cache_degraded", backend="memory", reason=str(exc))
        _cache = MemoryCache()
    return _cache


def get_cache() -> RedisCache | MemoryCache:
    global _cache
    if _cache is None:
        _cache = MemoryCache()
    return _cache


async def get_redis() -> RedisCache | MemoryCache:
    """FastAPI dependency (name kept from spec Listing 9.2)."""
    return get_cache()


def set_cache(cache: RedisCache | MemoryCache | None) -> None:
    global _cache
    _cache = cache
