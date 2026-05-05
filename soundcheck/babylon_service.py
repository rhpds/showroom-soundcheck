"""Babylon GUID resolution service.

Stateless functions that resolve Babylon GUIDs to showroom URLs by querying
Kubernetes API servers.  Searches across all configured clusters for
ResourceClaims, Workshops, and MultiWorkshops matching the given GUID.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from . import babylon_client

logger = logging.getLogger(__name__)

RC_GROUP = "poolboy.gpte.redhat.com"
RC_VERSION = "v1"
RC_PLURAL = "resourceclaims"

BABYLON_GROUP = "babylon.gpte.redhat.com"
BABYLON_VERSION = "v1"
WS_PLURAL = "workshops"

LAB_UI_URL_KEYS = (
    "showroom_primary_view_url",
    "bookbag_url",
    "lab_ui_url",
    "labUserInterfaceUrl",
)
LAB_UI_URL_ANNOTATION = f"{BABYLON_GROUP}/labUserInterfaceUrl"
LAB_UI_URLS_ANNOTATION = f"{BABYLON_GROUP}/labUserInterfaceUrls"


def extract_showroom_urls(rc_def: dict[str, Any]) -> list[dict[str, str]]:
    """Extract showroom/lab UI URLs from a ResourceClaim definition."""
    urls: list[dict[str, str]] = []
    seen: set[str] = set()
    annotations = rc_def.get("metadata", {}).get("annotations", {})
    rc_name = rc_def.get("metadata", {}).get("name", "unknown")

    for resource in rc_def.get("status", {}).get("resources", []):
        state = resource.get("state")
        if not state or state.get("kind") != "AnarchySubject":
            continue

        provision_data = state.get("spec", {}).get("vars", {}).get("provision_data", {})

        for key in LAB_UI_URL_KEYS:
            url = provision_data.get(key)
            if url and url not in seen:
                seen.add(url)
                urls.append({"url": url, "label": f"{rc_name}"})
                break

        users = provision_data.get("users", {})
        if isinstance(users, dict):
            for username, user_data in users.items():
                if not isinstance(user_data, dict):
                    continue
                for key in LAB_UI_URL_KEYS:
                    url = user_data.get(key)
                    if url and url not in seen:
                        seen.add(url)
                        urls.append({"url": url, "label": f"{rc_name}/{username}"})
                        break

    ann_url = annotations.get(LAB_UI_URL_ANNOTATION)
    if ann_url and ann_url not in seen:
        seen.add(ann_url)
        urls.append({"url": ann_url, "label": f"{rc_name} (annotation)"})

    ann_urls_raw = annotations.get(LAB_UI_URLS_ANNOTATION)
    if ann_urls_raw:
        try:
            ann_urls = json.loads(ann_urls_raw)
            if isinstance(ann_urls, dict):
                for username, url in ann_urls.items():
                    if url and url not in seen:
                        seen.add(url)
                        urls.append({"url": url, "label": f"{rc_name}/{username} (annotation)"})
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse %s annotation on RC %s", LAB_UI_URLS_ANNOTATION, rc_name)

    return urls


def _extract_rc_guid(rc_def: dict[str, Any]) -> str:
    """Extract the provision GUID from a ResourceClaim, or return empty string."""
    for resource in rc_def.get("status", {}).get("resources", []):
        state = resource.get("state")
        if not state:
            continue
        spec_vars = state.get("spec", {}).get("vars", {})
        guid = spec_vars.get("job_vars", {}).get("guid") or spec_vars.get("provision_data", {}).get("guid")
        if guid:
            return guid
    return ""


def get_rc_provision_status(rc_def: dict[str, Any]) -> str:
    """Derive a human-readable provision status from a ResourceClaim's status fields.

    Poolboy ResourceClaims don't have a single phase string. Instead we inspect
    ``status.resourceHandle``, ``status.ready``, ``status.healthy``,
    ``status.lifespan``, and AnarchySubject ``current_state`` to infer a
    lifecycle stage.
    """
    status = rc_def.get("status", {})

    # Check AnarchySubject current_state for failure indicators
    for resource in status.get("resources", []):
        state = resource.get("state")
        if not state:
            continue
        current_state = state.get("spec", {}).get("vars", {}).get("current_state", "")
        if "failed" in current_state.lower() or "error" in current_state.lower():
            return "provision-failed"

    # Check summary state if present
    summary_state = status.get("summary", {}).get("state", "")
    if "failed" in summary_state.lower() or "error" in summary_state.lower():
        return "provision-failed"

    handle = status.get("resourceHandle")
    if handle and handle.get("detached"):
        return "destroying"

    lifespan = status.get("lifespan", {})
    end_raw = lifespan.get("end")
    if end_raw:
        try:
            end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            if end_dt < datetime.now(timezone.utc):
                return "destroying"
        except (ValueError, TypeError):
            pass

    if not handle:
        return "provisioning"

    if status.get("ready") is True:
        return "ready"

    return "provisioning"


def _rc_matches_guid(rc_def: dict[str, Any], guid: str) -> bool:
    """Check if a ResourceClaim matches a GUID."""
    for resource in rc_def.get("status", {}).get("resources", []):
        state = resource.get("state")
        if not state:
            continue
        spec_vars = state.get("spec", {}).get("vars", {})
        job_vars = spec_vars.get("job_vars", {})
        provision_data = spec_vars.get("provision_data", {})

        if job_vars.get("guid") == guid:
            return True
        if provision_data.get("guid") == guid:
            return True

    return False


async def _search_cluster_for_rc_guid(
    cluster: str, guid: str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Search a single cluster for ResourceClaims matching a GUID.

    When a matching RC has no showroom URLs yet (e.g. still provisioning),
    a placeholder entry is returned with ``url=""`` and a ``provision_status``.
    """
    urls: list[dict[str, str]] = []
    try:
        result = await babylon_client.k8s_list_cluster_wide(
            cluster, RC_GROUP, RC_VERSION, RC_PLURAL,
        )
        for item in result.get("items", []):
            if _rc_matches_guid(item, guid):
                found = extract_showroom_urls(item)
                if found:
                    urls.extend(found)
                else:
                    rc_name = item.get("metadata", {}).get("name", "unknown")
                    provision_status = get_rc_provision_status(item)
                    urls.append({
                        "url": "",
                        "label": rc_name,
                        "provision_status": provision_status,
                    })
    except Exception as e:
        msg = f"Cluster '{cluster}' ResourceClaim lookup failed for GUID '{guid}': {e}"
        logger.warning(msg)
        return [], [msg]
    return urls, []


