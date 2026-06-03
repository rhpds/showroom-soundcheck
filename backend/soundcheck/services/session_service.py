"""Session and group check orchestration.

Pure service functions for session/group DB persistence, GUID resolution,
and status management. No framework dependencies.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select

from ..models import CheckResult, CheckSession, GroupRun, SessionGroup, SessionTarget
from ..utils import escape_like, make_display_label, utc_now
from . import babylon_client
from .babylon_service import (
    ResolvedEntry,
    ResolutionContext,
    extract_resource_claim_metadata,
    extract_resource_pool_metadata,
    extract_workshop_metadata,
    lookup_rc_by_guid,
    lookup_resource_pool,
    lookup_workshop_by_guid,
    resolve_guids,
    resolve_resource_pool,
    resolve_workshop_guids,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------


async def create_session(
    db: AsyncSession,
    *,
    name: str,
    urls: list[str],
    guids: list[str],
    babylon_cluster: str = "",
    display_label: str = "",
    workshop_guids: list[str] | None = None,
    resource_pools: list[str] | None = None,
    group_id: str | None = None,
    group_run_id: str | None = None,
) -> str:
    """Create a new pending session with targets in the database. Returns session_id."""
    workshop_guids = workshop_guids or []
    resource_pools = resource_pools or []
    sid = str(uuid.uuid4())
    now = utc_now()

    cs = CheckSession(
        session_id=sid,
        name=name,
        group_id=group_id or None,
        group_run_id=group_run_id or None,
        source_urls=urls,
        source_guids=guids,
        source_workshop_guids=workshop_guids,
        source_resource_pools=resource_pools,
        babylon_cluster=babylon_cluster,
        display_label=display_label or make_display_label(urls, guids, workshop_guids, resource_pools),
        status="pending",
        created_at=now,
    )
    db.add(cs)

    for url in urls:
        target = SessionTarget(
            session_id=sid,
            url=url,
            label=url,
            status="pending",
        )
        db.add(target)

    await db.commit()
    return sid


async def fetch_session_data(db: AsyncSession, sid: str) -> dict:
    """Load session, targets, and results from DB."""
    session_q = select(CheckSession).where(CheckSession.session_id == sid)
    targets_q = select(SessionTarget).where(SessionTarget.session_id == sid)
    cs = (await db.execute(session_q)).scalars().first()
    targets = list((await db.execute(targets_q)).scalars().all())
    target_ids = [t.id for t in targets]
    results: list[CheckResult] = []
    if target_ids:
        results_q = (
            select(CheckResult)
            .where(CheckResult.target_id.in_(target_ids))  # type: ignore[union-attr]
            .order_by(col(CheckResult.checked_at).desc())
        )
        results = list((await db.execute(results_q)).scalars().all())
    return {"session": cs, "targets": targets, "results": results}


async def fetch_target_with_results(
    db: AsyncSession,
    target_id: int,
) -> tuple[SessionTarget | None, list[CheckResult]]:
    """Load a single target and its check results (for SSE incremental updates)."""
    target = (await db.execute(select(SessionTarget).where(SessionTarget.id == target_id))).scalars().first()
    results: list[CheckResult] = []
    if target:
        results = list(
            (
                await db.execute(
                    select(CheckResult)
                    .where(CheckResult.target_id == target_id)
                    .order_by(col(CheckResult.checked_at).desc())
                )
            )
            .scalars()
            .all()
        )
    return target, results


async def load_sessions_paginated(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
) -> tuple[list[CheckSession], int]:
    """Load sessions with pagination and search, newest first."""
    query = select(CheckSession)

    if search:
        pattern = f"%{escape_like(search)}%"
        query = query.where(
            CheckSession.name.ilike(pattern) | CheckSession.display_label.ilike(pattern)  # type: ignore[union-attr]
        )

    query = query.order_by(col(CheckSession.pinned).desc(), col(CheckSession.created_at).desc())

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    return list(result.scalars().all()), total


async def load_groups_paginated(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
) -> tuple[list[SessionGroup], int]:
    """Load groups with pagination and search, newest first."""
    query = select(SessionGroup)

    if search:
        pattern = f"%{escape_like(search)}%"
        query = query.where(SessionGroup.name.ilike(pattern))  # type: ignore[union-attr]

    query = query.order_by(col(SessionGroup.pinned).desc(), col(SessionGroup.created_at).desc())

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    return list(result.scalars().all()), total


# ---------------------------------------------------------------------------
# GUID / target resolution
# ---------------------------------------------------------------------------


def _not_found_target(
    sid: str,
    *,
    guid: str | None = None,
    workshop_guid: str | None = None,
) -> SessionTarget:
    if workshop_guid:
        return SessionTarget(
            session_id=sid,
            url="",
            label=f"Workshop not found: {workshop_guid}",
            workshop_guid=workshop_guid,
            status="error",
            error_message=f"No Workshop found for GUID '{workshop_guid}' on any configured cluster",
        )
    return SessionTarget(
        session_id=sid,
        url="",
        label=f"GUID not found: {guid}",
        guid=guid,
        status="error",
        error_message=f"No ResourceClaim or Workshop found for GUID '{guid}' on any configured cluster",
    )


def _status_for_resolution_entry(
    entry: ResolvedEntry,
    *,
    fallback_label: str,
    resolution_error_prefix: str,
) -> tuple[str, str | None, str | None]:
    is_placeholder = not entry.get("url")
    prov_status = entry.get("provision_status") or None
    resolution_error = entry.get("resolution_error") or None

    if resolution_error:
        return "error", f"{resolution_error_prefix}{resolution_error}", prov_status
    if is_placeholder and prov_status and "failed" in prov_status:
        return "error", f"Provision failed for ResourceClaim '{entry.get('label', fallback_label)}'", prov_status
    if is_placeholder and prov_status == "ready":
        return (
            "error",
            (
                f"No showroom endpoint found for ResourceClaim '{entry.get('label', fallback_label)}' "
                "(resource is running)"
            ),
            prov_status,
        )
    if is_placeholder:
        return "provisioning", None, prov_status
    return "pending", None, prov_status


def _resolved_target(
    sid: str,
    entry: ResolvedEntry,
    *,
    fallback_label: str,
    guid: str | None = None,
    workshop_guid: str | None = None,
    resolution_error_prefix: str,
) -> SessionTarget:
    status, err_msg, prov_status = _status_for_resolution_entry(
        entry,
        fallback_label=fallback_label,
        resolution_error_prefix=resolution_error_prefix,
    )
    return SessionTarget(
        session_id=sid,
        url=entry.get("url", ""),
        label=entry.get("label", entry.get("url", "")),
        guid=guid,
        workshop_guid=workshop_guid,
        resource_name=entry.get("rc_name", ""),
        resource_namespace=entry.get("rc_namespace", ""),
        provision_status=prov_status,
        status=status,
        error_message=err_msg,
    )


async def _populate_workshop_metadata(
    db: AsyncSession,
    sid: str,
    ws_guid: str,
    cluster: str,
    ctx: ResolutionContext,
) -> None:
    try:
        ws_def, resolved_cluster = await lookup_workshop_by_guid(ws_guid, cluster=cluster, ctx=ctx)
        if not ws_def:
            return
        meta = extract_workshop_metadata(ws_def)
        cs_result = await db.execute(select(CheckSession).where(CheckSession.session_id == sid))
        cs = cs_result.scalars().first()
        if cs:
            cs.resource_kind = "Workshop"
            cs.resource_name = meta.get("name", "")
            cs.resource_namespace = meta.get("namespace", "")
            cs.resource_display_name = meta.get("display_name", "")
            cs.resource_metadata = meta
            if resolved_cluster and not cs.babylon_cluster:
                cs.babylon_cluster = resolved_cluster
            if meta.get("display_name") and not cs.name:
                cs.name = meta["display_name"]
            db.add(cs)
            await db.commit()
    except Exception as e:
        logger.warning("Failed to populate workshop metadata for '%s': %s", ws_guid, e)


async def _populate_rc_metadata(
    db: AsyncSession,
    sid: str,
    guid: str,
    cluster: str,
    ctx: ResolutionContext,
) -> None:
    try:
        rc_def, resolved_cluster = await lookup_rc_by_guid(guid, cluster=cluster, ctx=ctx)
        if not rc_def:
            return
        meta = extract_resource_claim_metadata(rc_def)
        cs_result = await db.execute(select(CheckSession).where(CheckSession.session_id == sid))
        cs = cs_result.scalars().first()
        if cs:
            cs.resource_kind = "ResourceClaim"
            cs.resource_name = meta.get("name", "")
            cs.resource_namespace = meta.get("namespace", "")
            cs.resource_display_name = meta.get("display_name", "")
            cs.resource_metadata = meta
            if resolved_cluster and not cs.babylon_cluster:
                cs.babylon_cluster = resolved_cluster
            if meta.get("display_name") and not cs.name:
                cs.name = meta["display_name"]
            db.add(cs)
            await db.commit()
    except Exception as e:
        logger.warning("Failed to populate RC metadata for '%s': %s", guid, e)


async def _populate_pool_metadata(
    db: AsyncSession,
    sid: str,
    pool_name: str,
    cluster: str,
) -> None:
    try:
        pool_def, resolved_cluster = await lookup_resource_pool(pool_name, cluster=cluster)
        if not pool_def:
            return
        meta = extract_resource_pool_metadata(pool_def)
        cs_result = await db.execute(select(CheckSession).where(CheckSession.session_id == sid))
        cs = cs_result.scalars().first()
        if cs:
            cs.resource_kind = "ResourcePool"
            cs.resource_name = meta.get("name", "")
            cs.resource_namespace = meta.get("namespace", "")
            cs.resource_display_name = meta.get("catalog_item", "")
            cs.resource_metadata = meta
            if resolved_cluster and not cs.babylon_cluster:
                cs.babylon_cluster = resolved_cluster
            if meta.get("catalog_item") and not cs.name:
                cs.name = meta["catalog_item"]
            db.add(cs)
            await db.commit()
    except Exception as e:
        logger.warning("Failed to populate pool metadata for '%s': %s", pool_name, e)


async def resolve_session_targets(db: AsyncSession, sid: str) -> None:
    """Resolve GUIDs/workshop GUIDs/resource pools and create SessionTarget rows."""
    cs_result = await db.execute(select(CheckSession).where(CheckSession.session_id == sid))
    cs = cs_result.scalars().first()
    guids = cs.get_guids() if cs else []
    ws_guids = cs.get_workshop_guids() if cs else []
    pools = cs.get_resource_pools() if cs else []
    cluster = cs.babylon_cluster if cs else ""

    ctx = ResolutionContext()

    if guids:
        guid_results = await resolve_guids(guids, cluster=cluster, ctx=ctx)
        for guid, url_entries in guid_results.items():
            if not url_entries:
                db.add(_not_found_target(sid, guid=guid))
                continue
            for entry in url_entries:
                db.add(
                    _resolved_target(
                        sid,
                        entry,
                        fallback_label=guid,
                        guid=guid,
                        resolution_error_prefix="GUID resolution failed: ",
                    )
                )
        await db.commit()
        if len(guids) == 1:
            await _populate_rc_metadata(db, sid, guids[0], cluster, ctx)

    if ws_guids:
        ws_results = await resolve_workshop_guids(ws_guids, cluster=cluster, ctx=ctx)
        for ws_guid, url_entries in ws_results.items():
            if not url_entries:
                db.add(_not_found_target(sid, workshop_guid=ws_guid))
                continue
            for entry in url_entries:
                db.add(
                    _resolved_target(
                        sid,
                        entry,
                        fallback_label=ws_guid,
                        guid=entry.get("rc_guid") or None,
                        workshop_guid=ws_guid,
                        resolution_error_prefix="Workshop GUID resolution failed: ",
                    )
                )
        await db.commit()
        if len(ws_guids) == 1:
            await _populate_workshop_metadata(db, sid, ws_guids[0], cluster, ctx)

    if pools:
        for pool_name in pools:
            url_entries, errors, _resolved_cluster = await resolve_resource_pool(
                pool_name,
                cluster=cluster,
            )
            if not url_entries and not errors:
                db.add(
                    SessionTarget(
                        session_id=sid,
                        url="",
                        label=f"ResourcePool empty: {pool_name}",
                        resource_pool_name=pool_name,
                        status="error",
                        error_message=f"ResourcePool '{pool_name}' has no instances",
                    )
                )
            elif not url_entries and errors:
                db.add(
                    SessionTarget(
                        session_id=sid,
                        url="",
                        label=f"ResourcePool not found: {pool_name}",
                        resource_pool_name=pool_name,
                        status="error",
                        error_message="; ".join(errors)[:500],
                    )
                )
            else:
                for entry in url_entries:
                    status, err_msg, prov_status = _status_for_resolution_entry(
                        entry,
                        fallback_label=pool_name,
                        resolution_error_prefix="ResourcePool resolution failed: ",
                    )
                    db.add(
                        SessionTarget(
                            session_id=sid,
                            url=entry.get("url", ""),
                            label=entry.get("label", ""),
                            resource_pool_name=pool_name,
                            provision_status=prov_status,
                            status=status,
                            error_message=err_msg,
                        )
                    )
            await db.commit()
        if len(pools) == 1:
            await _populate_pool_metadata(db, sid, pools[0], cluster)


async def _try_finalize_session(
    session_factory: async_sessionmaker,
    session_id: str,
) -> tuple[bool, str | None, str | None, str | None]:
    """Finalize a session if all its checkable targets have reached a terminal state.

    Called by each check_target after it finishes.  The last target to
    complete triggers the actual finalization.  Safe to call concurrently
    — uses SELECT FOR UPDATE to prevent double-finalization.

    Returns (finalized, final_status, group_run_id, group_id).
    """
    terminal = {"healthy", "unhealthy", "degraded", "error"}

    async with session_factory() as db:
        cs_result = await db.execute(
            select(CheckSession).where(CheckSession.session_id == session_id).with_for_update()
        )
        cs = cs_result.scalars().first()
        if not cs or cs.status != "running":
            return (
                False,
                None,
                cs.group_run_id if cs else None,
                cs.group_id if cs else None,
            )

        targets_result = await db.execute(select(SessionTarget).where(SessionTarget.session_id == session_id))
        targets = list(targets_result.scalars().all())

        checkable = [t for t in targets if t.status != "provisioning"]
        if not all(t.status in terminal for t in checkable):
            return False, None, cs.group_run_id, cs.group_id

        has_provisioning = any(t.status == "provisioning" for t in targets)
        all_healthy = not has_provisioning and bool(checkable) and all(t.status == "healthy" for t in checkable)
        final_status = "completed" if all_healthy else "failed"
        cs.status = final_status
        cs.completed_at = utc_now()
        db.add(cs)
        await db.commit()

        return True, final_status, cs.group_run_id, cs.group_id


async def mark_session_running(
    session_factory: async_sessionmaker,
    sid: str,
) -> bool:
    """Mark session as running if it's still pending. Returns True on success."""
    async with session_factory() as db:
        result = await db.execute(select(CheckSession).where(CheckSession.session_id == sid).with_for_update())
        cs = result.scalars().first()
        if not cs or cs.status != "pending":
            return False
        cs.status = "running"
        db.add(cs)
        await db.commit()
    return True


