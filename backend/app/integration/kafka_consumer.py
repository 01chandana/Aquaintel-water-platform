"""Kafka consumer service: the stream processor (Ch. 5.3.1, Table 5.2).

Run as its own deployment: ``python -m app.integration.kafka_consumer``.

* Consumer group ``stream-processor`` on ``telemetry.raw`` (scale by adding replicas; topics
  are partitioned by asset id so per-asset ordering is preserved).
* At-least-once delivery: offsets are committed **after** the batch is persisted; the
  TimescaleDB insert is idempotent (``ON CONFLICT DO NOTHING``) so redelivery is safe.
* Poison messages are forwarded to the ``telemetry.dlq`` dead-letter topic (Table 5.3).
"""

from __future__ import annotations

import asyncio
import json
import signal

from app.core.config import get_settings
from app.core.events import TELEMETRY_DLQ, TELEMETRY_RAW, get_event_bus
from app.core.logging import configure_logging, get_logger
from app.services.telemetry_service import TelemetryPipeline
from app.workers.runtime import bootstrap

log = get_logger(__name__)


async def consume(stop: asyncio.Event) -> None:
    from kafka import KafkaConsumer

    s = get_settings()
    await bootstrap(pooled=True)
    pipeline = TelemetryPipeline()
    consumer = KafkaConsumer(
        TELEMETRY_RAW, bootstrap_servers=s.kafka_bootstrap_servers.split(","), group_id="stream-processor",
        enable_auto_commit=False, auto_offset_reset="earliest", max_poll_records=200,
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    log.info("stream_processor_started", topic=TELEMETRY_RAW)
    loop = asyncio.get_running_loop()
    try:
        while not stop.is_set():
            batch = await loop.run_in_executor(None, lambda: consumer.poll(timeout_ms=1000))
            for _tp, records in batch.items():
                for record in records:
                    try:
                        await pipeline.handle_event(record.value)
                    except Exception as exc:
                        log.exception("telemetry_batch_failed", offset=record.offset, error=str(exc))
                        await get_event_bus().publish(TELEMETRY_DLQ, {"error": str(exc), "value": record.value})
            if batch:
                await loop.run_in_executor(None, consumer.commit)
    finally:
        consumer.close()


def main() -> None:
    configure_logging(get_settings().log_level)
    stop = asyncio.Event()

    async def runner() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await consume(stop)

    asyncio.run(runner())


if __name__ == "__main__":
    main()
