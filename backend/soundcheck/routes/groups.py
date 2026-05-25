"""Group API routes."""

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from ..database import DbSession
from ..models import CheckSession, GroupRun, SessionGroup, SessionTarget
from ..schemas import (
    GroupCreate,
    GroupDetail,
    GroupListItem,
    GroupPublic,
    GroupRename,
    GroupRunPublic,
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
from ._serializers import session_to_list_item, target_to_public

router = APIRouter(prefix="/groups", tags=["groups"])


def _group_to_public(g: SessionGroup) -> GroupPublic:
    return GroupPublic(
        id=g.id,
        group_id=g.group_id,
        name=g.name,
        check_type=g.check_type,
        babylon_cluster=g.babylon_cluster,
        source_guids=g.get_guids(),
        source_workshop_guids=g.get_workshop_guids(),
        source_resource_pools=g.get_resource_pools(),
        source_metadata=g.get_source_metadata(),
        status=g.status,
        pinned=g.pinned,
        created_at=g.created_at,
    )


def _group_to_list_item(g: SessionGroup) -> GroupListItem:
    source_count = len(g.get_guids()) + len(g.get_workshop_guids()) + len(g.get_resource_pools())
    return GroupListItem(
        id=g.id,
        group_id=g.group_id,
        name=g.name,
        status=g.status,
        pinned=g.pinned,
        created_at=g.created_at,
        source_count=source_count,
    )


def _run_to_public(r: GroupRun) -> GroupRunPublic:
    return GroupRunPublic(
        id=r.id,
        run_id=r.run_id,
        group_id=r.group_id,
        status=r.status,
        created_at=r.created_at,
        completed_at=r.completed_at,
    )


@router.post("", response_model=GroupPublic, status_code=201)
async def create_group(body: GroupCreate, db: DbSession):
    """Create a new check group."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Group name is required")
    if not body.guids and not body.workshop_guids and not body.resource_pools:
        raise HTTPException(status_code=422, detail="Add at least one GUID or pool")

    gid = str(uuid.uuid4())
    grp = SessionGroup(
        group_id=gid,
        name=body.name.strip(),
        check_type=body.check_type,
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

    return _group_to_public(grp)


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
        items=[_group_to_list_item(g) for g in groups],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{group_id}", response_model=GroupDetail)
async def get_group(group_id: str, db: DbSession):
    """Get full group detail with runs, sessions, and targets."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    grp = grp_result.scalars().first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

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
        group=_group_to_public(grp),
        runs=[_run_to_public(r) for r in runs],
        run_sessions=run_sessions,
        targets_by_session=targets_by_session,
    )


@router.post("/{group_id}/run", response_model=StatusResponse)
async def run_group(group_id: str, db: DbSession):
    """Run checks for all sources in the group."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    if not grp_result.scalars().first():
        raise HTTPException(status_code=404, detail="Group not found")

    await queue.enqueue("run_group", group_id=group_id, timeout=1800)

    return StatusResponse(status="started")


@router.post("/{group_id}/run-source", response_model=StatusResponse)
async def run_source(group_id: str, body: SourceRequest, db: DbSession):
    """Run checks for a single source of the group."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    if not grp_result.scalars().first():
        raise HTTPException(status_code=404, detail="Group not found")

    await queue.enqueue(
        "run_single_source",
        group_id=group_id,
        source_type=body.source_type,
        source_value=body.source_value,
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


@router.delete("/{group_id}/sources", response_model=StatusResponse)
async def remove_source(group_id: str, body: SourceRequest, db: DbSession):
    """Remove a source from the group."""
    grp_result = await db.execute(select(SessionGroup).where(SessionGroup.group_id == group_id))
    grp = grp_result.scalars().first()
    if not grp:
        raise HTTPException(status_code=404, detail="Group not found")

    if body.source_type == "rc_guid":
        grp.source_guids = [g for g in grp.get_guids() if g != body.source_value]
    elif body.source_type == "workshop_guid":
        grp.source_workshop_guids = [g for g in grp.get_workshop_guids() if g != body.source_value]
    elif body.source_type == "pool":
        grp.source_resource_pools = [p for p in grp.get_resource_pools() if p != body.source_value]

    meta_key = f"{body.source_type}:{body.source_value}"
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
