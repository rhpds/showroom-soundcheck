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
from .models import CheckResult, CheckSession, GroupRun, SessionGroup, SessionTarget
from .utils import (
    InputValidationError,
    make_display_label,
    normalize_check_mode,
    normalize_check_type,
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
    group_id: Optional[str] = None,
    group_run_id: Optional[str] = None,
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
            group_id=group_id or None,
            group_run_id=group_run_id or None,
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
    async with rx.asession() as session:
        cs = (await session.execute(session_q)).scalars().first()
        targets = list((await session.execute(targets_q)).scalars().all())
        target_ids = [t.id for t in targets]
        results: list[CheckResult] = []
        if target_ids:
            results_q = (
                select(CheckResult)
                .where(CheckResult.target_id.in_(target_ids))  # type: ignore
                .order_by(col(CheckResult.checked_at).desc())
            )
            results = list((await session.execute(results_q)).scalars().all())
    return {"session": cs, "targets": targets, "results": results}


async def _load_all_sessions_async() -> list[CheckSession]:
    async with rx.asession() as session:
        result = await session.execute(
            select(CheckSession).order_by(col(CheckSession.created_at).desc()).limit(100)
        )
        return list(result.scalars().all())


async def _load_all_groups_async() -> list[SessionGroup]:
    async with rx.asession() as session:
        result = await session.execute(
            select(SessionGroup).order_by(col(SessionGroup.created_at).desc()).limit(100)
        )
        return list(result.scalars().all())


async def _batch_load_run_data(
    db_session, run_ids: list[str],
) -> tuple[dict[str, list[CheckSession]], dict[str, list[SessionTarget]]]:
    """Load all sessions and targets for a set of run IDs in batch queries.

    Returns (run_sessions, targets_by_session) without N+1 query overhead.
    """
    run_sessions: dict[str, list[CheckSession]] = {}
    targets_map: dict[str, list[SessionTarget]] = {}
    if not run_ids:
        return run_sessions, targets_map

    all_cs_result = await db_session.execute(
        select(CheckSession)
        .where(CheckSession.group_run_id.in_(run_ids))  # type: ignore
        .order_by(col(CheckSession.created_at).asc())
    )
    all_cs = list(all_cs_result.scalars().all())

    for cs in all_cs:
        run_sessions.setdefault(cs.group_run_id or "", []).append(cs)

    session_ids = [cs.session_id for cs in all_cs]
    if session_ids:
        all_targets_result = await db_session.execute(
            select(SessionTarget).where(
                SessionTarget.session_id.in_(session_ids)  # type: ignore
            )
        )
        for t in all_targets_result.scalars().all():
            targets_map.setdefault(t.session_id, []).append(t)

    return run_sessions, targets_map


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


def _build_catalog_url(cluster: str, meta: dict) -> str:
    """Build a Babylon catalog URL from member metadata."""
    if not cluster:
        return ""
    name = meta.get("name", "")
    namespace = meta.get("namespace", "")
    if not name:
        return ""
    base = babylon_client.get_catalog_url(cluster)
    if not base:
        return ""
    kind = meta.get("kind", "")
    if kind == "Workshop":
        return f"{base}/workshops/{namespace}/{name}"
    if kind == "ResourcePool":
        return f"{base}/admin/resourcepools/{name}/details"
    return f"{base}/services/{namespace}/{name}"


async def _lookup_member_metadata(
    member_type: str, member_value: str, cluster: str,
) -> dict:
    """Look up Kubernetes metadata for a single group member."""
    ctx = ResolutionContext()
    try:
        if member_type == "rc_guid":
            rc_def, resolved = await lookup_rc_by_guid(
                member_value, cluster=cluster, ctx=ctx,
            )
            if rc_def:
                meta = extract_resource_claim_metadata(rc_def)
                meta["cluster"] = resolved or cluster
                meta["catalog_url"] = _build_catalog_url(resolved or cluster, meta)
                return meta
        elif member_type == "workshop_guid":
            ws_def, resolved = await lookup_workshop_by_guid(
                member_value, cluster=cluster, ctx=ctx,
            )
            if ws_def:
                meta = extract_workshop_metadata(ws_def)
                meta["cluster"] = resolved or cluster
                meta["catalog_url"] = _build_catalog_url(resolved or cluster, meta)
                return meta
        elif member_type == "pool":
            pool_def, resolved = await lookup_resource_pool(
                member_value, cluster=cluster,
            )
            if pool_def:
                meta = extract_resource_pool_metadata(pool_def)
                meta["cluster"] = resolved or cluster
                meta["catalog_url"] = _build_catalog_url(resolved or cluster, meta)
                return meta
    except Exception as e:
        logger.warning("Failed to lookup %s '%s': %s", member_type, member_value, e)
    return {}


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
    all_groups: list[SessionGroup] = []

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
            groups_result = await session.execute(
                select(SessionGroup).order_by(col(SessionGroup.created_at).desc()).limit(100)
            )
            self.all_groups = list(groups_result.scalars().all())

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
            return f"{base}/admin/resourcepools/{cs.resource_name}/details"
        return f"{base}/services/{cs.resource_namespace}/{cs.resource_name}"

    @rx.var
    def _session_time_buckets(self) -> dict[str, list[CheckSession]]:
        """Single-pass partition of all_sessions into time-based buckets.

        Keys: today (last 24h), yesterday (24-48h), older (>48h).
        """
        now = utc_now()
        recent_cutoff = now - timedelta(hours=24)
        earlier_cutoff = now - timedelta(hours=48)
        today: list[CheckSession] = []
        yesterday: list[CheckSession] = []
        older: list[CheckSession] = []
        for s in self.all_sessions:
            if not s.created_at:
                older.append(s)
            elif s.created_at >= recent_cutoff:
                today.append(s)
            elif s.created_at >= earlier_cutoff:
                yesterday.append(s)
            else:
                older.append(s)
        return {"today": today, "yesterday": yesterday, "older": older}

    @rx.var
    def today_sessions(self) -> list[CheckSession]:
        return self._session_time_buckets["today"]

    @rx.var
    def yesterday_sessions(self) -> list[CheckSession]:
        return self._session_time_buckets["yesterday"]

    @rx.var
    def older_sessions(self) -> list[CheckSession]:
        return self._session_time_buckets["older"]

    # ---------- Sidebar items (groups + ungrouped sessions) ----------

    # ---------- Pin / unpin sidebar items ----------

    @rx.event
    async def toggle_pin(self, kind: str, item_id: str):
        """Toggle the pinned state of a sidebar item."""
        if kind == "group":
            async with rx.asession() as session:
                result = await session.execute(
                    select(SessionGroup).where(SessionGroup.group_id == item_id)
                )
                grp = result.scalars().first()
                if grp:
                    grp.pinned = not grp.pinned
                    session.add(grp)
                    await session.commit()
            self.all_groups = await _load_all_groups_async()
        else:
            async with rx.asession() as session:
                result = await session.execute(
                    select(CheckSession).where(CheckSession.session_id == item_id)
                )
                cs = result.scalars().first()
                if cs:
                    cs.pinned = not cs.pinned
                    session.add(cs)
                    await session.commit()
            self.all_sessions = await _load_all_sessions_async()

    @rx.var
    def _sidebar_items_buckets(self) -> dict[str, list[dict]]:
        """Merge groups and ungrouped sessions into time-bucketed sidebar items.

        Each item is a dict with keys: kind ("group" | "session"), id,
        name, label, status, created_at, pinned.
        Pinned items are separated into their own bucket.
        """
        now = utc_now()
        recent_cutoff = now - timedelta(hours=24)
        earlier_cutoff = now - timedelta(hours=48)
        grouped_session_ids: set[str] = set()
        for s in self.all_sessions:
            if s.group_id:
                grouped_session_ids.add(s.session_id)

        items: list[dict] = []
        for g in self.all_groups:
            member_count = (
                len(g.get_guids()) + len(g.get_workshop_guids()) + len(g.get_resource_pools())
            )
            items.append({
                "kind": "group",
                "id": g.group_id,
                "name": g.name or "Unnamed Group",
                "label": f"{member_count} member{'s' if member_count != 1 else ''}",
                "status": g.status,
                "created_at": _serialize_dt(g.created_at) if g.created_at else "",
                "pinned": g.pinned,
            })
        for s in self.all_sessions:
            if s.session_id in grouped_session_ids:
                continue
            items.append({
                "kind": "session",
                "id": s.session_id,
                "name": s.name,
                "label": s.display_label or s.source_urls,
                "status": s.status,
                "created_at": _serialize_dt(s.created_at) if s.created_at else "",
                "pinned": s.pinned,
            })

        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        pinned: list[dict] = []
        today: list[dict] = []
        yesterday: list[dict] = []
        older: list[dict] = []
        for item in items:
            if item.get("pinned"):
                pinned.append(item)
                continue
            ca = item.get("created_at", "")
            if not ca:
                older.append(item)
                continue
            try:
                dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                older.append(item)
                continue
            if dt >= recent_cutoff:
                today.append(item)
            elif dt >= earlier_cutoff:
                yesterday.append(item)
            else:
                older.append(item)
        return {"pinned": pinned, "today": today, "yesterday": yesterday, "older": older}

    @rx.var
    def sidebar_pinned(self) -> list[dict]:
        return self._sidebar_items_buckets["pinned"]

    @rx.var
    def sidebar_today(self) -> list[dict]:
        return self._sidebar_items_buckets["today"]

    @rx.var
    def sidebar_yesterday(self) -> list[dict]:
        return self._sidebar_items_buckets["yesterday"]

    @rx.var
    def sidebar_older(self) -> list[dict]:
        return self._sidebar_items_buckets["older"]

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

    @rx.var
    def session_parent_group(self) -> dict[str, str]:
        """Return {id, name} of the group this session belongs to, or empty dict."""
        cs = self.current_session
        if not cs or not cs.group_id:
            return {}
        for g in self.all_groups:
            if g.group_id == cs.group_id:
                return {"id": g.group_id, "name": g.name or "Unnamed Group"}
        return {"id": cs.group_id, "name": "Group"}


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
    active_form: str = ""

    @rx.event
    def show_check_form(self):
        self.active_form = "check"

    @rx.event
    def show_group_form(self):
        self.active_form = "group"

    @rx.event
    def hide_form(self):
        self.active_form = ""

    @rx.event
    def reset_form_lock(self):
        """Clear stale submit lock and error when navigating back to the home page."""
        self.form_submitting = False
        self.form_error = ""

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
# GroupState — group page data + management
# ---------------------------------------------------------------------------


class GroupState(SessionState):
    """State for viewing and managing session groups."""

    current_group: Optional[SessionGroup] = None
    current_group_id: str = ""
    group_runs: list[GroupRun] = []
    group_run_sessions: dict[str, list[CheckSession]] = {}
    group_targets_by_session: dict[str, list[SessionTarget]] = {}
    group_loading: bool = True
    group_checking: bool = False
    expanded_run_ids: list[str] = []
    sources_expanded: bool = False

    add_member_error: str = ""
    show_add_member: bool = False

    preview_session_id: str = ""
    show_session_preview: bool = False

    editing_group_name: bool = False
    edit_name_value: str = ""

    syncing_members: bool = False

    # Keys of members whose single check was just triggered (for UI feedback).
    # Format: "type:value". Cleared after a few seconds.
    started_member_keys: list[str] = []
    confirm_remove_open: bool = False
    pending_remove_type: str = ""
    pending_remove_value: str = ""

    @rx.event
    def start_editing_name(self):
        if self.current_group:
            self.edit_name_value = self.current_group.name
            self.editing_group_name = True

    @rx.event
    def cancel_editing_name(self):
        self.editing_group_name = False
        self.edit_name_value = ""

    @rx.event
    async def save_group_name(self, form_data: dict):
        new_name = (form_data.get("group_name") or "").strip()
        if not new_name or not self.current_group:
            self.editing_group_name = False
            return

        gid = self.current_group.group_id
        async with rx.asession() as session:
            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp = grp_result.scalars().first()
            if grp:
                grp.name = new_name
                session.add(grp)
                await session.commit()
                self.current_group = grp

        self.editing_group_name = False
        self.edit_name_value = ""
        self.all_groups = await _load_all_groups_async()

    @rx.var
    def page_group_id(self) -> str:
        route_group_id = getattr(self, "group_id", "")
        if route_group_id:
            return route_group_id
        path = self.router.url.path or ""
        if path.startswith("/group/"):
            return path.removeprefix("/group/").split("/", 1)[0]
        return ""

    @rx.event
    def on_group_load(self):
        self.group_loading = True
        switching_group = self.current_group_id != self.page_group_id
        self.current_group = None
        self.group_runs = []
        self.group_run_sessions = {}
        self.group_targets_by_session = {}
        if switching_group:
            self.expanded_run_ids = []
        self.add_member_error = ""
        return [
            GroupState.load_group,
            SessionState.load_sessions,
        ]

    @rx.event
    async def load_group(self):
        gid = self.page_group_id
        if not gid:
            self.current_group = None
            self.current_group_id = ""
            self.group_runs = []
            self.group_run_sessions = {}
            self.group_targets_by_session = {}
            self.group_loading = False
            return

        self.current_group_id = gid
        async with rx.asession() as session:
            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            self.current_group = grp_result.scalars().first()

            runs_result = await session.execute(
                select(GroupRun)
                .where(GroupRun.group_id == gid)
                .order_by(col(GroupRun.created_at).desc())
            )
            self.group_runs = list(runs_result.scalars().all())

            run_ids = [r.run_id for r in self.group_runs]
            run_sessions, targets_map = await _batch_load_run_data(session, run_ids)
            self.group_run_sessions = run_sessions
            self.group_targets_by_session = targets_map

        self.group_loading = False

        if self.current_group:
            has_members = bool(
                self.current_group.get_guids()
                or self.current_group.get_workshop_guids()
                or self.current_group.get_resource_pools()
            )
            if has_members and not self.current_group.get_member_metadata():
                return GroupState.sync_member_details

    # ---------- Member management ----------

    @rx.var
    def group_members(self) -> list[dict]:
        """Flat list of group members with metadata for rendering."""
        if not self.current_group:
            return []
        meta_map = self.current_group.get_member_metadata()
        members: list[dict] = []

        for g in self.current_group.get_guids():
            meta = meta_map.get(f"rc_guid:{g}", {})
            display_name = meta.get("display_name", "") or meta.get("catalog_item", "")
            members.append({
                "type": "rc_guid",
                "value": g,
                "display_name": display_name,
                "resource_name": meta.get("name", ""),
                "resource_namespace": meta.get("namespace", ""),
                "catalog_url": meta.get("catalog_url", ""),
                "cluster": meta.get("cluster", ""),
                "extra_info": meta.get("state", ""),
                "has_meta": bool(meta),
            })

        for g in self.current_group.get_workshop_guids():
            meta = meta_map.get(f"workshop_guid:{g}", {})
            display_name = meta.get("display_name", "") or meta.get("catalog_item", "")
            extra_parts: list[str] = []
            if meta.get("users_assigned") or meta.get("users_total"):
                extra_parts.append(
                    f"{meta.get('users_assigned', 0)}/{meta.get('users_total', '?')} users"
                )
            if meta.get("provision_active"):
                extra_parts.append(f"{meta['provision_active']} active")
            members.append({
                "type": "workshop_guid",
                "value": g,
                "display_name": display_name,
                "resource_name": meta.get("name", ""),
                "resource_namespace": meta.get("namespace", ""),
                "catalog_url": meta.get("catalog_url", ""),
                "cluster": meta.get("cluster", ""),
                "extra_info": " · ".join(extra_parts),
                "has_meta": bool(meta),
            })

        for p in self.current_group.get_resource_pools():
            meta = meta_map.get(f"pool:{p}", {})
            display_name = meta.get("catalog_item", "")
            extra_parts = []
            avail = meta.get("handles_available")
            total = meta.get("handles_total")
            if avail is not None or total is not None:
                extra_parts.append(f"{avail or 0}/{total or 0} handles")
            members.append({
                "type": "pool",
                "value": p,
                "display_name": display_name,
                "resource_name": meta.get("name", ""),
                "resource_namespace": meta.get("namespace", ""),
                "catalog_url": meta.get("catalog_url", ""),
                "cluster": meta.get("cluster", ""),
                "extra_info": " · ".join(extra_parts),
                "has_meta": bool(meta),
            })

        return members

    @rx.var
    def member_type_summary(self) -> list[dict]:
        """Summary counts per source type for the collapsed sources view."""
        if not self.current_group:
            return []
        counts: dict[str, int] = {}
        for m in self.group_members:
            t = m.get("type", "other")
            counts[t] = counts.get(t, 0) + 1
        labels = {
            "workshop_guid": ("Workshop", "blue"),
            "rc_guid": ("ResourceClaim", "purple"),
            "pool": ("Pool", "orange"),
        }
        result = []
        for t, n in counts.items():
            label, color = labels.get(t, (t, "gray"))
            display = (label + "s") if n != 1 else label
            result.append({"type": t, "label": display, "color_scheme": color, "count": n})
        return result

    @rx.event
    def toggle_sources_expanded(self):
        self.sources_expanded = not self.sources_expanded

    @rx.event
    async def add_member(self, form_data: dict):
        member_type = (form_data.get("member_type") or "").strip()
        member_value = (form_data.get("member_value") or "").strip()
        if not member_value:
            self.add_member_error = "Value is required"
            return
        if not self.current_group:
            return

        gid = self.current_group.group_id
        async with rx.asession() as session:
            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp = grp_result.scalars().first()
            if not grp:
                return

            if member_type == "rc_guid":
                items = grp.get_guids()
                if member_value not in items:
                    items.append(member_value)
                    grp.source_guids = json.dumps(items)
            elif member_type == "workshop_guid":
                items = grp.get_workshop_guids()
                if member_value not in items:
                    items.append(member_value)
                    grp.source_workshop_guids = json.dumps(items)
            elif member_type == "pool":
                items = grp.get_resource_pools()
                if member_value not in items:
                    items.append(member_value)
                    grp.source_resource_pools = json.dumps(items)

            session.add(grp)
            await session.commit()
            self.current_group = grp

        self.add_member_error = ""
        self.show_add_member = False
        self.all_groups = await _load_all_groups_async()
        return GroupState.sync_member_details

    @rx.event
    async def remove_member(self, member_type: str, member_value: str):
        if not self.current_group:
            return
        gid = self.current_group.group_id
        async with rx.asession() as session:
            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp = grp_result.scalars().first()
            if not grp:
                return

            if member_type == "rc_guid":
                items = [g for g in grp.get_guids() if g != member_value]
                grp.source_guids = json.dumps(items)
            elif member_type == "workshop_guid":
                items = [g for g in grp.get_workshop_guids() if g != member_value]
                grp.source_workshop_guids = json.dumps(items)
            elif member_type == "pool":
                items = [p for p in grp.get_resource_pools() if p != member_value]
                grp.source_resource_pools = json.dumps(items)

            session.add(grp)
            await session.commit()
            self.current_group = grp

        self.all_groups = await _load_all_groups_async()

    # ---------- Member confirm remove ----------

    @rx.event
    def request_remove_member(self, member_type: str, member_value: str):
        """Open the confirm dialog before removing a member."""
        self.pending_remove_type = member_type
        self.pending_remove_value = member_value
        self.confirm_remove_open = True

    @rx.event
    def set_confirm_remove_open(self, is_open: bool):
        self.confirm_remove_open = is_open

    @rx.event
    def set_show_add_member(self, is_open: bool):
        self.show_add_member = is_open
        if not is_open:
            self.add_member_error = ""

    @rx.event
    async def confirm_remove_member(self):
        """Remove the pending member after user confirmation."""
        self.confirm_remove_open = False
        member_type = self.pending_remove_type
        member_value = self.pending_remove_value
        self.pending_remove_type = ""
        self.pending_remove_value = ""

        if not self.current_group or not member_type or not member_value:
            return

        gid = self.current_group.group_id
        async with rx.asession() as session:
            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp = grp_result.scalars().first()
            if not grp:
                return

            if member_type == "rc_guid":
                items = [g for g in grp.get_guids() if g != member_value]
                grp.source_guids = json.dumps(items)
            elif member_type == "workshop_guid":
                items = [g for g in grp.get_workshop_guids() if g != member_value]
                grp.source_workshop_guids = json.dumps(items)
            elif member_type == "pool":
                items = [p for p in grp.get_resource_pools() if p != member_value]
                grp.source_resource_pools = json.dumps(items)

            meta_key = f"{member_type}:{member_value}"
            try:
                meta_map = json.loads(grp.member_metadata or "{}")
                meta_map.pop(meta_key, None)
                grp.member_metadata = json.dumps(meta_map, default=str)
            except (json.JSONDecodeError, TypeError):
                pass

            session.add(grp)
            await session.commit()
            self.current_group = grp

        self.all_groups = await _load_all_groups_async()

    @rx.var
    def pending_remove_display(self) -> str:
        if not self.pending_remove_type or not self.pending_remove_value:
            return ""
        type_labels = {"rc_guid": "RC", "workshop_guid": "Workshop", "pool": "Pool"}
        return f"{type_labels.get(self.pending_remove_type, self.pending_remove_type)}: {self.pending_remove_value}"

    # ---------- Sync member metadata ----------

    @rx.event(background=True)
    async def sync_member_details(self):
        """Look up metadata for all group members from Kubernetes."""
        async with self:
            if self.syncing_members:
                return
            self.syncing_members = True
            grp = self.current_group
            gid = self.current_group_id

        if not grp:
            async with self:
                self.syncing_members = False
            return

        cluster = grp.babylon_cluster or ""
        meta_map: dict[str, dict] = {}

        for guid in grp.get_guids():
            meta = await _lookup_member_metadata("rc_guid", guid, cluster)
            if meta:
                meta_map[f"rc_guid:{guid}"] = meta

        for ws_guid in grp.get_workshop_guids():
            meta = await _lookup_member_metadata("workshop_guid", ws_guid, cluster)
            if meta:
                meta_map[f"workshop_guid:{ws_guid}"] = meta

        for pool in grp.get_resource_pools():
            meta = await _lookup_member_metadata("pool", pool, cluster)
            if meta:
                meta_map[f"pool:{pool}"] = meta

        async with rx.asession() as session:
            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp_db = grp_result.scalars().first()
            if grp_db:
                grp_db.member_metadata = json.dumps(meta_map, default=str)
                session.add(grp_db)
                await session.commit()

        async with rx.asession() as db:
            grp_result = await db.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            updated_grp = grp_result.scalars().first()

        groups = await _load_all_groups_async()
        async with self:
            self.syncing_members = False
            if self.current_group_id == gid:
                self.current_group = updated_grp
            self.all_groups = groups

    # ---------- Run checks ----------

    @rx.event(background=True)
    async def run_group_checks(self):
        """Run checks for all members in the group."""
        async with self:
            if self.group_checking:
                return
            self.group_checking = True
            grp = self.current_group
            gid = self.current_group_id

        if not grp:
            async with self:
                self.group_checking = False
            return

        run_id = str(uuid.uuid4())
        now = utc_now()

        async with rx.asession() as session:
            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp_db = grp_result.scalars().first()
            if not grp_db:
                async with self:
                    self.group_checking = False
                return

            grp_db.status = "running"
            session.add(grp_db)

            group_run = GroupRun(
                run_id=run_id,
                group_id=gid,
                status="running",
                created_at=now,
            )
            session.add(group_run)
            await session.commit()

        rc_guids = grp.get_guids()
        ws_guids = grp.get_workshop_guids()
        pools = grp.get_resource_pools()
        check_type = grp.check_type or "readyz"
        check_mode = grp.check_mode or "manual"
        cluster = grp.babylon_cluster or ""

        session_ids: list[str] = []
        try:
            for guid in rc_guids:
                sid = await _persist_new_session(
                    name=f"RC: {guid}",
                    check_type=check_type,
                    check_mode=check_mode,
                    urls=[],
                    guids=[guid],
                    babylon_cluster=cluster,
                    group_id=gid,
                    group_run_id=run_id,
                )
                session_ids.append(sid)

            for ws_guid in ws_guids:
                sid = await _persist_new_session(
                    name=f"Workshop: {ws_guid}",
                    check_type=check_type,
                    check_mode=check_mode,
                    urls=[],
                    guids=[],
                    workshop_guids=[ws_guid],
                    babylon_cluster=cluster,
                    group_id=gid,
                    group_run_id=run_id,
                )
                session_ids.append(sid)

            for pool in pools:
                sid = await _persist_new_session(
                    name=f"Pool: {pool}",
                    check_type=check_type,
                    check_mode=check_mode,
                    urls=[],
                    guids=[],
                    resource_pools=[pool],
                    babylon_cluster=cluster,
                    group_id=gid,
                    group_run_id=run_id,
                )
                session_ids.append(sid)

            await self._push_group_to_ui(gid)

            # Re-enable the "Run All Checks" button after a short cooldown
            # so the user gets confirmation it fired, without waiting for
            # all checks to finish.
            async def _clear_group_checking():
                await asyncio.sleep(5)
                async with self:
                    self.group_checking = False

            asyncio.create_task(_clear_group_checking())

            for sid in session_ids:
                await _mark_session_running_db(sid)
                await _resolve_session_targets(sid)
                await self._push_group_to_ui(gid)
                await _execute_session_checks(
                    sid, push_fn=lambda: self._push_group_to_ui(gid),
                )
                await _finalize_session_status(sid)
                await self._push_group_to_ui(gid)

            await self._finalize_group_run(run_id, gid)
        except Exception as e:
            logger.exception("Error running group checks for %s: %s", gid, e)
            for sid in session_ids:
                await _mark_session_failed_db(sid)
            await self._finalize_group_run(run_id, gid, force_failed=True)
        finally:
            sessions = await _load_all_sessions_async()
            groups = await _load_all_groups_async()
            async with self:
                self.group_checking = False
                self.all_sessions = sessions
                self.all_groups = groups

    @rx.event(background=True)
    async def run_single_member_check(self, member_type: str, member_value: str):
        """Run checks for a single member of the group."""
        member_key = f"{member_type}:{member_value}"
        async with self:
            if member_key in self.started_member_keys:
                return
            self.started_member_keys = [*self.started_member_keys, member_key]
            grp = self.current_group
            gid = self.current_group_id

        if not grp:
            async with self:
                self.started_member_keys = [
                    k for k in self.started_member_keys if k != member_key
                ]
            return

        run_id = str(uuid.uuid4())
        now = utc_now()

        async with rx.asession() as session:
            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp_db = grp_result.scalars().first()
            if not grp_db:
                return

            grp_db.status = "running"
            session.add(grp_db)

            group_run = GroupRun(
                run_id=run_id,
                group_id=gid,
                status="running",
                created_at=now,
            )
            session.add(group_run)
            await session.commit()

        check_type = grp.check_type or "readyz"
        check_mode = grp.check_mode or "manual"
        cluster = grp.babylon_cluster or ""

        try:
            if member_type == "rc_guid":
                sid = await _persist_new_session(
                    name=f"RC: {member_value}",
                    check_type=check_type, check_mode=check_mode,
                    urls=[], guids=[member_value],
                    babylon_cluster=cluster,
                    group_id=gid, group_run_id=run_id,
                )
            elif member_type == "workshop_guid":
                sid = await _persist_new_session(
                    name=f"Workshop: {member_value}",
                    check_type=check_type, check_mode=check_mode,
                    urls=[], guids=[], workshop_guids=[member_value],
                    babylon_cluster=cluster,
                    group_id=gid, group_run_id=run_id,
                )
            elif member_type == "pool":
                sid = await _persist_new_session(
                    name=f"Pool: {member_value}",
                    check_type=check_type, check_mode=check_mode,
                    urls=[], guids=[], resource_pools=[member_value],
                    babylon_cluster=cluster,
                    group_id=gid, group_run_id=run_id,
                )
            else:
                return

            await self._push_group_to_ui(gid)

            async def _clear_started_key():
                await asyncio.sleep(5)
                async with self:
                    self.started_member_keys = [
                        k for k in self.started_member_keys if k != member_key
                    ]

            asyncio.create_task(_clear_started_key())

            await _mark_session_running_db(sid)
            await _resolve_session_targets(sid)
            await _execute_session_checks(
                sid, push_fn=lambda: self._push_group_to_ui(gid),
            )
            await _finalize_session_status(sid)
            await self._finalize_group_run(run_id, gid)
        except Exception as e:
            logger.exception("Error running single check for %s/%s: %s", member_type, member_value, e)
            await self._finalize_group_run(run_id, gid, force_failed=True)
        finally:
            sessions = await _load_all_sessions_async()
            groups = await _load_all_groups_async()
            async with self:
                self.started_member_keys = [
                    k for k in self.started_member_keys if k != member_key
                ]
                self.all_sessions = sessions
                self.all_groups = groups

    async def _finalize_group_run(
        self, run_id: str, gid: str, *, force_failed: bool = False,
    ) -> None:
        """Set final status on the GroupRun and the SessionGroup."""
        async with rx.asession() as session:
            run_result = await session.execute(
                select(GroupRun).where(GroupRun.run_id == run_id)
            )
            run = run_result.scalars().first()

            sessions_result = await session.execute(
                select(CheckSession).where(CheckSession.group_run_id == run_id)
            )
            run_sessions = list(sessions_result.scalars().all())

            if force_failed:
                run_status = "failed"
            elif not run_sessions:
                run_status = "completed"
            else:
                statuses = [s.status for s in run_sessions]
                if all(st == "completed" for st in statuses):
                    run_status = "completed"
                else:
                    run_status = "failed"

            if run:
                run.status = run_status
                run.completed_at = utc_now()
                session.add(run)

            grp_result = await session.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp = grp_result.scalars().first()
            if grp:
                grp.status = run_status
                session.add(grp)

            await session.commit()

        await self._push_group_to_ui(gid)

    async def _push_group_to_ui(self, gid: str) -> None:
        """Reload group data from DB and push to state."""
        async with rx.asession() as db:
            grp_result = await db.execute(
                select(SessionGroup).where(SessionGroup.group_id == gid)
            )
            grp = grp_result.scalars().first()

            runs_result = await db.execute(
                select(GroupRun)
                .where(GroupRun.group_id == gid)
                .order_by(col(GroupRun.created_at).desc())
            )
            runs = list(runs_result.scalars().all())

            run_ids = [r.run_id for r in runs]
            run_sessions, targets_map = await _batch_load_run_data(db, run_ids)

        async with self:
            if self.current_group_id == gid:
                self.current_group = grp
                self.group_runs = runs
                self.group_run_sessions = run_sessions
                self.group_targets_by_session = targets_map

    # ---------- Expand/collapse ----------

    @rx.event
    def toggle_run_expand(self, run_id: str):
        if run_id in self.expanded_run_ids:
            self.expanded_run_ids = [r for r in self.expanded_run_ids if r != run_id]
        else:
            self.expanded_run_ids = self.expanded_run_ids + [run_id]

    # ---------- Session preview drawer ----------

    @rx.event
    async def open_session_preview(self, session_id: str):
        self.preview_session_id = session_id
        self.show_session_preview = True
        self.session_loading = True
        self.target_filter = "all"

        data = await _fetch_session_data(session_id)
        self.current_session = data["session"]
        self.current_targets = data["targets"]
        self.current_results = data["results"]
        self.target_check_summaries = _build_check_summaries(data["results"])
        self.session_loading = False

    def _clear_preview_state(self):
        self.show_session_preview = False
        self.preview_session_id = ""
        self.current_session = None
        self.current_targets = []
        self.current_results = []
        self.target_check_summaries = {}

    @rx.event
    def close_session_preview(self):
        self._clear_preview_state()

    @rx.event
    def set_session_preview_open(self, is_open: bool):
        if not is_open:
            self._clear_preview_state()

    @rx.event
    def retry_preview_session(self):
        """Re-run the previewed session's member check within the group."""
        cs = self.current_session
        if not cs:
            return
        member_type = ""
        member_value = ""
        ws_guids = cs.get_workshop_guids()
        rc_guids = cs.get_guids()
        pools = cs.get_resource_pools()
        if ws_guids:
            member_type = "workshop_guid"
            member_value = ws_guids[0]
        elif rc_guids:
            member_type = "rc_guid"
            member_value = rc_guids[0]
        elif pools:
            member_type = "pool"
            member_value = pools[0]
        if not member_type:
            return

        self._clear_preview_state()
        return GroupState.run_single_member_check(member_type, member_value)

    # ---------- Computed vars ----------

    @rx.var
    def group_status(self) -> str:
        if not self.current_group:
            return "pending"
        return self.current_group.status

    @rx.var
    def group_target_counts(self) -> dict[str, int]:
        """Aggregate target counts across all sessions in the latest run."""
        counts: dict[str, int] = {
            "healthy": 0, "degraded": 0, "error": 0,
            "total": 0, "checkable": 0, "sessions": 0,
        }
        if not self.group_runs:
            return counts
        latest_run = self.group_runs[0]
        run_cs = self.group_run_sessions.get(latest_run.run_id, [])
        counts["sessions"] = len(run_cs)
        for cs in run_cs:
            for t in self.group_targets_by_session.get(cs.session_id, []):
                counts["total"] += 1
                if t.url or t.status == "provisioning":
                    counts["checkable"] += 1
                if t.status == "healthy":
                    counts["healthy"] += 1
                elif t.status == "degraded":
                    counts["degraded"] += 1
                elif t.status in ("error", "unhealthy"):
                    counts["error"] += 1
        return counts

    @rx.var
    def group_run_summaries(self) -> list[dict]:
        """Per-run summary data for the run history list."""
        summaries: list[dict] = []
        for run in self.group_runs:
            run_cs = self.group_run_sessions.get(run.run_id, [])
            total_targets = 0
            healthy = 0
            for cs in run_cs:
                for t in self.group_targets_by_session.get(cs.session_id, []):
                    total_targets += 1
                    if t.status == "healthy":
                        healthy += 1
            expanded = run.run_id in self.expanded_run_ids
            summaries.append({
                "run_id": run.run_id,
                "status": run.status,
                "created_at": _serialize_dt(run.created_at) if run.created_at else "",
                "completed_at": _serialize_dt(run.completed_at) if run.completed_at else "",
                "session_count": len(run_cs),
                "target_count": total_targets,
                "healthy_count": healthy,
                "expanded": expanded,
            })
        return summaries

    @rx.var
    def group_session_summaries(self) -> list[dict]:
        """Per-session summary data for rendering cards inside expanded runs."""
        meta_map = self.current_group.get_member_metadata() if self.current_group else {}
        summaries: list[dict] = []
        for run in self.group_runs:
            for cs in self.group_run_sessions.get(run.run_id, []):
                targets = self.group_targets_by_session.get(cs.session_id, [])
                h = sum(1 for t in targets if t.status == "healthy")
                d = sum(1 for t in targets if t.status == "degraded")
                e = sum(1 for t in targets if t.status in ("error", "unhealthy"))
                ck = sum(1 for t in targets if t.url or t.status == "provisioning")

                member_type = ""
                member_value = ""
                ws_guids = cs.get_workshop_guids()
                rc_guids = cs.get_guids()
                pools = cs.get_resource_pools()
                if ws_guids:
                    member_type = "workshop_guid"
                    member_value = ws_guids[0]
                elif rc_guids:
                    member_type = "rc_guid"
                    member_value = rc_guids[0]
                elif pools:
                    member_type = "pool"
                    member_value = pools[0]

                meta_key = f"{member_type}:{member_value}" if member_type else ""
                meta = meta_map.get(meta_key, {}) if meta_key else {}
                display_name = meta.get("display_name", "") or meta.get("catalog_item", "")
                resource_ns = meta.get("namespace", "")
                resource_name = meta.get("name", "")
                catalog_url = meta.get("catalog_url", "")
                cluster = meta.get("cluster", "")

                summaries.append({
                    "run_id": run.run_id,
                    "session_id": cs.session_id,
                    "name": cs.name or cs.display_label or "Unnamed Session",
                    "status": cs.status,
                    "healthy": h,
                    "degraded": d,
                    "error": e,
                    "checkable": ck,
                    "total": len(targets),
                    "created_at": _serialize_dt(cs.created_at) if cs.created_at else "",
                    "member_type": member_type,
                    "member_value": member_value,
                    "display_name": display_name,
                    "resource_namespace": resource_ns,
                    "resource_name": resource_name,
                    "catalog_url": catalog_url,
                    "cluster": cluster,
                    "has_meta": bool(meta),
                })
        return summaries


class GroupFormState(SessionState):
    """Handles group creation with full settings."""

    group_form_error: str = ""
    group_form_submitting: bool = False

    @rx.event
    async def handle_group_page(self):
        """Called on /group/new page load. Create group from query params and redirect."""
        query = self.router.url.query_parameters
        name = (query.get("name") or "").strip()
        if not name:
            return rx.redirect("/")

        raw_guids = query.get("guid", "")
        raw_ws_guids = query.get("workshop", "")
        raw_pools = query.get("pool", "")
        check_type = normalize_check_type((query.get("type") or "readyz").strip())
        check_mode = normalize_check_mode((query.get("mode") or "manual").strip())
        cluster_raw = (query.get("cluster") or "").strip()
        cluster = "" if cluster_raw == "(auto)" else cluster_raw

        rc_guids = [g.strip() for g in raw_guids.split(",") if g.strip()] if raw_guids else []
        ws_guids = [g.strip() for g in raw_ws_guids.split(",") if g.strip()] if raw_ws_guids else []
        pools = [p.strip() for p in raw_pools.split(",") if p.strip()] if raw_pools else []

        if not rc_guids and not ws_guids and not pools:
            return rx.redirect("/")

        needs_cluster = rc_guids or ws_guids or pools
        if needs_cluster and not babylon_client.get_configured_clusters():
            return rx.redirect("/")

        gid = str(uuid.uuid4())
        now = utc_now()
        async with rx.asession() as session:
            grp = SessionGroup(
                group_id=gid,
                name=name,
                check_type=check_type,
                check_mode=check_mode,
                babylon_cluster=cluster,
                source_guids=json.dumps(rc_guids),
                source_workshop_guids=json.dumps(ws_guids),
                source_resource_pools=json.dumps(pools),
                status="pending",
                created_at=now,
            )
            session.add(grp)
            await session.commit()

        return rx.redirect(f"/group/{gid}")

    @rx.event
    async def create_group(self, form_data: dict):
        if self.group_form_submitting:
            return
        self.group_form_submitting = True

        name = (form_data.get("group_name") or "").strip()
        if not name:
            self.group_form_error = "Group name is required"
            self.group_form_submitting = False
            return

        raw_guids = (form_data.get("rc_guids") or "").strip()
        raw_ws_guids = (form_data.get("workshop_guids") or "").strip()
        raw_pools = (form_data.get("resource_pools") or "").strip()

        rc_guids = [g.strip() for g in raw_guids.splitlines() if g.strip()] if raw_guids else []
        ws_guids = [g.strip() for g in raw_ws_guids.splitlines() if g.strip()] if raw_ws_guids else []
        pools = [p.strip() for p in raw_pools.splitlines() if p.strip()] if raw_pools else []

        if not rc_guids and not ws_guids and not pools:
            self.group_form_error = "Add at least one GUID or pool"
            self.group_form_submitting = False
            return

        check_type = form_data.get("check_type") or "readyz"
        check_mode = form_data.get("check_mode") or "manual"
        cluster_raw = form_data.get("babylon_cluster") or ""
        cluster = "" if cluster_raw == "(auto)" else cluster_raw

        needs_cluster = rc_guids or ws_guids or pools
        if needs_cluster and not babylon_client.get_configured_clusters():
            self.group_form_error = "No Babylon clusters configured — cannot resolve GUIDs or ResourcePools"
            self.group_form_submitting = False
            return

        self.group_form_error = ""
        gid = str(uuid.uuid4())
        now = utc_now()
        async with rx.asession() as session:
            grp = SessionGroup(
                group_id=gid,
                name=name,
                check_type=check_type,
                check_mode=check_mode,
                babylon_cluster=cluster,
                source_guids=json.dumps(rc_guids),
                source_workshop_guids=json.dumps(ws_guids),
                source_resource_pools=json.dumps(pools),
                status="pending",
                created_at=now,
            )
            session.add(grp)
            await session.commit()

        self.group_form_submitting = False
        return rx.redirect(f"/group/{gid}")


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
# Check pipeline — module-level helpers shared by session and group runners
# ---------------------------------------------------------------------------


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


def _resolved_target(
    sid: str,
    entry: dict[str, str],
    *,
    fallback_label: str,
    guid: Optional[str] = None,
    workshop_guid: Optional[str] = None,
    resolution_error_prefix: str,
) -> SessionTarget:
    status, err_msg, prov_status = _status_for_resolution_entry(
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


async def _populate_workshop_metadata(
    sid: str, ws_guid: str, cluster: str, ctx: ResolutionContext,
) -> None:
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
    sid: str, guid: str, cluster: str, ctx: ResolutionContext,
) -> None:
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
    sid: str, pool_name: str, cluster: str,
) -> None:
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


