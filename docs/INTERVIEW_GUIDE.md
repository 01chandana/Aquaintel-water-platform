# Interview guide

A script for presenting AquaIntel in about ten minutes, the design decisions worth defending, and
straight answers to the questions a panel is likely to ask. Figures come from a default seed:
60 days, two plants, about 715 k telemetry points, 52 alert rules, about 25 k KPI values. They
change slightly from one seed to the next.

## 1. One-minute pitch

> AquaIntel is an operations platform for a water utility. SCADA and IoT telemetry come in through
> protocol adapters, are validated, and stream through Kafka into TimescaleDB. A rules engine turns
> them into alerts with a proper lifecycle, so operators aren't flooded. A KPI engine computes the
> 30 KPIs management reports on, and five ML models predict pump failures, forecast demand, detect
> anomalies, predict chlorine residual and estimate pump energy. A MILP optimiser turns the demand
> forecast into a cheaper pump schedule. It's FastAPI and React, deployable with Docker Compose or
> Kubernetes, with CI, metrics and an audit trail. The same code runs on a laptop, without Kafka or
> Celery, through in-process fallbacks.

## 2. Demo script (about 8 minutes)

Start `simulate_live.py --inject-fault plant_a_pump_002` before the interview, so a fault is
developing while you present.

1. **Sign in as admin, open the Executive dashboard.**
   * Point out the KPI tiles. Each **BandBar** shows the value against its warning and critical
     bands.
   * Colour appears only when something is abnormal. That is ISA-101 high-performance HMI: grey by
     default, so a red tile actually means something.
2. **Operations → Live telemetry.**
   * Values tick every 10 seconds over the WebSocket.
   * The table is virtualised (react-window), so a thousand tags scroll smoothly.
3. **Alert Centre.**
   * Open the vibration alert on pump 2 and walk the timeline: triggered → acknowledge → investigate.
   * Show that it was correlated into an incident.
   * Explain the anti-fatigue measures: sustain time and hysteresis on the rule, dedup and cooldown,
     flood control, suppression during maintenance.
4. **Rule Manager → test a rule.**
   * Replay a threshold rule over recent history and note how many alerts it *would* have raised.
   * Set hysteresis to 0 and replay again to show the difference. This is how an engineer tunes a
     rule before switching it on.
5. **ML models.**
   * Pump failure: F1 about 0.96, ROC-AUC about 0.99, average warning about 12 days ahead.
   * Open a prediction's explanation, the per-feature contributions behind the probability.
   * Show the drift panel. It says "collecting" right after training, because it only scores data
     the model has never seen.
6. **Optimisation.**
   * Run the pump schedule: the plan shifts pumping out of the shaded peak-tariff hours and keeps
     the reservoir between its limits.
   * Show the saving against the follow-demand baseline.
   * Then dosing: coagulant dose from raw turbidity, chlorine set-point from the decay model.
7. **Reports → Shift handover PDF**, and the **Compliance** page with exceedances against MCL limits.
8. **Sign in as `operator.b@aquaintel.io`.**
   * Only Hillcrest assets are visible (ABAC scope), and admin pages are hidden (RBAC).
   * Back as admin, open **Audit log → Verify chain**.

Close with Grafana (`:3001`) for platform metrics, and the CI workflow file.

## 3. Design decisions and trade-offs

