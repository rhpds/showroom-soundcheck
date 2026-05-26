"""Session API routes."""

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.sse import EventSourceResponse
from sqlmodel import select

from ..database import DbSession, async_session_factory
from ..models import CheckResult, CheckSession, SessionTarget
from ..schemas import (
    CheckRedirectResponse,
    PaginatedResponse,
    PinnedResponse,
    SessionCreate,
    SessionDetail,
    SessionUpdate,
    StatusResponse,
)
from ..services import session_service
from ..utils import InputValidationError, parse_check_params
from ..worker import queue
from ._serializers import result_to_public, session_to_list_item, session_to_public, target_to_public


@router.post("", response_model=CheckRedirectResponse, status_code=201)
async def create_session(body: SessionCreate, db: DbSession):
    """Create a new health-check session and return its ID."""
    try:
        parsed = parse_check_params(
            raw_urls=",".join(body.urls),
            raw_guids=",".join(body.guids),
            raw_ws_guids=",".join(body.workshop_guids),
            raw_resource_pools=",".join(body.resource_pools),
            check_type=body.check_type,
            session_name=body.name,
            cluster=body.babylon_cluster,
            url_separator=",",
        )
    except InputValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    sid = await session_service.create_session(
        db,
        name=parsed.session_name,
        check_type=parsed.check_type,
        urls=parsed.urls,
        guids=parsed.guids,
        babylon_cluster=parsed.babylon_cluster,
        workshop_guids=parsed.workshop_guids,
        resource_pools=parsed.resource_pools,
    )

    await queue.enqueue("run_session_checks", session_id=sid, timeout=900)

    return CheckRedirectResponse(session_id=sid)


@router.get("", response_model=PaginatedResponse[SessionListItem])
async def list_sessions(
    db: DbSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
):
    """List sessions with pagination and search, newest first."""
    sessions, total = await session_service.load_sessions_paginated(
        db,
        page=page,
        per_page=per_page,
        search=search,
    )
    return PaginatedResponse(
        items=[session_to_list_item(s) for s in sessions],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, db: DbSession):
    """Get full session detail with targets and results."""
    data = await session_service.fetch_session_data(db, session_id)
    cs = data["session"]
    if not cs:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(
        session=session_to_public(cs),
        targets=[target_to_public(t) for t in data["targets"]],
        results=[result_to_public(r) for r in data["results"]],
    )


@router.post("/{session_id}/clone", response_model=CheckRedirectResponse)
async def clone_session(session_id: str, db: DbSession):
    """Clone an existing session and start new checks."""
    data = await session_service.fetch_session_data(db, session_id)
    cs = data["session"]
    if not cs:
        raise HTTPException(status_code=404, detail="Session not found")

    sid = await session_service.create_session(
        db,
        name=cs.name,
        check_type=cs.check_type,
        urls=cs.get_urls(),
        guids=cs.get_guids(),
        babylon_cluster=cs.babylon_cluster,
        display_label=cs.display_label,
        workshop_guids=cs.get_workshop_guids(),
        resource_pools=cs.get_resource_pools(),
    )

    await queue.enqueue("run_session_checks", session_id=sid, timeout=900)

    return CheckRedirectResponse(session_id=sid)


