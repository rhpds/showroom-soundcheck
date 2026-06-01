"""Workshop dashboard API routes.

Provides real-time visibility into Workshop CRDs across all configured
Babylon clusters, with filtering by cluster, status, white-glove, and
time window.

Unlike session/group routes that use SSE streaming via Redis Pub/Sub,
this module serves workshop data via standard request/response because
it reads directly from Kubernetes APIs rather than from SAQ-driven DB
state.  A caching layer should be added before heavy multi-user usage.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..database import DbSession
from ..services import babylon_client
from ..services.babylon_client import get_catalog_url
from ..services.babylon_service import (
    BABYLON_GROUP,
    BABYLON_VERSION,
    MWS_PLURAL,
    RC_GROUP,
    RC_VERSION,
    RC_PLURAL,
    WORKSHOP_ID_LABEL,
    WS_PLURAL,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["workshops"])

DEMO_DOMAIN = "demo.redhat.com"
WHITE_GLOVE_LABEL = f"{DEMO_DOMAIN}/white-glove"
LOCK_ENABLED_LABEL = f"{DEMO_DOMAIN}/lock-enabled"
CATALOG_ITEM_LABEL = f"{BABYLON_GROUP}/catalogItemName"
MULTIWORKSHOP_LABEL = f"{BABYLON_GROUP}/multiworkshop"
MULTIWORKSHOP_ID_LABEL = f"{BABYLON_GROUP}/multi-workshop-id"

WorkshopStatus = Literal[
    "scheduled", "provisioning", "running", "stopped", "degraded", "failed", "completed", "unknown"
]


class WorkshopDashboardItem(BaseModel):
    """Single workshop entry for the dashboard."""

    name: str
    namespace: str
    display_name: str
    cluster: str
    catalog_item: str
    requester: str
    ordered_by: str
    workshop_id: str
    workshop_url: str
    catalog_url: str

    status: WorkshopStatus

    lifespan_start: str
    lifespan_end: str
    ready_by: str
    action_start: str
    action_stop: str

    provision_ordered: int
    provision_active: int
    provision_failed: int
    provision_retries: int

    users_assigned: int
    users_available: int
    users_total: int

    white_glove: bool
    demo_team_provisioned: bool
    locked: bool
    disable_auto_stop: bool
    open_registration: bool
    access_password_set: bool


class WorkshopSummary(BaseModel):
    """Aggregated workshop counts for summary cards."""

    total: int
    scheduled: int
    provisioning: int
    running: int
    stopped: int
    degraded: int
    failed: int
    completed: int


class MultiWorkshopAsset(BaseModel):
    """Single asset entry within a MultiWorkshop."""

    display_name: str
    key: str
    workshop_id: str
    name: str
    namespace: str


class MultiWorkshopDashboardItem(BaseModel):
    """A multi-asset workshop (event) grouping multiple child workshops."""

    name: str
    namespace: str
    display_name: str
    cluster: str
    multi_workshop_id: str
    catalog_url: str
    requester: str
    ordered_by: str
    purpose: str
    number_seats: int
    start_date: str
    end_date: str
    status: WorkshopStatus
    assets: list[MultiWorkshopAsset]
    children: list[WorkshopDashboardItem]

    provision_ordered: int
    provision_active: int
    provision_failed: int
    users_assigned: int
    users_total: int


class WorkshopListResponse(BaseModel):
    """Response for GET /api/workshops."""

    items: list[WorkshopDashboardItem]
    multi_workshops: list[MultiWorkshopDashboardItem]
    summary: WorkshopSummary
    cluster_errors: list[str] = []
    fetched_at: str = ""


def _derive_status(
    lifespan_start: str,
    lifespan_end: str,
    provision_ordered: int,
    provision_active: int,
    provision_failed: int,
    provision_disabled: bool,
    resource_claim_state: str,
) -> WorkshopStatus:
    """Derive workshop lifecycle status from provision counts, lifespan, and ResourceClaim state."""
    now = datetime.now(UTC)

    if lifespan_end:
        try:
            end_dt = datetime.fromisoformat(lifespan_end.replace("Z", "+00:00"))
            if end_dt < now:
                return "completed"
        except (ValueError, TypeError):
            pass

    if lifespan_start:
        try:
            start_dt = datetime.fromisoformat(lifespan_start.replace("Z", "+00:00"))
            if start_dt > now:
                return "scheduled"
        except (ValueError, TypeError):
            pass

    # ResourceClaim summary.state is the authoritative source for environment state
    rc_state = resource_claim_state.lower().replace(" ", "-") if resource_claim_state else ""
    if rc_state in ("started", "running", "available"):
        return "running"
    if rc_state in ("stopped", "stop-pending", "stopping"):
        return "stopped"
    if rc_state in ("provision-failed", "failed", "stop-error"):
        return "failed"

    if provision_disabled and provision_active == 0:
        return "stopped"

    if provision_ordered > 0 and provision_active >= provision_ordered:
        return "running"
    if provision_failed > 0 and provision_active == 0:
        return "failed"
    if provision_failed > 0 and provision_active < provision_ordered:
        return "degraded"
    if provision_ordered > 0:
        return "provisioning"

    return "unknown"


def _email_to_namespace(email: str) -> str:
    """Convert an email address to the expected Kubernetes namespace format."""
    return f"user-{email.replace('@', '-').replace('.', '-')}"


def _extract_workshop_item(
    ws_def: dict[str, Any], cluster: str, resource_claim_state: str = ""
) -> WorkshopDashboardItem:
    """Transform a raw Workshop CRD into a dashboard item."""
    meta = ws_def.get("metadata", {})
    spec = ws_def.get("spec", {})
    status = ws_def.get("status", {})
    labels = meta.get("labels", {})
    annotations = meta.get("annotations", {})

    lifespan = spec.get("lifespan", {})
    action_schedule = spec.get("actionSchedule", {})
    provision_count = status.get("provisionCount", {})
    user_count = status.get("userCount", {})

    lifespan_start = lifespan.get("start", "")
    lifespan_end = lifespan.get("end", "")
    provision_ordered = provision_count.get("ordered", 0)
    provision_active = provision_count.get("active", 0)
    provision_failed = provision_count.get("failed", 0)
    provision_disabled = spec.get("provisionDisabled", False)

    derived_status = _derive_status(
        lifespan_start, lifespan_end, provision_ordered, provision_active, provision_failed,
        provision_disabled, resource_claim_state,
    )

    SIX_MONTHS_S = 6 * 30 * 24 * 3600
    action_stop_raw = action_schedule.get("stop", "")
    disable_auto_stop = True
    if action_stop_raw:
        try:
            stop_dt = datetime.fromisoformat(action_stop_raw.replace("Z", "+00:00"))
            disable_auto_stop = (stop_dt - datetime.now(UTC)).total_seconds() > SIX_MONTHS_S
        except (ValueError, TypeError):
            pass

    ws_name = meta.get("name", "")
    ws_namespace = meta.get("namespace", "")
    base_url = get_catalog_url(cluster)
    catalog_url = f"{base_url}/workshops/{ws_namespace}/{ws_name}" if base_url and ws_namespace and ws_name else ""

    return WorkshopDashboardItem(
        name=ws_name,
        namespace=ws_namespace,
        display_name=spec.get("displayName", "") or ws_name,
        cluster=cluster,
        catalog_item=labels.get(CATALOG_ITEM_LABEL, ""),
        requester=annotations.get(f"{DEMO_DOMAIN}/requester", ""),
        ordered_by=annotations.get(f"{DEMO_DOMAIN}/orderedBy", ""),
        workshop_id=labels.get(WORKSHOP_ID_LABEL, ""),
        workshop_url=status.get("workshopURL", ""),
        catalog_url=catalog_url,
        status=derived_status,
        lifespan_start=lifespan_start,
        lifespan_end=lifespan_end,
        ready_by=lifespan.get("readyBy", ""),
        action_start=action_schedule.get("start", ""),
        action_stop=action_schedule.get("stop", ""),
        provision_ordered=provision_ordered,
        provision_active=provision_active,
        provision_failed=provision_failed,
        provision_retries=provision_count.get("retries", 0),
        users_assigned=user_count.get("assigned", 0),
        users_available=user_count.get("available", 0),
        users_total=user_count.get("total", 0),
        white_glove=labels.get(WHITE_GLOVE_LABEL, "false").lower() == "true",
        demo_team_provisioned=(
            bool(annotations.get(f"{DEMO_DOMAIN}/orderedBy", ""))
            and _email_to_namespace(annotations.get(f"{DEMO_DOMAIN}/orderedBy", "")) != ws_namespace
        ),
        locked=labels.get(LOCK_ENABLED_LABEL, "false").lower() == "true",
        disable_auto_stop=disable_auto_stop,
        open_registration=spec.get("openRegistration", False),
        access_password_set=bool(spec.get("accessPassword")),
    )


def _get_owner_rc(ws_def: dict[str, Any]) -> tuple[str, str]:
    """Extract the owning ResourceClaim (namespace, name) from a Workshop."""
    meta = ws_def.get("metadata", {})
    ns = meta.get("namespace", "")
    for owner in meta.get("ownerReferences", []):
        if owner.get("kind") == "ResourceClaim":
            return (ns, owner.get("name", ""))
    return ("", "")


def _rc_summary_state(rc_def: dict[str, Any]) -> str:
    """Extract summary.state from a ResourceClaim, falling back to resource current_state."""
    status = rc_def.get("status", {})
    summary = status.get("summary", {})
    if summary.get("state"):
        return summary["state"]
    # Fallback: check first resource's AnarchySubject current_state
    resources = status.get("resources", [])
    if resources:
        state_obj = resources[0].get("state", {})
        if state_obj.get("kind") == "AnarchySubject":
            return state_obj.get("spec", {}).get("vars", {}).get("current_state", "")
    return ""


async def _fetch_workshops_from_cluster(
    cluster: str,
) -> tuple[list[WorkshopDashboardItem], list[str]]:
    """Fetch all Workshop CRDs from a single cluster, enriched with ResourceClaim state."""
    errors: list[str] = []
    try:
        result = await babylon_client.k8s_list_cluster_wide(
            cluster,
            BABYLON_GROUP,
            BABYLON_VERSION,
            WS_PLURAL,
        )
    except Exception as e:
        msg = f"Failed to fetch workshops from cluster '{cluster}': {e}"
        logger.warning(msg)
        return [], [msg]

    workshops = result.get("items", [])
    if not workshops:
        return [], []

    rc_refs: dict[str, tuple[str, str]] = {}
    for ws in workshops:
        ws_uid = ws.get("metadata", {}).get("uid", "")
        ns, name = _get_owner_rc(ws)
        if ns and name:
            rc_refs[ws_uid] = (ns, name)

    # Fetch only the specific ResourceClaims referenced by workshops rather than
    # listing every RC cluster-wide (which can be thousands of objects).
    unique_rc_keys = set(rc_refs.values())
    rc_index: dict[tuple[str, str], dict] = {}
    if unique_rc_keys:
        rc_tasks = {
            (ns, name): babylon_client.k8s_get_resource(
                cluster, RC_GROUP, RC_VERSION, RC_PLURAL, ns, name,
            )
            for ns, name in unique_rc_keys
        }
        rc_results = await asyncio.gather(*rc_tasks.values(), return_exceptions=True)
        for (ns, name), result in zip(rc_tasks.keys(), rc_results, strict=True):
            if isinstance(result, Exception):
                logger.debug("RC %s/%s not found on cluster '%s': %s", ns, name, cluster, result)
            else:
                rc_index[(ns, name)] = result

    rc_states: dict[str, str] = {}
    for ws_uid, (ns, name) in rc_refs.items():
        rc_def = rc_index.get((ns, name))
        if rc_def:
            rc_states[ws_uid] = _rc_summary_state(rc_def)

    items = [
        _extract_workshop_item(ws, cluster, rc_states.get(ws.get("metadata", {}).get("uid", ""), ""))
        for ws in workshops
    ]
    return items, errors


async def _fetch_multiworkshops_from_cluster(
    cluster: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch all MultiWorkshop CRDs from a single cluster (raw K8s objects)."""
    try:
        result = await babylon_client.k8s_list_cluster_wide(
            cluster,
            BABYLON_GROUP,
            BABYLON_VERSION,
            MWS_PLURAL,
        )
    except Exception as e:
        msg = f"Failed to fetch multiworkshops from cluster '{cluster}': {e}"
        logger.warning(msg)
        return [], [msg]

    items = result.get("items", [])
    for item in items:
        item.setdefault("_cluster", cluster)
    return items, []