async def _resolve_session_targets(sid: str) -> bool:
    """Resolve GUIDs/workshop GUIDs/resource pools and create SessionTarget rows.

    Returns True if any targets were resolved from GUIDs/pools.
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
                    session.add(_not_found_target(sid, guid=guid))
                    continue
                for entry in url_entries:
                    session.add(
                        _resolved_target(
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
            await _populate_rc_metadata(sid, guids[0], cluster, ctx)

    if ws_guids:
        ws_results = await resolve_workshop_guids(ws_guids, cluster=cluster, ctx=ctx)
        async with rx.asession() as session:
            for ws_guid, url_entries in ws_results.items():
                if not url_entries:
                    session.add(_not_found_target(sid, workshop_guid=ws_guid))
                    continue
                for entry in url_entries:
                    session.add(
                        _resolved_target(
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
            await _populate_workshop_metadata(sid, ws_guids[0], cluster, ctx)

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
                        status, err_msg, prov_status = _status_for_resolution_entry(
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
            await _populate_pool_metadata(sid, pools[0], cluster)

    return guid_resolved


async def _execute_session_checks(sid: str, push_fn=None) -> None:
    """Run health checks concurrently for all targets in the session.

    ``push_fn`` is an optional async callback for periodic UI updates.
    """
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
        await _mark_session_failed_db(sid)
        if push_fn:
            await push_fn()
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

    if push_fn:
        await push_fn()

    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    last_ui_push = time.monotonic()
    ui_push_interval = 1.0

    async def maybe_push_ui():
        nonlocal last_ui_push
        if not push_fn:
            return
        elapsed = time.monotonic() - last_ui_push
        if elapsed >= ui_push_interval:
            last_ui_push = time.monotonic()
            await push_fn()

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


async def _finalize_session_status(sid: str) -> None:
    """Set final session status based on target results."""
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


async def _mark_session_failed_db(sid: str) -> None:
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


async def _mark_session_running_db(sid: str) -> bool:
    """Mark session as running if it's still pending. Returns True on success."""
    async with rx.asession() as session:
        session_result = await session.execute(
            select(CheckSession).where(CheckSession.session_id == sid).with_for_update()
        )
        cs = session_result.scalars().first()
        if not cs or cs.status != "pending":
            return False
        cs.status = "running"
        session.add(cs)
        await session.commit()
    return True


