"""TimescaleDB hypertables, continuous aggregates, retention, views and audit immutability.

Implements:
* Table 6.3 hypertable configuration for ``telemetry_data`` (7-day chunks, HASH(tag_id) x4,
  compression after 30 days, retention 2 years)
* Table 6.4 ``telemetry_hourly`` continuous aggregate (+ refresh policy)
* Appendix A.3.5 ``telemetry_daily`` (p50/p95/p99) materialized view
* Table 6.8 retention policies for KPI values and predictions
* Table 6.7 BRIN (time, tag_id) and HASH (tag_id) indexes
* Listing 6.1 views: active_alerts_summary, asset_health_scores, daily_compliance_summary
* Ch. 17.7 append-only audit log (UPDATE/DELETE rejected by trigger)

If the ``timescaledb`` extension is not installed (e.g. plain PostgreSQL in a laptop
setup), the migration degrades gracefully: hypertable features are skipped and the
aggregates are created as ordinary views with identical columns, so every query in the
application keeps working unchanged.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timescale_available() -> bool:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")).first()
    return row is not None


HOURLY_COLUMNS = """
    tag_id,
    avg(value)    AS avg_value,
    min(value)    AS min_value,
    max(value)    AS max_value,
    stddev(value) AS stddev_value,
    count(*)      AS count,
