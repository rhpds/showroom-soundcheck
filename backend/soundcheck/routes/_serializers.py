"""Shared model-to-schema serializers for route modules."""

from ..models import CheckSession, SessionTarget
from ..schemas import SessionListItem, TargetPublic
from ..utils import sanitize_error


def _first_source_id(cs: CheckSession) -> str:
    for getter in (cs.get_workshop_guids, cs.get_guids, cs.get_resource_pools):
        ids = getter()
        if ids:
            return ids[0]
    return ""


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
