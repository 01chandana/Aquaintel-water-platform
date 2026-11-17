"""Model artifacts & registry (Ch. 10.6.3, 10.11, 14.9).

Artifacts are pickled bundles stored in MinIO (``aquaintel-models``) or the local store.
If ``AQUAINTEL_MLFLOW_TRACKING_URI`` is set, every training run is also logged to MLflow
(params, metrics, artifact) behind a circuit breaker - an MLflow outage never blocks
training or serving. The ``ml_models`` table mirrors registry state so the API can
enforce stage transitions (None -> Staging -> Production -> Archived).
"""

from __future__ import annotations

import io
import pickle
from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.resilience import BREAKERS
from app.core.storage import get_store

log = get_logger(__name__)


async def save_artifact(name: str, version: str, bundle: dict[str, Any]) -> str:
    buf = io.BytesIO()
    pickle.dump(bundle, buf, protocol=pickle.HIGHEST_PROTOCOL)
    return await get_store().put(get_settings().minio_bucket_models, f"{name}/{version}/model.pkl", buf.getvalue(),
                                 "application/octet-stream")


_bundle_cache: dict[str, dict[str, Any]] = {}


async def load_artifact(name: str, version: str) -> dict[str, Any]:
    key = f"{name}:{version}"
    if key not in _bundle_cache:  # in-process model cache keeps inference < 100 ms (Ch. 1.8)
        raw = await get_store().get(get_settings().minio_bucket_models, f"{name}/{version}/model.pkl")
        _bundle_cache[key] = pickle.loads(raw)  # noqa: S301 - artifacts are produced by our own pipeline
    return _bundle_cache[key]


def log_to_mlflow(experiment: str, run_name: str, params: dict[str, Any], metrics: dict[str, float],
                  bundle: dict[str, Any]) -> str | None:
    uri = get_settings().mlflow_tracking_uri
    if not uri:
        return None

    def _log() -> str:
        import mlflow

        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment)
        with mlflow.start_run(run_name=run_name) as run:
            mlflow.log_params({k: v for k, v in params.items() if isinstance(v, (int, float, str, bool))})
            mlflow.log_metrics({k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))})
            buf = pickle.dumps(bundle)
            mlflow.log_dict({"features": bundle.get("features", [])}, "features.json")
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "model.pkl"
                p.write_bytes(buf)
                mlflow.log_artifact(str(p))
            return run.info.run_id

    try:
        return BREAKERS["mlflow"].call(_log)
    except Exception as exc:  # noqa: BLE001
        log.warning("mlflow_unavailable", error=str(exc))
        return None


@lru_cache
def next_version(existing: tuple[str, ...], bump: str = "minor") -> str:
    if not existing:
        return "1.0.0"
    major, minor, patch = max(tuple(int(x) for x in v.split(".")) for v in existing)
    return f"{major}.{minor + 1}.0" if bump == "minor" else f"{major}.{minor}.{patch + 1}"
