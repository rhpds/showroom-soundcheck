"""Group API routes."""

import asyncio
import time
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.sse import EventSourceResponse
from sqlmodel import col, select

from ..config import MAX_SSE_CONNECTIONS

from ..database import DbSession, async_session_factory
from ..models import CheckSession, GroupRun, SessionGroup, SessionTarget
from ..schemas import (
    GroupCreate,
    GroupDetail,
    GroupListItem,
    GroupPublic,
    GroupRename,
    NameResponse,
    PaginatedResponse,
    PinnedResponse,
    SessionListItem,
    SourceRequest,
    StatusResponse,
    TargetPublic,
)
from ..services import session_service
from ..utils import utc_now
from ..worker import queue
from ._serializers import (
    group_to_list_item,
    group_to_public,
    run_to_public,
    session_to_list_item,
    target_to_public,
)

router = APIRouter(prefix="/groups", tags=["groups"])

_sse_semaphore = asyncio.Semaphore(MAX_SSE_CONNECTIONS)


@router.post("", response_model=GroupPublic, status_code=201)
async def create_group(body: GroupCreate, db: DbSession):
    """Create a new check group."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Group name is required")
    if not body.guids and not body.workshop_guids and not body.resource_pools:
        raise HTTPException(status_code=422, detail="Add at least one GUID, workshop GUID, or resource pool")

    gid = str(uuid.uuid4())
    grp = SessionGroup(
        group_id=gid,
        name=body.name.strip(),
        babylon_cluster=body.babylon_cluster.strip() if body.babylon_cluster.strip() != "(auto)" else "",
        source_guids=body.guids,
        source_workshop_guids=body.workshop_guids,
        source_resource_pools=body.resource_pools,
        status="pending",
        created_at=utc_now(),
    )
    db.add(grp)
    await db.commit()
    await db.refresh(grp)

    await queue.enqueue("sync_metadata", group_id=gid)

    return group_to_public(grp)


@router.get("", response_model=PaginatedResponse[GroupListItem])
async def list_groups(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
):
    """List groups with pagination and search, newest first."""
    groups, total = await session_service.load_groups_paginated(
        db,
        page=page,
        per_page=per_page,
        search=search,
    )
    return PaginatedResponse(
        items=[group_to_list_item(g) for g in groups],
        total=total,
        page=page,
        per_page=per_page,
    )


async def _fetch_group_detail(group_id: str) -> GroupDetail | None:
    """Fetch full group detail from DB. Returns None if group not found."""
    async with async_session_factory() as db:
        grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
        grp = grp_result.scalars().first()
        if not grp:
            return None

        runs_result = await db.execute(
            select(GroupRun).where(GroupRun.group_id == group_id).order_by(col(GroupRun.created_at).desc())
        )
        runs = list(runs_result.scalars().all())

        run_ids = [r.run_id for r in runs]
        run_sessions: dict[str, list[SessionListItem]] = {}
        targets_by_session: dict[str, list[TargetPublic]] = {}

        if run_ids:
            all_cs_result = await db.execute(
                select(CheckSession)
                .where(CheckSession.group_run_id.in_(run_ids))  # type: ignore[union-attr]
                .order_by(col(CheckSession.created_at).asc())
            )
            all_cs = list(all_cs_result.scalars().all())

            for cs in all_cs:
                run_sessions.setdefault(cs.group_run_id or "", []).append(session_to_list_item(cs))

            session_ids = [cs.session_id for cs in all_cs]
            if session_ids:
                all_targets_result = await db.execute(
                    select(SessionTarget).where(
                        SessionTarget.session_id.in_(session_ids)  # type: ignore[union-attr]
                    )
                )
                for t in all_targets_result.scalars().all():
                    targets_by_session.setdefault(t.session_id, []).append(target_to_public(t))

        return GroupDetail(
            group=group_to_public(grp),
            runs=[run_to_public(r) for r in runs],
            run_sessions=run_sessions,
            targets_by_session=targets_by_session,
        )


@router.get("/{group_id}", response_model=GroupDetail)
async def get_group(group_id: str):
    """Get full group detail with runs, sessions, and targets."""
    detail = await _fetch_group_detail(group_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Group not found")
    return detail


@router.get("/{group_id}/stream")
async def stream_group(group_id: str, request: Request):
    """SSE stream for live group progress updates.

    Subscribes to the group's Redis Pub/Sub channel and re-fetches
    the full GroupDetail on each event.  Throttled to at most one
    DB refresh per second to handle bursts of target completions.
    """
    if _sse_semaphore.locked():
        raise HTTPException(status_code=503, detail="Too many concurrent SSE connections")

    MAX_WAIT_SECONDS = 600
    THROTTLE_SECONDS = 1.0

    async def event_generator():
        async with _sse_semaphore:
            redis = queue.redis
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"group:{group_id}")
            try:
                detail = await _fetch_group_detail(group_id)
                if not detail:
                    return

                payload = detail.model_dump_json()
                yield f"data: {payload}\n\n"

                elapsed = 0
                last_yield = time.monotonic()
                pending_refresh = False

                while elapsed < MAX_WAIT_SECONDS:
                    if await request.is_disconnected():
                        return

                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if msg and msg.get("data"):
                        now = time.monotonic()
                        if now - last_yield < THROTTLE_SECONDS:
                            pending_refresh = True
                            continue
                    elif pending_refresh:
                        pass
                    else:
                        elapsed += 1
                        continue

                    pending_refresh = False
                    detail = await _fetch_group_detail(group_id)
                    if not detail:
                        return

                    payload = detail.model_dump_json()
                    yield f"data: {payload}\n\n"
                    last_yield = time.monotonic()

                    has_active = detail.group.status == "running" or any(
                        r.status == "running" for r in detail.runs
                    )
                    if not has_active:
                        return
            finally:
                await pubsub.unsubscribe(f"group:{group_id}")
                await pubsub.close()

    return EventSourceResponse(event_generator())


@router.post("/{group_id}/run", response_model=StatusResponse)
async def run_group(group_id: str, request: Request, db: DbSession):
    """Run checks for all sources in the group."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    if not grp_result.scalars().first():
        raise HTTPException(status_code=404, detail="Group not found")

    await queue.enqueue("run_group", group_id=group_id, request_id=request.state.request_id, timeout=1800)

    return StatusResponse(status="started")


