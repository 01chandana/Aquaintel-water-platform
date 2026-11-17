"""Telemetry validation & normalization (Appendix A.3.4, Ch. 5.3.1 step 3).

Each sample receives a ``status`` of ``good`` / ``suspect`` / ``bad``:

* ``bad``      - non-finite value, or outside the tag's physical range (``min_valid``/``max_valid``
                 or the parameter defaults below). Stored for audit but excluded from aggregates.
* ``suspect``  - OPC-UA quality < 192, rate of change above ``max_delta_per_hour``, or
                 |z-score| > 3.5 against recent history. Kept in aggregates, flagged in UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev

# Appendix A.3.4 "range" + "rate_of_change" defaults, keyed by parameter
# Appendix A.3.4 validation rules
RANGES: dict[str, tuple[float, float]] = {
    "ph": (0, 14), "turbidity": (0, 1000), "temperature": (-5, 50), "water_temperature": (-5, 50),
        "ambient_temperature": (-40, 60), "discharge_cfs": (0, 1_000_000), "chlorine": (0, 10),
        "pressure": (0, 40), "flow": (0, 100_000), "tank_level": (0, 100), "power_kw": (0, 10_000),
        "power_factor": (0, 1), "vibration": (0, 100), "bearing_temperature": (-5, 200),
        "motor_current": (0, 2000), "thm": (0, 500), "toc": (0, 50),
}
MAX_DELTA_PER_HOUR: dict[str, float] = {"ph": 2.0, "temperature": 10.0, "water_temperature": 10.0}
Z_SCORE_THRESHOLD = 3.5


@dataclass
class Verdict:
    status: str
    reasons: list[str]


def validate_point(
    value: float,
    quality: int,
    parameter: str,
    min_valid: float | None,
    max_valid: float | None,
    max_delta_per_hour: float | None,
    previous: tuple[float, float] | None,  # (epoch_s, value)
    ts: float,
    history: list[float] | None = None,
) -> Verdict:
    reasons: list[str] = []
    if not math.isfinite(value):
        return Verdict("bad", ["non_finite"])
    lo, hi = RANGES.get(parameter, (None, None))
    lo = min_valid if min_valid is not None else lo
    hi = max_valid if max_valid is not None else hi
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        return Verdict("bad", ["out_of_range"])
    if quality < 192:
        reasons.append("low_quality")
    limit = max_delta_per_hour or MAX_DELTA_PER_HOUR.get(parameter)
    if limit and previous and ts > previous[0]:
        hours = max((ts - previous[0]) / 3600, 1 / 60)
        if abs(value - previous[1]) / hours > limit and abs(value - previous[1]) > limit / 4:
            reasons.append("rate_of_change")
    if history and len(history) >= 20:
        mu, sd = fmean(history), pstdev(history)
        if sd > 0 and abs(value - mu) / sd > Z_SCORE_THRESHOLD:
            reasons.append("z_score_outlier")
    return Verdict("suspect" if reasons else "good", reasons)


def iqr_bounds(values: list[float], k: float = 1.5) -> tuple[float, float]:
    s = sorted(values)
    q1, q3 = s[len(s) // 4], s[(3 * len(s)) // 4]
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr
