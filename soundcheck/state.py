"""Application state for Showroom Soundcheck.

Split into focused substates:
- SessionState: core session data, navigation, session-level computed vars
- SessionFormState: form handling and session creation from form/query params
- CheckRunnerState: background check orchestration and GUID resolution
- TargetDetailState: selected target detail dialog computed vars
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import reflex as rx
from reflex.utils.serializers import serializer
from sqlmodel import col, select

from . import babylon_client
from .babylon_service import (
    ResolutionContext,
    extract_resource_claim_metadata,
    extract_resource_pool_metadata,
    extract_workshop_metadata,
    lookup_rc_by_guid,
    lookup_resource_pool,
    lookup_workshop_by_guid,
    resolve_guids,
    resolve_resource_pool,
    resolve_workshop_guids,
)
from .check_service import TargetCheckResult, check_single_target, create_client
from .models import CheckResult, CheckSession, SessionTarget
from .utils import (
    InputValidationError,
    extract_guid_from_url,
    make_display_label,
    parse_check_params,
    utc_now,
)

logger = logging.getLogger(__name__)

_DATETIME_MIN_UTC = datetime.min.replace(tzinfo=timezone.utc)


@serializer(to=str)
def _serialize_dt(dt: date | datetime) -> str:
    """Override Reflex's default ``str(dt)`` which uses a space separator.

    Produces proper ISO 8601 (``T`` separator) so Moment.js always parses
    the full date+time.  Aware datetimes are normalised to UTC with a ``Z``
    suffix.
    """
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return dt.isoformat()


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s must be an integer (got %r); using %d", name, raw, default)
        return default
    if value < 1:
        logger.warning("%s must be >= 1 (got %d); using 1", name, value)
        return 1
    return value


CHECK_CONCURRENCY = _positive_int_env("CHECK_CONCURRENCY", 10)
VERIFY_SSL = os.environ.get("VERIFY_SSL", "true").lower() in ("true", "1", "yes")


def local_time(dt_var: rx.Var, **kwargs: object) -> rx.Component:
    kwargs.setdefault("format", "ddd, MMM D YYYY [at] h:mm A")
    kwargs.setdefault("local", True)
    return rx.moment(dt_var, **kwargs)


# ---------------------------------------------------------------------------
# Session persistence helper
# ---------------------------------------------------------------------------


async def _persist_new_session(
    *,
    name: str,
    check_type: str,
    check_mode: str,
    urls: list[str],
    guids: list[str],
    babylon_cluster: str = "",
    display_label: str = "",
    workshop_guids: Optional[list[str]] = None,
    resource_pools: Optional[list[str]] = None,
) -> str:
    """Create a new pending session with targets in the database. Returns session_id."""
    workshop_guids = workshop_guids or []
    resource_pools = resource_pools or []
    sid = str(uuid.uuid4())
    now = utc_now()

    async with rx.asession() as session:
        cs = CheckSession(
            session_id=sid,
            name=name,
            check_type=check_type,
            check_mode=check_mode,
            source_urls=CheckSession.encode_urls(urls),
            source_guids=CheckSession.encode_guids(guids),
            source_workshop_guids=CheckSession.encode_workshop_guids(workshop_guids),
            source_resource_pools=CheckSession.encode_resource_pools(resource_pools),
            babylon_cluster=babylon_cluster,
            display_label=display_label or make_display_label(urls, guids, workshop_guids, resource_pools),
            status="pending",
            created_at=now,
        )
        session.add(cs)

        for url in urls:
            target = SessionTarget(
                session_id=sid,
                url=url.rstrip("/"),
                label=url,
                status="pending",
            )
            session.add(target)

        await session.commit()

    return sid


# ---------------------------------------------------------------------------
# DB helper (shared across substates)
# ---------------------------------------------------------------------------


async def _fetch_session_data(sid: str) -> dict:
    """Load session, targets, and results from DB."""
    session_q = select(CheckSession).where(CheckSession.session_id == sid)
    targets_q = select(SessionTarget).where(SessionTarget.session_id == sid)
    results_q = select(CheckResult).order_by(col(CheckResult.checked_at).desc())
    async with rx.asession() as session:
        cs = (await session.execute(session_q)).scalars().first()
        targets = list((await session.execute(targets_q)).scalars().all())
        target_ids = [t.id for t in targets]
        results: list[CheckResult] = []
        if target_ids:
            results = list(
                (await session.execute(
                    results_q.where(CheckResult.target_id.in_(target_ids))  # type: ignore
                )).scalars().all()
            )
    return {"session": cs, "targets": targets, "results": results}


async def _load_all_sessions_async() -> list[CheckSession]:
    async with rx.asession() as session:
        result = await session.execute(
            select(CheckSession).order_by(col(CheckSession.created_at).desc()).limit(100)
        )
        return list(result.scalars().all())


def _build_check_summaries(results: list[CheckResult]) -> dict[int, dict]:
    """Parse check result detail JSON into per-target display summaries.

    Only the first (most recent) result per target is considered.
    Called explicitly when results change rather than on every render cycle.
    """
    summaries: dict[int, dict] = {}
    seen: set[int] = set()
    for r in results:
        if r.target_id in seen or not r.detail:
            continue
        seen.add(r.target_id)
        try:
            detail = json.loads(r.detail)
        except (json.JSONDecodeError, TypeError):
            continue

        content_pages = detail.get("content_pages") or []
        tabs = detail.get("tabs") or []
        summaries[r.target_id] = {
            "content_ok": sum(1 for p in content_pages if p.get("reachable")),
            "content_total": len(content_pages),
            "tabs_ok": sum(
                1 for t in tabs
                if t.get("reachable") and (not t.get("iframe_blocked") or t.get("external"))
            ),
            "tabs_total": len(tabs),
            "has_detail": True,
            "is_legacy": bool(detail.get("legacy", False)),
        }
    return summaries


# ---------------------------------------------------------------------------
# SessionState — core session data + navigation
# ---------------------------------------------------------------------------


class SessionState(rx.State):
    """Core application state for session-based health checks."""

    current_session_id: str = ""
    current_session: Optional[CheckSession] = None
    current_targets: list[SessionTarget] = []
    current_results: list[CheckResult] = []

    all_sessions: list[CheckSession] = []

    session_loading: bool = True
    sidebar_open: bool = False

    @rx.event
    def open_sidebar(self):
        self.sidebar_open = True

    @rx.event
    def close_sidebar(self):
        self.sidebar_open = False

    @rx.event
    def set_sidebar_open(self, is_open: bool):
        self.sidebar_open = is_open

    @rx.var
    def page_session_id(self) -> str:
        route_session_id = getattr(self, "session_id", "")
        if route_session_id:
            return route_session_id
        path = self.router.url.path or ""
        if path.startswith("/session/"):
            return path.removeprefix("/session/").split("/", 1)[0]
        return ""

    # ---------- Session history loading ----------

    @rx.event
    async def load_sessions(self):
        async with rx.asession() as session:
            result = await session.execute(
                select(CheckSession).order_by(col(CheckSession.created_at).desc()).limit(100)
            )
            self.all_sessions = list(result.scalars().all())

    # ---------- Load a specific session ----------

    @rx.event
    async def load_session(self):
        """Load session data based on the URL parameter.

        Returns run_checks when the session is pending so the background
        task starts *after* current_session_id is committed to state.
        """
        sid = self.page_session_id
        if not sid:
            self.current_session_id = ""
            self.current_session = None
            self.current_targets = []
            self.current_results = []
            self.target_check_summaries = {}
            self.session_loading = False
            return

        self.current_session_id = sid
        data = await _fetch_session_data(sid)
        self.current_session = data["session"]
        self.current_targets = data["targets"]
        self.current_results = data["results"]
        self.target_check_summaries = _build_check_summaries(data["results"])
        self.session_loading = False

        if self.current_session and self.current_session.status == "pending":
            return CheckRunnerState.run_checks

    # ---------- Clone / retry a session ----------

    @rx.event
    async def clone_session(self):
        """Create a new pending session cloned from the current one and redirect to it."""
        cs = self.current_session
        if not cs:
            return

        sid = await _persist_new_session(
            name=cs.name,
            check_type=cs.check_type,
            check_mode=cs.check_mode,
            urls=cs.get_urls(),
            guids=cs.get_guids(),
            babylon_cluster=cs.babylon_cluster,
            display_label=cs.display_label,
            workshop_guids=cs.get_workshop_guids(),
            resource_pools=cs.get_resource_pools(),
        )
        return rx.redirect(f"/session/{sid}")

    # ---------- Page on_load handlers ----------

    @rx.event
    def on_session_load(self):
        self.session_loading = True
        self.current_session = None
        self.current_targets = []
        self.current_results = []
        self.target_check_summaries = {}
        self.target_filter = "all"
        return [
            SessionState.load_session,
            SessionState.load_sessions,
        ]

    @rx.event
    def on_home_load(self):
        return [SessionState.load_sessions, SessionFormState.reset_form_lock]

    # ---------- Session-level computed vars ----------

    @rx.var
    def target_counts(self) -> dict[str, int]:
        """Single-pass status breakdown over current_targets.

        Keys: healthy, degraded, error, checked, total, checkable.
        """
        counts: dict[str, int] = {
            "healthy": 0, "degraded": 0, "error": 0,
            "checked": 0, "total": 0, "checkable": 0,
        }
        for t in self.current_targets:
            counts["total"] += 1
            if t.url or t.status == "provisioning":
                counts["checkable"] += 1
            if t.status in ("healthy", "degraded", "unhealthy", "error"):
                counts["checked"] += 1
            if t.status == "healthy":
                counts["healthy"] += 1
            elif t.status == "degraded":
                counts["degraded"] += 1
            elif t.status in ("error", "unhealthy"):
                counts["error"] += 1
        counts["issues"] = counts["error"] + counts["degraded"]
        return counts

    @rx.var
    def checks_in_progress(self) -> bool:
        if not self.current_session:
            return False
        return self.current_session.status in ("pending", "running")

    @rx.var
    def available_clusters(self) -> list[str]:
        return babylon_client.get_configured_clusters()

    @rx.var
    def cluster_select_options(self) -> list[str]:
        return ["(auto)"] + babylon_client.get_configured_clusters()

    @rx.var
    def guid_resolution(self) -> dict[str, int | bool]:
        """Single-pass GUID resolution statistics.

        Keys: started (bool), ws_resolved, ws_total, rc_resolved, rc_total.
        A GUID counts as resolved when at least one target for it has a
        URL or a non-error status.
        """
        empty: dict[str, int | bool] = {
            "started": False, "ws_resolved": 0, "ws_total": 0,
            "rc_resolved": 0, "rc_total": 0,
        }
        if not self.current_session:
            return empty
        ws_guids = set(self.current_session.get_workshop_guids())
        rc_guids = set(self.current_session.get_guids())
        if not ws_guids and not rc_guids:
            return empty

        started = False
        ws_resolved: set[str] = set()
        rc_resolved: set[str] = set()
        for t in self.current_targets:
            if t.workshop_guid:
                started = True
                if t.url or t.status != "error":
                    ws_resolved.add(t.workshop_guid)
            if t.guid and not t.workshop_guid:
                started = True
                if t.url or t.status != "error":
                    rc_resolved.add(t.guid)

        return {
            "started": started,
            "ws_resolved": sum(1 for g in ws_guids if g in ws_resolved),
            "ws_total": len(ws_guids),
            "rc_resolved": sum(1 for g in rc_guids if g in rc_resolved),
            "rc_total": len(rc_guids),
        }

    @rx.var
    def session_source_guids(self) -> list[str]:
        if not self.current_session:
            return []
        rc = self.current_session.get_guids()
        ws = [f"ws:{g}" for g in self.current_session.get_workshop_guids()]
        return ws + rc

    @rx.var
    def session_workshop_guids_prefixed(self) -> list[str]:
        """Workshop GUIDs with the ws: prefix, for badge rendering."""
        if not self.current_session:
            return []
        return [f"ws:{g}" for g in self.current_session.get_workshop_guids()]

    @rx.var
    def session_rc_guids(self) -> list[str]:
        """ResourceClaim GUIDs (plain), for badge rendering."""
        if not self.current_session:
            return []
        return self.current_session.get_guids()

    @rx.var
    def session_source_guids_raw(self) -> list[str]:
        """Source GUIDs without the ws: prefix (the resource kind badge provides that context)."""
        if not self.current_session:
            return []
        return self.current_session.get_workshop_guids() + self.current_session.get_guids()

    @rx.var
    def session_catalog_url(self) -> str:
        """Babylon catalog URL for the session's resolved resource (Workshop, RC, or Pool)."""
        cs = self.current_session
        if not cs or not cs.babylon_cluster or not cs.resource_namespace or not cs.resource_name:
            return ""
        base = babylon_client.get_catalog_url(cs.babylon_cluster)
        if not base:
            return ""
        if cs.resource_kind == "Workshop":
            return f"{base}/workshops/{cs.resource_namespace}/{cs.resource_name}"
        if cs.resource_kind == "ResourcePool":
            return f"{base}/admin/resourcepools/{cs.resource_name}/yaml"
        return f"{base}/services/{cs.resource_namespace}/{cs.resource_name}"

    @rx.var
    def today_sessions(self) -> list[CheckSession]:
        cutoff = utc_now() - timedelta(hours=24)
        return [s for s in self.all_sessions if s.created_at and s.created_at >= cutoff]

    @rx.var
    def yesterday_sessions(self) -> list[CheckSession]:
        now = utc_now()
        recent = now - timedelta(hours=24)
        earlier = now - timedelta(hours=48)
        return [s for s in self.all_sessions if s.created_at and earlier <= s.created_at < recent]

    @rx.var
    def older_sessions(self) -> list[CheckSession]:
        cutoff = utc_now() - timedelta(hours=48)
        return [s for s in self.all_sessions if s.created_at and s.created_at < cutoff]

    target_filter: str = "all"

    @rx.event
    def set_target_filter(self, value: str):
        self.target_filter = value

    @staticmethod
    def _sort_targets(targets: list) -> list:
        order = {
            "checking": 0, "error": 1, "degraded": 2, "provisioning": 3,
            "pending": 4, "unhealthy": 5, "healthy": 6,
        }

        def sort_key(t):
            return (order.get(t.status, 6), t.check_started_at or _DATETIME_MIN_UTC)

        return sorted(targets, key=sort_key)

    @rx.var
    def _target_buckets(self) -> dict[str, list[SessionTarget]]:
        """Single-pass partition of current_targets into status buckets.

        Returns keys: all, issues, healthy, in_progress — each
        sorted by status priority then check start time.
        """
        issues: list[SessionTarget] = []
        healthy: list[SessionTarget] = []
        in_progress: list[SessionTarget] = []
        for t in self.current_targets:
            if t.status in ("error", "unhealthy", "degraded"):
                issues.append(t)
            elif t.status == "healthy":
                healthy.append(t)
            elif t.status in ("checking", "pending", "provisioning"):
                in_progress.append(t)
        all_sorted = self._sort_targets(self.current_targets)
        return {
            "all": all_sorted,
            "issues": self._sort_targets(issues),
            "healthy": self._sort_targets(healthy),
            "in_progress": self._sort_targets(in_progress),
        }

    @rx.var
    def sorted_targets(self) -> list[SessionTarget]:
        return self._target_buckets["all"]

    @rx.var
    def issue_targets(self) -> list[SessionTarget]:
        return self._target_buckets["issues"]

    @rx.var
    def healthy_targets(self) -> list[SessionTarget]:
        return self._target_buckets["healthy"]

    @rx.var
    def in_progress_targets(self) -> list[SessionTarget]:
        return self._target_buckets["in_progress"]

    target_check_summaries: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# SessionFormState — form handling and session creation
