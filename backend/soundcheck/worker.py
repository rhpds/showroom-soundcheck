"""SAQ worker configuration.

Defines the two queues (orchestration + checks), lifecycle hooks,
and settings dicts consumed by the ``saq`` CLI. Task functions live
in the ``tasks`` subpackage.
"""

import logging

from saq import CronJob, Queue

from .config import CHECK_CONCURRENCY, ORCHESTRATION_CONCURRENCY, REDIS_URL
from .database import async_session_factory
from .services import babylon_client
from .tasks.checks import check_target
from .tasks.orchestration import run_group, run_session_checks, run_single_source, sweep_stale_sessions, sync_metadata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Two separate queues
# ---------------------------------------------------------------------------

orchestration_queue = Queue.from_url(REDIS_URL, name="orchestration")
checks_queue = Queue.from_url(REDIS_URL, name="checks")

queue = orchestration_queue


# ---------------------------------------------------------------------------
# Worker lifecycle hooks
# ---------------------------------------------------------------------------


async def _orchestration_startup(ctx) -> None:
    await babylon_client._default_manager.init_clients_async()
    ctx["session_factory"] = async_session_factory
    ctx["redis"] = orchestration_queue.redis
    ctx["orchestration_queue"] = orchestration_queue
    ctx["checks_queue"] = checks_queue
    logger.info("SAQ orchestration worker started")


async def _orchestration_shutdown(ctx) -> None:
    await babylon_client._default_manager.close_clients()
    logger.info("SAQ orchestration worker shut down")


async def _check_startup(ctx) -> None:
    ctx["session_factory"] = async_session_factory
    ctx["redis"] = checks_queue.redis
    logger.info("SAQ check worker started")


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