WORKSHOP_ID_LABEL = f"{BABYLON_GROUP}/workshop-id"


def _resolution_error_entry(guid: str, errors: list[str]) -> dict[str, str]:
    detail = "; ".join(errors)[:500]
    return {
        "url": "",
        "label": guid,
        "resolution_error": detail,
    }


async def _search_cluster_for_workshop_guid(
    cluster: str, guid: str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Search a cluster for Workshops whose workshop-id label matches the GUID.

    When a Workshop is found, fetches each ResourceClaim listed in
    ``status.resourceClaims`` and extracts showroom URLs from them.
    """
    urls: list[dict[str, str]] = []
    errors: list[str] = []
    try:
        result = await babylon_client.k8s_list_cluster_wide(
            cluster, BABYLON_GROUP, BABYLON_VERSION, WS_PLURAL,
            label_selector=f"{WORKSHOP_ID_LABEL}={guid}",
        )
        workshops = result.get("items", [])
        if not workshops:
            return [], []

        for ws in workshops:
            ws_name = ws.get("metadata", {}).get("name", "unknown")
            ws_ns = ws.get("metadata", {}).get("namespace", "")
            rc_map = ws.get("status", {}).get("resourceClaims", {})
            if not rc_map or not ws_ns:
                continue

            logger.info(
                "Workshop '%s/%s' matched GUID '%s' with %d ResourceClaim(s)",
                ws_ns, ws_name, guid, len(rc_map),
            )

            rc_tasks = [
                babylon_client.k8s_get_resource(
                    cluster, RC_GROUP, RC_VERSION, RC_PLURAL, ws_ns, rc_name,
                )
                for rc_name in rc_map
            ]
            rc_results = await asyncio.gather(*rc_tasks, return_exceptions=True)

            for rc_name, rc_result in zip(rc_map, rc_results):
                if isinstance(rc_result, Exception):
                    msg = (
                        f"Cluster '{cluster}' failed to fetch RC '{ws_ns}/{rc_name}' "
                        f"for workshop '{ws_name}': {rc_result}"
                    )
                    logger.warning(msg)
                    errors.append(msg)
                    continue
                rc_guid = _extract_rc_guid(rc_result)
                found = extract_showroom_urls(rc_result)
                if found:
                    for entry in found:
                        entry["rc_guid"] = rc_guid
                    urls.extend(found)
                else:
                    provision_status = get_rc_provision_status(rc_result)
                    urls.append({
                        "url": "",
                        "label": rc_name,
                        "rc_guid": rc_guid,
                        "provision_status": provision_status,
                    })

    except Exception as e:
        msg = f"Cluster '{cluster}' Workshop lookup failed for GUID '{guid}': {e}"
        logger.warning(msg)
        return [], [msg]
    if urls:
        return urls, []
    return [], errors


async def _search_cluster_for_guid(
    cluster: str, guid: str,
) -> tuple[list[dict[str, str]], list[str]]:
    """Search a single cluster for a GUID, trying ResourceClaims first, then Workshops."""
    rc_urls, rc_errors = await _search_cluster_for_rc_guid(cluster, guid)
    if rc_urls:
        return rc_urls, []
    ws_urls, ws_errors = await _search_cluster_for_workshop_guid(cluster, guid)
    if ws_urls:
        return ws_urls, []
    return [], rc_errors + ws_errors


async def resolve_guid(guid: str, cluster: str = "") -> list[dict[str, str]]:
    """Resolve a GUID to showroom URLs by searching configured clusters.

    When *cluster* is specified, only that cluster is searched.  Otherwise all
    configured clusters are tried sequentially until a match is found.

    Returns a list of {url, label} dicts.
    """
    if cluster:
        urls, errors = await _search_cluster_for_guid(cluster, guid)
        if urls:
            return urls
        if errors:
            return [_resolution_error_entry(guid, errors)]
        return []

    clusters = babylon_client.get_configured_clusters()
    if not clusters:
        logger.warning("No Babylon clusters configured for GUID resolution")
        return []

    all_errors: list[str] = []
    for c in clusters:
        urls, errors = await _search_cluster_for_guid(c, guid)
        if urls:
            return urls  # GUID is unique, stop after first cluster with results
        all_errors.extend(errors)

    if all_errors:
        return [_resolution_error_entry(guid, all_errors)]
    return []


async def resolve_guids(
    guids: list[str], cluster: str = "",
) -> dict[str, list[dict[str, str]]]:
    """Resolve multiple GUIDs concurrently. Returns {guid: [{url, label}, ...]}."""
    resolved = await asyncio.gather(*[resolve_guid(g, cluster=cluster) for g in guids])
    return dict(zip(guids, resolved))


async def resolve_workshop_guid(guid: str, cluster: str = "") -> list[dict[str, str]]:
    """Resolve a Workshop GUID (workshop-id label) to showroom URLs.

    Searches only for Workshop CRs — skips the ResourceClaim scan.
    """
    if cluster:
        urls, errors = await _search_cluster_for_workshop_guid(cluster, guid)
        if urls:
            return urls
        if errors:
            return [_resolution_error_entry(guid, errors)]
        return []

    clusters = babylon_client.get_configured_clusters()
    if not clusters:
        logger.warning("No Babylon clusters configured for Workshop GUID resolution")
        return []

    all_errors: list[str] = []
    for c in clusters:
        urls, errors = await _search_cluster_for_workshop_guid(c, guid)
        if urls:
            return urls
        all_errors.extend(errors)

    if all_errors:
        return [_resolution_error_entry(guid, all_errors)]
    return []


async def resolve_workshop_guids(
    guids: list[str], cluster: str = "",
) -> dict[str, list[dict[str, str]]]:
    """Resolve multiple Workshop GUIDs concurrently. Returns {guid: [{url, label}, ...]}."""
    resolved = await asyncio.gather(
        *[resolve_workshop_guid(g, cluster=cluster) for g in guids],
    )
    return dict(zip(guids, resolved))
