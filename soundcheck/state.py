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
from .babylon_service import ResolutionContext, resolve_guids, resolve_workshop_guids
from .check_service import TargetCheckResult, check_single_target, create_client
from .models import CheckResult, CheckSession, SessionTarget
from .utils import (
    InputValidationError,
    extract_guid_from_url,
    make_display_label,
    parse_check_params,
    utc_now_naive,
)

logger = logging.getLogger(__name__)


# Override Reflex's default datetime serializer so naive-UTC datetimes are
# sent to the browser as proper ISO 8601 with a "Z" suffix.  The default
# uses str() which produces a space separator and no timezone indicator,
# causing Moment.js to misinterpret the value as local time.
@serializer(to=str)
def _serialize_dt(dt: date | datetime) -> str:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.isoformat() + "Z"
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


APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "UTC")
CHECK_CONCURRENCY = _positive_int_env("CHECK_CONCURRENCY", 10)
VERIFY_SSL = os.environ.get("VERIFY_SSL", "true").lower() in ("true", "1", "yes")


def local_time(dt_var: rx.Var, **kwargs: object) -> rx.Component:
    kwargs.setdefault("from_now", True)
    kwargs.setdefault("with_title", True)
    kwargs.setdefault("title_format", "ddd, MMM D YYYY [at] h:mm A")
    return rx.moment(dt_var, **kwargs)


# ---------------------------------------------------------------------------
# Session persistence helper
# ---------------------------------------------------------------------------


