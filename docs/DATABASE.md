# The database, explained simply

AquaIntel keeps everything in **one PostgreSQL database**. There is no second store to keep in sync.
It has 26 tables, but you only need **six of them** to follow what the platform does. Everything else
adds detail around those six.

> **The one-sentence version:** a plant is a tree of **assets**. Each asset has sensors (**tags**). Every
> sensor reading is one row in **telemetry_data**. **alert_rules** watch the readings, and when one is
> broken an **alert** is raised for a **user** to handle.

## 1. The six tables to remember

```mermaid
erDiagram
    assets ||--o{ assets : "parent of"
    assets ||--o{ telemetry_tags : "has sensors"
    telemetry_tags ||--o{ telemetry_data : "one row per reading"
    telemetry_tags ||--o{ alert_rules : "watched by"
    alert_rules ||--o{ alerts : "raises"
    assets ||--o{ alerts : "about"
    users ||--o{ alerts : "acknowledges / resolves"
```

| Table | One row is… | Example |
|---|---|---|
| `assets` | a piece of the plant: site, area, pump, valve, analyser | *High-Lift Pump 2*, path `plant_a/plant_a_pumping/plant_a_pump_002` |
| `telemetry_tags` | one sensor on an asset, with its unit and valid range | `plant_a_pump_002_vib`, mm/s, valid 0–50 |
| `telemetry_data` | one reading: *which sensor, when, what value* | `(18:19 UTC, pump_002_vib, 10.0)` |
| `alert_rules` | a condition to watch | "vibration > 7.1 mm/s for 15 minutes" |
| `alerts` | one alarm, with its lifecycle status | *major · Pump vibration above ISO 10816 zone C · escalated* |
| `users` | a person who signs in, with a role and the sites they may see | *operator@aquaintel.io · Operator · `plant_a/*`* |

### How one reading travels through them

1. The SCADA adapter sends a reading for tag `plant_a_pump_002_vib`. The API looks the tag up in
   `telemetry_tags`; an unknown tag is rejected.
2. The value is checked against the tag's valid range. `Infinity`, `NaN` and out-of-range values
   are never stored as good data.
3. It is inserted into `telemetry_data`. The key is `(time, tag_id)`, so the same reading sent twice
   is stored once.
4. The enabled `alert_rules` for that tag are evaluated. If one is broken, a row is added to
   `alerts`, and every status change after that is added to `alert_events`.

## 2. All 26 tables, grouped by purpose

Every table is used by working code. None is a placeholder.

| Area | Tables | What they hold |
|---|---|---|
| **People & security** | `users`, `roles`, `api_keys`, `audit_log` | Who can sign in and what each role may do. Keys for machines (SCADA adapters, Airflow). A tamper-evident log of every change. |
| **The plant** | `asset_types`, `assets`, `spare_parts` | Kinds of equipment, the equipment tree itself, spare parts held for it. |
| **Sensor data** | `telemetry_tags`, `telemetry_data` | Sensors and their readings: the only *large* table (≈ 720 k rows for 60 days of demo data). |
| **Alarms** | `alert_rules`, `alerts`, `alert_events`, `incidents`, `notifications` | Rules, the alarms they raise, each alarm's history, related alarms grouped into one incident, and the e-mails/SMS sent. |
| **KPIs** | `kpi_definitions`, `kpi_values` | The 30 KPIs (formula, unit, thresholds) and their computed values over time. |
| **Maintenance** | `work_orders` | Jobs for technicians, optionally linked to the alert that caused them. |
| **ML** | `ml_models`, `predictions` | Trained model versions (metrics, approval stage) and their outputs, such as failure probability per pump. |
| **Reports & compliance** | `reports`, `report_schedules`, `regulatory_limits` | Generated reports, their schedules, and legal water-quality limits (e.g. chlorine MRDL 4 mg/L). |
| **Screens & settings** | `dashboards`, `dashboard_widgets`, `schedules`, `system_config` | User-built dashboards, optimised pump schedules, and plant settings such as the tariff. |

Plus `alembic_version`, one row recording which migration the database is at.

## 3. Rules that keep the data trustworthy

These are enforced **by the database itself**, so a bug in one service cannot break them:

