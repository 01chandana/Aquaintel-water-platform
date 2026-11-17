"""Physics-flavoured plant simulator (Appendix A.4 "Data Generator for Development").

Generates realistic water-operations telemetry for the in-scope "simulated SCADA"
(Ch. 1.7 out-of-scope note): diurnal/seasonal demand, pump hydraulics with an
efficiency curve around BEP, bearing-degradation fault episodes ending in failure,
chlorine first-order decay along the network (C = C0 e^{-kt}), turbidity events,
DMA leakage bursts, valve torque drift, missing data and outliers.

The same model drives both the historical bulk generator
(``scripts/generate_synthetic_data.py``) and the live protocol-adapter simulator
(``scripts/simulate_live.py``) so training data and live data share one distribution.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.timeutil import local_hour, to_plant

GENERATOR_CONFIG: dict[str, Any] = {  # Listing A.3 defaults
    "num_assets": 50,
    "num_tags_per_asset": 10,
    "start_date": "2024-01-01",
    "end_date": "2026-07-01",
    "frequency_minutes": 15,
    "missing_data_ratio": 0.02,
    "outlier_ratio": 0.001,
    "add_known_fault_events": True,
    "fault_event_probability": 0.001,
}

PUMP_TAGS = [  # (suffix, parameter, unit, min, max)
    ("flow", "flow", "m3/h", 0, 2000), ("dp", "discharge_pressure", "bar", 0, 16),
    ("kw", "power_kw", "kW", 0, 600), ("pf", "power_factor", "cos_phi", 0, 1),
    ("vib", "vibration", "mm/s", 0, 50), ("tbrg", "bearing_temperature", "degC", -5, 150),
    ("amp", "motor_current", "A", 0, 1200), ("spd", "pump_speed", "%", 0, 100), ("run", "run_status", "bool", 0, 1),
]
FAILURE_CODES = ["BRG-OUTER-RACE", "BRG-INNER-RACE", "SEAL-LEAK", "IMPELLER-WEAR", "MOTOR-WINDING"]


@dataclass
class SiteSpec:
    code: str
    name: str
    lon: float
    lat: float
    design_flow: float  # m3/h
    n_pumps: int = 4
    pump_rated_flow: float = 900.0
    loss_ratio: float = 0.17
    pipe_volume_m3: dict[str, float] = field(default_factory=lambda: {"north": 4200, "south": 6100, "east": 8800})


SITES = [
    SiteSpec("plant_a", "Riverside Treatment Works", -122.335, 47.61, design_flow=2600),
    SiteSpec("plant_b", "Hillcrest Treatment Works", -122.20, 47.52, design_flow=2000, pump_rated_flow=700, loss_ratio=0.22),
]


def asset_blueprint() -> list[dict[str, Any]]:
    """Asset hierarchy + tags for every site: ~22 assets and ~64 tags per site."""
    out: list[dict[str, Any]] = []
    for s in SITES:
        def add(ext: str, name: str, type_name: str, parent: str | None, tags: tuple[tuple[Any, ...], ...] | list[tuple[Any, ...]] = (),
                s: SiteSpec = s, **meta: Any) -> None:
            out.append({"external_id": ext, "name": name, "type": type_name, "parent": parent, "site": s.code,
                        "metadata": meta, "tags": list(tags),
                        "location": {"type": "Point", "coordinates": [round(s.lon + random.uniform(-0.03, 0.03), 5),
                                                                     round(s.lat + random.uniform(-0.02, 0.02), 5)]}})

        add(s.code, s.name, "Treatment Plant", None, design_flow_m3h=s.design_flow, contracted_demand_kw=900)
        for area, label in (("intake", "Raw Water Intake"), ("treatment", "Treatment Process"),
                            ("pumping", "High-Lift Pumping"), ("distribution", "Distribution Network")):
            add(f"{s.code}_{area}", label, "Process Area", s.code)
        add(f"{s.code}_raw_station", "Raw Water Quality Station", "Analyzer", f"{s.code}_intake", [
            ("raw_turbidity", "raw_turbidity", "NTU", 0, 1000), ("raw_ph", "raw_ph", "pH", 0, 14),
            ("wtemp", "water_temperature", "degC", -5, 50), ("toc", "toc", "mg/L", 0, 50)])
        add(f"{s.code}_weather", "Weather Station", "Analyzer", f"{s.code}_intake", [
            ("tamb", "ambient_temperature", "degC", -40, 60)])
        add(f"{s.code}_coag", "Coagulant Dosing Skid", "Dosing Unit", f"{s.code}_treatment", [
            ("dose", "coagulant_dose", "kg/h", 0, 2000)])
        add(f"{s.code}_cl2", "Chlorinator", "Dosing Unit", f"{s.code}_treatment", [("dose", "chlorine_dose", "kg/h", 0, 500)])
        add(f"{s.code}_analyzer", "Treated Water Analyzer", "Analyzer", f"{s.code}_treatment", [
            ("cl", "chlorine", "mg/L", 0, 10), ("turb", "turbidity", "NTU", 0, 1000), ("ph", "ph", "pH", 0, 14),
            ("thm", "thm", "ug/L", 0, 500), ("coliform", "coliform_positive", "bool", 0, 1)], role="plant_outlet")
        add(f"{s.code}_clearwell", "Clearwell", "Storage Tank", f"{s.code}_treatment", [("level", "tank_level", "%", 0, 100)],
            capacity_m3=6000)
        for i in range(1, s.n_pumps + 1):
            add(f"{s.code}_pump_{i:03d}", f"High-Lift Pump {i}", "Centrifugal Pump", f"{s.code}_pumping",
                [(suf, par, unit, lo, hi) for suf, par, unit, lo, hi in PUMP_TAGS],
                rated_flow_m3h=s.pump_rated_flow, rated_head_m=48, bep_efficiency=0.82, motor_kw=250,
                manufacturer="Generic Pumps Co.", model=f"GP-{int(s.pump_rated_flow)}")
        add(f"{s.code}_outlet_meter", "Plant Outlet Flow Meter", "Flow Meter", f"{s.code}_pumping",
            [("q", "production_flow", "m3/h", 0, 20000)])
        add(f"{s.code}_reservoir", "Service Reservoir", "Storage Tank", f"{s.code}_distribution",
            [("level", "tank_level", "%", 0, 100)], capacity_m3=20000, area_m2=2500)
        for dma in ("north", "south", "east"):
            add(f"{s.code}_dma_{dma}", f"DMA {dma.title()}", "District Metered Area", f"{s.code}_distribution", [
                ("p", "pressure", "bar", 0, 16), ("billed", "billed_flow", "m3/h", 0, 10000),
                ("cl", "chlorine", "mg/L", 0, 10)], pipe_volume_m3=s.pipe_volume_m3[dma], role="distribution_endpoint")
        for i in (1, 2):
            add(f"{s.code}_valve_{i:03d}", f"Isolation Valve {i}", "Motorized Valve", f"{s.code}_distribution", [
                ("pos", "valve_position", "%", 0, 100), ("torque", "valve_torque", "Nm", 0, 500)], design_torque_nm=40)
    return out


@dataclass
class FaultEpisode:
    pump: str
    start: datetime
    failure: datetime
    repair_hours: float
    code: str


@dataclass
class LeakEvent:
    dma: str
    start: datetime
    end: datetime
    extra_m3h: float


class PlantModel:
    """Deterministic (seeded) plant simulation producing one value per tag per timestamp."""

    def __init__(self, start: datetime, end: datetime, seed: int = 42, faults: bool = True) -> None:
        self.rng = random.Random(seed)
        self.start, self.end = start, end
        self.faults: list[FaultEpisode] = []
        self.leaks: list[LeakEvent] = []
        self.turb_events: list[tuple[datetime, datetime, float]] = []
        days = max(1, (end - start).days)
        if faults:
            for s in SITES:
                pumps = [f"{s.code}_pump_{i:03d}" for i in range(1, s.n_pumps + 1)]
                # failures spread evenly over the window (with jitter) so every period - including the
                # most recent one used as the ML hold-out set - contains degradation episodes
                n_total = max(len(pumps), round(days / 45 * len(pumps) * 1.3))
                first = min(9.0, days * 0.4)
                for j in range(n_total):
                    pos = first + (j + self.rng.uniform(0.2, 0.8)) / n_total * (days - first)
                    fail = start + timedelta(days=pos, hours=self.rng.uniform(0, 23))
                    # P-F interval: bearing wear is measurable 9-16 days before functional failure
                    lead = timedelta(days=self.rng.uniform(9, 16))
                    self.faults.append(FaultEpisode(pumps[(j * 3 + 1) % len(pumps)], fail - lead, fail,
                                                    self.rng.uniform(4, 30), self.rng.choice(FAILURE_CODES)))
                for _ in range(max(1, days // 25)):
                    t0 = start + timedelta(days=self.rng.uniform(0, days))
                    self.leaks.append(LeakEvent(f"{s.code}_dma_{self.rng.choice(['north', 'south', 'east'])}", t0,
                                                t0 + timedelta(hours=self.rng.uniform(6, 60)), self.rng.uniform(80, 260)))
                for _ in range(max(1, days // 12)):  # storm -> raw turbidity spike
                    t0 = start + timedelta(days=self.rng.uniform(0, days))
                    self.turb_events.append((t0, t0 + timedelta(hours=self.rng.uniform(8, 48)), self.rng.uniform(20, 90)))
        self._tank = {s.code: 60.0 for s in SITES}
        self._res = {s.code: 70.0 for s in SITES}
        self._valve_drift = {f"{s.code}_valve_001": 0.0 for s in SITES}
        self._ar = {s.code: 0.0 for s in SITES}  # slow AR(1) demand drift (weather, events)

    # ---- helpers ----------------------------------------------------------------------
    @staticmethod
    def diurnal(t: datetime) -> float:
        t = to_plant(t)  # people use water by the plant's clock
        h = t.hour + t.minute / 60
        morning = 0.38 * math.exp(-((h - 7.5) ** 2) / 3.0)
        evening = 0.30 * math.exp(-((h - 19.5) ** 2) / 4.0)
        night = -0.32 * math.exp(-((h - 3.5) ** 2) / 5.0)
        weekend = 0.93 if t.weekday() >= 5 else 1.0
        return (0.88 + morning + evening + night) * weekend

    @staticmethod
    def seasonal_temp(t: datetime) -> float:
        doy = t.timetuple().tm_yday
        return 16 + 7 * math.sin(2 * math.pi * (doy - 110) / 365)

    def fault_state(self, pump: str, t: datetime) -> tuple[float, bool]:
        """(degradation 0..1, failed_and_in_repair)."""
        for f in self.faults:
            if f.pump != pump:
                continue
            if f.start <= t < f.failure:
                return ((t - f.start) / (f.failure - f.start)) ** 1.3, False
            if f.failure <= t < f.failure + timedelta(hours=f.repair_hours):
                return 0.0, True
        return 0.0, False

    def _noise(self, sd: float) -> float:
        return self.rng.gauss(0, sd)

    # ---- one simulation step ----------------------------------------------------------
    def step(self, t: datetime, dt_h: float = 0.25) -> dict[str, float | None]:
        v: dict[str, float | None] = {}
        r = self.rng
        for s in SITES:
            c = s.code
            amb = self.seasonal_temp(t) + 6 * math.sin(2 * math.pi * (local_hour(t) - 9) / 24) + self._noise(0.6)
            wtemp = self.seasonal_temp(t) - 2 + self._noise(0.15)
            self._ar[c] = 0.985 * self._ar[c] + self._noise(0.012)
            demand = s.design_flow * 0.78 * self.diurnal(t) * (1 + 0.012 * (amb - 16)) * (1 + self._ar[c]) * (1 + self._noise(0.02))
            raw_turb = 6 + 3 * math.sin(2 * math.pi * t.timetuple().tm_yday / 30) + abs(self._noise(1.0))
            for t0, t1, peak in self.turb_events:
                if t0 <= t <= t1:
                    raw_turb += peak * math.sin(math.pi * (t - t0) / (t1 - t0))
            toc = 2.6 + 0.04 * raw_turb + self._noise(0.1)
            v.update({f"{c}_weather_tamb": amb, f"{c}_raw_station_wtemp": wtemp, f"{c}_raw_station_raw_turbidity": raw_turb,
                      f"{c}_raw_station_raw_ph": 7.4 + self._noise(0.08), f"{c}_raw_station_toc": toc})

            # pumps: run the minimum number of healthy pumps needed, rotating duty daily
            available = []
            for i in range(1, s.n_pumps + 1):
                p = f"{c}_pump_{i:03d}"
                _, failed = self.fault_state(p, t)
                if not failed:
                    available.append(p)
            n_run = min(len(available), max(1, math.ceil(demand / (s.pump_rated_flow * 0.92))))
            # conservative operators often run an extra duty pump during the day shift; the energy
            # model learns the part-load penalty and the optimiser recommends against it
            lh = local_hour(t)
            if 7 <= lh < 19 and n_run < len(available) and (t.toordinal() * 24 + lh) % 7 < 3:
                n_run += 1
            rot = t.toordinal() % max(1, len(available))
            running = set((available[rot:] + available[:rot])[:n_run])
            total_q = 0.0
            total_kw = 0.0
            for i in range(1, s.n_pumps + 1):
                p = f"{c}_pump_{i:03d}"
                deg, failed = self.fault_state(p, t)
                if p in running:
                    q = demand / n_run * (1 + self._noise(0.01))
                    speed = min(100, 72 + 28 * q / s.pump_rated_flow + self._noise(0.5))
                    head_m = 48 - 9 * ((q / s.pump_rated_flow) - 0.85) ** 2 * 4 + self._noise(0.4)
                    eta = max(0.35, 0.82 - 1.4 * ((q / s.pump_rated_flow) - 0.85) ** 2 - 0.20 * deg + self._noise(0.004))
                    kw = 9.81 * (q / 3600) * head_m / eta
                    vib = 1.7 + 0.4 * (q / s.pump_rated_flow) + 8.5 * deg + abs(self._noise(0.15 + 0.4 * deg))
                    tbrg = 50 + amb * 0.25 + 30 * deg + self._noise(0.8)
                    pf = min(0.98, 0.86 + 0.06 * min(1, q / s.pump_rated_flow) - 0.04 * deg + self._noise(0.004))
                    amps = kw * 1000 / (math.sqrt(3) * 400 * pf) * (1 + 0.06 * deg)
                    v.update({f"{p}_flow": q, f"{p}_dp": head_m / 10.197, f"{p}_kw": kw, f"{p}_pf": pf, f"{p}_vib": vib,
                              f"{p}_tbrg": tbrg, f"{p}_amp": amps, f"{p}_spd": speed, f"{p}_run": 1.0})
                    total_q += q
                    total_kw += kw
                else:
                    v.update({f"{p}_flow": 0.0, f"{p}_dp": 0.4 + self._noise(0.02), f"{p}_kw": 0.0, f"{p}_pf": 0.0,
                              f"{p}_vib": abs(self._noise(0.05)), f"{p}_tbrg": amb + 4 + self._noise(0.5),
                              f"{p}_amp": 0.0, f"{p}_spd": 0.0, f"{p}_run": 0.0})
                    if failed:
                        v[f"{p}_tbrg"] = amb + 2
            v[f"{c}_outlet_meter_q"] = total_q * (1 + self._noise(0.004))

            # treatment & quality
            coag_mg_l = 9 + 1.15 * raw_turb
            v[f"{c}_coag_dose"] = total_q * coag_mg_l / 1000
            cl0 = 1.45 + 0.012 * (wtemp - 16) + self._noise(0.04)
            v[f"{c}_cl2_dose"] = total_q * (cl0 + 0.6 + 0.08 * toc) / 1000
            turb = 0.12 + 0.004 * raw_turb + abs(self._noise(0.02))
            if r.random() < 0.004:
                turb += r.uniform(0.2, 0.9)  # filter breakthrough event
            ph = 7.5 + self._noise(0.07) + (r.uniform(-1.3, 1.3) if r.random() < 0.0015 else 0)
            thm = 28 + 1.6 * (wtemp - 12) + 4 * toc + self._noise(2.0)
            v.update({f"{c}_analyzer_cl": cl0, f"{c}_analyzer_turb": turb, f"{c}_analyzer_ph": ph, f"{c}_analyzer_thm": thm})
            v[f"{c}_analyzer_coliform"] = (1.0 if r.random() < 0.02 else 0.0) if (to_plant(t).hour == 8 and to_plant(t).minute == 0) else None

            # storage balance
            self._tank[c] = min(98, max(15, self._tank[c] + (s.design_flow * 0.8 - total_q) * dt_h / 6000 * 100 * 0.5
                                         + self._noise(0.2)))
            v[f"{c}_clearwell_level"] = self._tank[c]
            billed_total = total_q * (1 - s.loss_ratio)
            consumption = demand * (1 - s.loss_ratio)
            self._res[c] = min(97, max(20, self._res[c] + (total_q - consumption / (1 - s.loss_ratio)) * dt_h / 20000 * 100
                                         + self._noise(0.15)))
            v[f"{c}_reservoir_level"] = self._res[c]

            # distribution: DMA pressure, billing, chlorine decay along the network
            k20 = 0.055  # 1/h bulk decay at 20 degC
            k = k20 * 1.065 ** (wtemp - 20) * (1 + 0.08 * (toc - 2.6))
            for dma, share in (("north", 0.34), ("south", 0.38), ("east", 0.28)):
                d = f"{c}_dma_{dma}"
                leak = sum(lk.extra_m3h for lk in self.leaks if lk.dma == d and lk.start <= t <= lk.end)
                residence_h = s.pipe_volume_m3[dma] / max(total_q * share, 50)
                v[f"{d}_p"] = 3.6 - 0.5 * (self.diurnal(t) - 0.8) - leak / 400 + self._noise(0.03)
                v[f"{d}_billed"] = billed_total * share * (1 + self._noise(0.015))
                v[f"{d}_cl"] = max(0.02, cl0 * math.exp(-k * residence_h) + self._noise(0.03))

            # valves (Use Case 9: torque drift on valve 1)
            for i in (1, 2):
                vk = f"{c}_valve_{i:03d}"
                drift = self._valve_drift.get(vk, 0.0)
                if vk in self._valve_drift:
                    self._valve_drift[vk] = min(60, drift + 0.002)
                v[f"{vk}_pos"] = 100.0 if r.random() > 0.01 else r.uniform(10, 90)
                v[f"{vk}_torque"] = 40 + drift + self._noise(1.2)
        return v

    def corrupt(self, values: dict[str, float | None], missing_ratio: float, outlier_ratio: float) -> dict[str, float | None]:
        """Inject missing data and outliers (Listing A.3 ``missing_data_ratio`` / ``outlier_ratio``)."""
        out: dict[str, float | None] = {}
        for k, val in values.items():
            if val is None or self.rng.random() < missing_ratio:
                out[k] = None
            elif self.rng.random() < outlier_ratio:
                out[k] = val * self.rng.choice([-5, 25]) + 999
            else:
                out[k] = val
        return out


def utcnow() -> datetime:
    return datetime.now(UTC)