async def _mark_session_failed(
    session_factory: async_sessionmaker,
    sid: str,
) -> None:
    async with session_factory() as db:
        cs_result = await db.execute(select(CheckSession).where(CheckSession.session_id == sid))
        cs = cs_result.scalars().first()
        if cs:
            cs.status = "failed"
            cs.completed_at = utc_now()
            db.add(cs)
            await db.commit()


async def _try_finalize_group_run(
    session_factory: async_sessionmaker,
    run_id: str,
    group_id: str,
) -> None:
    """Finalize a group run if all its sessions have reached a terminal state.

    Called by each check_target after its session finalizes. The last
    session to complete triggers the actual finalization. Uses SELECT
    FOR UPDATE on the GroupRun row to prevent concurrent
    double-finalization.
    """
    terminal = {"completed", "failed"}

    async with session_factory() as db:
        run_result = await db.execute(select(GroupRun).where(GroupRun.run_id == run_id).with_for_update())
        run = run_result.scalars().first()
        if not run or run.status != "running":
            return

        sessions_result = await db.execute(select(CheckSession).where(CheckSession.group_run_id == run_id))
        sessions = list(sessions_result.scalars().all())
        if not sessions or not all(s.status in terminal for s in sessions):
            return

        statuses = [s.status for s in sessions]
        run_status = "completed" if all(st == "completed" for st in statuses) else "failed"

        run.status = run_status
        run.completed_at = utc_now()
        db.add(run)

        grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
        grp = grp_result.scalars().first()
        if grp:
            grp.status = run_status
            db.add(grp)

        await db.commit()


