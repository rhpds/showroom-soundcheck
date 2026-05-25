"""Application configuration derived from environment variables."""

import logging
import os

logger = logging.getLogger(__name__)


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, 1)


def _default_db_url() -> str:
    return (
        f"postgresql://{os.environ.get('POSTGRES_USER', 'soundcheck')}"
        f":{os.environ.get('POSTGRES_PASSWORD', 'soundcheck_dev')}"
        f"@{os.environ.get('POSTGRES_HOST', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ.get('POSTGRES_DB', 'soundcheck')}"
    )


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


def get_async_db_url() -> str:
    explicit = os.environ.get("ASYNC_DATABASE_URL") or os.environ.get("ASYNC_DB_URL")
    if explicit:
        return explicit
    db_url = os.environ.get("DATABASE_URL", _default_db_url())
    return _derive_async_db_url(db_url)


CHECK_CONCURRENCY = _positive_int_env("CHECK_CONCURRENCY", 20)
ORCHESTRATION_CONCURRENCY = _positive_int_env("ORCHESTRATION_CONCURRENCY", 10)
DB_POOL_SIZE = _positive_int_env("DB_POOL_SIZE", 10)
DB_MAX_OVERFLOW = _positive_int_env("DB_MAX_OVERFLOW", 20)
DB_POOL_RECYCLE = _positive_int_env("DB_POOL_RECYCLE", 3600)
VERIFY_SSL = os.environ.get("VERIFY_SSL", "true").lower() in ("true", "1", "yes")
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text").lower()
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")]
API_KEY = os.environ.get("API_KEY", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


def warn_default_credentials() -> None:
    """Log a warning if using default database credentials."""
    if not os.environ.get("POSTGRES_PASSWORD") and not os.environ.get("DATABASE_URL"):
        logger.warning(
            "Using default database credentials (soundcheck_dev). Set POSTGRES_PASSWORD or DATABASE_URL for production."
        )
