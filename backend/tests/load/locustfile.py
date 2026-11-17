"""Load scenarios from Table 16.1 (spec Ch. 16.7).

    locust -f tests/load/locustfile.py --host http://localhost:8000 --users 500 --spawn-rate 50 \
           --run-time 10m --headless --csv var/load

Run it against an instance started with AQUAINTEL_RATE_LIMIT_ENABLED=false: the test measures capacity,
and the per-IP login limit (5/min) and per-token limits would otherwise reject a single load generator.
Each demo account logs in once; virtual users share those tokens.

Acceptance criteria are checked on exit (``quitting`` hook) so CI can fail the run:
  * API baseline (500 concurrent users): P95 < 200 ms, 0% errors
  * Alert evaluation (Rule Manager test endpoint, 1000 rule evaluations/s): P95 < 100 ms
  * Telemetry ingestion via REST is exercised with an integration API key when AQUAINTEL_LOAD_API_KEY is set
    (the 10K msg/s target is a Kafka-path figure measured with the stream-processor, not through REST)
"""

from __future__ import annotations

import os
import random
from datetime import UTC, datetime

from gevent.lock import Semaphore
from locust import HttpUser, between, events, task

USERS = [("operator@aquaintel.io", 6), ("engineer@aquaintel.io", 3), ("viewer@aquaintel.io", 1)]
PASSWORD = os.environ.get("AQUAINTEL_LOAD_PASSWORD", "AquaIntel!2026")
VIEWS = ["operations", "executive", "energy", "quality", "maintenance"]
_TOKENS: dict[str, str] = {}
_LOGIN_LOCK = Semaphore()  # users spawn concurrently; only the first one per account logs in


def _bearer(user: HttpUser, email: str) -> None:
    with _LOGIN_LOCK:
        if email not in _TOKENS:
            r = user.client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}, name="/v1/auth/login")
            _TOKENS[email] = r.json()["data"]["tokens"]["access_token"]
    user.client.headers["Authorization"] = f"Bearer {_TOKENS[email]}"


class DashboardUser(HttpUser):
    """API baseline: the read traffic a control-room screen and an analyst generate."""

    weight = 8
    wait_time = between(1, 3)

    def on_start(self) -> None:
        _bearer(self, random.choices([u for u, _ in USERS], weights=[w for _, w in USERS])[0])

    @task(5)
    def dashboard_kpis(self) -> None:
        self.client.get("/v1/kpis/dashboard", params={"view": random.choice(VIEWS)}, name="/v1/kpis/dashboard")

    @task(4)
    def active_alerts(self) -> None:
        self.client.get("/v1/alerts", params={"status": "triggered,acknowledged", "per_page": 25}, name="/v1/alerts")

    @task(4)
    def latest_telemetry(self) -> None:
        self.client.get("/v1/telemetry/latest", name="/v1/telemetry/latest")

    @task(2)
    def asset_tree(self) -> None:
        self.client.get("/v1/assets", params={"view": "tree"}, name="/v1/assets?view=tree")

    @task(1)
    def alert_analytics(self) -> None:
        self.client.get("/v1/alerts/analytics", name="/v1/alerts/analytics")


class RuleEvaluator(HttpUser):
    """Alert evaluation: each request evaluates a threshold rule over 100 samples (=100 evaluations)."""

    weight = 1
    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        _bearer(self, "engineer@aquaintel.io")
        tags = self.client.get("/v1/telemetry/tags", params={"parameter": "vibration"}, name="/v1/telemetry/tags")
        self.tag_id = tags.json()["data"][0]["id"]

    @task
    def evaluate(self) -> None:
        values = [random.gauss(3.0, 1.2) for _ in range(100)]
        rule = {"name": "load-test vibration", "rule_type": "threshold", "severity": "major", "tag_id": self.tag_id,
                "condition": {"operator": "greater_than", "value": 4.5, "sustained_seconds": 120, "hysteresis": 0.2}}
        self.client.post("/v1/alerts/rules/test", json={"rule": rule, "values": values, "interval_seconds": 60},
                         name="/v1/alerts/rules/test")


class IngestClient(HttpUser):
    """REST ingestion from a protocol adapter (only when an integration key is provided)."""

    weight = 1
    wait_time = between(0.5, 1)
    abstract = not os.environ.get("AQUAINTEL_LOAD_API_KEY")

    def on_start(self) -> None:
        self.client.headers["X-API-Key"] = os.environ["AQUAINTEL_LOAD_API_KEY"]

    @task
    def ingest(self) -> None:
        now = datetime.now(UTC).isoformat()
        points = [{"tag": f"plant_a_pump_00{p}_vibration", "time": now, "value": round(random.gauss(3, 0.3), 3)}
                  for p in range(1, 5)]
        self.client.post("/v1/telemetry/ingest", json={"source": "load-test", "points": points},
                         name="/v1/telemetry/ingest")


@events.quitting.add_listener
def acceptance(environment, **_kw) -> None:  # type: ignore[no-untyped-def]
    stats = environment.stats
    failures = []
    if stats.total.fail_ratio > 0:
        failures.append(f"error ratio {stats.total.fail_ratio:.2%} (target 0%)")
    for name, limit_ms in (("/v1/kpis/dashboard", 200), ("/v1/alerts", 200), ("/v1/telemetry/latest", 200),
                           ("/v1/alerts/rules/test", 100)):
        entry = stats.entries.get((name, "GET")) or stats.entries.get((name, "POST"))
        if entry and entry.num_requests and entry.get_response_time_percentile(0.95) > limit_ms:
            failures.append(f"{name} P95 {entry.get_response_time_percentile(0.95):.0f} ms > {limit_ms} ms")
    if failures:
        print("Load-test acceptance FAILED:\n  " + "\n  ".join(failures))
        environment.process_exit_code = 1
    else:
        print("Load-test acceptance passed (Table 16.1)")