# ---------------------------------------------------------------------------
# CheckRunnerState — background check orchestration
# ---------------------------------------------------------------------------


class CheckRunnerState(SessionState):
    """Background task orchestration for health checks."""

    _running_session_id: str = ""

    @rx.event(background=True)
    async def run_checks(self):
        """Background task: resolve GUIDs and run health checks for current session."""
        async with self:
            sid = self.current_session_id
            if not sid:
                return
            if self._running_session_id == sid:
                return
            self._running_session_id = sid

        if not await _mark_session_running_db(sid):
            async with self:
                self._running_session_id = ""
            return

        async def push():
            data = await _fetch_session_data(sid)
            summaries = _build_check_summaries(data["results"])
            async with self:
                if self.current_session_id == sid:
                    self.current_session = data["session"]
                    self.current_targets = data["targets"]
                    self.current_results = data["results"]
                    self.target_check_summaries = summaries

        try:
            await push()
            resolved = await _resolve_session_targets(sid)
            if resolved:
                await push()
            await _execute_session_checks(sid, push_fn=push)
            await _finalize_session_status(sid)
            await push()
        except Exception as e:
            logger.exception("Error running checks for session %s: %s", sid, e)
            await _mark_session_failed_db(sid)
            await push()
        finally:
            sessions = await _load_all_sessions_async()
            groups = await _load_all_groups_async()
            async with self:
                self._running_session_id = ""
                self.all_sessions = sessions
                self.all_groups = groups
