"""Session page content — summary card, targets list, and detail dialog."""

import reflex as rx

from .. import styles
from ..state import SessionState, local_time
from .target import target_detail_dialog, target_row


def _resource_details() -> rx.Component:
    """Inline details about the resolved Workshop or ResourceClaim."""
    return rx.hstack(
        rx.badge(
            SessionState.session_resource_kind,
            variant="solid",
            color_scheme="purple",
            size="1",
        ),
        rx.text(
            SessionState.session_resource_namespace + "/" + SessionState.session_resource_name,
            size="2",
            weight="medium",
            color=rx.color("gray", 11),
        ),
        rx.cond(
            SessionState.current_session.babylon_cluster != "",
            rx.badge(
                SessionState.current_session.babylon_cluster,
                variant="outline",
                color_scheme="blue",
                size="1",
            ),
        ),
        spacing="2",
        align="center",
        flex_wrap="wrap",
    )


def session_summary() -> rx.Component:
    return rx.cond(
        SessionState.current_session,
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.heading(
                        rx.cond(
                            SessionState.current_session.name != "",
                            SessionState.current_session.name,
                            "Health Check Session",
                        ),
                        size="5",
                    ),
                    rx.spacer(),
                    rx.hstack(
                        rx.match(
                            SessionState.current_session.status,
                            ("completed", rx.badge("All Passed", color_scheme="green", variant="solid", size="2")),
                            ("failed", rx.badge("Issues Found", color_scheme="red", variant="solid", size="2")),
                            ("running", rx.badge(
                                rx.hstack(rx.icon("loader", size=14, style=styles.spin_style), rx.text("Running"), spacing="1", align="center"),
                                color_scheme="blue", variant="solid", size="2",
                            )),
                            ("pending", rx.badge("Pending", color_scheme="yellow", variant="solid", size="2")),
                            rx.badge(SessionState.current_session.status, color_scheme="gray", variant="solid", size="2"),
                        ),
                        rx.cond(
                            (SessionState.current_session.status == "completed")
                            | (SessionState.current_session.status == "failed"),
                            rx.button(
                                rx.icon("rotate-ccw", size=14),
                                rx.text("Retry"),
                                variant="outline",
                                color_scheme="blue",
                                size="2",
                                on_click=SessionState.clone_session,
                            ),
                        ),
                        spacing="2",
                        align="center",
                    ),
                    width="100%",
                    align="center",
                ),
                rx.hstack(
                    rx.text(
                        SessionState.target_counts["healthy"].to(str)
                        + " healthy",
                        size="2",
                        weight="medium",
                        color=rx.cond(
                            SessionState.target_counts["healthy"].to(int) > 0,
                            rx.color("green", 11),
                            "inherit",
                        ),
                    ),
                    rx.cond(
                        SessionState.target_counts["degraded"].to(int) > 0,
                        rx.hstack(
                            rx.text("·", color="gray"),
                            rx.text(
                                SessionState.target_counts["degraded"].to(str)
                                + " degraded",
                                size="2",
                                weight="medium",
                                color=rx.color("yellow", 11),
                            ),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    rx.cond(
                        SessionState.target_counts["error"].to(int) > 0,
                        rx.hstack(
                            rx.text("·", color="gray"),
                            rx.text(
                                SessionState.target_counts["error"].to(str)
                                + " error",
                                size="2",
                                weight="medium",
                                color=rx.color("red", 11),
                            ),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    rx.text(
                        "/ "
                        + SessionState.target_counts["checkable"].to(str)
                        + " Showroom UIs",
                        size="2",
                        weight="medium",
                        color="gray",
                    ),
                    rx.cond(
                        SessionState.guid_resolution_started
                        & (SessionState.workshop_guid_total_count > 0),
                        rx.hstack(
                            rx.text("·", color="gray"),
                            rx.text(
                                SessionState.workshop_guid_resolved_count.to(str)
                                + "/"
                                + SessionState.workshop_guid_total_count.to(str)
                                + " Workshop GUIDs resolved",
                                size="2",
                                weight="medium",
                                color=rx.cond(
                                    SessionState.workshop_guid_resolved_count
                                    == SessionState.workshop_guid_total_count,
                                    rx.color("green", 11),
                                    rx.color("red", 11),
                                ),
                            ),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    rx.cond(
                        SessionState.guid_resolution_started
                        & (SessionState.rc_guid_total_count > 0),
                        rx.hstack(
                            rx.text("·", color="gray"),
                            rx.text(
                                SessionState.rc_guid_resolved_count.to(str)
                                + "/"
                                + SessionState.rc_guid_total_count.to(str)
                                + " ResourceClaim GUIDs resolved",
                                size="2",
                                weight="medium",
                                color=rx.cond(
                                    SessionState.rc_guid_resolved_count
                                    == SessionState.rc_guid_total_count,
                                    rx.color("green", 11),
                                    rx.color("red", 11),
                                ),
                            ),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                ),
                rx.hstack(
                    rx.text("Type: " + SessionState.current_session.check_type, size="2", color="gray"),
                    rx.text("·", color="gray"),
                    rx.text("Mode: " + SessionState.current_session.check_mode, size="2", color="gray"),
                    rx.text("·", color="gray"),
                    rx.cond(
                        SessionState.session_created_at != "",
                        rx.text(
                            rx.moment(
                                date=SessionState.session_created_at,
                                from_now=True,
                                with_title=True,
                                title_format="MMM D [at] h:mm:ss A",
                            ),
                            size="2",
                            color="gray",
                        ),
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.cond(
                    SessionState.session_resource_kind != "",
                    _resource_details(),
                ),
                rx.cond(
                    (SessionState.session_resource_kind == "")
                    & (SessionState.session_source_guids.length() > 0),
                    rx.hstack(
                        rx.text("GUIDs:", size="1", color="gray", weight="bold"),
                        rx.foreach(
                            SessionState.session_source_guids,
                            lambda g: rx.badge(g, variant="outline", color_scheme="purple", size="1"),
                        ),
                        rx.cond(
                            SessionState.current_session.babylon_cluster != "",
                            rx.badge(
                                SessionState.current_session.babylon_cluster,
                                variant="outline", color_scheme="blue", size="1",
                            ),
                        ),
                        spacing="2",
                        align="center",
                    ),
                ),
                spacing="3",
                width="100%",
            ),
            **styles.card_style,
        ),
    )


def _targets_empty_state() -> rx.Component:
    """Show a loading indicator while running, or a 'not found' message when done."""
    is_active = (SessionState.current_session.status == "pending") | (
        SessionState.current_session.status == "running"
    )
    return rx.cond(
        SessionState.current_session,
        rx.cond(
            is_active,
            rx.center(
                rx.vstack(
                    rx.icon("loader", size=32, color=rx.color("blue", 9), style=styles.spin_style),
                    rx.text("Resolving targets…", size="3", color=rx.color("blue", 11)),
                    rx.text(
                        "Looking up GUIDs and discovering showroom URLs. "
                        "Targets will appear here as they are found.",
                        size="2", color="gray", text_align="center", max_width="400px",
                    ),
                    spacing="2",
                    align="center",
                    padding="2em",
                ),
            ),
            rx.center(
                rx.vstack(
                    rx.icon("search", size=32, color=rx.color("gray", 8)),
                    rx.text("No targets found", size="3", color="gray"),
                    rx.text(
                        "No showroom URLs were resolved for this session. "
                        "Check that the URLs or GUIDs are correct.",
                        size="2", color="gray",
                    ),
                    spacing="2",
                    align="center",
                    padding="2em",
                ),
            ),
        ),
    )


def _check_progress() -> rx.Component:
    """Progress indicator shown while checks are actively running."""
    return rx.cond(
        SessionState.checks_in_progress & (SessionState.target_counts["total"].to(int) > 0),
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.icon("loader", size=16, color=rx.color("blue", 9), style=styles.spin_style),
                    rx.text(
                        "Checking "
                        + SessionState.target_counts["checked"].to(str)
                        + " of "
                        + SessionState.target_counts["total"].to(str)
                        + " targets…",
                        size="2",
                        weight="medium",
                        color=rx.color("blue", 11),
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.progress(
                    value=SessionState.target_counts["checked"].to(int) * 100 / rx.cond(
                        SessionState.target_counts["total"].to(int) > 0,
                        SessionState.target_counts["total"].to(int),
                        1,
                    ),
                    width="100%",
                    color_scheme="blue",
                ),
                spacing="2",
                width="100%",
            ),
            **styles.card_style,
        ),
    )


def _tab_label(label: str, count: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2"),
        rx.cond(
            count > 0,
            rx.badge(count.to(str), variant="soft", size="1"),
        ),
        spacing="1",
        align="center",
    )


def targets_list() -> rx.Component:
    return rx.cond(
        SessionState.current_targets.length() > 0,
        rx.card(
            rx.vstack(
                rx.tabs.root(
                    rx.tabs.list(
                        rx.tabs.trigger(
                            _tab_label("All", SessionState.target_counts["total"].to(int)),
                            value="all",
                        ),
                        rx.tabs.trigger(
                            _tab_label("Issues", SessionState.target_counts["issues"].to(int)),
                            value="issues",
                        ),
                        rx.tabs.trigger(
                            _tab_label("Healthy", SessionState.target_counts["healthy"].to(int)),
                            value="healthy",
                        ),
                        rx.tabs.trigger(
                            _tab_label("In Progress", SessionState.in_progress_targets.length()),
                            value="in_progress",
                        ),
                    ),
                    rx.tabs.content(
                        rx.foreach(SessionState.sorted_targets, target_row),
                        value="all",
                    ),
                    rx.tabs.content(
                        rx.cond(
                            SessionState.issue_targets.length() > 0,
                            rx.foreach(SessionState.issue_targets, target_row),
                            rx.center(
                                rx.text("No issues found", size="2", color="gray", padding="2em"),
                            ),
                        ),
                        value="issues",
                    ),
                    rx.tabs.content(
                        rx.cond(
                            SessionState.healthy_targets.length() > 0,
                            rx.foreach(SessionState.healthy_targets, target_row),
                            rx.center(
                                rx.text("No healthy targets yet", size="2", color="gray", padding="2em"),
                            ),
                        ),
                        value="healthy",
                    ),
                    rx.tabs.content(
                        rx.cond(
                            SessionState.in_progress_targets.length() > 0,
                            rx.foreach(SessionState.in_progress_targets, target_row),
                            rx.center(
                                rx.text("No checks in progress", size="2", color="gray", padding="2em"),
                            ),
                        ),
                        value="in_progress",
                    ),
                    value=SessionState.target_filter,
                    on_change=SessionState.set_target_filter,
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
            **styles.card_style,
        ),
        _targets_empty_state(),
    )


def _session_loading() -> rx.Component:
    """Full-viewport loading screen with a pulsing activity icon."""
    return rx.center(
        rx.vstack(
            rx.icon(
                "activity",
                size=64,
                color=rx.color("accent", 9),
                style=styles.pulse_style,
            ),
            rx.text(
                "Soundcheck",
                size="5",
                weight="bold",
                color=rx.color("accent", 11),
            ),
            rx.text(
                "Loading session…",
                size="2",
                color=rx.color("gray", 9),
            ),
            spacing="3",
            align="center",
        ),
        flex="1",
    )


def _session_not_found() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon("circle_x", size=48, color=rx.color("red", 9)),
            rx.heading("Session not found", size="5"),
            rx.text(
                "The session you're looking for doesn't exist or has been removed.",
                size="3",
                color="gray",
                text_align="center",
            ),
            spacing="4",
            align="center",
            max_width="400px",
        ),
        flex="1",
    )


def session_content() -> rx.Component:
    return rx.el.main(
        rx.cond(
            SessionState.session_loading,
            _session_loading(),
            rx.cond(
                SessionState.current_session,
                rx.vstack(
                    session_summary(),
                    _check_progress(),
                    targets_list(),
                    spacing="4",
                    width="100%",
                ),
                _session_not_found(),
            ),
        ),
        target_detail_dialog(),
        **styles.content_style,
    )
