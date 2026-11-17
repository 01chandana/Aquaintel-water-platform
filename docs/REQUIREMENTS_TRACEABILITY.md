# Requirements traceability

Each row maps a part of the *AquaIntel Software Architecture & Design Specification v1.0* to the
code that implements it. Status: **Done** means implemented and covered by tests or a running
screen; **Partial** means the core is there and the gap is stated; **Not built** means deliberately
left out, with the reason.

## Part I – Foundation

| Spec | Requirement | Where | Status |
|---|---|---|---|
| 1.3 / 1.4 | Core capabilities 1–10: ingestion, assets, rules/alerts, KPIs, dashboards, ML, optimisation, compliance, reporting, administration | see the rows below | Done |
| 1.4 | Data sources: SCADA (Modbus), IoT (MQTT), CSV batch upload, REST | `integration/modbus_gateway.py`, `integration/mqtt_bridge.py`, `POST /v1/telemetry/ingest/csv`, `POST /v1/telemetry/ingest` | Done |
| 1.4 | OPC-UA | `integration/opcua_bridge.py`: adapter interface plus `SimulatedOpcUaSource`. The roadmap (week 5) calls for OPC-UA *stubs* | Partial (stub per roadmap) |
| 3.2 | Layered architecture: presentation → API → services → data | `api/v1` → `services` → `repositories` → `models` ([ARCHITECTURE §4](ARCHITECTURE.md#4-backend-layering-ch-9)) | Done |
| 3.3 | Logical services: ingestion, asset, rules, alert, KPI, analytics/ML, optimisation, compliance, reporting, notification, auth, admin | one module per service in `backend/app/services/` | Done |
| 3.4 | Event-driven communication over Kafka topics | `core/events.py` (topics, envelope, DLQ), `integration/kafka_consumer.py`, `infra/kafka/create-topics.sh` | Done |

## Part II – Technical design

| Spec | Requirement | Where | Status |
|---|---|---|---|
| 4 | Technology stack (Table 4.x) | `backend/requirements/*.txt`, `frontend/package.json`, `docker-compose.yml` | Done |
| 5.2 | Protocol adapters, validation, quality flags | `integration/*`, `integration/validation.py` (Appendix A.3.4 range / rate / z-score / IQR) | Done |
| 5.3.1 | Telemetry ingestion workflow | `TelemetryService.ingest` → Kafka → `TelemetryPipeline.process` | Done |
| 5.3.2 | Predictive maintenance workflow: score → predictive rule → alert → work order | `workers/jobs.py::batch_score`, predictive rule type, "Create work order" on the alert detail page (`WorkOrderService.create` with `alert_id`) | Done |
| 5.4 | Partitioning by asset id, idempotent writes, DLQ | `KafkaEventBus.publish(key=asset_id)`, `bulk_insert … ON CONFLICT DO NOTHING`, `telemetry.dlq` | Done |
| 6.2–6.4 | Schema (26 tables) and enums | `models/*.py`, migration `0001_core_schema.py` | Done |
| 6.5 | Hypertables, compression, retention, continuous aggregates | migration `0002_timescale_views_audit.py` | Done |
| 6.6 | Indexing (BRIN, HASH, composite) | migration 0002 | Done |
| 6.7 | Views: active alerts, asset health, daily compliance | migration 0002 | Done |
| 6.8 | Materialised path for the asset hierarchy | `Asset.path`, `AssetRepository.subtree` | Done |
| 7.1–7.3 | URL design, standard envelope, pagination, filtering, sorting | `core/responses.py`, `api/deps.py::Pagination` | Done |
| 7.4–7.11 | Endpoint catalogue #1–#95 | `api/v1/*.py`; each route's OpenAPI summary carries its catalogue number (116 routes in total) | Done |
| 7.12 | Error codes | `core/exceptions.py`, `core/responses.py::error_body` | Done |
| 7.13 | Rate limits per user / API key / login | `middleware/rate_limit.py` (Redis sliding window) | Done |
| 7.14 | WebSocket protocol (subscribe, telemetry, alert, heartbeat) | `api/v1/websocket.py`, `frontend/src/hooks/useWebSocket.ts` | Done |
| 7.15 | API versioning and changelog | `/v1` prefix, `GET /v1/docs/changelog` | Done |
| 8.2–8.4 | Frontend structure, state management, routing | `frontend/src/{api,store,features}`, `Router.tsx` (lazy routes, permission guards) | Done |
| 8.5 | Component library: KPI cards, charts, gauges, heat map, asset tree, virtualised tables | `components/{charts,widgets}` | Done |
| 8.6 | Role dashboards: executive, operations, energy, quality, maintenance | `features/dashboard/DashboardPage.tsx` | Done |
| 8.7 | Real-time updates | `useWebSocket` | Done |
| 8.8 | Forms with React Hook Form + Zod | `utils/validators.ts`, rule manager, report builder, user forms | Done |
| 8.9 | Theme: dark/light, ISA-101 high-performance HMI | `src/theme/*`, BandBar | Done |
| 8.10 | Performance: code splitting, memoisation, virtualisation | `vite.config.ts` manualChunks, lazy routes, react-window | Done |
| 8.11 | Accessibility | ARIA labels, live-region announcements for alerts, keyboard focus styles | Done |
| 8.12 | Custom dashboards with drag-and-drop widgets | `features/dashboard/CustomDashboards.tsx`, `/v1/dashboards` | Done |
| 9.2–9.8 | Service and repository patterns, dependency injection, transactions | `services/*`, `repositories/base.py`, `api/deps.py` | Done |
| 9.9 | Exception hierarchy | `core/exceptions.py` | Done |
| 9.10 | Circuit breakers, retries, bulkheads, timeouts | `core/resilience.py` | Done |
| 9.11 | Caching strategy and TTLs | `core/cache.py` | Done |
| 9.12 | Background tasks (Celery queues and beat) | `workers/celery_app.py`, `workers/tasks/*` | Done |
| 9.13 | Structured logging and request context | `core/logging.py`, `middleware/request_id.py` | Done |

## Part III – Analytics and AI

| Spec | Requirement | Where | Status |
|---|---|---|---|
| 10.2–10.5 | Data pipeline: cleaning, resampling, feature engineering | `ml/features.py` | Done |
| 10.6 | Time-based train / validation / test split, no leakage | `ml/models.py::time_split` | Done |
| 10.7 | Evaluation metrics and acceptance criteria (Ch. 10.7.2) | `ml/models.py` (each trainer returns metrics + `acceptance`) | Done |
| 10.8 | Model registry and versioning (MLflow) | `ml/registry.py`, `ml_models` table, MLflow behind a circuit breaker | Done |
| 10.9 | Drift monitoring (PSI, KL, KS); alert at PSI > 0.2 | `ml/drift.py`, `MLService.drift` ([ARCHITECTURE §6](ARCHITECTURE.md#6-ml-lifecycle-ch-10-14)) | Done |
| 10.10 | Retraining calendar (Table 10.2) | `workers/celery_app.py::ML_LIFECYCLE_SCHEDULE`, `airflow/dags/aquaintel_ml_pipeline.py` | Done |
| 10.11 | Deployment: two-person rule, champion/challenger | `MLService.deploy` (the production approver must differ from the model creator), shadow scoring | Done |
| 11 | KPI catalogue (30 KPIs, formulas, thresholds, targets) | `services/kpi_catalog.py`, `services/kpi_engine.py` (one function per KPI) | Done |
| 11 | KPI computation schedule and backfill | `workers/jobs.py::compute_kpis`, `KPIEngine.backfill` | Done |
| 11 | Custom KPI formulas | `kpi_engine.CUSTOM_FORMULA` (safe expression grammar) | Done |
| 13.2 | Rule types: threshold, rate, deviation, composite, predictive | `services/rules_engine.py` | Done |
| 13.3 | Rule testing against history | `POST /v1/alerts/rules/test`, `RulesEngine.replay` | Done |
| 13.4 | Alert lifecycle (Figure 13.1) | `alert_service.ALLOWED_TRANSITIONS` | Done |
| 13.5 | Escalation (Table 13.1) | `alert_service.ESCALATION_MATRIX`, `escalate_alerts` job | Done |
| 13.6 | Alert fatigue: dedup, cooldown, flood control, maintenance suppression, silent hours | `AlertService.create_alert` | Done |
| 13.7 | Correlation into incidents | `Incident` model, correlation step in `create_alert` | Done |
| 13.8 | Alert analytics: MTTA, MTTR, Pareto, false-positive rate | `GET /v1/alerts/analytics` | Done |
| 14.2 | Pump failure prediction (XGBoost + LR ensemble, explanations) | `ml/models.py::train_pump_failure` | Done |
| 14.3 | Demand forecasting (LightGBM, 24/72 h) | `train_demand`, `forecast_demand` | Done |
| 14.4 | Anomaly detection (Isolation Forest) | `train_anomaly` | Done |
| 14.5 | Chlorine decay (physics + ML residual) | `train_chlorine` | Done |
| 14.6 | Energy model | `train_energy` | Done |
| 14.7–14.8 | Online and batch inference, latency metric | `/v1/ml/predict/*`, `batch_score`, `ml_inference_latency_seconds` | Done |

### Industrial use cases (Ch. 12)

| # | Use case | Implementation | Status |
|---|---|---|---|
| 1 | Real-time operations monitoring | Operations dashboard, Live Telemetry page, WebSocket push | Done |
| 2 | Shift handover reporting | `shift_handover` report, scheduled 30 min before each shift change | Done |
| 3 | SCADA integration gateway | Modbus register-map gateway, MQTT bridge, OPC-UA stub | Partial (OPC-UA stub) |
| 4 | Compliance monitoring dashboard | Compliance page, `ComplianceService`, `regulatory_limits` (MCL/MRDL) | Done |
| 5 | Asset performance benchmarking | `benchmark` report section (percentile ranking of pumps) | Done |
| 6 | Event correlation and root cause | Incidents grouping alerts on the same asset or its parent within a time window (`AlertService._correlate`) | Done |
| 7 | Water balance and loss analysis | `DISTRIBUTION_LOSS` KPI ((produced - billed) / produced) | Partial (KPI level; no per-DMA IWA balance sheet) |
| 8 | Predictive maintenance for pumps | Pump failure model → predictive rule → alert → work order | Done |
| 9 | Valve condition monitoring | Simulated actuator torque drift with a sustained-threshold rule | Done (rule-based) |
| 10 | Bearing failure prediction | Bearing temperature and vibration features in the pump-failure model, plus bearing-temperature rule (Listing 13.1) | Done (inside model 14.2) |
| 11 | Motor health analytics | Motor current in the anomaly and failure feature sets | Partial (no dedicated motor model) |
| 12 | Instrumentation health monitoring | Validation rejects (range, rate, z-score, quality flag) counted per reason | Partial (no sensor-drift calibration tracking) |
| 13 | Maintenance cost optimisation | MTBF, MTTR, PM compliance and O&M cost KPIs, spare-parts availability | Partial (KPIs, no cost optimiser) |
| 14 | Real-time water quality prediction | Chlorine decay model (endpoint residual prediction) | Done |
| 15 | Chemical dosing optimisation | `POST /v1/optimization/dosing` (coagulant dose and chlorine set-point) | Done |
| 16 | Disinfection byproduct management | `DBP_RISK` KPI, THM 80%-of-MCL rule | Done |
| 17 | Taste and odour event detection | Not built: the dataset (Appendix A) has no geosmin/MIB or odour-panel data | Not built |
| 18 | Pump scheduling optimisation | MILP in `optimization/pump_scheduler.py` against a follow-demand baseline | Done |
| 19 | Peak demand management | Contracted-kW constraint in the same MILP; `MAXIMUM_DEMAND_UTILIZATION` KPI | Done |
| 20 | Carbon footprint tracking | `energy_carbon` report section (Scope 2, configurable grid factor) | Done |
| 21 | Water-energy nexus | SEC KPI and the energy/carbon section per site | Partial (no cross-site optimisation) |
| 22 | Demand forecasting | LightGBM forecaster of the change from the same hour last week, using relative inputs; within a few percent of seasonal-naive; 7–9% MAPE | Done |
| 23 | Anomaly detection in the distribution network | Sigma-deviation rules on DMA pressure, plus multivariate pump anomaly model | Done |
| 24 | Asset lifecycle cost analysis | Not built: needs capital-cost and depreciation data absent from the dataset | Not built |
| 25 | Digital twin simulation | `integration/simulator.py::PlantModel` (hydraulic, pump-curve and decay model driving the demo) | Partial (simulation backbone, no what-if UI) |

## Part IV – Operations and deployment

| Spec | Requirement | Where | Status |
|---|---|---|---|
| 15.2 | Container topology | `docker-compose.yml` (+ override for development), `nginx/nginx.conf` | Done |
| 15.3 | Multi-stage Docker images, non-root runtime | `backend/Dockerfile`, `frontend/Dockerfile`, `backend/Dockerfile.test` | Done |
| 15.4 | Kubernetes: namespaces, deployments, HPA, queue-based worker scaling, PDB | `infra/kubernetes/base/*.yaml` (kustomize; KEDA for queue depth) | Done |
| 15.5 | Ingress, TLS, network policies | `ingress.yaml`, `network-policies.yaml` | Done |
| 15.7 | Backup and recovery | `backup-cronjob.yaml` (nightly `pg_dump`, 30-day retention) | Done |
| 16.2 | Unit tests | `backend/tests/unit`, `frontend/src/__tests__` | Done |
| 16.3 | Integration tests (database, pipeline, Kafka) | `backend/tests/integration` | Done |
| 16.4 | API tests | `backend/tests/api/test_api.py` | Done |
| 16.5 | ML model tests (acceptance, drift) | seeded integration suite, `test_core.py::TestDrift` | Done |
| 16.6 | End-to-end journeys (Playwright) | `frontend/tests/e2e/journeys.spec.ts` | Done |
| 16.7 | Load testing (Table 16.1) | `backend/tests/load/locustfile.py` with acceptance check on exit | Done |
| 16.8 | Coverage ≥ 80% | `pyproject.toml` `fail_under = 80` (currently about 87%) | Done |
| 17.2 | Authentication: JWT, refresh rotation, MFA, lockout | `services/auth_service.py`, `core/security.py` | Done |
| 17.3 | RBAC (Table 17.1) and ABAC scopes | `core/permissions.py`, `api/deps.py` | Done |
| 17.4 | API keys | `api_keys` table, `/v1/admin/api-keys` | Done |
| 17.5 | Audit trail (immutable, verifiable) | `services/audit_service.py`, trigger in migration 0002 | Done |
| 17.6 | Input validation and security headers | Pydantic schemas, body-size limit, nginx headers | Done |
| 18 | CI/CD (Listing 18.1) | `.github/workflows/ci.yml`, `frontend/.husky/pre-commit` | Done |
| 19.2 | Prometheus metrics (Listing 19.1) | `core/metrics.py`, `/metrics` | Done |
| 19.4 | Structured JSON logging; ELK | `core/logging.py`; `--profile elk`, `infra/elk/logstash.conf` | Done |
| 19.6 | Grafana dashboards | `infra/grafana/dashboards/aquaintel-platform.json` | Done |
| 19.7 | Alerting rules | `infra/prometheus/alert_rules.yml` | Done |
| 19.8 | Health checks (live / ready / detailed) | `/health/live`, `/health/ready`, `/health` | Done |

## Part V and appendices

| Spec | Requirement | Where | Status |
|---|---|---|---|
| 20 | Roadmap phases | Delivered scope is this document | Done |
| 21 | Interview preparation | [`INTERVIEW_GUIDE.md`](INTERVIEW_GUIDE.md) | Done |
| 22 | Developer onboarding | [`README.md`](../README.md) run instructions, pre-commit hook | Done |
| A | Dataset guide: synthetic plant data | `scripts/generate_synthetic_data.py`, `integration/simulator.py` | Done |
| C | Environment configuration | `.env.example`, `core/config.py` (every `AQUAINTEL_*` setting), `infra/kubernetes/base/config.yaml` | Done |
