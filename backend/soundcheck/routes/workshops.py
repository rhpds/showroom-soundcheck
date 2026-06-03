"""Workshop dashboard API routes.

Thin route handlers that delegate to the workshop service for K8s
fetching, caching, status derivation, and filtering.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from ..database import DbSession
from ..schemas_workshops import (
    MultiWorkshopDashboardItem,
    WorkshopCheckStatusEntry,
    WorkshopCheckStatusRequest,
    WorkshopCheckStatusResponse,
    WorkshopDashboardItem,
    WorkshopListResponse,
    WorkshopSummary,
)
from ..services import babylon_client
from ..services.workshop_service import (
    build_summary,
    fetch_multiworkshops_cached,
    fetch_workshops_cached,
    group_workshops_with_multiworkshops,
    matches_filters,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["workshops"])


@router.get("", response_model=WorkshopListResponse)
async def list_workshops(
    cluster: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    white_glove: str | None = Query(default=None),
    provision_type: str | None = Query(default=None),
    has_failures: bool = Query(default=False),
    from_time: str | None = Query(default=None),
    to_time: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all workshops across configured clusters with optional filtering."""
    configured_clusters = babylon_client.get_configured_clusters()
    if not configured_clusters:
        return WorkshopListResponse(
            items=[],
            multi_workshops=[],
            summary=WorkshopSummary(
                total=0, scheduled=0, provisioning=0, running=0, stopped=0, degraded=0, failed=0, completed=0
            ),
        )

    target_clusters = configured_clusters
    if cluster:
        target_clusters = [c for c in configured_clusters if c in cluster]

    ws_tasks = [fetch_workshops_cached(c) for c in target_clusters]
    mws_tasks = [fetch_multiworkshops_cached(c) for c in target_clusters]
    all_results = await asyncio.gather(*ws_tasks, *mws_tasks, return_exceptions=True)

    all_items: list[WorkshopDashboardItem] = []
    all_errors: list[str] = []
    all_fetched_at: list[str] = []
    for i, result in enumerate(all_results[: len(target_clusters)]):
        if isinstance(result, BaseException):
            logger.warning("Workshop fetch failed for cluster '%s': %s", target_clusters[i], result)
            all_errors.append(f"Cluster '{target_clusters[i]}' fetch failed: {result}")
            continue
        cluster_items, cluster_errors, cluster_ts = result
        all_items.extend(cluster_items)
        all_errors.extend(cluster_errors)
        if cluster_ts:
            all_fetched_at.append(cluster_ts)

    raw_multiworkshops: list[dict[str, Any]] = []
    for i, result in enumerate(all_results[len(target_clusters):]):
        if isinstance(result, BaseException):
            logger.warning("MultiWorkshop fetch failed for cluster '%s': %s", target_clusters[i], result)
            all_errors.append(f"Cluster '{target_clusters[i]}' multiworkshop fetch failed: {result}")
            continue
        cluster_mws, cluster_errors, cluster_ts = result
        raw_multiworkshops.extend(cluster_mws)
        all_errors.extend(cluster_errors)
        if cluster_ts:
            all_fetched_at.append(cluster_ts)

    standalone, multi_workshops = group_workshops_with_multiworkshops(all_items, raw_multiworkshops)

    filtered_standalone = [
        item
        for item in standalone
        if matches_filters(item, cluster, status, white_glove, provision_type, has_failures, from_time, to_time)
    ]

    filtered_multi: list[MultiWorkshopDashboardItem] = []
    for mws in multi_workshops:
        matching_children = [
            child
            for child in mws.children
            if matches_filters(child, cluster, status, white_glove, provision_type, has_failures, from_time, to_time)
        ]
        if matching_children:
            filtered_multi.append(mws.model_copy(update={
                "children": matching_children,
                "provision_ordered": sum(c.provision_ordered for c in matching_children),
                "provision_active": sum(c.provision_active for c in matching_children),
                "provision_failed": sum(c.provision_failed for c in matching_children),
                "users_assigned": sum(c.users_assigned for c in matching_children),
                "users_total": sum(c.users_total for c in matching_children),
            }))

    filtered_standalone.sort(key=lambda w: w.lifespan_start or "", reverse=True)
    filtered_multi.sort(key=lambda m: m.start_date or "", reverse=True)

    all_filtered_workshops = list(filtered_standalone)
    for mws in filtered_multi:
        all_filtered_workshops.extend(mws.children)
    summary = build_summary(all_filtered_workshops)

    paginated = filtered_standalone[offset:offset + limit]
    fetched_at = min(all_fetched_at) if all_fetched_at else ""
    return WorkshopListResponse(
        items=paginated, multi_workshops=filtered_multi, summary=summary,
        cluster_errors=all_errors, fetched_at=fetched_at,
    )


@router.get("/summary", response_model=WorkshopSummary)
async def workshops_summary():
    """Return aggregated workshop counts across all clusters (unfiltered)."""
    configured_clusters = babylon_client.get_configured_clusters()
    if not configured_clusters:
        return WorkshopSummary(
            total=0, scheduled=0, provisioning=0, running=0, stopped=0, degraded=0, failed=0, completed=0
        )

    cluster_results = await asyncio.gather(
        *[fetch_workshops_cached(c) for c in configured_clusters],
        return_exceptions=True,
    )

    all_items: list[WorkshopDashboardItem] = []
    for result in cluster_results:
        if isinstance(result, BaseException):
            continue
        cluster_items, _, _ = result
        all_items.extend(cluster_items)

    return build_summary(all_items)


# ---------------------------------------------------------------------------
# Check-status lookup (DB-backed)
# ---------------------------------------------------------------------------

_CHECK_STATUS_QUERY = text("""
    SELECT DISTINCT ON (elem.value)
        elem.value AS workshop_id,
        s.session_id,
        s.status,
        s.created_at
    FROM sessions s,
        json_array_elements_text(s.source_workshop_guids) AS elem
    WHERE elem.value = ANY(:workshop_ids)
    ORDER BY elem.value, s.created_at DESC
""")


@router.post("/check-status", response_model=WorkshopCheckStatusResponse)
async def workshop_check_status(body: WorkshopCheckStatusRequest, db: DbSession):
    """Look up the most recent check session for each workshop ID."""
    workshop_ids = [wid for wid in body.workshop_ids if wid]
    if not workshop_ids:
        return WorkshopCheckStatusResponse(statuses={})

    result = await db.execute(_CHECK_STATUS_QUERY, {"workshop_ids": workshop_ids})
    rows = result.all()

    statuses: dict[str, WorkshopCheckStatusEntry | None] = {}
    for row in rows:
        statuses[row.workshop_id] = WorkshopCheckStatusEntry(
            status=row.status,
            session_id=row.session_id,
            created_at=row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
        )

    for wid in workshop_ids:
        statuses.setdefault(wid, None)

    return WorkshopCheckStatusResponse(statuses=statuses)