| Decision | Why | Trade-off / what I'd revisit |
|---|---|---|
| TimescaleDB rather than a separate TSDB | One database for relational and time-series data: joins between telemetry, assets and alerts stay SQL, and continuous aggregates and compression come built in | Very high cardinality (millions of tags) would push towards a dedicated store |
| Kafka between ingestion and processing | Decouples bursty SCADA input from database writes; replayable; per-asset ordering by keying on asset id | More moving parts. The in-memory bus keeps local development simple, behind the same interface |
| Idempotent writes (`ON CONFLICT DO NOTHING`) | Kafka is at-least-once; replays and retries must not duplicate points | Late corrections need an explicit update path |
| Rules engine in Python, not a CEP product | Rule types and lifecycle are domain-specific; easy to test (`RulesEngine.replay`) | Throughput per process is bounded. Scale is horizontal through Kafka partitions |
| Hysteresis + sustain + cooldown on every rule | Alarm floods are the main failure of SCADA alarming (ISA-18.2) | Slightly slower to alarm. Critical rules use 0 s sustain |
| Repository + service layers | Routers stay thin; services are testable without HTTP; queries are in one place | More files than a "fat router" app |
| Two-person rule for production models | A model that raises maintenance alerts is an operational change | Slower deployment, by design |
| Drift only on unseen data, seasonal inputs excluded from alerting | Comparing a model with its own training data is meaningless, and water temperature always drifts in autumn | Seasonal features need the retraining calendar to keep up |
| MILP for pump scheduling | Exact optimum for 24 h × N pumps in well under a second, with explainable constraints | Pump curves are linearised. A nonlinear solver would be more precise |
| ISA-101 visual design | Operators must spot the abnormal in a second | Looks quieter than a typical dashboard. That's the point |

## 4. Questions you should expect

**How does data get from a pump to the screen?**
Adapter → `POST /v1/telemetry/ingest` (API key) → validation → Kafka `telemetry.raw`, keyed by
asset → stream processor writes to the hypertable → rules are evaluated → alerts and latest values
are published to Redis → each API instance fans out to its WebSocket clients. The spec's target is alert
delivery under 30 s; ingestion lag is tracked by the `telemetry_ingestion_lag_seconds` histogram,
and Prometheus alerts when it passes 60 s.

**What happens when Kafka or Redis is down?**
* **Kafka down:** the Kafka circuit breaker opens, `/health` reports it, and ingestion returns an
  error to the adapter. The adapter buffers and retries; the MQTT bridge keeps a local queue.
  Reads keep working from PostgreSQL.
* **Redis down at startup:** the API runs on a per-process in-memory cache, so rate limits and the
  token blacklist become per-instance.
* **Redis lost at runtime:** cache-dependent calls fail fast. Making that path degrade gracefully
  too is on my list of improvements.

**How do you avoid alert fatigue?**
Rules support sustain and hysteresis. Alerts are deduplicated per rule and asset, there is a
cooldown after resolution, flood control caps alerts per asset per hour, assets under
maintenance are suppressed, and related alerts are grouped into incidents. The analytics endpoint
reports the false-positive rate, so noisy rules can be found and tuned with the replay tool.

**How do you know the pump model is good, and not just fitting the simulator?**
* The split is by time, with no shuffling, so the model never sees the future.
* Acceptance is checked against Ch. 10.7.2 targets on a held-out window.
* Lead time is measured: 12 days on average.
* Honestly, the data is synthetic: degradation follows a P-F curve with noise. In production I would
  backtest across real failure records and expect the metrics to drop. The pipeline, registry,
  drift monitoring and approval workflow are the part that carries over.

**Why does the drift monitor say "collecting"?**
It only compares data that arrived after the training window. Right after seeding there isn't any
yet, and reporting PSI on training data would be misleading. Once 20 hourly rows of new data exist,
it reports PSI, KL and KS per feature.

**How is access controlled?**
RBAC from Table 17.1, checked on every route by `require_permission`. ABAC asset scopes (globs on
the asset path) filter every query and are checked again on writes. API keys carry their own
permission list. Every change is written to a hash-chained audit log that the database refuses to
update or delete.

**How would this scale to 50 plants?**
* Kafka partitions keyed by asset spread the stream processors.
* TimescaleDB chunks plus compression keep storage linear; queries over long windows read
  continuous aggregates, not raw rows.
* API pods are stateless (HPA on CPU); workers scale on queue depth (KEDA).
* The next pressure points would be the per-tag rule cache and WebSocket fan-out. Both partition
  by site.

