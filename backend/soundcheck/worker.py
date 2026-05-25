"""SAQ worker for background health-check processing.

Two separate queues:
  - orchestration: coordinators (run_group, run_session_checks, etc.)
  - checks: individual target health checks (check_target)

Fire-and-finalize pattern at every level:
  - run_group enqueues run_session_checks jobs and returns immediately.
  - run_session_checks resolves targets, enqueues check_target jobs,
    and returns immediately.
  - Each check_target self-finalizes its session via _try_finalize_session.
  - The last session to finalize also finalizes the parent group run.

No task ever blocks waiting for siblings or children.
"""

import json
import logging
import uuid

from saq import CronJob, Queue
from sqlalchemy import delete
from sqlmodel import select

from .config import CHECK_CONCURRENCY, ORCHESTRATION_CONCURRENCY, REDIS_URL, VERIFY_SSL
from .database import async_session_factory
from .models import CheckResult, CheckSession, GroupRun, SessionGroup, SessionTarget
from .services import babylon_client
from .services.check_service import TargetCheckResult, check_single_target, create_client
from .services.session_service import (
    _mark_session_failed,
    _try_finalize_group_run,
    _try_finalize_session,
    cleanup_stale_sessions,
    create_session,
    mark_session_running,
    resolve_session_targets,
    sync_source_metadata,
)
from .utils import utc_now

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Two separate queues
# ---------------------------------------------------------------------------

orchestration_queue = Queue.from_url(REDIS_URL, name="orchestration")
checks_queue = Queue.from_url(REDIS_URL, name="checks")

# Alias used by routes for enqueue (always targets the orchestration queue)
queue = orchestration_queue


# ---------------------------------------------------------------------------
# Orchestration tasks (run on orchestration queue)
# ---------------------------------------------------------------------------


async def run_session_checks(ctx, *, session_id: str) -> None:
    """Resolve targets and fan out check jobs for a single session.

    Marks session running, resolves targets, enqueues individual
    check_target jobs, and returns immediately.  Session finalization
    is handled by the last check_target to complete (fire-and-finalize).
    """
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]

    if not await mark_session_running(session_factory, session_id):
        return

    try:
        async with session_factory() as db:
            await resolve_session_targets(db, session_id)

        await _publish_session_event(redis, session_id, "session_running", {})
        await _enqueue_target_checks(session_factory, redis, session_id)
    except Exception as e:
        logger.exception("Error in session orchestration %s: %s", session_id, e)
        await _mark_session_failed(session_factory, session_id)
        async with session_factory() as db:
            cs = (await db.execute(select(CheckSession).where(CheckSession.session_id == session_id))).scalars().first()
        await _on_session_finalized(
            session_factory,
            redis,
            session_id,
            "failed",
            cs.group_run_id if cs else None,
            cs.group_id if cs else None,
        )


async def run_group(ctx, *, group_id: str) -> None:
    """Create child sessions for every group source and enqueue them.

    Returns immediately after dispatching — does NOT block waiting for
    children.  Group-run finalization is triggered by the last
    run_session_checks to complete (fire-and-finalize pattern).
    """
    session_factory = ctx["session_factory"]

    run_id, session_ids = await _create_group_sessions(session_factory, group_id)
    if not run_id:
        return

    for sid in session_ids:
        await orchestration_queue.enqueue(
            "run_session_checks",
            session_id=sid,
            timeout=900,
        )


async def run_single_source(ctx, *, group_id: str, source_type: str, source_value: str) -> None:
    """Create a session for one group source and enqueue it.

    Returns immediately — finalization is handled by run_session_checks
    when the session completes.
    """
    session_factory = ctx["session_factory"]

    run_id, sid = await _create_single_source_session(
        session_factory,
        group_id,
        source_type,
        source_value,
    )
    if not run_id:
        return

    await orchestration_queue.enqueue(
        "run_session_checks",
        session_id=sid,
        timeout=900,
    )


async def sync_metadata(ctx, *, group_id: str) -> None:
    """Refresh K8s metadata for all group sources."""
    session_factory = ctx["session_factory"]
    await sync_source_metadata(session_factory, group_id)


# ---------------------------------------------------------------------------
# Check task (runs on checks queue)
# ---------------------------------------------------------------------------


