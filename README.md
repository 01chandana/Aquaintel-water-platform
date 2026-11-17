# AquaIntel Operations Platform

Industrial operations intelligence for a water utility: real-time SCADA telemetry, a rules engine with
alert lifecycle management, 30 operational KPIs, five production ML models, pump-schedule optimisation
and regulatory compliance reporting. It is built to the *AquaIntel Software Architecture & Design
Specification v1.0*. Each requirement is traced to code in
[`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md).

| Layer | Technology (spec Ch. 4) |
|---|---|
| Frontend | React 18, TypeScript (strict), Vite 8, React Router 7, Redux Toolkit + RTK Query, MUI 5, Recharts + D3, React Hook Form + Zod 4, react-window |
| API | FastAPI on Python 3.11, Pydantic v2, SQLAlchemy 2.0 async (asyncpg), Alembic |
| Data | PostgreSQL 15 + TimescaleDB 2.10 (hypertables, continuous aggregates, compression, retention), Redis 7 |
| Streaming | Apache Kafka (KRaft): `telemetry.raw` → stream processor → `telemetry.processed` |
| Background jobs | Celery + beat (Redis broker); Airflow DAGs for the model-retraining calendar |
| ML | scikit-learn, XGBoost, LightGBM, SHAP-style contributions, MLflow tracking, MinIO artifact store |
| Optimisation | Mixed-integer linear programme (SciPy HiGHS) for pump scheduling |
| Observability | Prometheus metrics, Grafana dashboard, structlog JSON logs (optional ELK) |
| Delivery | Docker multi-stage images, docker-compose, Kubernetes (kustomize), GitHub Actions |

## What is in the box

* **116 REST endpoints** under `/v1`, covering the 95 catalogued in Ch. 7 plus a few the UI needs. Every
  response uses the standard envelope (Listing 7.1) and every error uses the error-code table (Table 7.12).
  The API serves OpenAPI docs at `/docs` (Swagger) and `/redoc`.
* **Authentication and authorisation:** JWT access tokens with rotating refresh tokens, TOTP MFA,
  API keys for integrations, the RBAC matrix (Table 17.1) and ABAC site scopes. The audit log is
  hash-chained and append-only (a database trigger blocks updates and deletes).
* **Telemetry pipeline:** REST, CSV, MQTT and Modbus adapters plus an OPC-UA stub. Each point is
  validated (Appendix A.3.4), written to the TimescaleDB hypertable, evaluated by the rules engine and
  pushed to dashboards over WebSocket.
* **Rules engine:** threshold rules with sustain and hysteresis, plus rate-of-change, statistical
  deviation, composite and predictive rules. Alerts follow the state machine in Figure 13.1 with
  dedup, cooldown, flood control, maintenance suppression, incident correlation and the
  escalation matrix (Table 13.1).
* **KPI engine:** all 30 KPIs from the Ch. 11 catalogue, with targets and status bands, hourly
  computation, backfill, and custom formula KPIs.
* **ML:**

  | Model | Approach |
  |---|---|
  | Pump failure | XGBoost + logistic regression ensemble, with per-prediction explanations |
  | Demand forecast | LightGBM, multi-step |
  | Anomaly detection | Isolation Forest |
  | Chlorine decay | First-order physics model plus an ML residual |
  | Energy | XGBoost |

  All five are tracked in a model registry with acceptance gates, a two-person promotion rule,
  champion/challenger shadow scoring and PSI/KS drift monitoring.
* **Optimisation:** a 24-hour pump schedule that minimises energy cost under tariff, tank-level and
  peak-demand constraints, plus coagulant and chlorine dosing recommendations.
* **Reports:** shift handover, daily and monthly compliance, KPI and energy/carbon, alert summary
  and asset benchmarking. Each comes as PDF, Excel or HTML, either ad hoc or on a cron schedule.
* **Frontend:** 25 pages:
  * five role dashboards and a drag-and-drop dashboard builder
  * live telemetry, the asset tree and asset map
  * the alert centre and rule manager with a "test rule" replay
  * KPI explorer, trend analysis, the report builder and compliance views
  * work orders, ML models, optimisation and administration

  The UI follows ISA-101 high-performance HMI conventions: neutral greys by default, with colour
  reserved for abnormal conditions.

## Run it

### Option A: Docker (full stack)

```bash
cp .env.example .env                  # set JWT_SECRET_KEY (32+ characters)
docker compose -f docker-compose.yml --profile demo up -d --build
# http://localhost        app (via nginx)       sign in: admin@aquaintel.io / AquaIntel!2026
# http://localhost:3001  Grafana (admin/admin)   http://localhost:8080 Airflow   http://localhost:5000 MLflow
```

The `demo` profile runs `seed`, which loads 60 days of simulated history for two plants, trains the
five models and writes an integration key, and then `simulator`, which streams live SCADA data.
`--profile edge` adds Mosquitto and the MQTT bridge, and `--profile elk` adds Elasticsearch, Logstash
and Kibana. Leaving out `-f docker-compose.yml` applies `docker-compose.override.yml`, which gives
hot-reload development containers.

### Option B: Local processes (no Docker)

You need PostgreSQL 15+ (TimescaleDB is optional; migration 0002 falls back to plain views) and Redis.

```bash
cd backend
python -m venv .venv && . .venv/bin/activate && pip install -r requirements/dev.txt
export AQUAINTEL_SECRET_KEY=dev-secret-key-at-least-32-characters-long
alembic upgrade head
python scripts/seed_dev_data.py               # ~3 min: history, KPIs, alerts, models
uvicorn app.main:app --reload                 # EVENT_BUS=auto and TASK_MODE=inline: no Kafka/Celery needed
python scripts/simulate_live.py --interval 10 --inject-fault plant_a_pump_002   # optional live feed

cd ../frontend && npm ci && npm run dev       # http://localhost:5173
```

In local mode, Kafka falls back to an in-process event bus and Celery to an asyncio scheduler. The
same services and the same code paths run either way, and `/health` reports which backend is active.

### Demo accounts (password `AquaIntel!2026`)

| Email | Role | Scope |
|---|---|---|
| superadmin@aquaintel.io | Super admin | all |
| admin@aquaintel.io | Admin | all |
| engineer@aquaintel.io | Engineer | all |
| datascience@aquaintel.io | Data scientist | all |
| operator@aquaintel.io | Operator | Riverside (plant_a) only |
| operator.b@aquaintel.io | Operator | Hillcrest (plant_b) only |
| technician@aquaintel.io | Technician | all |
| viewer@aquaintel.io | Viewer | Riverside only |

These accounts exist only in demo data. **For a real installation**, skip the seed and create the
first administrator from a shell on the server. There is no public sign-up, and everyone else is
added in *Admin → Users*:

```bash
cd backend && alembic upgrade head
python scripts/create_admin.py --email ops.lead@utility.example --name "Ops Lead"   # prompts for the password
```

Set `AQUAINTEL_TZ` to the plant's time zone (e.g. `Asia/Kolkata`). Tariff windows, shift reports and
demand patterns follow the plant clock. The UI always shows times in each viewer's own zone.

## Quality gates

```bash
cd backend && ruff check app scripts tests && mypy app && pytest --cov=app     # 147 tests, coverage gate 80 %
cd backend && pip-audit -r requirements/prod.txt                                # dependency advisories (clean)
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
cd frontend && npm audit                                                        # dependency advisories (clean)
cd frontend && npx playwright test                                              # e2e journeys (running stack + simulator)
cd backend && locust -f tests/load/locustfile.py --host http://localhost:8000   # Table 16.1 load scenarios
```

The backend suite includes a session-seeded integration run. It generates three weeks of plant
history, trains the models and checks end-to-end behaviour such as alert lifecycles, KPI values,
report rendering, drift monitoring and RBAC/ABAC. `tests/api/test_audit_regressions.py` re-runs every
attack from the QA audit of the earlier prototype (see [`docs/QA_AUDIT_RESPONSE.md`](docs/QA_AUDIT_RESPONSE.md)). CI (`.github/workflows/ci.yml`) runs all of this
against TimescaleDB, Redis and Kafka service containers, then builds and scans the images and
deploys them with kustomize.

## Repository layout

```
backend/        FastAPI app (api, services, repositories, models, ml, optimization, integration, workers)
  scripts/      seed + synthetic data generator + live simulator
  tests/        unit / integration / api / load
frontend/       React SPA (features/*, components/{charts,widgets,layout,common}, api/, store/)
airflow/dags/   model-retraining DAGs (Table 10.2 cadence)
infra/          kubernetes/, prometheus/, grafana/, kafka/, postgres/, elk/
nginx/          edge reverse proxy
docs/           architecture, database guide, requirements traceability, QA audit response, interview guide
```

| Document | Read it for |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the parts fit together, with diagrams |
| [`docs/DATABASE.md`](docs/DATABASE.md) | The database in plain language: the six tables that matter, all 26 by purpose, example SQL |
| [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md) | Each spec chapter and use case → the code that implements it |
| [`docs/QA_AUDIT_RESPONSE.md`](docs/QA_AUDIT_RESPONSE.md) | All 33 findings of the prototype's QA audit, re-tested here: what applied, what was fixed, which test guards it |
| [`docs/INTERVIEW_GUIDE.md`](docs/INTERVIEW_GUIDE.md) | A demo script, design decisions and likely questions |
