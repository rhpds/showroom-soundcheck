"""Database models for Showroom Soundcheck.

Session-based health check tracking: sessions contain targets (showroom URLs),
each target has check results from the two-tier health check strategy.

Source URLs and GUIDs are stored as JSON strings on CheckSession for simplicity.
Use the get_urls() / get_guids() helpers instead of raw json.loads().
"""

import json
from datetime import datetime
from typing import Optional

import reflex as rx
from sqlmodel import Field

from .utils import utc_now_naive


class CheckSession(rx.Model, table=True):
    """A health-check session initiated by a user.

    Created when a user visits /check?urls=...&guid=... or submits the form.
    The session_id (UUID) is used in shareable URLs (/session/<session_id>).
    """

    __tablename__ = "sessions"

    session_id: str = Field(index=True)
    name: str = ""
    check_type: str = "readyz"  # readyz | healthz
    check_mode: str = "manual"  # manual | showroom
    source_urls: str = "[]"  # JSON list of original input URLs
    source_guids: str = "[]"  # JSON list of ResourceClaim GUIDs (if any)
    source_workshop_guids: str = "[]"  # JSON list of Workshop GUIDs (workshop-id labels)
    babylon_cluster: str = ""  # Babylon cluster name for GUID resolution
    display_label: str = ""
    status: str = "pending"  # pending | running | completed | failed
    created_at: datetime = Field(default_factory=utc_now_naive)
    completed_at: Optional[datetime] = None

    def get_urls(self) -> list[str]:
        try:
            return json.loads(self.source_urls) if self.source_urls else []
        except (json.JSONDecodeError, TypeError):
            return []

    def get_guids(self) -> list[str]:
        try:
            return json.loads(self.source_guids) if self.source_guids else []
        except (json.JSONDecodeError, TypeError):
            return []

    def get_workshop_guids(self) -> list[str]:
        try:
            return json.loads(self.source_workshop_guids) if self.source_workshop_guids else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def encode_urls(urls: list[str]) -> str:
        return json.dumps(urls)

    @staticmethod
    def encode_guids(guids: list[str]) -> str:
        return json.dumps(guids)

    @staticmethod
    def encode_workshop_guids(guids: list[str]) -> str:
        return json.dumps(guids)


class SessionTarget(rx.Model, table=True):
    """A single showroom URL being checked within a session.

    When a ResourceClaim exists but has no showroom URL yet (still provisioning),
    ``url`` will be empty and ``provision_status`` will indicate the RC lifecycle
    stage (provisioning, ready, destroying).
    """

    __tablename__ = "session_targets"

    session_id: str = Field(index=True)
    url: str = ""
    label: str = ""
    guid: Optional[str] = None
    workshop_guid: Optional[str] = None
    provision_status: Optional[str] = None  # provisioning | ready | destroying
    status: str = "pending"  # pending | checking | healthy | unhealthy | error | provisioning
    tier_used: Optional[int] = None  # 1 or 2
    response_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    check_started_at: Optional[datetime] = None
    check_completed_at: Optional[datetime] = None


class CheckResult(rx.Model, table=True):
    """A single check attempt for a session target."""

    __tablename__ = "check_results"

    target_id: int = Field(index=True)
    check_type: str = ""  # readyz_delegate, healthz_delegate, readyz_local, healthz_local
    tier: int = 1  # 1 (delegate) or 2 (local fallback)
    is_healthy: bool = False
    status_code: Optional[int] = None
    response_time_ms: int = 0
    error_message: Optional[str] = None
    detail: Optional[str] = None  # JSON: config parsed, tabs checked, etc.
    checked_at: datetime = Field(default_factory=utc_now_naive)
