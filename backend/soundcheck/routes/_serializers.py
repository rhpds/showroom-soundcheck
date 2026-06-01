"""Shared model-to-schema serializers for route modules."""

from ..models import CheckResult, CheckSession, GroupRun, SessionGroup, SessionTarget
from ..schemas import (
    CheckResultPublic,
    GroupListItem,
    GroupPublic,
    GroupRunPublic,
    SessionListItem,
    SessionPublic,
    TargetPublic,
)
from ..utils import sanitize_error


def _first_source_id(cs: CheckSession) -> str:
    for getter in (cs.get_workshop_guids, cs.get_guids, cs.get_resource_pools):
        ids = getter()
        if ids:
            return ids[0]
    return ""


# ---------------------------------------------------------------------------
# Session serializers
# ---------------------------------------------------------------------------


def session_to_public(cs: CheckSession) -> SessionPublic:
    return SessionPublic(
        id=cs.id,
        session_id=cs.session_id,
        name=cs.name,
        group_id=cs.group_id,
        group_run_id=cs.group_run_id,
        check_type=cs.check_type,
        source_urls=cs.get_urls(),
        source_guids=cs.get_guids(),
        source_workshop_guids=cs.get_workshop_guids(),
        source_resource_pools=cs.get_resource_pools(),
        babylon_cluster=cs.babylon_cluster,
        display_label=cs.display_label,
        status=cs.status,
        pinned=cs.pinned,
        created_at=cs.created_at,
        completed_at=cs.completed_at,
        resource_name=cs.resource_name,
        resource_namespace=cs.resource_namespace,
        resource_kind=cs.resource_kind,
        resource_display_name=cs.resource_display_name,
        resource_metadata=cs.get_resource_metadata(),
    )


def session_to_list_item(cs: CheckSession) -> SessionListItem:
    return SessionListItem(
        id=cs.id,
        session_id=cs.session_id,
        name=cs.name,
        group_id=cs.group_id,
        display_label=cs.display_label,
        status=cs.status,
        pinned=cs.pinned,
        created_at=cs.created_at,
        completed_at=cs.completed_at,
        resource_display_name=cs.resource_display_name,
        source_id=_first_source_id(cs),
    )


# ---------------------------------------------------------------------------
# Target / result serializers
# ---------------------------------------------------------------------------


def target_to_public(t: SessionTarget) -> TargetPublic:
    return TargetPublic(
        id=t.id,
        session_id=t.session_id,
        url=t.url,
        label=t.label,
        guid=t.guid,
        workshop_guid=t.workshop_guid,
        resource_pool_name=t.resource_pool_name,
        resource_name=t.resource_name,
        resource_namespace=t.resource_namespace,
        provision_status=t.provision_status,
        status=t.status,
        tier_used=t.tier_used,
        response_time_ms=t.response_time_ms,
        error_message=sanitize_error(t.error_message),
        check_started_at=t.check_started_at,
        check_completed_at=t.check_completed_at,
    )


def result_to_public(r: CheckResult) -> CheckResultPublic:
 return CheckResultPublic(
 id=r.id,
 target_id=r.target_id,
 check_type=r.check_type,
 tier=r.tier,
 is_healthy=r.is_healthy,
 status_code=r.status_code,
 response_time_ms=r.response_time_ms,
 error_message=sanitize_error(r.error_message),
 detail=r.detail,
 checked_at=r.checked_at,
 )


# ---------------------------------------------------------------------------
# Group serializers
# ---------------------------------------------------------------------------


def group_to_public(g: SessionGroup) -> GroupPublic:
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


def group_to_list_item(g: SessionGroup) -> GroupListItem:
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


def run_to_public(r: GroupRun) -> GroupRunPublic:
    return GroupRunPublic(
        id=r.id,
        run_id=r.run_id,
        group_id=r.group_id,
        status=r.status,
        created_at=r.created_at,
        completed_at=r.completed_at,
    )