# ---------------------------------------------------------------------------


class SessionFormState(SessionState):
    """Handles session creation from both query params and form submissions."""

    form_urls: str = ""
    form_guids: str = ""
    form_check_type: str = "readyz"
    form_error: str = ""
    form_submitting: bool = False

    @rx.event
    def reset_form_lock(self):
        """Clear stale submit lock when navigating back to the home page."""
        self.form_submitting = False

    @rx.event
    async def handle_check_page(self):
        """Called on /check page load. Create session from query params and redirect."""
        query = self.router.url.query_parameters
        raw_urls = query.get("urls", "")
        raw_guids = query.get("guid", "")
        raw_ws_guids = query.get("workshop", "")
        raw_pools = query.get("pool", "")
        check_type = query.get("type", "readyz")
        check_mode = query.get("mode", "manual")
        session_name = query.get("name", "")
        cluster = query.get("cluster", "")

        if not raw_urls and not raw_guids and not raw_ws_guids and not raw_pools:
            return rx.redirect("/")

        try:
            parsed = parse_check_params(
                raw_urls=raw_urls,
                raw_guids=raw_guids,
                raw_ws_guids=raw_ws_guids,
                raw_resource_pools=raw_pools,
                check_type=check_type,
                check_mode=check_mode,
                session_name=session_name,
                cluster=cluster,
                url_separator=",",
            )
        except InputValidationError:
            return rx.redirect("/")

        sid = await _persist_new_session(
            name=parsed.session_name,
            check_type=parsed.check_type,
            check_mode=parsed.check_mode,
            urls=parsed.urls,
            guids=parsed.guids,
            babylon_cluster=parsed.babylon_cluster,
            workshop_guids=parsed.workshop_guids,
            resource_pools=parsed.resource_pools,
        )
        return rx.redirect(f"/session/{sid}")

    @rx.event
    async def create_session_from_form(self, form_data: dict):
        if self.form_submitting:
            return
        self.form_submitting = True
        try:
            parsed = parse_check_params(
                raw_urls=(form_data.get("urls") or "").strip(),
                raw_guids=(form_data.get("guids") or "").strip(),
                raw_ws_guids=(form_data.get("workshop_guids") or "").strip(),
                raw_resource_pools=(form_data.get("resource_pool") or "").strip(),
                check_type=form_data.get("check_type") or "readyz",
                check_mode=form_data.get("check_mode") or "manual",
                session_name=form_data.get("session_name") or "",
                cluster=form_data.get("babylon_cluster") or "",
                url_separator="\n",
            )
        except InputValidationError as e:
            self.form_error = str(e)
            self.form_submitting = False
            return

        needs_cluster = parsed.guids or parsed.workshop_guids or parsed.resource_pools
        if needs_cluster and not babylon_client.get_configured_clusters():
            self.form_error = "No Babylon clusters configured — cannot resolve GUIDs or ResourcePools"
            self.form_submitting = False
            return

        sid = await _persist_new_session(
            name=parsed.session_name,
            check_type=parsed.check_type,
            check_mode=parsed.check_mode,
            urls=parsed.urls,
            guids=parsed.guids,
            babylon_cluster=parsed.babylon_cluster,
            workshop_guids=parsed.workshop_guids,
            resource_pools=parsed.resource_pools,
        )

        self.form_error = ""
        self.form_urls = ""
        self.form_guids = ""
        return rx.redirect(f"/session/{sid}")