def _persist_new_session(
    *,
    name: str,
    check_type: str,
    check_mode: str,
    urls: list[str],
    guids: list[str],
    babylon_cluster: str = "",
    display_label: str = "",
    workshop_guids: Optional[list[str]] = None,
) -> str:
    """Create a new pending session with targets in the database. Returns session_id."""
    workshop_guids = workshop_guids or []
    sid = str(uuid.uuid4())
    now = utc_now_naive()

    with rx.session() as session:
        cs = CheckSession(
            session_id=sid,
            name=name,
            check_type=check_type,
            check_mode=check_mode,
            source_urls=CheckSession.encode_urls(urls),
            source_guids=CheckSession.encode_guids(guids),
            source_workshop_guids=CheckSession.encode_workshop_guids(workshop_guids),
            babylon_cluster=babylon_cluster,
            display_label=display_label or make_display_label(urls, guids, workshop_guids),
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

        session.commit()

    return sid


# ---------------------------------------------------------------------------
# DB helper (shared across substates)
# ---------------------------------------------------------------------------


def _session_data_queries() -> tuple:
    """Return the three SELECT statements used by both sync and async fetch.

    Keeps the query logic in one place so the sync and async variants
    stay consistent.
    """
    session_q = select(CheckSession)
    targets_q = select(SessionTarget)
    results_q = select(CheckResult).order_by(col(CheckResult.checked_at).desc())
    return session_q, targets_q, results_q


def _fetch_session_data(sid: str) -> dict:
    """Sync: load session, targets, results from DB.

    Used by the synchronous ``load_session`` @rx.event handler.
    See ``_fetch_session_data_async`` for the async equivalent.
    """
    sq, tq, rq = _session_data_queries()
    with rx.session() as session:
        cs = session.exec(sq.where(CheckSession.session_id == sid)).first()
        targets = session.exec(tq.where(SessionTarget.session_id == sid)).all()
        target_ids = [t.id for t in targets]
        results: list[CheckResult] = []
        if target_ids:
            results = session.exec(
                rq.where(CheckResult.target_id.in_(target_ids))  # type: ignore
            ).all()
    return {"session": cs, "targets": targets, "results": results}


async def _fetch_session_data_async(sid: str) -> dict:
    """Async: load session, targets, results from DB.

    Used by ``CheckRunnerState._push_session_to_ui`` in background tasks.
    See ``_fetch_session_data`` for the sync equivalent.
    """
    sq, tq, rq = _session_data_queries()
    async with rx.asession() as session:
        cs = (await session.execute(sq.where(CheckSession.session_id == sid))).scalars().first()
        targets = list((await session.execute(tq.where(SessionTarget.session_id == sid))).scalars().all())
        target_ids = [t.id for t in targets]
        results: list[CheckResult] = []
        if target_ids:
            results = list(
                (await session.execute(
                    rq.where(CheckResult.target_id.in_(target_ids))  # type: ignore
                )).scalars().all()
            )
    return {"session": cs, "targets": targets, "results": results}


async def _load_all_sessions_async() -> list[CheckSession]:
    async with rx.asession() as session:
        result = await session.execute(
            select(CheckSession).order_by(col(CheckSession.created_at).desc()).limit(100)
        )
        return list(result.scalars().all())


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

    form_urls: str = ""
    form_guids: str = ""
    form_check_type: str = "readyz"
    form_error: str = ""
    form_submitting: bool = False

    selected_target_id: int = 0
    show_target_detail: bool = False

    @rx.var
    def page_session_id(self) -> str:
        return self.router.page.params.get("session_id", "")

    # ---------- Session history loading ----------

    @rx.event
    def load_sessions(self):
        with rx.session() as session:
            rows = session.exec(
                select(CheckSession).order_by(col(CheckSession.created_at).desc()).limit(100)
            ).all()
            need_commit = False
            for cs in rows:
                if not cs.display_label:
                    cs.display_label = make_display_label(
                        cs.get_urls(), cs.get_guids(), cs.get_workshop_guids(),
                    )
                    session.add(cs)
                    need_commit = True
            if need_commit:
                session.commit()
                rows = session.exec(
                    select(CheckSession).order_by(col(CheckSession.created_at).desc()).limit(100)
                ).all()
            self.all_sessions = rows

    # ---------- Load a specific session ----------

    @rx.event
    def load_session(self):
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
            self.session_loading = False
            return

        self.current_session_id = sid
        data = _fetch_session_data(sid)
        self.current_session = data["session"]
        self.current_targets = data["targets"]
        self.current_results = data["results"]
        self.session_loading = False

        if self.current_session and self.current_session.status == "pending":
            return CheckRunnerState.run_checks

    # ---------- Clone / retry a session ----------

    @rx.event
    def clone_session(self):
        """Create a new pending session cloned from the current one and redirect to it."""
        cs = self.current_session
        if not cs:
            return

        sid = _persist_new_session(
            name=cs.name,
            check_type=cs.check_type,
            check_mode=cs.check_mode,
            urls=cs.get_urls(),
            guids=cs.get_guids(),
            babylon_cluster=cs.babylon_cluster,
            display_label=cs.display_label,
            workshop_guids=cs.get_workshop_guids(),
        )
        return rx.redirect(f"/session/{sid}")

    # ---------- Page on_load handlers ----------

    @rx.event
    def on_session_load(self):
        self.session_loading = True
        return [
            SessionState.load_session,
            SessionState.load_sessions,
        ]

    @rx.event
    def on_home_load(self):
        return [SessionState.load_sessions]

    # ---------- Session-level computed vars ----------

    @rx.var
    def healthy_count(self) -> int:
        return sum(1 for t in self.current_targets if t.status == "healthy")

    @rx.var
    def total_count(self) -> int:
        return len(self.current_targets)

    @rx.var
    def checked_count(self) -> int:
        return sum(
            1 for t in self.current_targets
            if t.status in ("healthy", "unhealthy", "error")
        )

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

    # ---------- Breakdown counts for session summary ----------

    @rx.var
    def showroom_healthy_count(self) -> int:
        """Targets that were actually health-checked and came back healthy."""
        return sum(
            1 for t in self.current_targets
            if t.status == "healthy"
        )

    @rx.var
    def showroom_total_count(self) -> int:
        """Targets that have a URL (i.e. were checkable or are provisioning)."""
        return sum(
            1 for t in self.current_targets
            if t.url or t.status == "provisioning"
        )

    @rx.var
    def guid_resolution_started(self) -> bool:
        """True once at least one target has been created from GUID resolution."""
        if not self.current_session:
            return False
        has_guids = bool(self.current_session.get_guids()) or bool(self.current_session.get_workshop_guids())
        if not has_guids:
            return False
        return any(
            t.guid or t.workshop_guid for t in self.current_targets
        )

    @rx.var
    def workshop_guid_resolved_count(self) -> int:
        if not self.current_session:
            return 0
        ws_guids = self.current_session.get_workshop_guids()
        if not ws_guids:
            return 0
        # A workshop GUID is "resolved" if at least one target from it
        # has a URL or a non-error status (e.g. provisioning, healthy).
        # It only counts as unresolved when *every* target for that GUID
        # is an error placeholder with no URL.
        resolved: set[str] = set()
        seen: set[str] = set()
        for t in self.current_targets:
            if t.workshop_guid:
                seen.add(t.workshop_guid)
                if t.url or t.status != "error":
                    resolved.add(t.workshop_guid)
        return sum(1 for g in ws_guids if g in resolved)

    @rx.var
    def workshop_guid_total_count(self) -> int:
        if not self.current_session:
            return 0
        return len(self.current_session.get_workshop_guids())

    @rx.var
    def rc_guid_resolved_count(self) -> int:
        if not self.current_session:
            return 0
        rc_guids = self.current_session.get_guids()
        if not rc_guids:
            return 0
        resolved: set[str] = set()
        for t in self.current_targets:
            if t.guid and not t.workshop_guid:
                if t.url or t.status != "error":
                    resolved.add(t.guid)
        return sum(1 for g in rc_guids if g in resolved)

    @rx.var
    def rc_guid_total_count(self) -> int:
        if not self.current_session:
            return 0
        return len(self.current_session.get_guids())

    @rx.var
    def session_source_guids(self) -> list[str]:
        if not self.current_session:
            return []
        rc = self.current_session.get_guids()
        ws = [f"ws:{g}" for g in self.current_session.get_workshop_guids()]
        return ws + rc

    @rx.var
    def session_source_urls(self) -> list[str]:
        if not self.current_session:
            return []
        return self.current_session.get_urls()

    @rx.var
    def today_sessions(self) -> list[CheckSession]:
        now = utc_now_naive()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return [s for s in self.all_sessions if s.created_at and s.created_at >= today_start]

    @rx.var
    def yesterday_sessions(self) -> list[CheckSession]:
        now = utc_now_naive()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        return [s for s in self.all_sessions if s.created_at and yesterday_start <= s.created_at < today_start]

    @rx.var
    def older_sessions(self) -> list[CheckSession]:
        now = utc_now_naive()
        yesterday_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        return [s for s in self.all_sessions if s.created_at and s.created_at < yesterday_start]

    @rx.var
    def sorted_targets(self) -> list[SessionTarget]:
        """Targets sorted by status priority, then by check start time."""
        order = {
            "checking": 0,
            "error": 1,
            "provisioning": 2,
            "pending": 3,
            "unhealthy": 4,
            "healthy": 5,
        }

        def sort_key(t: SessionTarget):
            rank = order.get(t.status, 5)
            ts = t.check_started_at or datetime.min
            return (rank, ts)

        return sorted(self.current_targets, key=sort_key)


# ---------------------------------------------------------------------------
# SessionFormState — form handling and session creation
# ---------------------------------------------------------------------------


class SessionFormState(SessionState):
    """Handles session creation from both query params and form submissions."""

    @rx.event
    def handle_check_page(self):
        """Called on /check page load. Create session from query params and redirect."""
        raw_urls = self.router.page.params.get("urls", "")
        raw_guids = self.router.page.params.get("guid", "")
        raw_ws_guids = self.router.page.params.get("workshop", "")
        check_type = self.router.page.params.get("type", "readyz")
        check_mode = self.router.page.params.get("mode", "manual")
        session_name = self.router.page.params.get("name", "")
        cluster = self.router.page.params.get("cluster", "")

        if not raw_urls and not raw_guids and not raw_ws_guids:
            return rx.redirect("/")

        try:
            parsed = parse_check_params(
                raw_urls=raw_urls,
                raw_guids=raw_guids,
                raw_ws_guids=raw_ws_guids,
                check_type=check_type,
                check_mode=check_mode,
                session_name=session_name,
                cluster=cluster,
                url_separator=",",
            )
        except InputValidationError:
            return rx.redirect("/")

        sid = _persist_new_session(
            name=parsed.session_name,
            check_type=parsed.check_type,
            check_mode=parsed.check_mode,
            urls=parsed.urls,
            guids=parsed.guids,
            babylon_cluster=parsed.babylon_cluster,
            workshop_guids=parsed.workshop_guids,
        )
        return rx.redirect(f"/session/{sid}")

    @rx.event
    def create_session_from_form(self, form_data: dict):
        self.form_submitting = True
        try:
            parsed = parse_check_params(
                raw_urls=form_data.get("urls", "").strip(),
                raw_guids=form_data.get("guids", "").strip(),
                raw_ws_guids=form_data.get("workshop_guids", "").strip(),
                check_type=form_data.get("check_type", "readyz"),
                check_mode=form_data.get("check_mode", "manual"),
                session_name=form_data.get("session_name", ""),
                cluster=form_data.get("babylon_cluster", ""),
                url_separator="\n",
            )
        except InputValidationError as e:
            self.form_error = str(e)
            self.form_submitting = False
            return

        if (parsed.guids or parsed.workshop_guids) and not babylon_client.get_configured_clusters():
            self.form_error = "No Babylon clusters configured — cannot resolve GUIDs"
            self.form_submitting = False
            return

        sid = _persist_new_session(
            name=parsed.session_name,
            check_type=parsed.check_type,
            check_mode=parsed.check_mode,
            urls=parsed.urls,
            guids=parsed.guids,
            babylon_cluster=parsed.babylon_cluster,
            workshop_guids=parsed.workshop_guids,
        )

        self.form_error = ""
        self.form_urls = ""
        self.form_guids = ""
        self.form_submitting = False
        return rx.redirect(f"/session/{sid}")


# ---------------------------------------------------------------------------
# TargetDetailState — selected target detail dialog computed vars
# ---------------------------------------------------------------------------


class TargetDetailState(SessionState):
    """Computed vars for the target detail dialog."""

    @rx.event
    def open_target_detail(self, target_id: int):
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
            normalized.append({
                "name": tab.get("name", "unknown"),
                "url": tab.get("url", ""),
                "reachable": bool(tab.get("reachable", False)),
                "status_code": sc,
                "status_ok": 200 <= sc < 400 if sc else False,
                "error": tab.get("error") or "",
                "iframe_blocked": bool(tab.get("iframe_blocked", False) or tab.get("iframeBlocked", False)),
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
            async with self:
                self.all_sessions = await _load_all_sessions_async()

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
            provision_status=prov_status,
            status=status,
            error_message=err_msg,
        )

    async def _resolve_and_create_targets(self, sid: str) -> None:
        """Resolve GUIDs/workshop GUIDs and create SessionTarget rows."""
        async with rx.asession() as session:
            session_result = await session.execute(
                select(CheckSession).where(CheckSession.session_id == sid)
            )
            cs = session_result.scalars().first()
            guids = cs.get_guids() if cs else []
            ws_guids = cs.get_workshop_guids() if cs else []
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

        if guid_resolved:
            await self._push_session_to_ui(sid)

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

        now = utc_now_naive()
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

                completed_at = utc_now_naive()
                status = "healthy" if result.is_healthy else "error" if result.error_message else "unhealthy"

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
                        t.check_completed_at = utc_now_naive()
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
                cs.completed_at = utc_now_naive()
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
                cs.completed_at = utc_now_naive()
                session.add(cs)
                await session.commit()

    async def _push_session_to_ui(self, sid: str) -> None:
        """Fetch session data from DB, then acquire state lock only for assignment."""
        data = await _fetch_session_data_async(sid)
        async with self:
            if self.current_session_id == sid:
                self.current_session = data["session"]
                self.current_targets = data["targets"]
                self.current_results = data["results"]
