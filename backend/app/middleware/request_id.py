"""Correlation-id middleware (Ch. 9.3 "request/response logging with correlation IDs")."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import client_ip_var, new_request_id, request_id_var, user_id_var


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or new_request_id()
        tokens = (request_id_var.set(rid), client_ip_var.set(client_ip(request)), user_id_var.set(None))
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(tokens[0])
            client_ip_var.reset(tokens[1])
            user_id_var.reset(tokens[2])
        response.headers["X-Request-ID"] = rid
        return response