def _derive_multi_workshop_status(
    start_date: str,
    end_date: str,
    children: list[WorkshopDashboardItem],
) -> WorkshopStatus:
    """Derive aggregated status for a MultiWorkshop from its dates and child statuses."""
    now = datetime.now(UTC)

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_dt < now:
                return "completed"
        except (ValueError, TypeError):
            pass

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            if start_dt > now:
                return "scheduled"
        except (ValueError, TypeError):
            pass

    if not children:
        return "unknown"

    child_statuses = {c.status for c in children}

    if child_statuses == {"running"}:
        return "running"
    if "failed" in child_statuses and all(s in ("failed", "degraded") for s in child_statuses):
        return "failed"
    if "failed" in child_statuses or "degraded" in child_statuses:
        return "degraded"
    if "provisioning" in child_statuses:
        return "provisioning"
    if "stopped" in child_statuses and "running" not in child_statuses:
        return "stopped"
    if "running" in child_statuses:
        return "running"

    return "unknown"


def _build_multi_workshop_item(
    mws_def: dict[str, Any],
    cluster: str,
    children: list[WorkshopDashboardItem],
) -> MultiWorkshopDashboardItem:
    """Transform a raw MultiWorkshop CRD + matched children into a dashboard item."""
    meta = mws_def.get("metadata", {})
    spec = mws_def.get("spec", {})
    labels = meta.get("labels", {})
    annotations = meta.get("annotations", {})

    start_date = spec.get("startDate", "")
    end_date = spec.get("endDate", "")

    assets = [
        MultiWorkshopAsset(
            display_name=a.get("displayName", ""),
            key=a.get("key", ""),
            workshop_id=a.get("workshopId", ""),
            name=a.get("name", ""),
            namespace=a.get("namespace", ""),
        )
        for a in spec.get("assets", [])
    ]

    status = _derive_multi_workshop_status(start_date, end_date, children)

    mws_name = meta.get("name", "")
    mws_namespace = meta.get("namespace", "")
    base_url = get_catalog_url(cluster)
    catalog_url = f"{base_url}/multi-workshop/{mws_namespace}/{mws_name}" if base_url and mws_namespace and mws_name else ""

    return MultiWorkshopDashboardItem(
        name=mws_name,
        namespace=mws_namespace,
        display_name=spec.get("displayName", "") or spec.get("name", "") or mws_name,
        cluster=cluster,
        multi_workshop_id=labels.get(MULTIWORKSHOP_ID_LABEL, ""),
        catalog_url=catalog_url,
        requester=annotations.get(f"{DEMO_DOMAIN}/requester", ""),
        ordered_by=annotations.get(f"{DEMO_DOMAIN}/orderedBy", annotations.get("demo.redhat.com/orderedBy", "")),
        purpose=spec.get("purpose", ""),
        number_seats=spec.get("numberSeats", 0),
        start_date=start_date,
        end_date=end_date,
        status=status,
        assets=assets,
        children=children,
        provision_ordered=sum(c.provision_ordered for c in children),
        provision_active=sum(c.provision_active for c in children),
        provision_failed=sum(c.provision_failed for c in children),
        users_assigned=sum(c.users_assigned for c in children),
        users_total=sum(c.users_total for c in children),
    )


