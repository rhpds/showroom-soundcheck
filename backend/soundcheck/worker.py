"""SAQ worker configuration.

Defines the two queues (orchestration + checks), lifecycle hooks,
and settings dicts consumed by the ``saq`` CLI. Task functions live
in the ``tasks`` subpackage.
"""

import logging

import redis.asyncio as aioredis
from saq import CronJob
from saq.queue.redis import RedisQueue

from .config import CHECK_CONCURRENCY, LOG_FORMAT, ORCHESTRATION_CONCURRENCY, REDIS_URL
from .database import async_session_factory
from .services import babylon_client
from .tasks.checks import check_target
from .tasks.orchestration import run_group, run_session_checks, run_single_source, sweep_stale_sessions, sync_metadata


def _configure_worker_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    if LOG_FORMAT == "json":
        from pythonjsonlogger.json import JsonFormatter

        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
                defaults={"request_id": "-"},
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s",
                defaults={"request_id": "-"},
            )
        )
    root.addHandler(handler)


_configure_worker_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Two separate queues
# ---------------------------------------------------------------------------

_REDIS_KWARGS = {
    "health_check_interval": 30,
    "socket_keepalive": True,
    "socket_connect_timeout": 5,
    "socket_timeout": 30,
    "retry_on_timeout": True,
}

orchestration_queue = RedisQueue(aioredis.from_url(REDIS_URL, **_REDIS_KWARGS), name="orchestration")
checks_queue = RedisQueue(aioredis.from_url(REDIS_URL, **_REDIS_KWARGS), name="checks")

queue = orchestration_queue


def _safe_redis_url() -> str:
    """Return REDIS_URL with password masked for logging."""
    from urllib.parse import urlparse

    parsed = urlparse(REDIS_URL)
    if parsed.password:
        return REDIS_URL.replace(f":{parsed.password}@", ":***@")
    return REDIS_URL


# ---------------------------------------------------------------------------
# Worker lifecycle hooks
# ---------------------------------------------------------------------------


async def _orchestration_startup(ctx) -> None:
    await babylon_client._default_manager.init_clients_async()
    ctx["session_factory"] = async_session_factory
    ctx["redis"] = orchestration_queue.redis
    ctx["orchestration_queue"] = orchestration_queue
    ctx["checks_queue"] = checks_queue
    logger.info(
        "Orchestration worker ready — redis=%s, concurrency=%d",
        _safe_redis_url(),
        ORCHESTRATION_CONCURRENCY,
    )


async def _orchestration_shutdown(ctx) -> None:
    await babylon_client._default_manager.close_clients()
    logger.info("SAQ orchestration worker shut down")


async def _check_startup(ctx) -> None:
    ctx["session_factory"] = async_session_factory
    ctx["redis"] = checks_queue.redis
    logger.info(
        "Check worker ready — redis=%s, concurrency=%d",
        _safe_redis_url(),
        CHECK_CONCURRENCY,
    )


async def _check_shutdown(ctx) -> None:
    logger.info("SAQ check worker shut down")


# ---------------------------------------------------------------------------
# SAQ settings dicts
# ---------------------------------------------------------------------------

orchestration_settings = {
    "queue": orchestration_queue,
    "functions": [run_session_checks, run_group, run_single_source, sync_metadata],
    "concurrency": ORCHESTRATION_CONCURRENCY,
    "cron_jobs": [CronJob(sweep_stale_sessions, cron="*/5 * * * *")],
    "startup": _orchestration_startup,
    "shutdown": _orchestration_shutdown,
}

check_settings = {
    "queue": checks_queue,
    "functions": [check_target],
    "concurrency": CHECK_CONCURRENCY,
    "startup": _check_startup,
    "shutdown": _check_shutdown,
}
