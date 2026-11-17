"""Pump scheduling optimisation, mixed-integer linear programme (Use Case 18, roadmap week 12).

Decision variables for P pumps over T hourly periods:

* ``x[p,t] in {0,1}``   pump p runs in hour t
* ``s[p,t] >= 0``       start-up indicator (x[p,t] - x[p,t-1]), penalised to limit cycling
* ``L[t]``              reservoir volume at the end of hour t (m3)

Minimise   sum_t tariff[t] * sum_p kW_p * x[p,t]  +  start_cost * sum s[p,t]
subject to L[t] = L[t-1] + sum_p Q_p x[p,t] - demand[t]      (mass balance)
           L_min <= L[t] <= L_max                            (tank limits)
           L[T] >= L[0]                                      (no "borrowing" storage)
           sum_p kW_p x[p,t] <= contracted_kW                (peak-demand cap, Use Case 19)

Solved with HiGHS via ``scipy.optimize.milp``. The baseline for savings is the common
"follow demand" policy: run just enough pumps each hour to meet that hour's demand.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


@dataclass
class PumpSpec:
    name: str
    flow_m3h: float
    power_kw: float


def solve(
    pumps: list[PumpSpec],
    demand: list[float],
    tariff: list[float],
    capacity_m3: float,
    initial_pct: float,
    min_pct: float,
    max_pct: float,
    contracted_kw: float | None = None,
    start_cost: float = 2.0,
    time_limit_s: float = 10.0,
) -> dict[str, Any]:
    P, T = len(pumps), len(demand)
    nx, ns = P * T, P * T
    n = nx + ns + T
    ix = lambda p, t: p * T + t  # noqa: E731
    is_ = lambda p, t: nx + p * T + t  # noqa: E731
    il = lambda t: nx + ns + t  # noqa: E731
    L0 = capacity_m3 * initial_pct / 100

    c = np.zeros(n)
    for p, pump in enumerate(pumps):
        for t in range(T):
            c[ix(p, t)] = tariff[t] * pump.power_kw
            c[is_(p, t)] = start_cost

    rows: list[np.ndarray] = []
    lo: list[float] = []
    hi: list[float] = []

    def row() -> np.ndarray:
        return np.zeros(n)

    def add(r: np.ndarray, lower: float, upper: float) -> None:
        rows.append(r)
        lo.append(lower)
        hi.append(upper)

    for t in range(T):  # mass balance: L[t] - L[t-1] - sum Q x = -D
        r = row()
        r[il(t)] = 1
        if t > 0:
            r[il(t - 1)] = -1
        for p, pump in enumerate(pumps):
            r[ix(p, t)] = -pump.flow_m3h
        rhs = -demand[t] + (L0 if t == 0 else 0)
        add(r, rhs, rhs)
    for p in range(P):  # start-up indicators
        for t in range(T):
            r = row()
            r[is_(p, t)] = 1
            r[ix(p, t)] = -1
            if t > 0:
                r[ix(p, t - 1)] = 1
            add(r, 0, np.inf)
    r = row()
    r[il(T - 1)] = 1
    add(r, L0, np.inf)
    if contracted_kw:
        for t in range(T):
            r = row()
            for p, pump in enumerate(pumps):
                r[ix(p, t)] = pump.power_kw
            add(r, 0, contracted_kw)

    lb = np.zeros(n)
    ub = np.ones(n)
    ub[nx:nx + ns] = 1
    lb[nx + ns:] = capacity_m3 * min_pct / 100
    ub[nx + ns:] = capacity_m3 * max_pct / 100
    integrality = np.zeros(n)
    integrality[:nx] = 1

    res = milp(c, constraints=LinearConstraint(np.array(rows), lo, hi), bounds=Bounds(lb, ub),
               integrality=integrality, options={"time_limit": time_limit_s, "mip_rel_gap": 1e-3})
    baseline = follow_demand_baseline(pumps, demand, tariff)
    if res.x is None:  # 2 = constraints cannot all be met; 1 here = time limit before any schedule was found
        return {"status": "infeasible" if res.status == 2 else "no_solution", "message": res.message,
                "baseline": baseline}
    x = np.round(res.x[:nx]).reshape(P, T)
    levels = res.x[nx + ns:]
    energy_cost = float(sum(tariff[t] * pumps[p].power_kw * x[p, t] for p in range(P) for t in range(T)))
    hours = []
    for t in range(T):
        on = [pumps[p].name for p in range(P) if x[p, t] > 0.5]
        hours.append({"hour": t, "pumps_on": on, "pumps_running": len(on),
                      "pumped_m3": round(sum(pumps[p].flow_m3h for p in range(P) if x[p, t] > 0.5), 1),
                      "demand_m3": round(demand[t], 1), "tariff": tariff[t],
                      "power_kw": round(sum(pumps[p].power_kw for p in range(P) if x[p, t] > 0.5), 1),
                      "level_pct": round(levels[t] / capacity_m3 * 100, 2)})
    savings = (baseline["cost"] - energy_cost) / baseline["cost"] * 100 if baseline["cost"] else 0.0
    # HiGHS status 1 = time limit hit with an incumbent: a valid, feasible schedule whose cost is within
    # mip_gap of the optimum. Operators get it (labelled), rather than nothing.
    status = "optimal" if res.status == 0 else "feasible" if res.status == 1 else str(res.message)
    return {"status": status, "cost": round(energy_cost, 2),
            "baseline": baseline, "savings_pct": round(savings, 2), "hours": hours,
            "starts": int(round(res.x[nx:nx + ns].sum())), "mip_gap": getattr(res, "mip_gap", None)}


def follow_demand_baseline(pumps: list[PumpSpec], demand: list[float], tariff: list[float]) -> dict[str, Any]:
    ordered = sorted(pumps, key=lambda p: p.power_kw / p.flow_m3h)
    cost = 0.0
    for t, d in enumerate(demand):
        remaining, used = d, 0
        while remaining > 1e-6 and used < len(ordered):
            remaining -= ordered[used].flow_m3h
            used += 1
        cost += tariff[t] * sum(p.power_kw for p in ordered[:used])
    return {"policy": "follow_demand", "cost": round(cost, 2)}


def pump_power(flow_m3h: float, head_m: float, efficiency: float) -> float:
    return 9.81 * (flow_m3h / 3600) * head_m / max(efficiency, 0.3)


def coagulant_dose_mg_l(raw_turbidity: float, slope: float = 1.15, intercept: float = 9.0) -> float:
    """Rule-based jar-test curve; slope/intercept are refitted from plant history by the service."""
    return max(5.0, intercept + slope * raw_turbidity)


def chlorine_setpoint(target_mg_l: float, k_per_h: float, worst_residence_h: float, safety: float = 1.05) -> float:
    """Invert first-order decay so the worst endpoint still receives the target residual."""
    return min(4.0, target_mg_l * math.exp(k_per_h * worst_residence_h) * safety)
