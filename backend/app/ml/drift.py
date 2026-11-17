"""Drift detection (Ch. 10.9): Population Stability Index, KL divergence and KS test.

PSI < 0.1 stable · 0.1-0.2 moderate · > 0.2 significant -> alert + retraining trigger.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

PSI_ALERT = 0.2
PSI_ACCEPT = 0.1  # Ch. 10.7.2 acceptance criterion
REFERENCE_DAYS = 30  # baseline = the most recent month of training data, so slow seasonal trend doesn't dominate
MIN_ROWS = 20

# Weather-driven inputs move with the season by design. Their drift is reported but does not raise an alert;
# the monthly retraining cadence absorbs it. Alerts fire on equipment/process features only.
SEASONAL_FEATURES = frozenset({"water_temperature", "temperature", "ambient_temperature", "toc", "rolling_7d",
                               "hours_since_pm"})


def baseline_profile(df: pd.DataFrame, features: list[str], bins: int = 10) -> dict[str, Any]:
    """Quantile-bin each training feature; stored with the model for later PSI checks."""
    out: dict[str, Any] = {}
    for f in features:
        x = df[f].dropna().to_numpy()
        if len(x) < 20:
            continue
        edges = np.unique(np.quantile(x, np.linspace(0, 1, bins + 1)))
        if len(edges) < 3:
            continue
        counts, _ = np.histogram(x, bins=edges)
        out[f] = {"edges": edges.tolist(), "freq": (counts / counts.sum()).tolist(),
                  "mean": float(x.mean()), "std": float(x.std()), "sample": np.random.default_rng(0).choice(
                      x, size=min(500, len(x)), replace=False).round(5).tolist()}
    return out


def psi(expected: np.ndarray, actual: np.ndarray, eps: float = 1e-4) -> float:
    e = np.clip(expected, eps, None)
    a = np.clip(actual, eps, None)
    return float(np.sum((a - e) * np.log(a / e)))


def drift_report(baseline: dict[str, Any], current: pd.DataFrame) -> dict[str, Any]:
    features = []
    for f, prof in baseline.items():
        if f not in current:
            continue
        x = current[f].dropna().to_numpy()
        if len(x) < MIN_ROWS:
            continue
        edges = np.array(prof["edges"])
        counts, _ = np.histogram(np.clip(x, edges[0], edges[-1]), bins=edges)
        actual = counts / max(counts.sum(), 1)
        expected = np.array(prof["freq"])
        p = psi(expected, actual)
        kl = float(stats.entropy(np.clip(actual, 1e-4, None), np.clip(expected, 1e-4, None)))
        ks = stats.ks_2samp(np.array(prof["sample"]), x)
        features.append({"feature": f, "psi": round(p, 4), "kl_divergence": round(kl, 4),
                         "ks_statistic": round(float(ks.statistic), 4), "ks_pvalue": round(float(ks.pvalue), 6),
                         "baseline_mean": round(prof["mean"], 4), "current_mean": round(float(x.mean()), 4),
                         "seasonal": f in SEASONAL_FEATURES,
                         "status": "significant" if p > PSI_ALERT else "moderate" if p > PSI_ACCEPT else "stable"})
    max_psi = max((f["psi"] for f in features), default=0.0)
    alert_psi = max((f["psi"] for f in features if not f["seasonal"]), default=0.0)
    return {"features": sorted(features, key=lambda f: -f["psi"]), "max_psi": round(max_psi, 4),
            "monitored_max_psi": round(alert_psi, 4), "drift_detected": alert_psi > PSI_ALERT,
            "retrain_recommended": max_psi > PSI_ALERT,
            "thresholds": {"stable": f"< {PSI_ACCEPT}", "moderate": f"{PSI_ACCEPT}-{PSI_ALERT}", "significant": f"> {PSI_ALERT}"}}
