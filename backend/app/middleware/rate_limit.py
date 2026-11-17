"""Redis sliding-window rate limiting (Ch. 7.15, 17.5.3, Table 9.1).

* Global: 1000 req/min per IP (anonymous)
* Authenticated: 5000 req/min per token / API key
* Bulk endpoints (``/telemetry/ingest``): 100 req/min
* Login: 5 attempts/min per IP (enforced by the ``login_rate_limit`` dependency)

Every response carries ``X-RateLimit-Limit``, ``X-RateLimit-Remaining`` and
``X-RateLimit-Reset``.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.exceptions import RateLimitError
from app.core.responses import error_body
from app.core.security import sha256
from app.middleware.request_id import client_ip

BULK_PATHS = ("/telemetry/ingest",)
EXEMPT = ("/health", "/metrics", "/docs", "/openapi.json", "/redoc", "/ws")


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        path = request.url.path
        if not settings.rate_limit_enabled or any(path.startswith(p) or path.endswith(p) for p in EXEMPT):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        api_key = request.headers.get("x-api-key")
        if path.endswith(BULK_PATHS):
            bulk_source = api_key or auth or client_ip(request) or "anonymous"
            bulk_hash = sha256(bulk_source)[:16]
            ident = f"bulk:{bulk_hash}"
            limit = settings.rate_limit_bulk_per_minute
        elif auth.startswith("Bearer ") or api_key:
            token_hash = sha256(api_key or auth)[:16]
            ident = f"tok:{token_hash}"
            limit = settings.rate_limit_authenticated_per_minute
        else:
            ident = f"ip:{client_ip(request)}"
            limit = settings.rate_limit_global_per_minute

        allowed, remaining, reset = await get_cache().sliding_window(f"rl:{ident}", limit, 60)
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset),
        }
        if not allowed:
            headers["Retry-After"] = "60"
            return JSONResponse(error_body("RATE_LIMITED", "Too many requests"), status_code=429, headers=headers)
        response = await call_next(request)
        response.headers.update(headers)
        return response


async def login_rate_limit(request: Request) -> None:
    """Dependency for auth endpoints: 5 attempts/minute per IP (Table 7.1)."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    route = request.url.path.rsplit("/", 1)[-1]
    limit = 3 if route in ("forgot-password", "reset-password") else settings.rate_limit_login_per_minute
    allowed, _, _ = await get_cache().sliding_window(f"rl:auth:{route}:{client_ip(request)}", limit, 60)
    if not allowed:
        raise RateLimitError("Too many authentication attempts, try again in a minute")
