"""Structured JSON logging (Ch. 19.4) with correlation ids.

Logs are emitted as JSON lines (shipped to Elasticsearch by Logstash/Filebeat). A small
in-memory ring buffer keeps the most recent entries so ``GET /admin/logs`` (endpoint #90)
can show them without a round-trip to the ELK stack.
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from typing import Any

import structlog

from app.core.context import client_ip_var, request_id_var, user_id_var

RECENT_LOGS: deque[dict[str, Any]] = deque(maxlen=500)


def _add_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    if rid := request_id_var.get():
        event_dict.setdefault("correlation_id", rid)
    if uid := user_id_var.get():
        event_dict.setdefault("user_id", uid)
    if ip := client_ip_var.get():
        event_dict.setdefault("source_ip", ip)
    return event_dict


def _ring_buffer(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    RECENT_LOGS.append({k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
                        for k, v in event_dict.items()})
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp")
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        _add_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _ring_buffer,
    ]
    renderer = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, structlog.processors.EventRenamer("message"), renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")
    for noisy in ("kafka", "aiokafka", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> Any:
    log = structlog.get_logger()
    return log.bind(logger=name) if name else log
