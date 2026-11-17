"""Kafka event publisher (Ch. 5.2.2, Table 5.2) with an in-process fallback bus.

Topics are partitioned by asset id (Ch. 5.4.1) by using the asset id as the message key,
which keeps per-asset ordering while allowing parallel consumption.

``EventBus`` has two implementations sharing one interface:

* :class:`KafkaEventBus`  - production; ``kafka-python`` producer with ``acks=all``.
* :class:`MemoryEventBus` - development/test fallback; delivers events to in-process
  subscribers (e.g. the stream processor) so the full ingestion -> rules -> alerts ->
  WebSocket pipeline works in a single ``uvicorn`` process with no Kafka broker.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.metrics import events_published_total

log = get_logger(__name__)

# ---- Topic catalogue (Table 5.2) --------------------------------------------------------
TELEMETRY_RAW = "telemetry.raw"
TELEMETRY_PROCESSED = "telemetry.processed"
TELEMETRY_DLQ = "telemetry.dlq"  # dead-letter queue (Table 5.3)
ALERTS_GENERATED = "alerts.generated"
ALERTS_ACKNOWLEDGED = "alerts.acknowledged"
KPIS_COMPUTED = "kpis.computed"
ML_INFERENCE_REQUEST = "ml.inference.request"
ML_INFERENCE_RESULT = "ml.inference.result"
AUDIT_EVENTS = "audit.events"
ASSETS_CHANGED = "assets.changed"

TOPIC_RETENTION_DAYS = {
    TELEMETRY_RAW: 7, TELEMETRY_PROCESSED: 30, TELEMETRY_DLQ: 30, ALERTS_GENERATED: 90,
    ALERTS_ACKNOWLEDGED: 90, KPIS_COMPUTED: 90, ML_INFERENCE_REQUEST: 7,
    ML_INFERENCE_RESULT: 30, AUDIT_EVENTS: 365, ASSETS_CHANGED: 90,
}

Handler = Callable[[dict[str, Any]], Awaitable[Any]]


def envelope(event_type: str, payload: dict[str, Any], source: str = "api") -> dict[str, Any]:
    return {
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "source": source,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


class MemoryEventBus:
    name = "memory"

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._tasks: set[asyncio.Task[None]] = set()
        self.published: dict[str, int] = defaultdict(int)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].append(handler)

    async def publish(self, topic: str, value: dict[str, Any], key: str | None = None) -> None:
        self.published[topic] += 1
        events_published_total.labels(topic=topic, bus=self.name).inc()
        for handler in self._handlers.get(topic, []):
            task = asyncio.create_task(self._safe(handler, topic, value))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _safe(self, handler: Handler, topic: str, value: dict[str, Any]) -> None:
        try:
            await handler(value)
        except Exception as exc:
            log.exception("event_handler_failed", topic=topic, error=str(exc))
            if topic != TELEMETRY_DLQ:
                await self.publish(TELEMETRY_DLQ, {"topic": topic, "error": str(exc), "value": value})

    async def drain(self) -> None:
        """Wait for in-flight handlers (used by tests and graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def health(self) -> dict[str, Any]:
        return {"status": "degraded", "backend": "memory", "lag": 0}

    async def close(self) -> None:
        await self.drain()


class KafkaEventBus:
    name = "kafka"

    def __init__(self, bootstrap_servers: str) -> None:
        from kafka import KafkaProducer  # local import: optional at runtime

        self.bootstrap_servers = bootstrap_servers
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(","),
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
            key_serializer=lambda k: k.encode() if k else None,
            acks="all",
            linger_ms=5,
            retries=5,
            max_in_flight_requests_per_connection=1,  # preserves per-key ordering on retry
            request_timeout_ms=5000,
            api_version_auto_timeout_ms=3000,
        )

    def subscribe(self, topic: str, handler: Handler) -> None:  # pragma: no cover
        raise NotImplementedError("Kafka consumers run as separate processes (app.integration.kafka_consumer)")

    async def publish(self, topic: str, value: dict[str, Any], key: str | None = None) -> None:
        from app.core.resilience import BREAKERS

        def _send() -> None:
            self._producer.send(topic, value=value, key=key)

        await asyncio.get_running_loop().run_in_executor(None, BREAKERS["kafka"].call, _send)
        events_published_total.labels(topic=topic, bus=self.name).inc()

    async def health(self) -> dict[str, Any]:
        connected = self._producer.bootstrap_connected()
        return {"status": "healthy" if connected else "unhealthy", "backend": "kafka", "lag": 0}

    async def close(self) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self._producer.flush, 5)
        self._producer.close(timeout=5)


EventBus = MemoryEventBus | KafkaEventBus
_bus: EventBus | None = None


def init_event_bus(mode: str, bootstrap_servers: str) -> EventBus:
    global _bus
    if mode in ("auto", "kafka"):
        try:
            _bus = KafkaEventBus(bootstrap_servers)
            log.info("event_bus_connected", backend="kafka", servers=bootstrap_servers)
            return _bus
        except Exception as exc:
            if mode == "kafka":
                raise
            log.warning("event_bus_degraded", backend="memory", reason=str(exc))
    _bus = MemoryEventBus()
    return _bus


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = MemoryEventBus()
    return _bus


def set_event_bus(bus: EventBus | None) -> None:
    global _bus
    _bus = bus