def _group_workshops_with_multiworkshops(
    all_workshops: list[WorkshopDashboardItem],
    raw_multiworkshops: list[dict[str, Any]],
) -> tuple[list[WorkshopDashboardItem], list[MultiWorkshopDashboardItem]]:
    """Separate standalone workshops from those belonging to a MultiWorkshop.

    Returns (standalone_items, multi_workshop_items).
    """
    if not raw_multiworkshops:
        return all_workshops, []

    # Build a lookup: (namespace, multiworkshop-name) → raw MWS definition
    mws_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for mws in raw_multiworkshops:
        meta = mws.get("metadata", {})
        mws_by_key[(meta.get("namespace", ""), meta.get("name", ""))] = mws

    # Build a set of workshop names that belong to any MultiWorkshop (via assets)
    mws_child_names: dict[str, tuple[str, str]] = {}  # child ws name → (mws ns, mws name)
    for mws in raw_multiworkshops:
        meta = mws.get("metadata", {})
        mws_ns = meta.get("namespace", "")
        mws_name = meta.get("name", "")
        for asset in mws.get("spec", {}).get("assets", []):
            child_name = asset.get("name", "")
            if child_name:
                mws_child_names[child_name] = (mws_ns, mws_name)

    # Partition workshops into standalone vs grouped-by-parent
    standalone: list[WorkshopDashboardItem] = []
    children_by_parent: dict[tuple[str, str], list[WorkshopDashboardItem]] = {}

    for ws in all_workshops:
        parent_key = mws_child_names.get(ws.name)
        if parent_key:
            children_by_parent.setdefault(parent_key, []).append(ws)
        else:
            standalone.append(ws)

    # Build MultiWorkshopDashboardItem objects
    multi_workshops: list[MultiWorkshopDashboardItem] = []
    for key, mws_def in mws_by_key.items():
        cluster = mws_def.get("_cluster", "")
        children = children_by_parent.get(key, [])
        multi_workshops.append(_build_multi_workshop_item(mws_def, cluster, children))

    return standalone, multi_workshops


