"""Kafka event bus against a real broker (CI provides one; skipped when none is reachable).

Checks the two properties the stream processor relies on (Ch. 5.4.1): the message round-trips as the
standard event envelope, and the asset id is used as the message key so per-asset ordering holds.
"""

from __future__ import annotations

import json
import os
import socket
import uuid

import pytest

from app.core.events import TELEMETRY_RAW, KafkaEventBus, envelope

BOOTSTRAP = os.environ.get("AQUAINTEL_TEST_KAFKA", "localhost:9092")


def _reachable() -> bool:
    host, port = BOOTSTRAP.split(",")[0].rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _reachable(), reason=f"no Kafka broker at {BOOTSTRAP}")]


async def test_publish_is_keyed_by_asset_and_round_trips() -> None:
    from kafka import KafkaConsumer, TopicPartition

    asset_id = str(uuid.uuid4())
    bus = KafkaEventBus(BOOTSTRAP)
    try:
        assert (await bus.health())["status"] == "healthy"
        await bus.publish(TELEMETRY_RAW, envelope("telemetry.raw", {"points": [{"value": 1.5}]}, source="test"),
                          key=asset_id)
    finally:
        await bus.close()

    consumer = KafkaConsumer(bootstrap_servers=BOOTSTRAP.split(","), consumer_timeout_ms=10_000,
                             value_deserializer=lambda b: json.loads(b.decode()))
    partitions = [TopicPartition(TELEMETRY_RAW, p) for p in consumer.partitions_for_topic(TELEMETRY_RAW) or {0}]
    consumer.assign(partitions)
    consumer.seek_to_beginning()
    found = [m for m in consumer if m.key and m.key.decode() == asset_id]
    consumer.close()
    assert len(found) == 1
    assert found[0].value["payload"]["points"][0]["value"] == 1.5 and found[0].value["source"] == "test"
