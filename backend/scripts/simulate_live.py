"""Live protocol-adapter simulator (out-of-scope SCADA replaced by simulation, Ch. 1.7).

Streams plant telemetry into the platform through the real ingestion path:
``POST /v1/telemetry/ingest`` with an integration API key -> ``telemetry.raw`` -> stream
processor -> TimescaleDB, rules engine, alerts and WebSocket dashboards.

Usage::

    python scripts/simulate_live.py --api-key $(cat var/simulator_api_key.txt)
    python scripts/simulate_live.py --interval 5 --speed 180   # 1 sample per 15 simulated min every 5 s
    python scripts/simulate_live.py --inject-fault plant_a_pump_002   # force a bearing degradation episode

``--backfill`` first fills the gap between the last stored sample and now, so dashboards
stay continuous after the stack was stopped.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integration.simulator import FaultEpisode, PlantModel

STEP = timedelta(minutes=15)


def post(client: httpx.Client, url: str, t: datetime, values: dict[str, float | None]) -> int:
    points = [{"tag": k, "time": t.isoformat(), "value": round(v, 5)} for k, v in values.items() if v is not None]
    for i in range(0, len(points), 5000):
        r = client.post(f"{url}/telemetry/ingest", json={"source": "mqtt", "points": points[i:i + 5000]})
        r.raise_for_status()
    return len(points)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--api-url", default="http://localhost:8000/v1")
    p.add_argument("--api-key", default=None, help="defaults to var/simulator_api_key.txt")
    p.add_argument("--interval", type=float, default=15.0, help="wall-clock seconds between batches")
    p.add_argument("--speed", type=float, default=1.0, help="simulated seconds per wall-clock second")
    p.add_argument("--backfill", action="store_true", help="fill the gap since the last stored sample first")
    p.add_argument("--backfill-hours", type=float, default=12)
    p.add_argument("--inject-fault", default=None, help="pump external id to degrade over the next hours")
    a = p.parse_args()
    key = a.api_key or (Path(__file__).resolve().parents[1] / "var" / "simulator_api_key.txt").read_text().strip()

    now = datetime.now(UTC).replace(second=0, microsecond=0)
    model = PlantModel(now - timedelta(days=1), now + timedelta(days=30), seed=int(now.timestamp()) % 10_000, faults=False)
    if a.inject_fault:
        model.faults.append(FaultEpisode(a.inject_fault, now - timedelta(days=6), now + timedelta(hours=8), 6, "BRG-OUTER-RACE"))

    with httpx.Client(timeout=30, headers={"X-API-Key": key}) as client:
        sim_t = now
        if a.backfill:
            t = now - timedelta(hours=a.backfill_hours)
            t -= timedelta(minutes=t.minute % 15)
            n = 0
            while t < now:
                n += post(client, a.api_url, t, model.step(t))
                t += STEP
            print(f"backfilled {n} points up to {now:%H:%M}")
            sim_t = t
        print(f"streaming every {a.interval}s (speed x{a.speed}); Ctrl+C to stop")
        while True:
            started = time.time()
            values = model.step(sim_t, dt_h=a.interval * a.speed / 3600)
            try:
                n = post(client, a.api_url, sim_t, values)
                print(f"{datetime.now(UTC):%H:%M:%S} sent {n} points for {sim_t:%Y-%m-%d %H:%M}")
            except httpx.TransportError as exc:  # API restarting or unreachable: keep simulating, skip this sample
                print(f"{datetime.now(UTC):%H:%M:%S} API unreachable ({exc.__class__.__name__}); retrying next interval")
            sim_t += timedelta(seconds=a.interval * a.speed)
            if a.speed <= 1:
                sim_t = max(sim_t, datetime.now(UTC))
            time.sleep(max(0.0, a.interval - (time.time() - started)))


if __name__ == "__main__":
    main()
