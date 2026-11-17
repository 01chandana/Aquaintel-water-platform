"""Standard response envelope (Ch. 7.2.3) and centralized error handlers (Ch. 7.2.4, 9.3)."""

from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import current_request_id
from app.core.exceptions import AquaIntelError
from app.core.logging import get_logger

log = get_logger(__name__)


def ok(data: Any = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"status": "success", "data": jsonable_encoder(data)}
    if meta is not None:
        body["meta"] = meta
    body["request_id"] = current_request_id()
    return body


def page_meta(page: int, per_page: int, total: int) -> dict[str, int]:
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, math.ceil(total / per_page)) if per_page else 1,
    }


def paginated(items: list[Any], page: int, per_page: int, total: int) -> dict[str, Any]:
    return ok(items, page_meta(page, per_page, total))


def error_body(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {"code": code, "message": message, "details": details or []},
        "request_id": current_request_id(),
    }


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


# SQLSTATE -> (HTTP status, error code, message)
_CONSTRAINT_ERRORS = {
    "23503": (422, "INVALID_REFERENCE", "A referenced record does not exist"),   # foreign_key_violation
    "23505": (409, "DUPLICATE", "A record with the same unique value already exists"),  # unique_violation
    "23502": (422, "VALIDATION_ERROR", "A required value is missing"),         # not_null_violation
    "23514": (422, "VALIDATION_ERROR", "A value is outside the allowed range"),  # check_violation
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AquaIntelError)
    async def _domain(_: Request, exc: AquaIntelError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("domain_error", code=exc.code, error=exc.message)
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")),
                "message": err.get("msg", "invalid"),
                "code": str(err.get("type", "invalid")).upper(),
            }
            for err in exc.errors()
        ]
        return JSONResponse(error_body("VALIDATION_ERROR", "Invalid field value", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            error_body(code, str(exc.detail)), status_code=exc.status_code, headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        """Database constraint violations are client errors, not 500s (QA audit AQ-009 / AQ-011).

        PostgreSQL enforces the foreign keys, uniqueness and NOT NULL rules declared in the schema; the
        SQLSTATE says which one fired. The constraint name is returned, never the SQL or row values.
        """
        orig = getattr(exc, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None) or getattr(getattr(orig, "__cause__", None), "sqlstate", None)
        constraint = getattr(getattr(orig, "__cause__", None), "constraint_name", None)
        status, code, message = _CONSTRAINT_ERRORS.get(
            sqlstate or "", (409, "CONFLICT", "The change conflicts with existing data"))
        log.info("constraint_violation", sqlstate=sqlstate, constraint=constraint)
        details = [{"constraint": constraint}] if constraint else []
        return JSONResponse(error_body(code, message, details), status_code=status)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - safety net
        log.exception("unhandled_error", error=str(exc))
        return JSONResponse(error_body("INTERNAL_ERROR", "Internal server error"), status_code=500)
