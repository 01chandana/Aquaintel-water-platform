"""MQTT protocol adapter (Ch. 1.4 item 1, Ch. 5.3.1 steps 1-2).

Subscribes to ``aquaintel/<site>/<tag_external_id>`` on the plant MQTT broker. Payloads are
JSON ``{"t": iso8601, "v": float, "q": 192}`` (or a bare number). Samples are batched and
forwarded to the platform's ingestion API with an integration API key, which publishes them
to ``telemetry.raw``.

Run: ``python -m app.integration.mqtt_bridge --broker mqtt://localhost:1883 --api-key aq_...``
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)
TOPIC = "aquaintel/+/+"


def parse_message(topic: str, payload: bytes) -> dict[str, object] | None:
    try:
        _, _site, tag = topic.split("/", 2)
        body = json.loads(payload.decode())
        if isinstance(body, (int, float)):
            body = {"v": body}
        return {"tag": tag, "time": body.get("t") or datetime.now(UTC).isoformat(), "value": float(body["v"]),
                "quality": int(body.get("q", 192))}
    except (ValueError, KeyError, TypeError):
        return None


class MqttBridge:
    def __init__(self, broker: str, api_url: str, api_key: str, batch_size: int = 500, flush_s: float = 2.0) -> None:
        import paho.mqtt.client as mqtt

        self.url = urlparse(broker)
        self.api_url, self.api_key = api_url.rstrip("/"), api_key
        self.batch_size, self.flush_s = batch_size, flush_s
        self.buffer: queue.Queue[dict[str, object]] = queue.Queue(maxsize=100_000)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aquaintel-mqtt-bridge")
        self.client.on_connect = lambda c, *_: c.subscribe(TOPIC, qos=1)
        self.client.on_message = self._on_message

    def _on_message(self, _c: object, _u: object, msg: object) -> None:
        point = parse_message(msg.topic, msg.payload)  # type: ignore[attr-defined]
        if point is not None:
            self.buffer.put(point)

    def _flush_loop(self) -> None:
        with httpx.Client(timeout=10, headers={"X-API-Key": self.api_key}) as http:
            while True:
                batch: list[dict[str, object]] = []
                deadline = time.time() + self.flush_s
                while len(batch) < self.batch_size and time.time() < deadline:
                    try:
                        batch.append(self.buffer.get(timeout=0.2))
                    except queue.Empty:
                        continue
                if not batch:
                    continue
                for attempt in range(5):  # retry with backoff; points stay buffered on failure
                    try:
                        r = http.post(f"{self.api_url}/telemetry/ingest", json={"source": "mqtt", "points": batch})
                        r.raise_for_status()
                        break
                    except httpx.HTTPError as exc:
                        log.warning("ingest_retry", attempt=attempt, error=str(exc))
                        time.sleep(2 ** attempt * 0.5)

    def run(self) -> None:
        threading.Thread(target=self._flush_loop, daemon=True).start()
        self.client.connect(self.url.hostname or "localhost", self.url.port or 1883)
        self.client.loop_forever()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--broker", default=os.environ.get("AQUAINTEL_MQTT_BROKER", "mqtt://localhost:1883"))
    p.add_argument("--api-url", default=os.environ.get("AQUAINTEL_INGEST_API_URL", "http://localhost:8000/v1"))
    p.add_argument("--api-key", default=os.environ.get("AQUAINTEL_INTEGRATION_API_KEY"))
    a = p.parse_args()
    if not a.api_key:
        p.error("--api-key or AQUAINTEL_INTEGRATION_API_KEY is required")
    configure_logging()
    MqttBridge(a.broker, a.api_url, a.api_key).run()


if __name__ == "__main__":
    main()