def _matches_filters(
    item: WorkshopDashboardItem,
    clusters: list[str] | None,
    statuses: list[str] | None,
    white_glove: str | None,
    provision_type: str | None,
    has_failures: bool,
    from_time: str | None,
    to_time: str | None,
) -> bool:
    """Apply client-requested filters to a workshop item."""
    if clusters and item.cluster not in clusters:
        return False

    if statuses and item.status not in statuses:
        return False

    if white_glove == "true" and not item.white_glove:
        return False

    if provision_type == "self_service" and item.demo_team_provisioned:
        return False
    if provision_type == "demo_team" and not item.demo_team_provisioned:
        return False

    if has_failures and item.provision_failed == 0:
        return False

    if from_time:
        try:
            from_dt = datetime.fromisoformat(from_time.replace("Z", "+00:00"))
            if item.lifespan_end:
                end_dt = datetime.fromisoformat(item.lifespan_end.replace("Z", "+00:00"))
                if end_dt < from_dt:
                    return False
        except (ValueError, TypeError):
            pass

    if to_time:
        try:
            to_dt = datetime.fromisoformat(to_time.replace("Z", "+00:00"))
            if item.lifespan_start:
                start_dt = datetime.fromisoformat(item.lifespan_start.replace("Z", "+00:00"))
                if start_dt > to_dt:
                    return False
        except (ValueError, TypeError):
            pass

    return True