**What would you do next?**
* A real OPC-UA client (asyncua) in place of the stub.
* Per-DMA water-balance reports (IWA method).
* A what-if UI on the simulator, as a digital-twin step.
* A Helm chart with values per environment.

These gaps are listed in the traceability matrix, not hidden.

## 5. Numbers worth remembering

* 116 API routes, 25 pages, 30 KPIs, 5 model types, 52 seeded rules, 26 tables.
* About 105 backend tests (unit, integration, API, and a seeded end-to-end run) at about 87%
  coverage. Frontend unit tests plus four Playwright journeys.
* Pump failure F1 about 0.96 with about 12 days' lead time.
* Demand forecast 7–9% MAPE (spec target < 10%).
  * It predicts the *change* from the same hour last week, from relative inputs (how demand and
    temperature have moved since last week). It therefore stays within a few percent of that
    seasonal-naive baseline, either way, instead of losing to it badly when the season shifts.
  * Honest point if asked: in this simulated plant, weekly repetition is most of the signal. Real
    weather and event data is where the model would earn its keep.
* Chlorine residual MAE about 0.013 mg/L, better than the physics-only model.
* Load test (Table 16.1): dashboard endpoints P95 under 200 ms; rule evaluation P95 under 100 ms.

## 6. When the panel brings up their QA audit

They audited the earlier prototype (SQLite, 14 endpoints) and found 33 defects. The honest framing:
*"I took the audit as a test plan, not a to-do list."* Every finding was re-run against this
platform, using the same kinds of attack, and the result is recorded in
[`QA_AUDIT_RESPONSE.md`](QA_AUDIT_RESPONSE.md).

**Points worth making:**

* **Most criticals can't happen by design, and that's still tested.**
  * No public sign-up exists, so AQ-001 has nothing to attack; a test proves the route isn't there.
  * The API serves no files (AQ-002).
  * React escapes output (AQ-004).
* **Re-testing found real bugs of the same class here, and I fixed them:**
  * `Infinity`/`NaN` were being stored (AQ-008).
  * A wrong foreign key returned 500 instead of 422 (AQ-009/011).
  * Duplicate alert rules were allowed (AQ-016).
  * Excel exports could carry live formulas (AQ-022).
  * Detail pages hung on bad ids (AQ-026).
  * The UI showed times in UTC to IST users (AQ-013).
  * The project had no `.gitignore` (AQ-029).

  Each now has a regression test named after its audit ID.
* **The fix I'd highlight:** when the API is unreachable, the header used to say **"0 critical ·
  0 major"**. In a control room that reads as *all clear*. It now says *"Alert counts unavailable"*,
  and failed tables show the error instead of "No records". Silent failure is worse than loud
  failure.
* **The auditors' recommendations, adopted:**
  * a controlled admin bootstrap (`scripts/create_admin.py`);
  * a refusal to start with a published signing key;
  * PyJWT rather than python-jose (already the case here);
  * dependency audits in CI;
  * bundled fonts for air-gapped sites.

  The dependency audits found advisories in Starlette 0.46, kafka-python 2.0, zod 3, Vite 5 and
  Vitest 2. All were upgraded, and both `pip-audit` and `npm audit` are now clean and blocking in CI.
* **A bug the re-test caught in my own test suite:** the e2e journey cleaned up its test rule as a
  user without delete permission, so it silently left duplicates behind. The new duplicate-rule
  check exposed it, and cleanup now asserts that it worked.

**If asked "why 26 tables when the prototype had 5?"**
The six tables in [`DATABASE.md`](DATABASE.md) §1 carry the story: assets → tags → readings →
rules → alerts → users. The rest each serve one spec feature (KPIs, ML registry, reports, work
orders, audit), and none is unused: every column is referenced by code. TimescaleDB is optional;
plain PostgreSQL runs everything.