"""


def upgrade() -> None:
    timescale = _timescale_available()

    if timescale:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        # ---- Table 6.3 hypertable ----------------------------------------------------------
        op.execute(
            """
            SELECT create_hypertable('telemetry_data', 'time',
                   partitioning_column => 'tag_id', number_partitions => 4,
                   chunk_time_interval => INTERVAL '7 days', migrate_data => true)
            """
        )
        op.execute(
            """
            ALTER TABLE telemetry_data SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'tag_id',
                timescaledb.compress_orderby = 'time DESC')
            """
        )
        op.execute("SELECT add_compression_policy('telemetry_data', INTERVAL '30 days')")
        op.execute("SELECT add_retention_policy('telemetry_data', INTERVAL '2 years')")

        op.execute(
            "SELECT create_hypertable('kpi_values', 'time', chunk_time_interval => INTERVAL '30 days', migrate_data => true)"
        )
        op.execute("SELECT add_retention_policy('kpi_values', INTERVAL '1 year')")
        op.execute(
            "SELECT create_hypertable('predictions', 'time', chunk_time_interval => INTERVAL '7 days', migrate_data => true)"
        )
        op.execute("SELECT add_retention_policy('predictions', INTERVAL '90 days')")

        # ---- Table 6.4 continuous aggregate ------------------------------------------------
        op.execute(
            f"""
            CREATE MATERIALIZED VIEW telemetry_hourly
            WITH (timescaledb.continuous) AS
            SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
                   {HOURLY_COLUMNS}
                   first(value, time) AS first_value,
                   last(value, time)  AS last_value
            FROM telemetry_data
            WHERE status <> 'bad'
            GROUP BY bucket, tag_id
            WITH NO DATA
            """
        )
        op.execute(
            """
            SELECT add_continuous_aggregate_policy('telemetry_hourly',
                   start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
                   schedule_interval => INTERVAL '30 minutes')
            """
        )
        op.execute("SELECT add_retention_policy('telemetry_hourly', INTERVAL '2 years')")

        op.execute(
            """
            CREATE MATERIALIZED VIEW kpi_daily
            WITH (timescaledb.continuous) AS
            SELECT time_bucket(INTERVAL '1 day', time) AS bucket, kpi_id, asset_id,
                   avg(value) AS avg_value, min(value) AS min_value, max(value) AS max_value,
                   last(value, time) AS last_value
            FROM kpi_values GROUP BY bucket, kpi_id, asset_id
            WITH NO DATA
            """
        )
        op.execute(
            """
            SELECT add_continuous_aggregate_policy('kpi_daily',
                   start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 hour',
                   schedule_interval => INTERVAL '6 hours')
            """
        )
        op.execute("SELECT add_retention_policy('kpi_daily', INTERVAL '5 years')")
    else:
        # ---- Graceful degradation: same shape as plain views ----------------------------
        op.execute(
            f"""
            CREATE VIEW telemetry_hourly AS
            SELECT date_trunc('hour', time) AS bucket,
                   {HOURLY_COLUMNS}
                   (array_agg(value ORDER BY time ASC))[1]  AS first_value,
                   (array_agg(value ORDER BY time DESC))[1] AS last_value
            FROM telemetry_data
            WHERE status <> 'bad'
            GROUP BY 1, tag_id
            """
        )
        op.execute(
            """
            CREATE VIEW kpi_daily AS
            SELECT date_trunc('day', time) AS bucket, kpi_id, asset_id,
                   avg(value) AS avg_value, min(value) AS min_value, max(value) AS max_value,
                   (array_agg(value ORDER BY time DESC))[1] AS last_value
            FROM kpi_values GROUP BY 1, kpi_id, asset_id
            """
        )

    # ---- Appendix A.3.5 daily aggregates with percentiles (refreshed nightly by Celery) ----
    op.execute(
        """
        CREATE MATERIALIZED VIEW telemetry_daily AS
        SELECT date_trunc('day', time) AS bucket, tag_id,
               avg(value) AS avg_value, min(value) AS min_value, max(value) AS max_value,
               percentile_cont(0.50) WITHIN GROUP (ORDER BY value) AS p50,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY value) AS p99,
               count(*) AS count
        FROM telemetry_data WHERE status <> 'bad'
        GROUP BY 1, tag_id
        WITH NO DATA
        """
    )
    op.execute("CREATE UNIQUE INDEX ix_telemetry_daily_bucket_tag ON telemetry_daily (bucket, tag_id)")

    # ---- Table 6.7 additional index types ---------------------------------------------------
    op.execute("CREATE INDEX ix_telemetry_time_tag_brin ON telemetry_data USING BRIN (time, tag_id)")
    op.execute("CREATE INDEX ix_telemetry_tag_hash ON telemetry_data USING HASH (tag_id)")

    # ---- Listing 6.1 views ------------------------------------------------------------------
    op.execute(
        """
        CREATE VIEW active_alerts_summary AS
        SELECT a.id, a.severity, a.status, a.created_at, a.title,
               ast.name AS asset_name, ast.location,
               ar.name AS rule_name, ar.condition
        FROM alerts a
        JOIN assets ast ON a.asset_id = ast.id
        LEFT JOIN alert_rules ar ON a.rule_id = ar.id
        WHERE a.status IN ('triggered', 'acknowledged', 'investigating', 'escalated')
        """
    )
    op.execute(
        """
        CREATE VIEW asset_health_scores AS
        SELECT kv.asset_id,
               AVG(CASE WHEN kd.health_category = 'reliability' THEN kv.normalized_value END) AS reliability_score,
               AVG(CASE WHEN kd.health_category = 'efficiency'  THEN kv.normalized_value END) AS efficiency_score,
               AVG(CASE WHEN kd.health_category = 'quality'     THEN kv.normalized_value END) AS quality_score
        FROM kpi_values kv
        JOIN kpi_definitions kd ON kv.kpi_id = kd.id
        WHERE kv.time >= NOW() - INTERVAL '24 hours'
        GROUP BY kv.asset_id
        """
    )
    # Spec listing groups telemetry_data by asset_id, which lives on telemetry_tags;
    # the join below implements the intended query.
    op.execute(
        """
        CREATE VIEW daily_compliance_summary AS
        SELECT DATE(td.time) AS report_date, tt.asset_id, td.tag_id, tt.parameter,
               MIN(td.value) AS min_value, MAX(td.value) AS max_value, AVG(td.value) AS avg_value,
               COUNT(*) AS sample_count,
               COUNT(*) FILTER (WHERE td.quality < 192) AS suspect_readings,
               COUNT(*) FILTER (WHERE (rl.limit_max IS NOT NULL AND td.value > rl.limit_max)
                                   OR (rl.limit_min IS NOT NULL AND td.value < rl.limit_min)) AS exceedances
        FROM telemetry_data td
        JOIN telemetry_tags tt ON tt.id = td.tag_id
        LEFT JOIN regulatory_limits rl ON rl.parameter = tt.parameter
        WHERE td.time >= NOW() - INTERVAL '30 days'
        GROUP BY DATE(td.time), tt.asset_id, td.tag_id, tt.parameter
        """
    )

    # ---- Ch. 17.7 append-only, tamper-evident audit log -----------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_immutable
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    for view in ("daily_compliance_summary", "asset_health_scores", "active_alerts_summary"):
        op.execute(f"DROP VIEW IF EXISTS {view}")
    op.execute("DROP INDEX IF EXISTS ix_telemetry_tag_hash")
    op.execute("DROP INDEX IF EXISTS ix_telemetry_time_tag_brin")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS telemetry_daily")
    timescale = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
    ).first() is not None
    if timescale:
        op.execute("DROP MATERIALIZED VIEW IF EXISTS kpi_daily CASCADE")
        op.execute("DROP MATERIALIZED VIEW IF EXISTS telemetry_hourly CASCADE")
    else:
        op.execute("DROP VIEW IF EXISTS kpi_daily")
        op.execute("DROP VIEW IF EXISTS telemetry_hourly")
