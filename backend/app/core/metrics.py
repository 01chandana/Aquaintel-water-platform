"""Prometheus metric definitions (spec Listing 19.1, Ch. 19.3)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Summary

# HTTP metrics
http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)

# Business metrics
telemetry_ingestion_rate = Counter(
    "telemetry_ingestion_rate", "Telemetry data points ingested", ["source", "asset_type"]
)
telemetry_ingestion_lag_seconds = Histogram(
    "telemetry_ingestion_lag_seconds", "Delay between sample time and ingestion", ["source"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300, 900],
)
telemetry_rejected_total = Counter(
    "telemetry_rejected_total", "Telemetry points rejected by validation", ["reason"]
)
alert_generation_rate = Counter("alert_generation_rate", "Alerts generated", ["severity", "rule_type"])
alert_suppressed_total = Counter("alert_suppressed_total", "Alerts suppressed by fatigue controls", ["reason"])
kpi_computation_duration = Summary(
    "kpi_computation_duration_seconds", "KPI computation time", ["kpi_category"]
)
ml_inference_latency = Histogram(
    "ml_inference_latency_seconds", "Model inference latency", ["model"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1],
)
ml_predictions_total = Counter("ml_predictions_total", "Predictions served", ["model", "mode"])
ml_feature_drift_psi = Gauge("ml_feature_drift_psi", "Max PSI across equipment/process features", ["model"])
notifications_sent_total = Counter("notifications_sent_total", "Notifications dispatched", ["channel", "status"])
websocket_connections = Gauge("websocket_connections", "Open dashboard WebSocket connections")
events_published_total = Counter("events_published_total", "Domain events published", ["topic", "bus"])

# Resource metrics
db_connection_pool_size = Gauge("db_connection_pool_size", "Active database connections")
redis_memory_usage_bytes = Gauge("redis_memory_usage_bytes", "Redis memory usage")


async def refresh_resource_gauges() -> None:
    """Sample pool and cache gauges at scrape time (cheap; avoids a background poller)."""
    from app.core.cache import get_cache
    from app.db.session import get_engine

    try:
        db_connection_pool_size.set(get_engine().pool.checkedout())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - engine not initialised or NullPool
        db_connection_pool_size.set(0)
    cache = get_cache()
    if hasattr(cache, "memory_bytes"):
        try:
            redis_memory_usage_bytes.set(await cache.memory_bytes())
        except Exception:  # noqa: BLE001 - Redis down; leave the last value, health check reports it
            return
