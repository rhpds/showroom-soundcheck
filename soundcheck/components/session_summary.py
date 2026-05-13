"""Session summary card and progress indicator components."""

import reflex as rx

from .. import styles
from ..state import GroupState, SessionState


def _resource_details() -> rx.Component:
    """Inline details about the resolved Workshop or ResourceClaim."""
    return rx.hstack(
        rx.badge(
            rx.match(
                SessionState.current_session.resource_kind,
                ("ResourcePool", "Pool"),
                SessionState.current_session.resource_kind,
            ),
            variant="solid",
            color_scheme=rx.match(
                SessionState.current_session.resource_kind,
                ("Workshop", "blue"),
                ("ResourcePool", "orange"),
                "purple",
            ),
            size="1",
        ),
        rx.foreach(
            SessionState.session_source_guids_raw,
            lambda g: rx.badge(
                g,
                variant="outline",
                color_scheme=rx.match(
                    SessionState.current_session.resource_kind,
                    ("Workshop", "blue"),
                    ("ResourcePool", "orange"),
                    "purple",
                ),
                size="1",
            ),
        ),
        rx.cond(
            SessionState.session_catalog_url != "",
            rx.link(
                rx.hstack(
                    rx.text(
                        SessionState.current_session.resource_namespace
                        + "/"
                        + SessionState.current_session.resource_name,
                        size="2",
                        weight="medium",
                    ),
                    rx.icon("external-link", size=12),
                    spacing="1",
                    align="center",
                ),
                href=SessionState.session_catalog_url,
                is_external=True,
            ),
            rx.text(
                SessionState.current_session.resource_namespace
                + "/"
                + SessionState.current_session.resource_name,
                size="2",
                weight="medium",
                color=rx.color("gray", 11),
            ),
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


def _group_breadcrumb() -> rx.Component:
    """Back-to-group link shown when the session belongs to a group (hidden in drawer)."""
    return rx.cond(
        SessionState.session_parent_group.contains("id")
        & ~GroupState.show_session_preview,
        rx.link(
            rx.hstack(
                rx.icon("arrow-left", size=14),
                rx.icon("folder", size=14, color=rx.color("accent", 9)),
                rx.text(
                    SessionState.session_parent_group["name"],
                    size="2",
                    weight="medium",
                ),
                spacing="2",
                align="center",
            ),
            href="/group/" + SessionState.session_parent_group["id"],
            style={
                "text_decoration": "none",
                "color": rx.color("gray", 11),
                "_hover": {"color": rx.color("accent", 11)},
            },
        ),
    )


def session_summary() -> rx.Component:
    return rx.cond(
        SessionState.current_session,
        rx.card(
            rx.vstack(
                _group_breadcrumb(),
                rx.hstack(
                    rx.heading(
                        rx.cond(
                            SessionState.current_session.name != "",
                            SessionState.current_session.name,
                            "Health Check Session",
                        ),
                        size="5",
                        min_width="0",
                        style={"word_break": "break-word"},
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
                            rx.cond(
                                GroupState.show_session_preview,
                                rx.button(
                                    rx.icon("rotate-ccw", size=14),
                                    rx.text("Re-run"),
                                    variant="outline",
                                    color_scheme="blue",
                                    size="2",
                                    on_click=GroupState.retry_preview_session,
                                ),
                                rx.button(
                                    rx.icon("rotate-ccw", size=14),
                                    rx.text("Retry"),
                                    variant="outline",
                                    color_scheme="blue",
                                    size="2",
                                    on_click=SessionState.clone_session,
                                ),
                            ),
                        ),
                        spacing="2",
                        align="center",
                        flex_shrink="0",
                    ),
                    width="100%",
                    align="center",
                    flex_wrap="wrap",
                    gap="2",
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
                        SessionState.guid_resolution["started"].to(bool)
                        & (SessionState.guid_resolution["ws_total"].to(int) > 0),
                        rx.hstack(
                            rx.text("·", color="gray"),
                            rx.text(
                                SessionState.guid_resolution["ws_resolved"].to(str)
                                + "/"
                                + SessionState.guid_resolution["ws_total"].to(str)
                                + " Workshop GUIDs resolved",
                                size="2",
                                weight="medium",
                                color=rx.cond(
                                    SessionState.guid_resolution["ws_resolved"].to(int)
                                    == SessionState.guid_resolution["ws_total"].to(int),
                                    rx.color("green", 11),
                                    rx.color("red", 11),
                                ),
                            ),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    rx.cond(
                        SessionState.guid_resolution["started"].to(bool)
                        & (SessionState.guid_resolution["rc_total"].to(int) > 0),
                        rx.hstack(
                            rx.text("·", color="gray"),
                            rx.text(
                                SessionState.guid_resolution["rc_resolved"].to(str)
                                + "/"
                                + SessionState.guid_resolution["rc_total"].to(str)
                                + " ResourceClaim GUIDs resolved",
                                size="2",
                                weight="medium",
                                color=rx.cond(
                                    SessionState.guid_resolution["rc_resolved"].to(int)
                                    == SessionState.guid_resolution["rc_total"].to(int),
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
                        SessionState.current_session.created_at,
                        rx.text(
                            rx.moment(
                                date=SessionState.current_session.created_at,
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
                    SessionState.current_session.resource_kind != "",
                    _resource_details(),
                ),
                rx.cond(
                    (SessionState.current_session.resource_kind == "")
                    & (SessionState.session_source_guids.length() > 0),
                    rx.hstack(
                        rx.text("GUIDs:", size="1", color="gray", weight="bold"),
                        rx.foreach(
                            SessionState.session_workshop_guids_prefixed,
                            lambda g: rx.badge(g, variant="outline", color_scheme="blue", size="1"),
                        ),
                        rx.foreach(
                            SessionState.session_rc_guids,
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


def check_progress() -> rx.Component:
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