# ---------------------------------------------------------------------------
# Source metadata sync
# ---------------------------------------------------------------------------


async def sync_source_metadata(
    session_factory: async_sessionmaker,
    gid: str,
) -> None:
    """Look up metadata for all group sources from Kubernetes."""
    async with session_factory() as db:
        grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == gid))
        grp = grp_result.scalars().first()

    if not grp:
        return

    cluster = grp.babylon_cluster or ""
    meta_map: dict[str, dict] = {}
    ctx = ResolutionContext()

    for guid in grp.get_guids():
        meta = await _lookup_source_metadata("rc_guid", guid, cluster, ctx)
        meta_map[f"rc_guid:{guid}"] = meta if meta else {"not_found": True}

    for ws_guid in grp.get_workshop_guids():
        meta = await _lookup_source_metadata("workshop_guid", ws_guid, cluster, ctx)
        meta_map[f"workshop_guid:{ws_guid}"] = meta if meta else {"not_found": True}

    for pool in grp.get_resource_pools():
        meta = await _lookup_source_metadata("pool", pool, cluster)
        meta_map[f"pool:{pool}"] = meta if meta else {"not_found": True}

    async with session_factory() as db:
        grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == gid))
        grp_db = grp_result.scalars().first()
        if grp_db:
            grp_db.member_metadata = meta_map
            db.add(grp_db)
            await db.commit()