@router.delete("/{session_id}", response_model=StatusResponse)
async def delete_session(session_id: str, db: DbSession):
    """Delete a session and all its targets and results."""
    result = await db.execute(select(CheckSession).where(CheckSession.session_id == session_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Session not found")
    await session_service.delete_session(db, session_id)
    return StatusResponse(status="deleted")


@router.patch("/{session_id}/pin", response_model=PinnedResponse)
async def toggle_pin(session_id: str, db: DbSession):
    """Toggle the pinned state of a session."""
    result = await db.execute(select(CheckSession).where(CheckSession.session_id == session_id))
    cs = result.scalars().first()
    if not cs:
        raise HTTPException(status_code=404, detail="Session not found")
    cs.pinned = not cs.pinned
    db.add(cs)
    await db.commit()
    return PinnedResponse(pinned=cs.pinned)


def _build_sse_update(
    session_id: str,
    status: str,
    targets_cache: dict[int, SessionTarget],
    results_cache: dict[int, CheckResult],
    session: "CheckSession | None" = None,
) -> str:
    payload = SessionUpdate(
        session_id=session_id,
        status=status,
        session=session_to_public(session) if session else None,
        targets=[target_to_public(t) for t in targets_cache.values()],
        results=[result_to_public(r) for r in results_cache.values()],
    ).model_dump_json()
    return f"data: {payload}\n\n"


@router.get("/{session_id}/stream")
async def stream_session(session_id: str, request: Request):
    """SSE stream for live session progress updates via Redis Pub/Sub.

    Uses an in-memory cache so that frequent target_update events only
    fetch the single changed target from the DB instead of the entire
    session.  Full refreshes are limited to initial load and session
    completion.
    """
    MAX_WAIT_SECONDS = 600

    async def _full_refresh(session_id):
        """Re-fetch all session data from DB and rebuild caches."""
        async with async_session_factory() as db:
            return await session_service.fetch_session_data(db, session_id)

    async def event_generator():
        # Subscribe BEFORE fetching initial data so events published
        # during the DB query are buffered and not lost.
        redis = queue.redis
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"session:{session_id}")
        try:
            data = await _full_refresh(session_id)

            cs = data["session"]
            if not cs:
                return

            session_status = cs.status
            targets_cache: dict[int, SessionTarget] = {t.id: t for t in data["targets"]}
            results_cache: dict[int, CheckResult] = {r.id: r for r in data["results"]}

            yield _build_sse_update(
                session_id, session_status, targets_cache, results_cache, session=cs,
            )

            if session_status in ("completed", "failed"):
                return

            elapsed = 0
            while elapsed < MAX_WAIT_SECONDS:
                if await request.is_disconnected():
                    return

                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("data"):
                    raw = msg["data"]
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    event_data = json.loads(raw)
                    event_type = event_data.get("type")

                    if event_type == "session_complete":
                        data = await _full_refresh(session_id)
                        if data["session"]:
                            targets_cache = {t.id: t for t in data["targets"]}
                            results_cache = {r.id: r for r in data["results"]}
                            yield _build_sse_update(
                                session_id,
                                data["session"].status,
                                targets_cache,
                                results_cache,
                                session=data["session"],
                            )
                        return

                    if event_type == "target_update":
                        target_id = event_data.get("target_id")
                        if target_id:
                            async with async_session_factory() as db:
                                target, results = await session_service.fetch_target_with_results(
                                    db,
                                    target_id,
                                )
                            if target:
                                targets_cache[target.id] = target
                            for r in results:
                                results_cache[r.id] = r
                        yield _build_sse_update(
                            session_id,
                            session_status,
                            targets_cache,
                            results_cache,
                        )

                    elif event_type == "session_running":
                        # Full refresh: target resolution and session metadata
                        # (name, resource_kind, etc.) are now committed to DB.
                        data = await _full_refresh(session_id)
                        if data["session"]:
                            cs = data["session"]
                            session_status = cs.status
                            targets_cache = {t.id: t for t in data["targets"]}
                            results_cache = {r.id: r for r in data["results"]}
                        yield _build_sse_update(
                            session_id,
                            session_status,
                            targets_cache,
                            results_cache,
                            session=cs,
                        )

                    elif event_type == "targets_running":
                        target_ids = event_data.get("target_ids", [])
                        has_unknown = any(tid not in targets_cache for tid in target_ids)
                        if has_unknown:
                            data = await _full_refresh(session_id)
                            if data["session"]:
                                targets_cache = {t.id: t for t in data["targets"]}
                                results_cache = {r.id: r for r in data["results"]}
                        else:
                            for tid in target_ids:
                                targets_cache[tid].status = "running"
                        yield _build_sse_update(
                            session_id,
                            session_status,
                            targets_cache,
                            results_cache,
                        )
                else:
                    elapsed += 1
        finally:
            await pubsub.unsubscribe(f"session:{session_id}")
            await pubsub.close()

    return EventSourceResponse(event_generator())
