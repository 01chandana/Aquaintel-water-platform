"""Defence-in-depth response headers (QA audit AQ-014, spec Ch. 17.6).

nginx / the ingress add the same headers at the edge; setting them here as well means the API is
safe when reached directly (port-forward, internal callers, a misconfigured proxy).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# JSON API: nothing may be framed, embedded or executed from a response
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
# Swagger UI / ReDoc pages load their bundle from jsDelivr
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
            "frame-ancestors 'none'")
DOCS_PATHS = ("/docs", "/redoc")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        path = request.url.path
        h.setdefault("Content-Security-Policy", DOCS_CSP if path.startswith(DOCS_PATHS) else API_CSP)
        if path.startswith("/v1/"):
            h.setdefault("Cache-Control", "no-store")  # operational data and tokens must not sit in shared caches
        return response
