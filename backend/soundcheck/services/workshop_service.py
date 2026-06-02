"""Workshop dashboard service — K8s fetching, caching, status derivation.

Encapsulates all logic for fetching Workshop/MultiWorkshop CRDs from
Babylon clusters, deriving lifecycle status, building dashboard items,
filtering, and in-memory caching.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from ..schemas_workshops import (
    MultiWorkshopAsset,
    MultiWorkshopDashboardItem,
    WorkshopDashboardItem,
    WorkshopStatus,
    WorkshopSummary,
)
from ..services import babylon_client
from ..services.babylon_client import get_catalog_url
from ..services.babylon_service import (
    BABYLON_GROUP,
    BABYLON_VERSION,
    MWS_PLURAL,
    RC_GROUP,
    RC_PLURAL,
    RC_VERSION,
    WORKSHOP_ID_LABEL,
    WS_PLURAL,
)

logger = logging.getLogger(__name__)

DEMO_DOMAIN = "demo.redhat.com"
WHITE_GLOVE_LABEL = f"{DEMO_DOMAIN}/white-glove"
LOCK_ENABLED_LABEL = f"{DEMO_DOMAIN}/lock-enabled"
CATALOG_ITEM_LABEL = f"{BABYLON_GROUP}/catalogItemName"
MULTIWORKSHOP_LABEL = f"{BABYLON_GROUP}/multiworkshop"
MULTIWORKSHOP_ID_LABEL = f"{BABYLON_GROUP}/multi-workshop-id"


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------


def derive_status(
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


# ---------------------------------------------------------------------------
# CRD extraction helpers
# ---------------------------------------------------------------------------


def _email_to_namespace(email: str) -> str:
    """Convert an email address to the expected Kubernetes namespace format."""
    return f"user-{email.replace('@', '-').replace('.', '-')}"


def extract_workshop_item(
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

    derived_status = derive_status(
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
    resources = status.get("resources", [])
    if resources:
        state_obj = resources[0].get("state", {})
        if state_obj.get("kind") == "AnarchySubject":
            return state_obj.get("spec", {}).get("vars", {}).get("current_state", "")
    return ""


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
    catalog_url = (
        f"{base_url}/multi-workshop/{mws_namespace}/{mws_name}"
        if base_url and mws_namespace and mws_name
        else ""
    )

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


# ---------------------------------------------------------------------------
# Cluster fetching
# ---------------------------------------------------------------------------


async def fetch_workshops_from_cluster(
    cluster: str,
) -> tuple[list[WorkshopDashboardItem], list[str]]:
    """Fetch all Workshop CRDs from a single cluster, enriched with ResourceClaim state."""
    errors: list[str] = []
    try:
        result = await babylon_client.k8s_list_cluster_wide(
            cluster, BABYLON_GROUP, BABYLON_VERSION, WS_PLURAL,
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
        for (ns, name), rc_result in zip(rc_tasks.keys(), rc_results, strict=True):
            if isinstance(rc_result, Exception):
                logger.debug("RC %s/%s not found on cluster '%s': %s", ns, name, cluster, rc_result)
            else:
                rc_index[(ns, name)] = rc_result

    rc_states: dict[str, str] = {}
    for ws_uid, (ns, name) in rc_refs.items():
        rc_def = rc_index.get((ns, name))
        if rc_def:
            rc_states[ws_uid] = _rc_summary_state(rc_def)

    items = [
        extract_workshop_item(ws, cluster, rc_states.get(ws.get("metadata", {}).get("uid", ""), ""))
        for ws in workshops
    ]
    return items, errors


async def fetch_multiworkshops_from_cluster(
    cluster: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch all MultiWorkshop CRDs from a single cluster (raw K8s objects)."""
    try:
        result = await babylon_client.k8s_list_cluster_wide(
            cluster, BABYLON_GROUP, BABYLON_VERSION, MWS_PLURAL,
        )
    except Exception as e:
        msg = f"Failed to fetch multiworkshops from cluster '{cluster}': {e}"
        logger.warning(msg)
        return [], [msg]

    items = result.get("items", [])
    for item in items:
        item.setdefault("_cluster", cluster)
    return items, []


