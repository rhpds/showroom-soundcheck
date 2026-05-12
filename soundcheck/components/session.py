"""Session page content — targets list, loading states, and page layout."""

import reflex as rx

from .. import styles
from ..state import SessionState
from .session_summary import check_progress, session_summary
from .target import target_detail_dialog, target_row


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
                    check_progress(),
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