@router.post("/{group_id}/run-source", response_model=StatusResponse)
async def run_source(group_id: str, body: SourceRequest, request: Request, db: DbSession):
    """Run checks for a single source of the group."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    if not grp_result.scalars().first():
        raise HTTPException(status_code=404, detail="Group not found")

    await queue.enqueue(
        "run_single_source",
        group_id=group_id,
        source_type=body.source_type,
        source_value=body.source_value,
        request_id=request.state.request_id,
        timeout=1800,
    )

    return StatusResponse(status="started")


@router.patch("/{group_id}/name", response_model=NameResponse)
async def rename_group(group_id: str, body: GroupRename, db: DbSession):
    """Rename a group."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    grp = grp_result.scalars().first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

    grp.name = body.name.strip()
    db.add(grp)
    await db.commit()
    return NameResponse(name=grp.name)


@router.post("/{group_id}/sources", response_model=StatusResponse)
async def add_source(group_id: str, body: SourceRequest, db: DbSession):
    """Add a source to the group."""
    if not body.source_value.strip():
        raise HTTPException(status_code=422, detail="Value is required")

    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    grp = grp_result.scalars().first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

    if body.source_type == "rc_guid":
        items = list(grp.get_guids())
        if body.source_value not in items:
            items.append(body.source_value)
            grp.source_guids = items
    elif body.source_type == "workshop_guid":
        items = list(grp.get_workshop_guids())
        if body.source_value not in items:
            items.append(body.source_value)
            grp.source_workshop_guids = items
    elif body.source_type == "pool":
        items = list(grp.get_resource_pools())
        if body.source_value not in items:
            items.append(body.source_value)
            grp.source_resource_pools = items
    else:
        raise HTTPException(status_code=422, detail=f"Invalid source_type: {body.source_type}")

    db.add(grp)
    await db.commit()

    await queue.enqueue("sync_metadata", group_id=group_id)

    return StatusResponse(status="added")


@router.delete("/{group_id}/sources/{source_type}/{source_value}", response_model=StatusResponse)
async def remove_source(
    group_id: str,
    source_type: Literal["rc_guid", "workshop_guid", "pool"],
    source_value: str,
    db: DbSession,
):
    """Remove a source from the group."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    grp = grp_result.scalars().first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

    if source_type == "rc_guid":
        grp.source_guids = [g for g in grp.get_guids() if g != source_value]
    elif source_type == "workshop_guid":
        grp.source_workshop_guids = [g for g in grp.get_workshop_guids() if g != source_value]
    elif source_type == "pool":
        grp.source_resource_pools = [p for p in grp.get_resource_pools() if p != source_value]

    meta_key = f"{source_type}:{source_value}"
    meta_map = dict(grp.get_source_metadata())
    meta_map.pop(meta_key, None)
    grp.member_metadata = meta_map

    db.add(grp)
    await db.commit()
    return StatusResponse(status="removed")


@router.delete("/{group_id}", response_model=StatusResponse)
async def delete_group(group_id: str, db: DbSession):
    """Delete a group and all its runs, sessions, targets, and results."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    if not grp_result.scalars().first():
        raise HTTPException(status_code=404, detail="Group not found")
    await session_service.delete_group(db, group_id)
    return StatusResponse(status="deleted")


@router.patch("/{group_id}/pin", response_model=PinnedResponse)
async def toggle_pin(group_id: str, db: DbSession):
    """Toggle the pinned state of a group."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    grp = grp_result.scalars().first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")
    grp.pinned = not grp.pinned
    db.add(grp)
    await db.commit()
    return PinnedResponse(pinned=grp.pinned)


@router.post("/{group_id}/sync-metadata", response_model=StatusResponse)
async def sync_metadata(group_id: str, db: DbSession):
    """Refresh K8s metadata for all group sources."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    if not grp_result.scalars().first():
        raise HTTPException(status_code=404, detail="Group not found")

    await queue.enqueue("sync_metadata", group_id=group_id)

    return StatusResponse(status="syncing")