# ---------------------------------------------------------------------------
# TargetDetailState — selected target detail dialog computed vars
# ---------------------------------------------------------------------------


class TargetDetailState(SessionState):
    """Computed vars for the target detail dialog."""

    selected_target_id: int = 0
    show_target_detail: bool = False

    @rx.event
    def open_target_detail(self, target_id: int):
        for t in self.current_targets:
            if t.id == target_id and t.status == "provisioning":
                return
        self.selected_target_id = target_id
        self.show_target_detail = True

    @rx.event
    def close_target_detail(self):
        self.show_target_detail = False
        self.selected_target_id = 0

    @rx.event
    def set_target_detail_open(self, is_open: bool):
        if not is_open:
            self.show_target_detail = False
            self.selected_target_id = 0

    @rx.var
    def selected_target(self) -> Optional[SessionTarget]:
        if not self.selected_target_id:
            return None
        for t in self.current_targets:
            if t.id == self.selected_target_id:
                return t
        return None

    @rx.var
    def selected_target_catalog_url(self) -> str:
        """Babylon catalog URL for the selected target's ResourceClaim."""
        cs = self.current_session
        target = self.selected_target
        if not cs or not target or not cs.babylon_cluster:
            return ""
        if not target.resource_namespace or not target.resource_name:
            return ""
        base = babylon_client.get_catalog_url(cs.babylon_cluster)
        if not base:
            return ""
        return f"{base}/services/{target.resource_namespace}/{target.resource_name}"

    @rx.var
    def selected_target_results(self) -> list[CheckResult]:
        if not self.selected_target_id:
            return []
        return [r for r in self.current_results if r.target_id == self.selected_target_id]

    @rx.var
    def selected_target_detail(self) -> dict:
        """Parse the detail JSON from the most recent check result for the selected target."""
        if not self.selected_target_id:
            return {}
        for r in self.current_results:
            if r.target_id == self.selected_target_id and r.detail:
                try:
                    return json.loads(r.detail)
                except (json.JSONDecodeError, TypeError):
                    return {}
        return {}

    @rx.var
    def has_detail(self) -> bool:
        return bool(self.selected_target_detail)

    @rx.var
    def detail_has_tabs(self) -> bool:
        return bool(self.selected_target_detail.get("tabs"))

    @rx.var
    def detail_tabs(self) -> list[dict]:
        """Normalized tab data with consistent keys."""
        raw_tabs = self.selected_target_detail.get("tabs", [])
        normalized = []
        for tab in raw_tabs:
            sc = tab.get("status_code") or tab.get("statusCode") or 0
            external = bool(tab.get("external", False))
            iframe_blocked = bool(tab.get("iframe_blocked", False) or tab.get("iframeBlocked", False))
            normalized.append({
                "name": tab.get("name", "unknown"),
                "url": tab.get("url", ""),
                "reachable": bool(tab.get("reachable", False)),
                "status_code": sc,
                "status_ok": 200 <= sc < 400 if sc else False,
                "error": tab.get("error") or "",
                "iframe_blocked": iframe_blocked,
                "external": external,
            })
        return normalized

    @rx.var
    def detail_content_list(self) -> list[dict]:
        """Content probes as a list for rx.foreach rendering.

        Uses the ``content_pages`` key (multiple probes) when present,
        falling back to the legacy single ``content`` key.
        """
        pages = self.selected_target_detail.get("content_pages") or []
        if pages:
            result = []
            for page in pages:
                sc = page.get("status_code") or page.get("statusCode") or 0
                result.append({
                    "name": page.get("name", "content"),
                    "url": page.get("url") or "",
                    "reachable": bool(page.get("reachable", False)),
                    "status_code": sc,
                    "status_ok": 200 <= sc < 400 if sc else False,
                    "error": page.get("error") or "",
                    "iframe_blocked": False,
                    "external": False,
                })
            return result

        content = self.selected_target_detail.get("content", {})
        if not content:
            return []
        sc = content.get("status_code") or content.get("statusCode") or 0
        return [{
            "name": "content",
            "url": content.get("url") or content.get("path") or "",
            "reachable": bool(content.get("reachable", False)),
            "status_code": sc,
            "status_ok": 200 <= sc < 400 if sc else False,
            "error": content.get("error") or "",
            "iframe_blocked": False,
            "external": False,
        }]

    @rx.var
    def detail_has_content(self) -> bool:
        return bool(
            self.selected_target_detail.get("content_pages")
            or self.selected_target_detail.get("content")
        )

    @rx.var
    def detail_config_file(self) -> str:
        return self.selected_target_detail.get("configFile", "") or self.selected_target_detail.get("config_file", "") or ""

    @rx.var
    def detail_config_url(self) -> str:
        return self.selected_target_detail.get("config_url", "") or ""

    @rx.var
    def detail_status(self) -> str:
        return self.selected_target_detail.get("status", "")

    @rx.var
    def detail_is_legacy(self) -> bool:
        return bool(self.selected_target_detail.get("legacy", False))


