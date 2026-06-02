"""Pydantic schemas for the workshop dashboard API."""

from typing import Literal

from pydantic import BaseModel, Field

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
