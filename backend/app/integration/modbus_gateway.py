"""Modbus TCP gateway (Ch. 1.4 item 1, Ch. 3.3.5).

Polls holding registers from PLC/RTUs according to a register map and forwards scaled
values to the ingestion API. Register map entries::

    {"tag": "plant_a_pump_001_flow", "unit_id": 1, "address": 100, "count": 2,
     "type": "float32", "scale": 1.0}

Run: ``python -m app.integration.modbus_gateway --host 10.0.0.12 --map map.json --api-key aq_...``
"""

from __future__ import annotations

import argparse
import json
import struct
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


def decode(registers: list[int], kind: str, scale: float) -> float:
    if kind == "float32":
        raw = struct.unpack(">f", struct.pack(">HH", registers[0], registers[1]))[0]
    elif kind == "int16":
        raw = struct.unpack(">h", struct.pack(">H", registers[0]))[0]
    else:  # uint16
        raw = registers[0]
    return float(raw) * scale


def poll_once(client: Any, register_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points = []
    now = datetime.now(UTC).isoformat()
    for entry in register_map:
        rr = client.read_holding_registers(entry["address"], count=entry.get("count", 1), slave=entry.get("unit_id", 1))
        if rr.isError():
            points.append({"tag": entry["tag"], "time": now, "value": 0.0, "quality": 0})  # bad quality marker
            continue
        points.append({"tag": entry["tag"], "time": now, "quality": 192,
                       "value": decode(rr.registers, entry.get("type", "uint16"), entry.get("scale", 1.0))})
    return points


def main() -> None:
    from pymodbus.client import ModbusTcpClient

    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=502)
    p.add_argument("--map", required=True, help="JSON register map")
    p.add_argument("--interval", type=float, default=15.0)
    p.add_argument("--api-url", default="http://localhost:8000/v1")
    p.add_argument("--api-key", required=True)
    a = p.parse_args()
    configure_logging()
    register_map = json.loads(open(a.map).read())
    client = ModbusTcpClient(a.host, port=a.port, timeout=3)
    with httpx.Client(timeout=10, headers={"X-API-Key": a.api_key}) as http:
        while True:
            if not client.connected:
                client.connect()
            try:
                points = poll_once(client, register_map)
                http.post(f"{a.api_url}/telemetry/ingest", json={"source": "modbus", "points": points}).raise_for_status()
            except Exception as exc:  # noqa: BLE001
                log.warning("modbus_poll_failed", error=str(exc))
            time.sleep(a.interval)


if __name__ == "__main__":
    main()