async def check_target(ctx, *, target_id: int, session_id: str, url: str, check_type: str) -> None:
    """Check a single target URL, write the result, and try to finalize.

    This is a leaf task -- one HTTP health check for one target.
    After writing the result, calls _try_finalize_session so the last
    target to complete triggers session (and possibly group) finalization.
    """
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]

    async with create_client(verify_ssl=VERIFY_SSL) as client:
        try:
            result = await check_single_target(url, check_type, client=client)
        except Exception as e:
            result = TargetCheckResult(
                url=url,
                check_type=check_type,
                error_message=str(e)[:500],
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
                detail=result.detail_json(),
                checked_at=completed_at,
            )
            db.add(cr)
            await db.commit()

        await _publish_session_event(
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
    except Exception as e:
        logger.exception("Error writing result for target %s: %s", target_id, e)
        async with session_factory() as db:
            t_result = await db.execute(select(SessionTarget).where(SessionTarget.id == target_id))
            t = t_result.scalars().first()
            if t:
                t.status = "error"
                t.error_message = str(e)[:500]
                t.check_completed_at = utc_now()
                db.add(t)
                await db.commit()

        await _publish_session_event(
            redis,
            session_id,
            "target_update",
            {
                "target_id": target_id,
                "status": "error",
                "error_message": str(e)[:500],
            },
        )

    finalized, final_status, group_run_id, group_id = await _try_finalize_session(
        session_factory,
        session_id,
    )
    if finalized:
        await _on_session_finalized(
            session_factory,
            redis,
            session_id,
            final_status,
            group_run_id,
            group_id,
        )


# ---------------------------------------------------------------------------
# Group orchestration helpers
# ---------------------------------------------------------------------------


async def _create_group_sessions(
    session_factory,
    group_id: str,
) -> tuple[str | None, list[str]]:
    """Create a GroupRun and sessions for all sources in a group.

    Returns (run_id, session_ids). Returns (None, []) if the group is not found.
    """
    run_id = str(uuid.uuid4())
    now = utc_now()

    async with session_factory() as db:
        grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
        grp = grp_result.scalars().first()
        if not grp:
            return None, []

        grp.status = "running"
        db.add(grp)

        group_run = GroupRun(
            run_id=run_id,
            group_id=group_id,
            status="running",
            created_at=now,
        )
        db.add(group_run)
        await db.commit()

        rc_guids = grp.get_guids()
        ws_guids = grp.get_workshop_guids()
        pools = grp.get_resource_pools()
        check_type = grp.check_type or "readyz"
        cluster = grp.babylon_cluster or ""

    session_ids: list[str] = []
    async with session_factory() as db:
        for guid in rc_guids:
            sid = await create_session(
                db,
                name=f"RC: {guid}",
                check_type=check_type,
                urls=[],
                guids=[guid],
                babylon_cluster=cluster,
                group_id=group_id,
                group_run_id=run_id,
            )
            session_ids.append(sid)

        for ws_guid in ws_guids:
            sid = await create_session(
                db,
                name=f"Workshop: {ws_guid}",
                check_type=check_type,
                urls=[],
                guids=[],
                workshop_guids=[ws_guid],
                babylon_cluster=cluster,
                group_id=group_id,
                group_run_id=run_id,
            )
            session_ids.append(sid)

        for pool in pools:
            sid = await create_session(
                db,
                name=f"Pool: {pool}",
                check_type=check_type,
                urls=[],
                guids=[],
                resource_pools=[pool],
                babylon_cluster=cluster,
                group_id=group_id,
                group_run_id=run_id,
            )
            session_ids.append(sid)

    return run_id, session_ids


async def _create_single_source_session(
    session_factory,
    group_id: str,
    source_type: str,
    source_value: str,
) -> tuple[str | None, str | None]:
    """Create a GroupRun and session for a single source.

    Returns (run_id, session_id). Returns (None, None) if the group is not found.
    """
    run_id = str(uuid.uuid4())
    now = utc_now()

    async with session_factory() as db:
        grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
        grp = grp_result.scalars().first()
        if not grp:
            return None, None

        grp.status = "running"
        db.add(grp)

        group_run = GroupRun(
            run_id=run_id,
            group_id=group_id,
            status="running",
            created_at=now,
        )
        db.add(group_run)
        await db.commit()

        check_type = grp.check_type or "readyz"
        cluster = grp.babylon_cluster or ""

    async with session_factory() as db:
        if source_type == "rc_guid":
            sid = await create_session(
                db,
                name=f"RC: {source_value}",
                check_type=check_type,
                urls=[],
                guids=[source_value],
                babylon_cluster=cluster,
                group_id=group_id,
                group_run_id=run_id,
            )
        elif source_type == "workshop_guid":
            sid = await create_session(
                db,
                name=f"Workshop: {source_value}",
                check_type=check_type,
                urls=[],
                guids=[],
                workshop_guids=[source_value],
                babylon_cluster=cluster,
                group_id=group_id,
                group_run_id=run_id,
            )
        elif source_type == "pool":
            sid = await create_session(
                db,
                name=f"Pool: {source_value}",
                check_type=check_type,
                urls=[],
                guids=[],
                resource_pools=[source_value],
                babylon_cluster=cluster,
                group_id=group_id,
                group_run_id=run_id,
            )
        else:
            return None, None

    return run_id, sid


# ---------------------------------------------------------------------------
# Check fan-out (enqueue to checks queue, return immediately)
# ---------------------------------------------------------------------------


async def _enqueue_target_checks(
    session_factory,
    redis,
    sid: str,
) -> None:
    """Mark checkable targets as running and enqueue individual check jobs.

    If no checkable targets exist, finalizes the session immediately.
    Returns after enqueuing — does NOT wait for checks to complete.
    """
    async with session_factory() as db:
        targets_result = await db.execute(select(SessionTarget).where(SessionTarget.session_id == sid))
        all_targets = list(targets_result.scalars().all())
        cs_result = await db.execute(select(CheckSession).where(CheckSession.session_id == sid))
        cs = cs_result.scalars().first()
        check_type = cs.check_type if cs else "readyz"

    targets = [t for t in all_targets if t.status not in ("provisioning", "error")]

    if not targets:
        if not all_targets:
            await _mark_session_failed(session_factory, sid)
            async with session_factory() as db:
                cs = (await db.execute(select(CheckSession).where(CheckSession.session_id == sid))).scalars().first()
            await _on_session_finalized(
                session_factory,
                redis,
                sid,
                "failed",
                cs.group_run_id if cs else None,
                cs.group_id if cs else None,
            )
        else:
            finalized, final_status, group_run_id, group_id = await _try_finalize_session(
                session_factory,
                sid,
            )
            if finalized:
                await _on_session_finalized(
                    session_factory,
                    redis,
                    sid,
                    final_status,
                    group_run_id,
                    group_id,
                )
        return

    now = utc_now()
    async with session_factory() as db:
        for target in targets:
            t_result = await db.execute(select(SessionTarget).where(SessionTarget.id == target.id))
            t = t_result.scalars().first()
            if t:
                t.status = "running"
                t.check_started_at = now
                db.add(t)
        await db.commit()

    await _publish_session_event(
        redis,
        sid,
        "targets_running",
        {
            "target_ids": [t.id for t in targets],
        },
    )

    for t in targets:
        await checks_queue.enqueue(
            "check_target",
            target_id=t.id,
            session_id=sid,
            url=t.url,
            check_type=check_type,
            timeout=300,
        )


async def _on_session_finalized(
    session_factory,
    redis,
    session_id: str,
    final_status: str | None,
    group_run_id: str | None,
    group_id: str | None,
) -> None:
    """Publish session completion and cascade to group finalization."""
    await _publish_session_event(
        redis,
        session_id,
        "session_complete",
        {
            "status": final_status or "failed",
        },
    )
    if group_run_id and group_id:
        await _try_finalize_group_run(session_factory, group_run_id, group_id)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _publish_session_event(redis, session_id: str, event_type: str, data: dict) -> None:
    """Publish a progress event to the Redis Pub/Sub channel for this session."""
    payload = json.dumps({"type": event_type, "session_id": session_id, **data})
    await redis.publish(f"session:{session_id}", payload)


# ---------------------------------------------------------------------------
# Cron: periodic stale-session sweep
# ---------------------------------------------------------------------------


async def sweep_stale_sessions(ctx) -> None:
    """Periodically mark sessions stuck in 'running' as failed and finalize
    orphaned group runs. Runs every 5 minutes on the orchestration worker."""
    session_factory = ctx["session_factory"]
    count = await cleanup_stale_sessions(session_factory, max_age_minutes=30)
    if count:
        logger.info("Sweep: cleaned up %d stale session(s)", count)


# ---------------------------------------------------------------------------
# Worker lifecycle hooks
# ---------------------------------------------------------------------------


async def _orchestration_startup(ctx) -> None:
    """Initialize orchestration worker resources."""
    babylon_client._default_manager.init_clients()
    ctx["session_factory"] = async_session_factory
    ctx["redis"] = orchestration_queue.redis
    logger.info("SAQ orchestration worker started")


async def _orchestration_shutdown(ctx) -> None:
    """Cleanup orchestration worker resources."""
    await babylon_client._default_manager.close_clients()
    logger.info("SAQ orchestration worker shut down")


async def _check_startup(ctx) -> None:
    """Initialize check worker resources."""
    ctx["session_factory"] = async_session_factory
    ctx["redis"] = checks_queue.redis
    logger.info("SAQ check worker started")


async def _check_shutdown(ctx) -> None:
    """Cleanup check worker resources."""
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
