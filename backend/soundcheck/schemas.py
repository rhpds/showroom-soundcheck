"""Pydantic/SQLModel request and response schemas for the REST API."""

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

IdentifierStr = Annotated[str, Field(max_length=255, pattern=r"^[a-zA-Z0-9._-]+$")]

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Envelope for paginated list responses."""

    items: list[T]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Session schemas
# ---------------------------------------------------------------------------


class SessionCreate(BaseModel):
    """POST /api/sessions request body."""

    urls: list[Annotated[str, Field(max_length=2048)]] = Field(default=[], max_length=500)
    guids: list[IdentifierStr] = Field(default=[], max_length=100)
    workshop_guids: list[IdentifierStr] = Field(default=[], max_length=100)
    resource_pools: list[IdentifierStr] = Field(default=[], max_length=100)
    check_type: Literal["readyz", "healthz"] = "readyz"
    name: str = Field(default="", max_length=255)
    babylon_cluster: str = Field(default="", max_length=255)


class SessionPublic(BaseModel):
    """Serialized CheckSession for API responses."""

    id: int
    session_id: str
    name: str
    group_id: str | None
    group_run_id: str | None
    check_type: str
    source_urls: list[str]
    source_guids: list[str]
    source_workshop_guids: list[str]
    source_resource_pools: list[str]
    babylon_cluster: str
    display_label: str
    status: str
    pinned: bool
    created_at: datetime
    completed_at: datetime | None
    resource_name: str
    resource_namespace: str
    resource_kind: str
    resource_display_name: str
    resource_metadata: dict[str, Any]


class TargetPublic(BaseModel):
    """Serialized SessionTarget for API responses."""

    id: int
    session_id: str
    url: str
    label: str
    guid: str | None
    workshop_guid: str | None
    resource_pool_name: str | None
    resource_name: str
    resource_namespace: str
    provision_status: str | None
    status: str
    tier_used: int | None
    response_time_ms: int | None
    error_message: str | None
    check_started_at: datetime | None
    check_completed_at: datetime | None


class CheckResultPublic(BaseModel):
    """Serialized CheckResult for API responses."""

    id: int
    target_id: int
    check_type: str
    tier: int
    is_healthy: bool
    status_code: int | None
    response_time_ms: int
    error_message: str | None
    detail: dict[str, Any] | None
    checked_at: datetime


class SessionDetail(BaseModel):
    """Full session response with targets and results."""

    session: SessionPublic
    targets: list[TargetPublic]
    results: list[CheckResultPublic]


class SessionListItem(BaseModel):
    """Compact session for list responses."""

    id: int
    session_id: str
    name: str
    group_id: str | None
    display_label: str
    status: str
    pinned: bool
    created_at: datetime
    completed_at: datetime | None
    resource_display_name: str = ""
    source_id: str = ""


# ---------------------------------------------------------------------------
# Group schemas
# ---------------------------------------------------------------------------


class GroupCreate(BaseModel):
    """POST /api/groups request body."""

    name: str = Field(max_length=255)
    guids: list[IdentifierStr] = Field(default=[], max_length=100)
    workshop_guids: list[IdentifierStr] = Field(default=[], max_length=100)
    resource_pools: list[IdentifierStr] = Field(default=[], max_length=100)
    check_type: Literal["readyz", "healthz"] = "readyz"
    babylon_cluster: str = Field(default="", max_length=255)


class GroupPublic(BaseModel):
    """Serialized SessionGroup for API responses."""

    id: int
    group_id: str
    name: str
    check_type: str
    babylon_cluster: str
    source_guids: list[str]
    source_workshop_guids: list[str]
    source_resource_pools: list[str]
    source_metadata: dict[str, Any]
    status: str
    pinned: bool
    created_at: datetime


class GroupRunPublic(BaseModel):
    """Serialized GroupRun for API responses."""

    id: int
    run_id: str
    group_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None


class GroupDetail(BaseModel):
    """Full group response with runs and their sessions."""

    group: GroupPublic
    runs: list[GroupRunPublic]
    run_sessions: dict[str, list[SessionListItem]]
    targets_by_session: dict[str, list[TargetPublic]]


class GroupListItem(BaseModel):
    """Compact group for list responses."""

    id: int
    group_id: str
    name: str
    status: str
    pinned: bool
    created_at: datetime
    source_count: int


class SourceRequest(BaseModel):
    """Request body for group source operations (add, remove, run-source)."""

    source_type: Literal["rc_guid", "workshop_guid", "pool"]
    source_value: IdentifierStr


class GroupRename(BaseModel):
    """PATCH /api/groups/{id}/name request body."""

    name: str = Field(max_length=255)


# ---------------------------------------------------------------------------
# Deep-link / check redirect
# ---------------------------------------------------------------------------


class CheckRedirectResponse(BaseModel):
    """Response for GET /api/check — returns the created session_id."""

    session_id: str


# ---------------------------------------------------------------------------
# SSE event models
# ---------------------------------------------------------------------------


class SessionUpdate(BaseModel):
    """SSE event payload for session progress streaming."""

    session_id: str
    status: str
    targets: list[TargetPublic]
    results: list[CheckResultPublic]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ClustersResponse(BaseModel):
    clusters: list[str]


# ---------------------------------------------------------------------------
# Mutating endpoint responses
# ---------------------------------------------------------------------------


class StatusResponse(BaseModel):
    """Generic status response for mutating endpoints."""

    status: str


class PinnedResponse(BaseModel):
    """Response for pin toggle endpoints."""

    pinned: bool


class NameResponse(BaseModel):
    """Response for rename endpoints."""

    name: str
