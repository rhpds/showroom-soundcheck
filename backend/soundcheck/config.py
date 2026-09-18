"""Application configuration loaded via pydantic-settings.

Defines a single ``Settings(BaseSettings)`` model that reads from environment
variables (and, optionally, a ``.env`` file) with typed, validated fields.

A singleton ``settings`` instance is created at import time, and every
previously-exported ALL-CAPS module-level constant / helper function is
re-exported here so existing call sites (``from .config import X`` /
``from ..config import X``) keep working unchanged.
"""

import logging
from typing import Annotated, Any, ClassVar

from pydantic import BeforeValidator, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared parsing helpers for comma-separated env vars.
#
# pydantic-settings normally tries to JSON-decode env values for complex
# field types (list, frozenset, etc). Our env vars are plain comma-separated
# strings, not JSON, so we opt out of that decoding (``NoDecode``) and parse
# them ourselves via a ``BeforeValidator``.
# ---------------------------------------------------------------------------


def _split_comma(value: Any) -> Any:
    """Split a comma-separated env var string into a stripped list."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",")]
    return value


def _split_comma_lower(value: Any) -> Any:
    """Split a comma-separated env var string into a lowercased, blank-filtered list."""
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return value


CommaSeparatedList = Annotated[list[str], NoDecode, BeforeValidator(_split_comma)]
LowercasedEmailSet = Annotated[frozenset[str], NoDecode, BeforeValidator(_split_comma_lower)]


def _derive_async_db_url(db_url: str | None) -> str:
    """Convert a sync PostgreSQL DB URL to its asyncpg equivalent."""
    if not db_url or "://" not in db_url:
        raise ValueError("DATABASE_URL must be a valid PostgreSQL URL")
    scheme, tail = db_url.split("://", 1)
    if scheme == "postgresql+asyncpg":
        return db_url
    if scheme in ("postgres", "postgresql") or scheme.startswith("postgresql+"):
        return f"postgresql+asyncpg://{tail}"
    raise ValueError(f"Unsupported DB scheme: {scheme}")


class Settings(BaseSettings):
    """Typed application configuration, loaded from env vars and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Concurrency / pool tuning -----------------------------------------
    check_concurrency: int = 20
    orchestration_concurrency: int = 10
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600
    max_sse_connections: int = 200

    _POSITIVE_INT_DEFAULTS: ClassVar[dict[str, int]] = {
        "check_concurrency": 20,
        "orchestration_concurrency": 10,
        "db_pool_size": 10,
        "db_max_overflow": 20,
        "db_pool_recycle": 3600,
        "max_sse_connections": 200,
    }

    @field_validator(
        "check_concurrency",
        "orchestration_concurrency",
        "db_pool_size",
        "db_max_overflow",
        "db_pool_recycle",
        "max_sse_connections",
        mode="before",
    )
    @classmethod
    def _coerce_positive_int(cls, v: Any, info: ValidationInfo) -> int:
        """Reproduce the old ``_positive_int_env`` semantics.

        Non-numeric input falls back to the field's default; a numeric value
        below 1 is clamped up to 1 (it does *not* fall back to the default —
        this matches the pre-existing ``max(value, 1)`` behavior).
        """
        default = cls._POSITIVE_INT_DEFAULTS[info.field_name]
        try:
            value = int(v)
        except (TypeError, ValueError):
            return default
        return max(value, 1)

    # -- HTTP / API ----------------------------------------------------------
    verify_ssl: bool = True
    log_format: str = "text"
    cors_origins: CommaSeparatedList = Field(default_factory=lambda: ["http://localhost:5173"])
    api_key: str = ""
    enable_docs: bool = True

    @field_validator("verify_ssl", "enable_docs", mode="before")
    @classmethod
    def _parse_legacy_bool(cls, v: Any) -> Any:
        """Match the old ``.lower() in ("true", "1", "yes")`` truthiness check.

        Deliberately narrower than pydantic's native bool coercion (which
        also accepts e.g. "on"/"y"/"t"), to avoid a behavior change.
        """
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes")

    @field_validator("log_format", mode="before")
    @classmethod
    def _lowercase_log_format(cls, v: Any) -> Any:
        return v.lower() if isinstance(v, str) else v

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _reject_wildcard_cors(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise RuntimeError(
                "CORS_ORIGINS must not contain '*' (wildcard is unsafe with allow_credentials=True). "
                "Set explicit origin(s) instead, e.g. CORS_ORIGINS=https://my-frontend.example.com"
            )
        return v

    # -- Redis / queues --------------------------------------------------
    redis_url: str = "redis://localhost:6379"

    # -- Demo team filter -------------------------------------------------
    demo_team_emails: LowercasedEmailSet = Field(default_factory=frozenset)

    @field_validator("demo_team_emails", mode="after")
    @classmethod
    def _warn_if_demo_team_empty(cls, v: frozenset[str]) -> frozenset[str]:
        if not v:
            logger.warning(
                "DEMO_TEAM_EMAILS is not set — the workshop 'Provisioned by: Demo team' filter "
                "will not match any workshops."
            )
        return v

    # -- Environment ---------------------------------------------------------
    environment: str = "development"

    @field_validator("environment", mode="before")
    @classmethod
    def _lowercase_environment(cls, v: Any) -> Any:
        return v.lower() if isinstance(v, str) else v

    # -- Database ----------------------------------------------------------
    postgres_user: str = "soundcheck"
    postgres_password: str | None = None
    postgres_host: str = "localhost"
    postgres_port: str = "5432"
    postgres_db: str = "soundcheck"
    database_url: str | None = None
    async_database_url: str | None = None
    async_db_url: str | None = None

    def _default_db_url(self) -> str:
        password = self.postgres_password or "soundcheck_dev"
        return (
            f"postgresql://{self.postgres_user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def get_async_db_url(self) -> str:
        explicit = self.async_database_url or self.async_db_url
        if explicit:
            return explicit
        db_url = self.database_url or self._default_db_url()
        return _derive_async_db_url(db_url)

    def warn_default_credentials(self) -> None:
        """Log a warning if using default database credentials.

        In non-development environments, refuse to start -- this prevents
        production deployments from silently running with insecure defaults
        when secrets are misconfigured.
        """
        if not self.postgres_password and not self.database_url:
            if self.environment != "development":
                raise RuntimeError(
                    "POSTGRES_PASSWORD or DATABASE_URL must be set in non-development environments. "
                    "Set ENVIRONMENT=development to use default credentials for local work."
                )
            logger.warning(
                "Using default database credentials (soundcheck_dev). "
                "Set POSTGRES_PASSWORD or DATABASE_URL for production."
            )


settings = Settings()

# ---------------------------------------------------------------------------
# Backwards-compatible module-level constants.
#
# Other modules (main.py, worker.py, database.py, routes/*, services/*,
# tasks/*, alembic/env.py) import these as plain module-level names. Keep
# re-exporting them here so those call sites don't need to change.
# ---------------------------------------------------------------------------
CHECK_CONCURRENCY = settings.check_concurrency
ORCHESTRATION_CONCURRENCY = settings.orchestration_concurrency
DB_POOL_SIZE = settings.db_pool_size
DB_MAX_OVERFLOW = settings.db_max_overflow
DB_POOL_RECYCLE = settings.db_pool_recycle
VERIFY_SSL = settings.verify_ssl
LOG_FORMAT = settings.log_format
CORS_ORIGINS = settings.cors_origins
API_KEY = settings.api_key
REDIS_URL = settings.redis_url
ENABLE_DOCS = settings.enable_docs
MAX_SSE_CONNECTIONS = settings.max_sse_connections
DEMO_TEAM_EMAILS = settings.demo_team_emails
ENVIRONMENT = settings.environment


def get_async_db_url() -> str:
    return settings.get_async_db_url()


def warn_default_credentials() -> None:
    settings.warn_default_credentials()
