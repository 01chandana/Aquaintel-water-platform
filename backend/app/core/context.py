"""Request-scoped context variables (correlation id, user) used by logging and envelopes."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def current_request_id() -> str:
    return request_id_var.get() or new_request_id()