def _build_summary(items: list[WorkshopDashboardItem]) -> WorkshopSummary:
    """Compute aggregated counts from filtered items."""
    summary = WorkshopSummary(
        total=len(items),
        scheduled=0,
        provisioning=0,
        running=0,
        stopped=0,
        degraded=0,
        failed=0,
        completed=0,
    )
    for item in items:
        if item.status == "scheduled":
            summary.scheduled += 1
        elif item.status == "provisioning":
            summary.provisioning += 1
        elif item.status == "running":
            summary.running += 1
        elif item.status == "stopped":
            summary.stopped += 1
        elif item.status == "degraded":
            summary.degraded += 1
        elif item.status == "failed":
            summary.failed += 1
        elif item.status == "completed":
            summary.completed += 1
    return summary


_CLUSTER_FETCH_SEM = asyncio.Semaphore(5)
_CACHE_TTL = 60  # seconds

_ws_cache: dict[str, tuple[float, str, list[WorkshopDashboardItem], list[str]]] = {}
_mws_cache: dict[str, tuple[float, str, list[dict[str, Any]], list[str]]] = {}


async def _fetch_workshops_bounded(
    cluster: str,
) -> tuple[list[WorkshopDashboardItem], list[str], str]:
    """Cached, concurrency-limited wrapper around _fetch_workshops_from_cluster."""
    cached = _ws_cache.get(cluster)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[2], cached[3], cached[1]
    async with _CLUSTER_FETCH_SEM:
        cached = _ws_cache.get(cluster)
        if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
            return cached[2], cached[3], cached[1]
        items, errors = await _fetch_workshops_from_cluster(cluster)
        wall_ts = datetime.now(UTC).isoformat()
        _ws_cache[cluster] = (time.monotonic(), wall_ts, items, errors)
        return items, errors, wall_ts