# ---------------------------------------------------------------------------
# CheckRunnerState — background check orchestration
# ---------------------------------------------------------------------------


class CheckRunnerState(SessionState):
    """Background task orchestration for health checks."""

    @rx.event(background=True)
    async def run_checks(self):
        """Background task: resolve GUIDs and run health checks for current session."""
        async with self:
            sid = self.current_session_id
            if not sid:
                return

        async with rx.asession() as session:
            session_result = await session.execute(
                select(CheckSession).where(CheckSession.session_id == sid).with_for_update()
            )
            cs = session_result.scalars().first()
            if not cs or cs.status != "pending":
                return
            cs.status = "running"
            session.add(cs)
            await session.commit()

        try:
            await self._push_session_to_ui(sid)
            await self._resolve_and_create_targets(sid)
            await self._execute_checks(sid)
            await self._finalize_session(sid)
        except Exception as e:
            logger.exception("Error running checks for session %s: %s", sid, e)
            await self._mark_session_failed(sid)
            await self._push_session_to_ui(sid)
        finally:
            sessions = await _load_all_sessions_async()
            async with self:
                self.all_sessions = sessions

    @staticmethod
    def _not_found_target(
        sid: str,
        *,
        guid: Optional[str] = None,
        workshop_guid: Optional[str] = None,
    ) -> SessionTarget:
        if workshop_guid:
            return SessionTarget(
                session_id=sid,
                url="",
                label=f"Workshop not found: {workshop_guid}",
                workshop_guid=workshop_guid,
                status="error",
                error_message=f"No Workshop found for GUID '{workshop_guid}' on any configured cluster",
            )
        return SessionTarget(
            session_id=sid,
            url="",
            label=f"GUID not found: {guid}",
            guid=guid,
            status="error",
            error_message=f"No ResourceClaim or Workshop found for GUID '{guid}' on any configured cluster",
        )

    @staticmethod
    def _status_for_resolution_entry(
        entry: dict[str, str],
        *,
        fallback_label: str,
        resolution_error_prefix: str,
    ) -> tuple[str, Optional[str], Optional[str]]:
        is_placeholder = not entry.get("url")
        prov_status = entry.get("provision_status") or None
        resolution_error = entry.get("resolution_error") or None

        if resolution_error:
            return "error", f"{resolution_error_prefix}{resolution_error}", prov_status
        if is_placeholder and prov_status and "failed" in prov_status:
            return "error", f"Provision failed for ResourceClaim '{entry.get('label', fallback_label)}'", prov_status
        if is_placeholder and prov_status == "ready":
            return "error", (
                f"No showroom endpoint found for ResourceClaim '{entry.get('label', fallback_label)}' "
                "(resource is running)"
            ), prov_status
        if is_placeholder:
            return "provisioning", None, prov_status
        return "pending", None, prov_status

    @classmethod
    def _resolved_target(
        cls,
        sid: str,
        entry: dict[str, str],
        *,
        fallback_label: str,
        guid: Optional[str] = None,
        workshop_guid: Optional[str] = None,
        resolution_error_prefix: str,
    ) -> SessionTarget:
        status, err_msg, prov_status = cls._status_for_resolution_entry(
            entry,
            fallback_label=fallback_label,
            resolution_error_prefix=resolution_error_prefix,
        )
        return SessionTarget(
            session_id=sid,
            url=entry["url"].rstrip("/") if entry.get("url") else "",
            label=entry.get("label", entry.get("url", "")),
            guid=guid,
            workshop_guid=workshop_guid,
            resource_name=entry.get("rc_name", ""),
            resource_namespace=entry.get("rc_namespace", ""),
            provision_status=prov_status,
            status=status,
            error_message=err_msg,
        )

    async def _resolve_and_create_targets(self, sid: str) -> None:
        """Resolve GUIDs/workshop GUIDs/resource pools and create SessionTarget rows.

        Also looks up the source resource (Workshop, ResourceClaim, or
        ResourcePool) to populate session-level metadata.
        """
        async with rx.asession() as session:
            session_result = await session.execute(
                select(CheckSession).where(CheckSession.session_id == sid)
            )
            cs = session_result.scalars().first()
            guids = cs.get_guids() if cs else []
            ws_guids = cs.get_workshop_guids() if cs else []
            pools = cs.get_resource_pools() if cs else []
            cluster = cs.babylon_cluster if cs else ""

        guid_resolved = False
        ctx = ResolutionContext()

        if guids:
            guid_results = await resolve_guids(guids, cluster=cluster, ctx=ctx)
            async with rx.asession() as session:
                for guid, url_entries in guid_results.items():
                    if not url_entries:
                        session.add(self._not_found_target(sid, guid=guid))
                        continue
                    for entry in url_entries:
                        session.add(
                            self._resolved_target(
                                sid,
                                entry,
                                fallback_label=guid,
                                guid=guid,
                                resolution_error_prefix="GUID resolution failed: ",
                            )
                        )
                await session.commit()
            guid_resolved = True

            if len(guids) == 1:
                await self._populate_rc_metadata(sid, guids[0], cluster, ctx)

        if ws_guids:
            ws_results = await resolve_workshop_guids(ws_guids, cluster=cluster, ctx=ctx)
            async with rx.asession() as session:
                for ws_guid, url_entries in ws_results.items():
                    if not url_entries:
                        session.add(self._not_found_target(sid, workshop_guid=ws_guid))
                        continue
                    for entry in url_entries:
                        session.add(
                            self._resolved_target(
                                sid,
                                entry,
                                fallback_label=ws_guid,
                                guid=entry.get("rc_guid") or None,
                                workshop_guid=ws_guid,
                                resolution_error_prefix="Workshop GUID resolution failed: ",
                            )
                        )
                await session.commit()
            guid_resolved = True

            if len(ws_guids) == 1:
                await self._populate_workshop_metadata(sid, ws_guids[0], cluster, ctx)

        if pools:
            for pool_name in pools:
                url_entries, errors, resolved_cluster = await resolve_resource_pool(
                    pool_name, cluster=cluster,
                )
                async with rx.asession() as session:
                    if not url_entries and not errors:
                        session.add(SessionTarget(
                            session_id=sid,
                            url="",
                            label=f"ResourcePool empty: {pool_name}",
                            resource_pool_name=pool_name,
                            status="error",
                            error_message=f"ResourcePool '{pool_name}' has no instances",
                        ))
                    elif not url_entries and errors:
                        session.add(SessionTarget(
                            session_id=sid,
                            url="",
                            label=f"ResourcePool not found: {pool_name}",
                            resource_pool_name=pool_name,
                            status="error",
                            error_message="; ".join(errors)[:500],
                        ))
                    else:
                        for entry in url_entries:
                            status, err_msg, prov_status = self._status_for_resolution_entry(
                                entry,
                                fallback_label=pool_name,
                                resolution_error_prefix="ResourcePool resolution failed: ",
                            )
                            session.add(SessionTarget(
                                session_id=sid,
                                url=entry["url"].rstrip("/") if entry.get("url") else "",
                                label=entry.get("label", ""),
                                resource_pool_name=pool_name,
                                provision_status=prov_status,
                                status=status,
                                error_message=err_msg,
                            ))
                    await session.commit()
                guid_resolved = True

            if len(pools) == 1:
                await self._populate_pool_metadata(sid, pools[0], cluster)

        if guid_resolved:
            await self._push_session_to_ui(sid)

    async def _populate_workshop_metadata(
        self, sid: str, ws_guid: str, cluster: str, ctx: ResolutionContext,
    ) -> None:
        """Look up the Workshop CRD and store metadata on the session."""
        try:
            ws_def, resolved_cluster = await lookup_workshop_by_guid(ws_guid, cluster=cluster, ctx=ctx)
            if not ws_def:
                return
            meta = extract_workshop_metadata(ws_def)
            async with rx.asession() as session:
                cs_result = await session.execute(
                    select(CheckSession).where(CheckSession.session_id == sid)
                )
                cs = cs_result.scalars().first()
                if cs:
                    cs.resource_kind = "Workshop"
                    cs.resource_name = meta.get("name", "")
                    cs.resource_namespace = meta.get("namespace", "")
                    cs.resource_display_name = meta.get("display_name", "")
                    cs.resource_metadata = CheckSession.encode_resource_metadata(meta)
                    if resolved_cluster and not cs.babylon_cluster:
                        cs.babylon_cluster = resolved_cluster
                    if meta.get("display_name") and not cs.name:
                        cs.name = meta["display_name"]
                    session.add(cs)
                    await session.commit()
        except Exception as e:
            logger.warning("Failed to populate workshop metadata for '%s': %s", ws_guid, e)

    async def _populate_rc_metadata(
        self, sid: str, guid: str, cluster: str, ctx: ResolutionContext,
    ) -> None:
        """Look up the ResourceClaim CRD and store metadata on the session."""
        try:
            rc_def, resolved_cluster = await lookup_rc_by_guid(guid, cluster=cluster, ctx=ctx)
            if not rc_def:
                return
            meta = extract_resource_claim_metadata(rc_def)
            async with rx.asession() as session:
                cs_result = await session.execute(
                    select(CheckSession).where(CheckSession.session_id == sid)
                )
                cs = cs_result.scalars().first()
                if cs:
                    cs.resource_kind = "ResourceClaim"
                    cs.resource_name = meta.get("name", "")
                    cs.resource_namespace = meta.get("namespace", "")
                    cs.resource_display_name = meta.get("display_name", "")
                    cs.resource_metadata = CheckSession.encode_resource_metadata(meta)
                    if resolved_cluster and not cs.babylon_cluster:
                        cs.babylon_cluster = resolved_cluster
                    if meta.get("display_name") and not cs.name:
                        cs.name = meta["display_name"]
                    session.add(cs)
                    await session.commit()
        except Exception as e:
            logger.warning("Failed to populate RC metadata for '%s': %s", guid, e)

    async def _populate_pool_metadata(
        self, sid: str, pool_name: str, cluster: str,
    ) -> None:
        """Look up the ResourcePool CRD and store metadata on the session."""
        try:
            pool_def, resolved_cluster = await lookup_resource_pool(pool_name, cluster=cluster)
            if not pool_def:
                return
            meta = extract_resource_pool_metadata(pool_def)
            async with rx.asession() as session:
                cs_result = await session.execute(
                    select(CheckSession).where(CheckSession.session_id == sid)
                )
                cs = cs_result.scalars().first()
                if cs:
                    cs.resource_kind = "ResourcePool"
                    cs.resource_name = meta.get("name", "")
                    cs.resource_namespace = meta.get("namespace", "")
                    cs.resource_display_name = meta.get("catalog_item", "")
                    cs.resource_metadata = CheckSession.encode_resource_metadata(meta)
                    if resolved_cluster and not cs.babylon_cluster:
                        cs.babylon_cluster = resolved_cluster
                    if meta.get("catalog_item") and not cs.name:
                        cs.name = meta["catalog_item"]
                    session.add(cs)
                    await session.commit()
        except Exception as e:
            logger.warning("Failed to populate pool metadata for '%s': %s", pool_name, e)

    async def _execute_checks(self, sid: str) -> None:
        """Run health checks concurrently for all targets in the session."""
        async with rx.asession() as session:
            targets_result = await session.execute(
                select(SessionTarget).where(SessionTarget.session_id == sid)
            )
            all_targets = list(targets_result.scalars().all())
            cs_result = await session.execute(
                select(CheckSession).where(CheckSession.session_id == sid)
            )
            cs = cs_result.scalars().first()
            check_type = cs.check_type if cs else "readyz"
            check_mode = cs.check_mode if cs else "manual"

        targets = [t for t in all_targets if t.status not in ("provisioning", "error")]

        if not all_targets:
            await self._mark_session_failed(sid)
            await self._push_session_to_ui(sid)
            return

        if not targets:
            return

        now = utc_now()
        async with rx.asession() as db:
            for target in targets:
                target_result = await db.execute(
                    select(SessionTarget).where(SessionTarget.id == target.id)
                )
                t = target_result.scalars().first()
                if t:
                    t.status = "checking"
                    t.check_started_at = now
                    db.add(t)
            await db.commit()

        await self._push_session_to_ui(sid)

        semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
        last_ui_push = time.monotonic()
        ui_push_interval = 1.0

        async def maybe_push_ui():
            nonlocal last_ui_push
            elapsed = time.monotonic() - last_ui_push
            if elapsed >= ui_push_interval:
                last_ui_push = time.monotonic()
                await self._push_session_to_ui(sid)

        async def process_target(target: SessionTarget, client):
            try:
                async with semaphore:
                    try:
                        result = await check_single_target(
                            target.url, check_type, check_mode, client=client,
                        )
                    except Exception as e:
                        result = TargetCheckResult(
                            url=target.url, check_type=check_type,
                            error_message=str(e)[:500],
                        )

                completed_at = utc_now()
                status = (
                    "healthy" if result.is_healthy
                    else "degraded" if result.is_degraded
                    else "error" if result.error_message
                    else "unhealthy"
                )

                async with rx.asession() as db:
                    target_result = await db.execute(
                        select(SessionTarget).where(SessionTarget.id == target.id)
                    )
                    t = target_result.scalars().first()
                    if t:
                        t.status = status
                        t.tier_used = result.tier_used
                        t.response_time_ms = result.response_time_ms
                        t.error_message = result.error_message
                        t.check_completed_at = completed_at
                        db.add(t)

                    cr = CheckResult(
                        target_id=target.id,
                        check_type=f"{check_type}_{'delegate' if result.tier_used == 1 else 'local'}",
                        tier=result.tier_used,
                        is_healthy=result.is_healthy,
                        status_code=result.status_code,
                        response_time_ms=result.response_time_ms,
                        error_message=result.error_message,
                        detail=result.detail_json(),
                        checked_at=completed_at,
                    )
                    db.add(cr)
                    await db.commit()

                await maybe_push_ui()

            except Exception as e:
                logger.exception("Error checking target %s: %s", target.url, e)
                async with rx.asession() as db:
                    target_result = await db.execute(
                        select(SessionTarget).where(SessionTarget.id == target.id)
                    )
                    t = target_result.scalars().first()
                    if t:
                        t.status = "error"
                        t.error_message = str(e)[:500]
                        t.check_completed_at = utc_now()
                        db.add(t)
                        await db.commit()

        async with create_client(verify_ssl=VERIFY_SSL) as client:
            await asyncio.gather(*[process_target(t, client) for t in targets])

    async def _finalize_session(self, sid: str) -> None:
        """Set final session status based on target results.

        Provisioning targets (no showroom URL yet) count as not-healthy,
        so the session is marked ``failed`` when any targets are still provisioning.
        """
        async with rx.asession() as session:
            cs_result = await session.execute(
                select(CheckSession).where(CheckSession.session_id == sid)
            )
            cs = cs_result.scalars().first()
            targets_result = await session.execute(
                select(SessionTarget).where(SessionTarget.session_id == sid)
            )
            final_targets = list(targets_result.scalars().all())
            checkable = [t for t in final_targets if t.status != "provisioning"]
            has_provisioning = any(t.status == "provisioning" for t in final_targets)
            all_healthy = (
                not has_provisioning
                and bool(checkable)
                and all(t.status == "healthy" for t in checkable)
            )
            if cs:
                cs.status = "completed" if all_healthy else "failed"
                cs.completed_at = utc_now()
                session.add(cs)
                await session.commit()

        await self._push_session_to_ui(sid)

    @staticmethod
    async def _mark_session_failed(sid: str) -> None:
        async with rx.asession() as session:
            cs_result = await session.execute(
                select(CheckSession).where(CheckSession.session_id == sid)
            )
            cs = cs_result.scalars().first()
            if cs:
                cs.status = "failed"
                cs.completed_at = utc_now()
                session.add(cs)
                await session.commit()

    async def _push_session_to_ui(self, sid: str) -> None:
        """Fetch session data from DB, then acquire state lock only for assignment."""
        data = await _fetch_session_data(sid)
        summaries = _build_check_summaries(data["results"])
        async with self:
            if self.current_session_id == sid:
                self.current_session = data["session"]
                self.current_targets = data["targets"]
                self.current_results = data["results"]
                self.target_check_summaries = summaries
