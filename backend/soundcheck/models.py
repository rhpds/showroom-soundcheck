"""Database models for Showroom Soundcheck.

Session-based health check tracking: sessions contain targets (showroom URLs),
each target has check results from the two-tier health check strategy.

JSON columns (source_urls, source_guids, etc.) use PostgreSQL JSON natively.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from .utils import utc_now


class SessionGroup(SQLModel, table=True):
    """A named collection of GUIDs/pools with shared check settings.

    Running checks against a group creates a GroupRun containing one
    CheckSession per GUID/pool.
    """

    __tablename__ = "session_groups"

    id: int | None = Field(default=None, primary_key=True)
    group_id: str = Field(index=True)
    name: str = ""
    check_type: str = "readyz"
    check_mode: str = "manual"
    babylon_cluster: str = ""
    source_guids: list = Field(default=[], sa_type=sa.JSON)
    source_workshop_guids: list = Field(default=[], sa_type=sa.JSON)
    source_resource_pools: list = Field(default=[], sa_type=sa.JSON)
    member_metadata: dict = Field(default={}, sa_type=sa.JSON)

    status: str = "pending"
    pinned: bool = False
    created_at: datetime = Field(default_factory=utc_now, sa_type=sa.DateTime(timezone=True))

    def get_guids(self) -> list[str]:
        return self.source_guids or []

    def get_workshop_guids(self) -> list[str]:
        return self.source_workshop_guids or []

    def get_resource_pools(self) -> list[str]:
        return self.source_resource_pools or []

    def get_source_metadata(self) -> dict:
        return self.member_metadata or {}


class GroupRun(SQLModel, table=True):
    """One batch of checks against a group (full or partial)."""

    __tablename__ = "group_runs"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    group_id: str = Field(index=True)
    status: str = "pending"
    created_at: datetime = Field(default_factory=utc_now, sa_type=sa.DateTime(timezone=True))
    completed_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))


class CheckSession(SQLModel, table=True):
    """A health-check session initiated by a user.

    Created when a user visits /check?urls=...&guid=... or submits the form.
    The session_id (UUID) is used in shareable URLs (/session/<session_id>).
    """

    __tablename__ = "sessions"
    __table_args__ = (
        sa.Index("ix_sessions_status", "status"),
        sa.Index("ix_sessions_created_at", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    name: str = ""
    group_id: str | None = Field(default=None, index=True)
    group_run_id: str | None = Field(default=None, index=True)
    check_type: str = "readyz"
    check_mode: str = "manual"
    source_urls: list = Field(default=[], sa_type=sa.JSON)
    source_guids: list = Field(default=[], sa_type=sa.JSON)
    source_workshop_guids: list = Field(default=[], sa_type=sa.JSON)
    source_resource_pools: list = Field(default=[], sa_type=sa.JSON)
    babylon_cluster: str = ""
    display_label: str = ""
    status: str = "pending"
    pinned: bool = False
    created_at: datetime = Field(default_factory=utc_now, sa_type=sa.DateTime(timezone=True))
    completed_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))

    resource_name: str = ""
    resource_namespace: str = ""
    resource_kind: str = ""
    resource_display_name: str = ""
    resource_metadata: dict = Field(default={}, sa_type=sa.JSON)

    def get_urls(self) -> list[str]:
        return self.source_urls or []

    def get_guids(self) -> list[str]:
        return self.source_guids or []

    def get_workshop_guids(self) -> list[str]:
        return self.source_workshop_guids or []

    def get_resource_pools(self) -> list[str]:
        return self.source_resource_pools or []

    def get_resource_metadata(self) -> dict:
        return self.resource_metadata or {}


class SessionTarget(SQLModel, table=True):
    """A single showroom URL being checked within a session.

    When a ResourceClaim exists but has no showroom URL yet (still provisioning),
    ``url`` will be empty and ``provision_status`` will indicate the RC lifecycle
    stage (provisioning, ready, destroying).
    """

    __tablename__ = "session_targets"

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    url: str = ""
    label: str = ""
    guid: str | None = None
    workshop_guid: str | None = None
    resource_pool_name: str | None = None
    resource_name: str = ""
    resource_namespace: str = ""
    provision_status: str | None = None
    status: str = "pending"
    tier_used: int | None = None
    response_time_ms: int | None = None
    error_message: str | None = None
    check_started_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    check_completed_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))


class CheckResult(SQLModel, table=True):
    """A single check attempt for a session target."""

    __tablename__ = "check_results"

    id: int | None = Field(default=None, primary_key=True)
    target_id: int = Field(index=True)
    check_type: str = ""
    tier: int = 1
    is_healthy: bool = False
    status_code: int | None = None
    response_time_ms: int = 0
    error_message: str | None = None
    detail: str | None = None
    checked_at: datetime = Field(default_factory=utc_now, sa_type=sa.DateTime(timezone=True))
