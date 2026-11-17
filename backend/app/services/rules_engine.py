"""Rule evaluation engine (Ch. 13.1-13.3).

Pure, side-effect-free evaluators for every rule family in the spec:

* Threshold (13.2.1): single threshold, deadband/range, sustained deviation with
  ``sustained_seconds`` and ``hysteresis`` (Listing 13.1)
* Rate of change (13.2.1): % or absolute change within a sliding window
  (KPI 4 alert: "rapid pressure drop >15% in 5 minutes")
* Statistical / deviation (13.2.2): n-sigma, EWMA, moving-average deviation
* Composite / correlation (13.2.1, 13.2.4): AND/OR across tags
* Predictive (13.2.3): ML output (failure probability, anomaly score, RUL)

Per (rule, asset) state - breach start, active flag, EWMA statistics - is a small dict that the
caller persists in Redis between data points, so the engine itself stays stateless and
horizontally scalable (Ch. 3.1.1 principle 7).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import fmean, pstdev
from typing import Any

GREATER = {"greater_than", "greater_equal"}
LESS = {"less_than", "less_equal"}


@dataclass
class EvalResult:
    triggered: bool  # condition currently satisfied (after sustain + hysteresis)
    breaching: bool  # raw condition satisfied at this sample
    value: float | None = None
    threshold: float | None = None
    message: str = ""
    severity: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    cleared_for_s: float = 0.0  # seconds the condition has been clear (auto-resolve input)


def compare(operator: str, value: float, threshold: float | None = None,
            low: float | None = None, high: float | None = None) -> bool:
    match operator:
        case "greater_than":
            return threshold is not None and value > threshold
        case "greater_equal":
            return threshold is not None and value >= threshold
        case "less_than":
            return threshold is not None and value < threshold
        case "less_equal":
            return threshold is not None and value <= threshold
        case "equals":
            return threshold is not None and math.isclose(value, threshold, rel_tol=1e-9, abs_tol=1e-9)
        case "not_equals":
            return threshold is not None and not math.isclose(value, threshold, rel_tol=1e-9, abs_tol=1e-9)
        case "outside_range":
            return low is not None and high is not None and (value < low or value > high)
        case "inside_range":  # deadband: alert while the value sits inside a zone
            return low is not None and high is not None and low <= value <= high
    raise ValueError(f"unknown operator {operator}")


def _with_hysteresis(cond: dict[str, Any], active: bool) -> dict[str, Any]:
    """Once active, the clear point moves by ``hysteresis`` to prevent alarm chattering."""
    h = float(cond.get("hysteresis") or 0)
    if not active or h == 0:
        return cond
    c = dict(cond)
    op = c["operator"]
    if op in GREATER and c.get("value") is not None:
        c["value"] = c["value"] - h
    elif op in LESS and c.get("value") is not None:
        c["value"] = c["value"] + h
    elif op == "outside_range":
        c["low"], c["high"] = c["low"] + h, c["high"] - h
    return c


def _sustain(breaching: bool, ts: float, state: dict[str, Any], sustained_s: int) -> tuple[bool, float]:
    """Track breach duration; returns (triggered, seconds_clear)."""
    if breaching:
        state.pop("clear_since", None)
        state.setdefault("breach_since", ts)
        triggered = (ts - state["breach_since"]) >= sustained_s
    else:
        state.pop("breach_since", None)
        state.setdefault("clear_since", ts)
        triggered = False
    if triggered:
        state["active"] = True
    elif not breaching:
        state["active"] = False
    cleared = ts - state["clear_since"] if "clear_since" in state else 0.0
    return triggered, cleared


def evaluate_threshold(cond: dict[str, Any], value: float, ts: float, state: dict[str, Any]) -> EvalResult:
    effective = _with_hysteresis(cond, bool(state.get("active")))
    breaching = compare(effective["operator"], value, effective.get("value"), effective.get("low"), effective.get("high"))
    triggered, cleared = _sustain(breaching, ts, state, int(cond.get("sustained_seconds") or 0))
    thr = cond.get("value") if cond.get("value") is not None else (cond.get("high") if value > (cond.get("high") or 0) else cond.get("low"))
    unit = cond.get("unit") or ""
    msg = f"value {value:.3f}{unit} {cond['operator'].replace('_', ' ')} {thr}{unit}"
    if cond.get("sustained_seconds"):
        msg += f" for {cond['sustained_seconds']}s"
    return EvalResult(triggered, breaching, value, thr, msg, state=state, cleared_for_s=cleared)


def evaluate_rate(cond: dict[str, Any], history: list[tuple[float, float]], value: float, ts: float,
                  state: dict[str, Any]) -> EvalResult:
    """``history``: (epoch_s, value) samples preceding ``value``, oldest first."""
    window = int(cond.get("window_seconds") or 300)
    in_window = [(t, v) for t, v in history if ts - t <= window]
    if not in_window:
        _sustain(False, ts, state, 0)
        return EvalResult(False, False, value, None, "insufficient history", state=state)
    ref = in_window[0][1]
    delta = value - ref
    direction = cond.get("direction", "any")
    signed = delta if direction == "rise" else (-delta if direction == "drop" else abs(delta))
    breaching = False
    threshold = None
    if cond.get("max_change_pct") is not None and ref not in (0, 0.0):
        pct = signed / abs(ref) * 100
        threshold = cond["max_change_pct"]
        breaching = pct > threshold
        msg = f"{direction} of {abs(delta / ref * 100):.1f}% within {window}s (limit {threshold}%)"
    else:
        threshold = cond.get("max_change_abs")
        breaching = threshold is not None and signed > threshold
        msg = f"{direction} of {abs(delta):.3f} within {window}s (limit {threshold})"
    triggered, cleared = _sustain(breaching, ts, state, 0)
    return EvalResult(triggered, breaching, value, threshold, msg, state=state, cleared_for_s=cleared)


def evaluate_deviation(cond: dict[str, Any], history: list[float], value: float, ts: float,
                       state: dict[str, Any]) -> EvalResult:
    method = cond.get("method", "sigma")
    window = int(cond.get("window_points") or 96)
    hist = history[-window:]
    if len(hist) < 5:
        _sustain(False, ts, state, 0)
        return EvalResult(False, False, value, None, "warming up", state=state)
    breaching = False
    threshold: float | None = None
    if method == "sigma":
        mu, sd = fmean(hist), pstdev(hist)
        n = float(cond.get("n_sigma") or 3)
        threshold = mu + n * sd if value >= mu else mu - n * sd
        breaching = sd > 0 and abs(value - mu) > n * sd
        msg = f"value {value:.3f} deviates {abs(value - mu) / sd if sd else 0:.1f} sigma from mean {mu:.3f}"
    elif method == "ewma":
        alpha = float(cond.get("alpha") or 0.3)
        mean = state.get("ewma", fmean(hist))
        var = state.get("ewvar", pstdev(hist) ** 2)
        n = float(cond.get("n_sigma") or 3)
        sd = math.sqrt(var)
        breaching = sd > 0 and abs(value - mean) > n * sd
        threshold = mean + n * sd
        diff = value - mean
        state["ewma"] = mean + alpha * diff
        state["ewvar"] = (1 - alpha) * (var + alpha * diff * diff)
        msg = f"EWMA deviation: value {value:.3f} vs smoothed {mean:.3f} (+/-{n * sd:.3f})"
    else:  # moving_average
        ma = fmean(hist)
        limit = float(cond.get("max_deviation_pct") or 10)
        threshold = limit
        dev = abs(value - ma) / abs(ma) * 100 if ma else 0
        breaching = dev > limit
        msg = f"deviation {dev:.1f}% from moving average {ma:.3f} (limit {limit}%)"
    triggered, cleared = _sustain(breaching, ts, state, 0)
    return EvalResult(triggered, breaching, value, threshold, msg, state=state, cleared_for_s=cleared)


def evaluate_composite(cond: dict[str, Any], latest: dict[str, float], ts: float, state: dict[str, Any]) -> EvalResult:
    results = []
    for term in cond["terms"]:
        v = latest.get(str(term["tag_id"]))
        results.append(v is not None and compare(term["operator"], v, term.get("value"), term.get("low"), term.get("high")))
    breaching = all(results) if cond.get("logic", "and") == "and" else any(results)
    triggered, cleared = _sustain(breaching, ts, state, int(cond.get("sustained_seconds") or 0))
    msg = f"{sum(results)}/{len(results)} conditions met ({cond.get('logic', 'and').upper()})"
    return EvalResult(triggered, breaching, float(sum(results)), float(len(results)), msg, state=state,
                      cleared_for_s=cleared)


def evaluate_predictive(cond: dict[str, Any], prediction: float, ts: float, state: dict[str, Any]) -> EvalResult:
    breaching = compare(cond.get("operator", "greater_than"), prediction, cond["value"])
    triggered, cleared = _sustain(breaching, ts, state, 0)
    msg = f"{cond['model']} {cond.get('metric', 'value')} = {prediction:.3f} (threshold {cond['value']})"
    return EvalResult(triggered, breaching, prediction, cond["value"], msg, state=state, cleared_for_s=cleared)


def replay(rule_type: str, cond: dict[str, Any], series: list[tuple[float, float]]) -> dict[str, Any]:
    """Run a single-tag rule over a historical series (Rule Manager *test* / *simulate*).

    Returns the alert episodes the rule *would* have produced - start, end (when the condition
    cleared), peak value - so engineers can tune thresholds before enabling a rule.
    """
    if rule_type not in ("threshold", "rate", "deviation"):
        raise ValueError("replay supports threshold, rate and deviation rules")
    state: dict[str, Any] = {}
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    history: list[tuple[float, float]] = []
    for ts, value in series:
        if rule_type == "threshold":
            res = evaluate_threshold(cond, value, ts, state)
        elif rule_type == "rate":
            res = evaluate_rate(cond, history, value, ts, state)
        else:
            res = evaluate_deviation(cond, [v for _, v in history], value, ts, state)
        history.append((ts, value))
        if len(history) > 2000:
            history = history[-2000:]
        if res.triggered and current is None:
            current = {"start": ts, "end": None, "peak": value, "message": res.message, "samples": 0}
        if current is not None:
            if res.triggered or res.breaching:
                current["samples"] += 1
                if abs(value) > abs(current["peak"]):
                    current["peak"] = value
            else:
                current["end"] = ts
                episodes.append(current)
                current = None
    if current is not None:
        episodes.append(current)
    return {"triggered": bool(episodes), "trigger_count": len(episodes), "episodes": episodes[:500]}
