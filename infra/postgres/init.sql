-- Runs once on first container start (docker-entrypoint-initdb.d).
-- TimescaleDB for hypertables/continuous aggregates; a separate database for Airflow metadata.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE DATABASE airflow;