| Rule | How |
|---|---|
| Every reading belongs to a real sensor, and every sensor to a real asset | Foreign keys. A bad reference is rejected and the API answers **422**, not a server error. |
| A reading always has a time, a sensor and a value | `NOT NULL` on `time`, `tag_id`, `value`. |
| No duplicate readings | Primary key `(time, tag_id)`; re-sent data is ignored, not doubled. |
| One account per e-mail | Unique e-mail, compared case-insensitively by the API. |
| Times are unambiguous | Every timestamp is `TIMESTAMP WITH TIME ZONE`, stored in UTC and returned with its offset (`…Z`). The UI shows it in the viewer's local time. |
| The audit trail cannot be edited | A trigger rejects any `UPDATE` or `DELETE` on `audit_log`. Each row also stores the hash of the previous row, so a gap or edit is detectable (`Admin → Audit log → Verify`). |
| Deleting is deliberate | Each foreign key states what happens on delete: readings go with their sensor, an alert outlives the rule that raised it (the link is cleared, the alert stays), and a user who created records cannot be removed while those records reference them. |

The API adds checks the database cannot express: value ranges per sensor, finite numbers only,
trimmed and length-limited text, and identical alert rules refused (409).

## 4. The speed-ups, and why they are optional

PostgreSQL alone runs everything. The **TimescaleDB** extension (spec Ch. 6.5) only makes the big
table cheaper to keep and faster to read:

| Feature | What it does | Without TimescaleDB |
|---|---|---|
| Hypertable on `telemetry_data` | Splits the table into weekly chunks behind the scenes | A normal table |
| Compression after 30 days, deletion after 2 years | Keeps disk use flat | Not applied |
| `telemetry_hourly` (continuous aggregate) | Pre-computed hourly min/avg/max per sensor, so a 90-day chart reads ~2 k rows instead of ~130 k | A normal view computing the same numbers on demand |
| `telemetry_daily`, `kpi_daily` | Daily summaries for reports | Same names, computed on demand |

The application asks for the same names either way (migration `0002` decides which form to
create), so **no code changes** when the extension is missing. A laptop with plain PostgreSQL works.

Three read-only **views** give ready-made answers: `active_alerts_summary` (open alarms with their
asset), `asset_health_scores` (reliability, efficiency and quality scores per asset, from its KPIs), and `daily_compliance_summary` (samples
and exceedances per parameter per day).

## 5. Look at it yourself

Connect with `psql postgresql://aquaintel:aquaintel@localhost:5432/aquaintel`, or any SQL client,
and try:

```sql
-- the plant as a tree
SELECT path, name, status FROM assets ORDER BY path;

-- latest value of every sensor on pump 2
SELECT DISTINCT ON (t.external_id) t.external_id, d.time, d.value, t.unit
FROM telemetry_data d JOIN telemetry_tags t ON t.id = d.tag_id
WHERE t.external_id LIKE 'plant_a_pump_002_%'
ORDER BY t.external_id, d.time DESC;

-- hourly average vibration for the last 6 hours (bad-quality readings excluded)
SELECT date_trunc('hour', d.time) AS hour, round(avg(d.value)::numeric, 2) AS avg_vibration
FROM telemetry_data d JOIN telemetry_tags t ON t.id = d.tag_id
WHERE t.external_id = 'plant_a_pump_002_vib' AND d.time > now() - interval '6 hours' AND d.status <> 'bad'
GROUP BY 1 ORDER BY 1;

-- which rules watch that sensor
SELECT r.name, r.severity, r.condition, r.enabled
FROM alert_rules r JOIN telemetry_tags t ON t.id = r.tag_id
WHERE t.external_id = 'plant_a_pump_002_vib';

-- open alarms, newest first
SELECT a.severity, a.title, s.name AS asset, a.status, a.created_at
FROM alerts a JOIN assets s ON s.id = a.asset_id
WHERE a.status IN ('triggered', 'acknowledged', 'investigating', 'escalated')
ORDER BY a.created_at DESC;

-- the life story of the newest alarm
SELECT created_at, from_status, to_status, actor, note
FROM alert_events
WHERE alert_id = (SELECT id FROM alerts ORDER BY created_at DESC LIMIT 1)
ORDER BY created_at;

-- latest value of each KPI
SELECT DISTINCT ON (k.code) k.code, round(v.value::numeric, 2) AS value, k.unit, v.time
FROM kpi_values v JOIN kpi_definitions k ON k.id = v.kpi_id
ORDER BY k.code, v.time DESC;

-- who changed what, most recent first
SELECT created_at, actor, action, entity_type FROM audit_log ORDER BY id DESC LIMIT 20;
```

## 6. Changing the schema

The schema lives in Python (`backend/app/models/*.py`). It changes only through **Alembic
migrations** in `backend/app/db/migrations/versions/`:

| Migration | Contents |
|---|---|
| `0001_core_schema.py` | All tables, keys and indexes |
| `0002_timescale_views_audit.py` | TimescaleDB features (or their plain fallbacks), the views, the audit-log trigger |

```bash
cd backend
alembic upgrade head        # create / update the schema
alembic downgrade base      # drop everything (development only)
alembic revision --autogenerate -m "add column x"   # after editing a model
```
