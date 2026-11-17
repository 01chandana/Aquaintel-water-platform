"""Custom exception hierarchy (spec Ch. 9.9).

Every domain error carries an HTTP status and a machine-readable ``code`` so the
centralized handlers in :mod:`app.core.responses` can render the standard error
envelope of Ch. 7.2.4 without routers knowing about HTTP details.
"""

from __future__ import annotations

from typing import Any


class AquaIntelError(Exception):
    """Base exception for all application errors."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str = "", details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.code)
        self.message = message or (self.__class__.__doc__ or self.code).strip()
        self.details = details or []


class NotFoundError(AquaIntelError):
    """Resource not found (404)."""

    status_code = 404
    code = "NOT_FOUND"


class ValidationError(AquaIntelError):
    """Business rule validation failure (422)."""

    status_code = 422
    code = "VALIDATION_ERROR"


class AuthenticationError(AquaIntelError):
    """Authentication failure (401)."""

    status_code = 401
    code = "UNAUTHORIZED"


class AuthorizationError(AquaIntelError):
    """Permission denied (403)."""

    status_code = 403
    code = "FORBIDDEN"


class ConflictError(AquaIntelError):
    """Resource conflict (409)."""

    status_code = 409
    code = "CONFLICT"


class RateLimitError(AquaIntelError):
    """Rate limit exceeded (429)."""

    status_code = 429
    code = "RATE_LIMITED"


class IntegrationError(AquaIntelError):
    """External system communication failure."""

    status_code = 502
    code = "INTEGRATION_ERROR"


class DataQualityError(AquaIntelError):
    """Telemetry data quality below threshold."""

    status_code = 422
    code = "DATA_QUALITY_ERROR"


class InvalidStateTransition(ValidationError):
    """Requested lifecycle transition is not allowed (e.g. alert closed -> acknowledged)."""

    code = "INVALID_STATE_TRANSITION"
