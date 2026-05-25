"""Orchestration tasks — run on the ``orchestration`` queue.

These are lightweight coordinators that fan out child jobs and return
immediately. No task ever blocks waiting for siblings or children.
"""

import logging
import uuid

from sqlmodel import select

from ..models import CheckSession, GroupRun, SessionGroup, SessionTarget
from ..services.session_service import (
    _mark_session_failed,
    _try_finalize_group_run,
    _try_finalize_session,
    cleanup_stale_sessions,
    create_session,
    mark_session_running,
    resolve_session_targets,
    sync_source_metadata,
)
from ..utils import utc_now
from .events import publish_group_event, publish_session_event

logger = logging.getLogger(__name__)


async def run_session_checks(ctx, *, session_id: str) -> None:
    """Resolve targets and fan out check jobs for a single session."""
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]
    checks_queue = ctx["checks_queue"]

    if not await mark_session_running(session_factory, session_id):
        return

    try:
        async with session_factory() as db:
            await resolve_session_targets(db, session_id)
            cs = (await db.execute(select(CheckSession).where(CheckSession.session_id == session_id))).scalars().first()
        group_id = cs.group_id if cs else None

        await publish_session_event(redis, session_id, "session_running", {})
        await publish_group_event(redis, group_id, "session_running")
        await _enqueue_target_checks(session_factory, redis, checks_queue, session_id)
    except Exception as e:
        logger.exception("Error in session orchestration: %s", e, extra={"request_id": session_id})
        await _mark_session_failed(session_factory, session_id)
        async with session_factory() as db:
            cs = (await db.execute(select(CheckSession).where(CheckSession.session_id == session_id))).scalars().first()
        await _on_session_finalized(
            session_factory, redis, session_id, "failed",
            cs.group_run_id if cs else None, cs.group_id if cs else None,
        )


async def run_group(ctx, *, group_id: str) -> None:
    """Create child sessions for every group source and enqueue them."""
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]
    orchestration_queue = ctx["orchestration_queue"]

    run_id, session_ids = await _create_group_sessions(session_factory, group_id)
    if not run_id:
        return

    await publish_group_event(redis, group_id, "run_started")

    for sid in session_ids:
        await orchestration_queue.enqueue("run_session_checks", session_id=sid, timeout=900)


async def run_single_source(ctx, *, group_id: str, source_type: str, source_value: str) -> None:
    """Create a session for one group source and enqueue it."""
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]
    orchestration_queue = ctx["orchestration_queue"]

    run_id, sid = await _create_single_source_session(session_factory, group_id, source_type, source_value)
    if not run_id:
        return

    await publish_group_event(redis, group_id, "run_started")
    await orchestration_queue.enqueue("run_session_checks", session_id=sid, timeout=900)


async def sync_metadata(ctx, *, group_id: str) -> None:
    """Refresh K8s metadata for all group sources."""
    await sync_source_metadata(ctx["session_factory"], group_id)


async def sweep_stale_sessions(ctx) -> None:
    """Periodically mark sessions stuck in 'running' as failed and finalize
    orphaned group runs. Runs every 5 minutes on the orchestration worker."""
    count = await cleanup_stale_sessions(ctx["session_factory"], max_age_minutes=30)
    if count:
        logger.info("Sweep: cleaned up %d stale session(s)", count)


# ---------------------------------------------------------------------------
# Group session creation helpers
# ---------------------------------------------------------------------------


async def _create_group_sessions(
    session_factory,
    group_id: str,
) -> tuple[str | None, list[str]]:
    """Create a GroupRun and sessions for all sources in a group."""
    run_id = str(uuid.uuid4())
    now = utc_now()

    async with session_factory() as db:
        grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
        grp = grp_result.scalars().first()
        if not grp:
            return None, []

        grp.status = "running"
        db.add(grp)
        db.add(GroupRun(run_id=run_id, group_id=group_id, status="running", created_at=now))
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
                db, name=f"RC: {guid}", check_type=check_type, urls=[], guids=[guid],
                babylon_cluster=cluster, group_id=group_id, group_run_id=run_id,
            )
            session_ids.append(sid)
        for ws_guid in ws_guids:
            sid = await create_session(
                db, name=f"Workshop: {ws_guid}", check_type=check_type, urls=[], guids=[],
                workshop_guids=[ws_guid], babylon_cluster=cluster, group_id=group_id, group_run_id=run_id,
            )
            session_ids.append(sid)
        for pool in pools:
            sid = await create_session(
                db, name=f"Pool: {pool}", check_type=check_type, urls=[], guids=[],
                resource_pools=[pool], babylon_cluster=cluster, group_id=group_id, group_run_id=run_id,
            )
            session_ids.append(sid)

    return run_id, session_ids


async def _create_single_source_session(
    session_factory,
    group_id: str,
    source_type: str,
    source_value: str,
) -> tuple[str | None, str | None]:
    """Create a GroupRun and session for a single source."""
    run_id = str(uuid.uuid4())
    now = utc_now()

    async with session_factory() as db:
        grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
        grp = grp_result.scalars().first()
        if not grp:
            return None, None

        grp.status = "running"
        db.add(grp)
        db.add(GroupRun(run_id=run_id, group_id=group_id, status="running", created_at=now))
        await db.commit()

        check_type = grp.check_type or "readyz"
        cluster = grp.babylon_cluster or ""

    kwargs = dict(check_type=check_type, urls=[], babylon_cluster=cluster, group_id=group_id, group_run_id=run_id)
    async with session_factory() as db:
        if source_type == "rc_guid":
            sid = await create_session(db, name=f"RC: {source_value}", guids=[source_value], **kwargs)
        elif source_type == "workshop_guid":
            sid = await create_session(db, name=f"Workshop: {source_value}", guids=[], workshop_guids=[source_value], **kwargs)
        elif source_type == "pool":
            sid = await create_session(db, name=f"Pool: {source_value}", guids=[], resource_pools=[source_value], **kwargs)
        else:
            return None, None

    return run_id, sid


# ---------------------------------------------------------------------------
# Check fan-out and finalization helpers
# ---------------------------------------------------------------------------


async def _enqueue_target_checks(session_factory, redis, checks_queue, sid: str) -> None:
    """Mark checkable targets as running and enqueue individual check jobs.

    If no checkable targets exist, finalizes the session immediately.
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
                session_factory, redis, sid, "failed",
                cs.group_run_id if cs else None, cs.group_id if cs else None,
            )
        else:
            finalized, final_status, group_run_id, group_id = await _try_finalize_session(session_factory, sid)
            if finalized:
                await _on_session_finalized(session_factory, redis, sid, final_status, group_run_id, group_id)
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

    group_id = cs.group_id if cs else None

    await publish_session_event(redis, sid, "targets_running", {"target_ids": [t.id for t in targets]})
    await publish_group_event(redis, group_id, "targets_running")

    for t in targets:
        await checks_queue.enqueue(
            "check_target",
            target_id=t.id, session_id=sid, url=t.url,
            check_type=check_type, group_id=group_id or "",
            timeout=300,
        )


async def _on_session_finalized(
    session_factory, redis, session_id: str,
    final_status: str | None, group_run_id: str | None, group_id: str | None,
) -> None:
    """Publish session completion and cascade to group finalization."""
    await publish_session_event(redis, session_id, "session_complete", {"status": final_status or "failed"})
    if group_run_id and group_id:
        await _try_finalize_group_run(session_factory, group_run_id, group_id)
        await publish_group_event(redis, group_id, "group_updated")
