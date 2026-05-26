"""Leaf check task — runs on the ``checks`` queue.

Each check_target job performs one HTTP health check for one target,
writes the result, and calls _try_finalize_session so the last target
to complete triggers session (and possibly group) finalization.
"""

import logging

from sqlalchemy import delete
from sqlmodel import select

from ..config import VERIFY_SSL
from ..models import CheckResult, SessionTarget
from ..services.check_service import TargetCheckResult, check_single_target, create_client
from ..services.session_service import _mark_session_failed, _try_finalize_group_run, _try_finalize_session
from ..utils import sanitize_error, utc_now
from . import TaskContext
from .events import publish_group_event, publish_session_event

logger = logging.getLogger(__name__)


async def check_target(ctx: TaskContext, *, target_id: int, session_id: str, url: str, check_type: str, group_id: str = "") -> None:
    """Check a single target URL, write the result, and try to finalize."""
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]

    async with create_client(verify_ssl=VERIFY_SSL) as client:
        try:
            result = await check_single_target(url, check_type, client=client)
        except Exception as e:
            result = TargetCheckResult(
                url=url,
                check_type=check_type,
                error_message=sanitize_error(str(e)[:500]),
            )

    completed_at = utc_now()
    status = (
        "healthy"
        if result.is_healthy
        else "degraded"
        if result.is_degraded
        else "error"
        if result.error_message
        else "unhealthy"
    )

    try:
        async with session_factory() as db:
            await db.execute(delete(CheckResult).where(CheckResult.target_id == target_id))

            t_result = await db.execute(select(SessionTarget).where(SessionTarget.id == target_id))
            t = t_result.scalars().first()
            if t:
                t.status = status
                t.tier_used = result.tier_used
                t.response_time_ms = result.response_time_ms
                t.error_message = result.error_message
                t.check_completed_at = completed_at
                db.add(t)

            cr = CheckResult(
                target_id=target_id,
                check_type=f"{check_type}_{'delegate' if result.tier_used == 1 else 'local'}",
                tier=result.tier_used,
                is_healthy=result.is_healthy,
                status_code=result.status_code,
                response_time_ms=result.response_time_ms,
                error_message=result.error_message,
                detail=result.detail,
                checked_at=completed_at,
            )
            db.add(cr)
            await db.commit()

        await publish_session_event(
            redis,
            session_id,
            "target_update",
            {
                "target_id": target_id,
                "status": status,
                "tier_used": result.tier_used,
                "response_time_ms": result.response_time_ms,
                "error_message": result.error_message,
            },
        )
        await publish_group_event(redis, group_id, "target_update")
    except Exception as e:
        logger.exception(
            "Error writing result for target %s: %s",
            target_id,
            e,
            extra={"request_id": session_id},
        )
        safe_error = sanitize_error(str(e)[:500])
        async with session_factory() as db:
            t_result = await db.execute(select(SessionTarget).where(SessionTarget.id == target_id))
            t = t_result.scalars().first()
            if t:
                t.status = "error"
                t.error_message = safe_error
                t.check_completed_at = utc_now()
                db.add(t)
                await db.commit()

        await publish_session_event(
            redis,
            session_id,
            "target_update",
            {
                "target_id": target_id,
                "status": "error",
                "error_message": safe_error,
            },
        )
        await publish_group_event(redis, group_id, "target_update")

    finalized, final_status, group_run_id, _group_id = await _try_finalize_session(
        session_factory,
        session_id,
    )
    if finalized:
        await publish_session_event(
            redis, session_id, "session_complete", {"status": final_status or "failed"},
        )
        if group_run_id and group_id:
            await _try_finalize_group_run(session_factory, group_run_id, group_id)
            await publish_group_event(redis, group_id, "group_updated")
