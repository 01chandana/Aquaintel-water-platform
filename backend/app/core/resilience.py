"""Resilience patterns (spec Table 5.3).

* Circuit breaker  -> ``pybreaker`` (the "Python circuit-breaker library")
* Retry w/ backoff -> ``tenacity``
* Timeout          -> httpx timeout configuration (see :data:`HTTP_TIMEOUT`)
* Bulkhead         -> bounded semaphores per integration (see :func:`bulkhead`)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

import httpx
import pybreaker
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.exceptions import IntegrationError
from app.core.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T")

HTTP_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


class _LogListener(pybreaker.CircuitBreakerListener):
    def state_change(self, cb: pybreaker.CircuitBreaker, old_state: Any, new_state: Any) -> None:
        log.warning("circuit_state_change", breaker=cb.name, old=str(old_state.name), new=str(new_state.name))


def _breaker(name: str, fail_max: int = 5, reset_timeout: int = 30) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(
        fail_max=fail_max, reset_timeout=reset_timeout, name=name, listeners=[_LogListener()]
    )


BREAKERS: dict[str, pybreaker.CircuitBreaker] = {
    "kafka": _breaker("kafka"),
    "minio": _breaker("minio"),
    "mlflow": _breaker("mlflow", fail_max=3, reset_timeout=60),
    "webhook": _breaker("webhook"),
    "smtp": _breaker("smtp"),
}

_BULKHEADS: dict[str, asyncio.Semaphore] = {}


def bulkhead(name: str, size: int = 10) -> asyncio.Semaphore:
    """Bulkhead isolation: cap concurrent calls into one integration."""
    if name not in _BULKHEADS:
        _BULKHEADS[name] = asyncio.Semaphore(size)
    return _BULKHEADS[name]


async def call_with_resilience(
    name: str,
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    attempts: int = 3,
    **kwargs: Any,
) -> T:
    """Run ``fn`` behind breaker ``name`` with exponential-backoff retries."""
    breaker = BREAKERS[name]
    if breaker.current_state == pybreaker.STATE_OPEN:
        raise IntegrationError(f"{name} circuit open")
    async with bulkhead(name):
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential(multiplier=0.2, max=2),
                retry=retry_if_exception_type(Exception),
                reraise=True,
            ):
                with attempt:
                    result = await fn(*args, **kwargs)
            breaker.call(lambda: None)  # record success
            return result
        except Exception as exc:
            try:
                breaker.call(_raise, exc)
            except Exception as breaker_exc:  # noqa: BLE001 - breaker re-raises; we normalise below
                log.debug("breaker_recorded_failure", breaker=name, error=str(breaker_exc))
            raise IntegrationError(f"{name} call failed: {exc}") from exc


def _raise(exc: Exception) -> None:
    raise exc


def breaker_states() -> dict[str, str]:
    return {name: str(b.current_state) for name, b in BREAKERS.items()}


def sync_breaker(name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return BREAKERS[name].call(fn, *args, **kwargs)

        return wrapper

    return deco
