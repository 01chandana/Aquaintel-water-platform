"""Request timing, Prometheus HTTP metrics and structured access logs (Ch. 19.3.1)."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger
from app.core.metrics import http_request_duration_seconds, http_requests_total

log = get_logger("app.access")
_SKIP = {"/metrics", "/health/live", "/health/ready"}


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        endpoint = getattr(route, "path", request.url.path)  # templated path keeps label cardinality low
        http_requests_total.labels(request.method, endpoint, str(response.status_code)).inc()
        http_request_duration_seconds.labels(request.method, endpoint).observe(elapsed)
        response.headers["X-Response-Time-ms"] = f"{elapsed * 1000:.1f}"
        if request.url.path not in _SKIP:
            log.info("http_request", method=request.method, path=endpoint, status=response.status_code,
                     duration_ms=round(elapsed * 1000, 2))
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies over the configured limit (Ch. 17.5.1: max 10 MB)."""

    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        length = request.headers.get("content-length")
        if length and int(length) > self.max_bytes:
            from fastapi.responses import JSONResponse

            from app.core.responses import error_body

            return JSONResponse(error_body("PAYLOAD_TOO_LARGE", "Request body exceeds limit"), status_code=413)
        return await call_next(request)
