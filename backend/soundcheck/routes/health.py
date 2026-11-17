"""Health and configuration routes."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..database import DbSession
from ..schemas import ClustersResponse
from ..services import babylon_client
from ..worker import orchestration_queue

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/ping")
async def ping():
    return {"status": "ok"}


@router.get("/health")
async def health(db: DbSession):
    """Verify PostgreSQL and Redis connectivity."""
    errors: list[str] = []
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: PostgreSQL unavailable")
        errors.append("postgres")

    try:
        await orchestration_queue.redis.ping()
    except Exception:
        logger.exception("Health check: Redis unavailable")
        errors.append("redis")

    if errors:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "unavailable": errors},
        )
    return {"status": "ok"}


@router.get("/config/clusters", response_model=ClustersResponse)
async def get_clusters():
    """Return the list of configured Babylon clusters.

    default_clusters is the subset pre-selected on the workshop dashboard's
    cluster filter (see BABYLON_DEFAULT_CLUSTERS); clusters is always the
    full configured list, for the filter's selectable chips and the manual
    cluster dropdowns on /sessions/new and /groups/new.
    """
    return ClustersResponse(
        clusters=babylon_client.get_configured_clusters(),
        default_clusters=babylon_client.get_default_clusters(),
    )