async def _fetch_multiworkshops_bounded(
    cluster: str,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Cached, concurrency-limited wrapper around _fetch_multiworkshops_from_cluster."""
    cached = _mws_cache.get(cluster)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[2], cached[3], cached[1]
    async with _CLUSTER_FETCH_SEM:
        cached = _mws_cache.get(cluster)
        if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
            return cached[2], cached[3], cached[1]
        items, errors = await _fetch_multiworkshops_from_cluster(cluster)
        wall_ts = datetime.now(UTC).isoformat()
        _mws_cache[cluster] = (time.monotonic(), wall_ts, items, errors)
        return items, errors, wall_ts


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

    ws_tasks = [_fetch_workshops_bounded(c) for c in target_clusters]
    mws_tasks = [_fetch_multiworkshops_bounded(c) for c in target_clusters]
    all_results = await asyncio.gather(*ws_tasks, *mws_tasks)

    all_items: list[WorkshopDashboardItem] = []
    all_errors: list[str] = []
    all_fetched_at: list[str] = []
    for cluster_items, cluster_errors, cluster_ts in all_results[: len(target_clusters)]:
        all_items.extend(cluster_items)
        all_errors.extend(cluster_errors)
        if cluster_ts:
            all_fetched_at.append(cluster_ts)

    raw_multiworkshops: list[dict[str, Any]] = []
    for cluster_mws, cluster_errors, cluster_ts in all_results[len(target_clusters) :]:
        raw_multiworkshops.extend(cluster_mws)
        all_errors.extend(cluster_errors)
        if cluster_ts:
            all_fetched_at.append(cluster_ts)

    standalone, multi_workshops = _group_workshops_with_multiworkshops(all_items, raw_multiworkshops)

    filtered_standalone = [
        item
        for item in standalone
        if _matches_filters(item, cluster, status, white_glove, provision_type, has_failures, from_time, to_time)
    ]

    filtered_multi: list[MultiWorkshopDashboardItem] = []
    for mws in multi_workshops:
        matching_children = [
            child
            for child in mws.children
            if _matches_filters(child, cluster, status, white_glove, provision_type, has_failures, from_time, to_time)
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
    summary = _build_summary(all_filtered_workshops)

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
        *[_fetch_workshops_bounded(c) for c in configured_clusters]
    )

    all_items: list[WorkshopDashboardItem] = []
    for cluster_items, _, _ in cluster_results:
        all_items.extend(cluster_items)

    return _build_summary(all_items)


# ---------------------------------------------------------------------------
# Check-status lookup (DB-backed)
# ---------------------------------------------------------------------------


class WorkshopCheckStatusRequest(BaseModel):
    """Request body for batch check-status lookup."""

    workshop_ids: list[str] = Field(max_length=200)


class WorkshopCheckStatusEntry(BaseModel):
    """Last check session info for a single workshop."""

    status: str
    session_id: str
    created_at: str


class WorkshopCheckStatusResponse(BaseModel):
    """Response for POST /api/workshops/check-status."""

    statuses: dict[str, WorkshopCheckStatusEntry | None]


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
