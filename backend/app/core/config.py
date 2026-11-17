"""Application settings (spec Ch. 9.11 and Appendix C.1).

12-factor configuration: every value is read from an environment variable carrying the
``AQUAINTEL_`` prefix. The spec uses two spellings for a few variables (e.g. Ch. 9.11
``jwt_secret_key`` vs Appendix C ``AQUAINTEL_SECRET_KEY``); both are accepted through
``AliasChoices`` so either document can be followed without breaking the other.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env(*names: str) -> AliasChoices:
    return AliasChoices(*[f"AQUAINTEL_{n}" for n in names])


# Anchor every default path to backend/, not to the folder the process was started from (QA audit AQ-020).
BACKEND_DIR = Path(__file__).resolve().parents[2]

# Placeholders shipped in .env.example / Kubernetes manifests, and the development default below.
_DEV_SECRET = "dev-only-secret-key-change-me-0123456789abcdef"
_PLACEHOLDER_MARKERS = ("change-me", "replace-with", "replace-me", "dev-only")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AQUAINTEL_", case_sensitive=False, env_file=BACKEND_DIR / ".env", extra="ignore"
    )

    # ---- Application -----------------------------------------------------------------
    app_name: str = "AquaIntel API"
    version: str = "1.0.0"
    environment: Literal["development", "feature", "staging", "production", "test"] = "development"
    debug: bool = False
    api_prefix: str = "/v1"
    tz: str = "UTC"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"]
    )
    max_request_body_mb: int = 10  # Ch. 17.5.1 payload size limit

    # ---- Database (Ch. 4.4) --------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://aquaintel:aquaintel@localhost:5432/aquaintel"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # ---- Redis (Ch. 4.4.3) ---------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # ---- Kafka (Ch. 5.2.2) ---------------------------------------------------------------
    kafka_bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias=_env("KAFKA_BOOTSTRAP_SERVERS", "KAFKA_BOOTSTRAP")
    )
    kafka_telemetry_topic: str = "telemetry.processed"
    # auto  -> try Kafka, fall back to the in-process bus (design principle 4: graceful degradation)
    event_bus: Literal["auto", "kafka", "memory"] = "auto"

    # ---- Auth (Ch. 17.2) -----------------------------------------------------------------
    jwt_secret_key: str = Field(
        default=_DEV_SECRET,
        validation_alias=_env("JWT_SECRET_KEY", "SECRET_KEY"),
    )
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
    jwt_refresh_expiry_days: int = Field(
        default=7, validation_alias=_env("JWT_REFRESH_EXPIRY_DAYS", "JWT_REFRESH_DAYS")
    )
    login_lockout_threshold: int = 10  # Ch. 17.5.3: 30-minute lockout after 10 failures
    login_lockout_minutes: int = 30

    # ---- Rate limiting (Ch. 7.15 / 17.5.3) ----------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_global_per_minute: int = 1000
    rate_limit_authenticated_per_minute: int = 5000
    rate_limit_bulk_per_minute: int = 100
    rate_limit_login_per_minute: int = 5

    # ---- Celery (Ch. 9.8) ----------------------------------------------------------------
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    # inline -> background jobs run as asyncio tasks inside the API process, with an in-process scheduler
    # (single-process dev mode); celery -> jobs go to the Redis broker and Celery beat drives the schedule
    task_mode: Literal["celery", "inline"] = "inline"
    # who owns the drift-check / retraining calendar (Table 10.2): Celery beat, or Airflow DAGs when deployed
    ml_orchestrator: Literal["celery", "airflow"] = "celery"

    # ---- MinIO (Ch. 3.3.4) ---------------------------------------------------------------
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_secure: bool = False
    minio_bucket_reports: str = "aquaintel-reports"
    minio_bucket_models: str = "aquaintel-models"
    local_storage_dir: str = str(BACKEND_DIR / "var" / "storage")

    # ---- MLflow (Ch. 10.6.3) -------------------------------------------------------------
    mlflow_tracking_uri: str | None = Field(
        default=None, validation_alias=_env("MLFLOW_TRACKING_URI", "MLFLOW_URI")
    )

    # ---- Notifications (Ch. 13.6) --------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "alerts@aquaintel.io"
    sms_provider: Literal["twilio", "aws", "log"] | None = "log"
    webhook_url: str | None = None

    # ---- Monitoring (Ch. 19) -------------------------------------------------------------
    sentry_dsn: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip().startswith("["):
                return value  # JSON list, let pydantic parse it
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def _secret_length(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("AQUAINTEL_SECRET_KEY must be at least 32 characters (Appendix C.1)")
        return value

    @field_validator("local_storage_dir")
    @classmethod
    def _anchor_storage(cls, value: str) -> str:
        path = Path(value)
        return str(path if path.is_absolute() else BACKEND_DIR / path)

    @model_validator(mode="after")
    def _no_public_secret_outside_dev(self) -> Settings:
        """QA audit AQ-003: a signing key that is published (default or placeholder) lets anyone mint tokens.

        Development and test keep a convenient default; every other environment refuses to start with it.
        """
        if self.environment not in ("development", "test") and any(
            m in self.jwt_secret_key.lower() for m in _PLACEHOLDER_MARKERS
        ):
            raise ValueError(
                f"AQUAINTEL_SECRET_KEY is a published placeholder; set a random value for '{self.environment}' "
                "(e.g. python -c 'import secrets; print(secrets.token_urlsafe(48))')"
            )
        return self

    @property
    def sync_database_url(self) -> str:
        """psycopg (sync) URL used by Alembic offline mode and pandas reads."""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