def _build_catalog_url(cluster: str, meta: dict) -> str:
    if not cluster:
        return ""
    name = meta.get("name", "")
    namespace = meta.get("namespace", "")
    if not name:
        return ""
    base = babylon_client.get_catalog_url(cluster)
    if not base:
        return ""
    kind = meta.get("kind", "")
    if kind == "Workshop":
        return f"{base}/workshops/{namespace}/{name}"
    if kind == "ResourcePool":
        return f"{base}/admin/resourcepools/{name}/details"
    return f"{base}/services/{namespace}/{name}"


async def _lookup_source_metadata(
    source_type: str,
    source_value: str,
    cluster: str,
    ctx: ResolutionContext | None = None,
) -> dict:
    if ctx is None:
        ctx = ResolutionContext()
    try:
        if source_type == "rc_guid":
            rc_def, resolved = await lookup_rc_by_guid(source_value, cluster=cluster, ctx=ctx)
            if rc_def:
                meta = extract_resource_claim_metadata(rc_def)
                meta["cluster"] = resolved or cluster
                meta["catalog_url"] = _build_catalog_url(resolved or cluster, meta)
                return meta
        elif source_type == "workshop_guid":
            ws_def, resolved = await lookup_workshop_by_guid(source_value, cluster=cluster, ctx=ctx)
            if ws_def:
                meta = extract_workshop_metadata(ws_def)
                meta["cluster"] = resolved or cluster
                meta["catalog_url"] = _build_catalog_url(resolved or cluster, meta)
                return meta
        elif source_type == "pool":
            pool_def, resolved = await lookup_resource_pool(source_value, cluster=cluster)
            if pool_def:
                meta = extract_resource_pool_metadata(pool_def)
                meta["cluster"] = resolved or cluster
                meta["catalog_url"] = _build_catalog_url(resolved or cluster, meta)
                return meta
    except Exception as e:
        logger.warning("Failed to lookup %s '%s': %s", source_type, source_value, e)
        return {"lookup_error": str(e)[:200]}
    return {}