# ---------------------------------------------------------------------------
# Caching layer
# ---------------------------------------------------------------------------

_CLUSTER_FETCH_SEM = asyncio.Semaphore(5)
_CACHE_TTL = 60  # seconds

_ws_cache: dict[str, tuple[float, str, list[WorkshopDashboardItem], list[str]]] = {}
_mws_cache: dict[str, tuple[float, str, list[dict[str, Any]], list[str]]] = {}


async def fetch_workshops_cached(
    cluster: str,
) -> tuple[list[WorkshopDashboardItem], list[str], str]:
    """Cached, concurrency-limited wrapper around fetch_workshops_from_cluster."""
    cached = _ws_cache.get(cluster)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[2], cached[3], cached[1]
    async with _CLUSTER_FETCH_SEM:
        cached = _ws_cache.get(cluster)
        if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
            return cached[2], cached[3], cached[1]
        items, errors = await fetch_workshops_from_cluster(cluster)
        wall_ts = datetime.now(UTC).isoformat()
        _ws_cache[cluster] = (time.monotonic(), wall_ts, items, errors)
        return items, errors, wall_ts


async def fetch_multiworkshops_cached(
    cluster: str,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Cached, concurrency-limited wrapper around fetch_multiworkshops_from_cluster."""
    cached = _mws_cache.get(cluster)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[2], cached[3], cached[1]
    async with _CLUSTER_FETCH_SEM:
        cached = _mws_cache.get(cluster)
        if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
            return cached[2], cached[3], cached[1]
        items, errors = await fetch_multiworkshops_from_cluster(cluster)
        wall_ts = datetime.now(UTC).isoformat()
        _mws_cache[cluster] = (time.monotonic(), wall_ts, items, errors)
        return items, errors, wall_ts


# ---------------------------------------------------------------------------
# Filtering and grouping
# ---------------------------------------------------------------------------


def group_workshops_with_multiworkshops(
    all_workshops: list[WorkshopDashboardItem],
    raw_multiworkshops: list[dict[str, Any]],
) -> tuple[list[WorkshopDashboardItem], list[MultiWorkshopDashboardItem]]:
    """Separate standalone workshops from those belonging to a MultiWorkshop.

    Returns (standalone_items, multi_workshop_items).
    """
    if not raw_multiworkshops:
        return all_workshops, []

    mws_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for mws in raw_multiworkshops:
        meta = mws.get("metadata", {})
        mws_by_key[(meta.get("namespace", ""), meta.get("name", ""))] = mws

    mws_child_names: dict[str, tuple[str, str]] = {}
    for mws in raw_multiworkshops:
        meta = mws.get("metadata", {})
        mws_ns = meta.get("namespace", "")
        mws_name = meta.get("name", "")
        for asset in mws.get("spec", {}).get("assets", []):
            child_name = asset.get("name", "")
            if child_name:
                mws_child_names[child_name] = (mws_ns, mws_name)

    standalone: list[WorkshopDashboardItem] = []
    children_by_parent: dict[tuple[str, str], list[WorkshopDashboardItem]] = {}

    for ws in all_workshops:
        parent_key = mws_child_names.get(ws.name)
        if parent_key:
            children_by_parent.setdefault(parent_key, []).append(ws)
        else:
            standalone.append(ws)

    multi_workshops: list[MultiWorkshopDashboardItem] = []
    for key, mws_def in mws_by_key.items():
        cluster = mws_def.get("_cluster", "")
        children = children_by_parent.get(key, [])
        multi_workshops.append(_build_multi_workshop_item(mws_def, cluster, children))

    return standalone, multi_workshops


def matches_filters(
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


def build_summary(items: list[WorkshopDashboardItem]) -> WorkshopSummary:
    """Compute aggregated counts from filtered items."""
    summary = WorkshopSummary(
        total=len(items),
        scheduled=0, provisioning=0, running=0,
        stopped=0, degraded=0, failed=0, completed=0,
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
