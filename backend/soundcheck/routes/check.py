"""Deep-link check redirect route.

Accepts query params like the old /check page and creates a session.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import DbSession
from ..schemas import CheckRedirectResponse
from ..services import session_service
from ..utils import InputValidationError, parse_check_params
from ..worker import queue

router = APIRouter(tags=["check"])


@router.get("/check", response_model=CheckRedirectResponse)
async def check_redirect(
    request: Request,
    db: DbSession,
    urls: str = Query(""),
    guid: str = Query(""),
    workshop: str = Query(""),
    pool: str = Query(""),
    type: str = Query("readyz"),
    name: str = Query(""),
    cluster: str = Query(""),
):
    """Create a session from query params and return its ID."""
    if not urls and not guid and not workshop and not pool:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one URL, GUID, Workshop GUID, or ResourcePool name",
        )

    try:
        parsed = parse_check_params(
            raw_urls=urls,
            raw_guids=guid,
            raw_ws_guids=workshop,
            raw_resource_pools=pool,
            check_type=type,
            session_name=name,
            cluster=cluster,
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

    await queue.enqueue("run_session_checks", session_id=sid, request_id=request.state.request_id, timeout=900)

    return CheckRedirectResponse(session_id=sid)