# ---------------------------------------------------------------------------
# Session / group deletion
# ---------------------------------------------------------------------------


async def delete_session(db: AsyncSession, session_id: str) -> None:
    """Delete a session — targets and results cascade via FK constraints."""
    await db.execute(delete(CheckSession).where(CheckSession.session_id == session_id))
    await db.commit()


async def delete_group(db: AsyncSession, group_id: str) -> None:
    """Delete a group — runs, sessions, targets, and results cascade via FK constraints."""
    await db.execute(delete(SessionGroup).where(SessionGroup.group_id == group_id))
    await db.commit()


# ---------------------------------------------------------------------------
# Stale session cleanup
# ---------------------------------------------------------------------------


async def cleanup_stale_sessions(
    session_factory: async_sessionmaker,
    max_age_minutes: int = 10,
) -> int:
    """Mark sessions stuck in 'running' for longer than max_age_minutes as failed.

    Called at startup and periodically via SAQ cron to recover from unclean
    shutdowns where workers were killed before finalizing session status.
    Also finalizes any group runs whose sessions are all now terminal.
    """
    cutoff = utc_now() - timedelta(minutes=max_age_minutes)
    async with session_factory() as db:
        result = await db.execute(
            select(CheckSession).where(CheckSession.status == "running").where(CheckSession.created_at < cutoff)
        )
        stale = list(result.scalars().all())
        for cs in stale:
            cs.status = "failed"
            cs.completed_at = utc_now()
            db.add(cs)
        if stale:
            await db.commit()
            logger.warning("Cleaned up %d stale running session(s)", len(stale))

    group_run_ids = {(cs.group_run_id, cs.group_id) for cs in stale if cs.group_run_id and cs.group_id}
    for run_id, group_id in group_run_ids:
        await _try_finalize_group_run(session_factory, run_id, group_id)

    return len(stale)
