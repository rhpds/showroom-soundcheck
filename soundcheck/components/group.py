"""Group detail page — source management, run checks, run history."""

import reflex as rx

from .. import styles
from ..state import GroupState, SessionState
from .session import targets_list
from .session_summary import check_progress, session_summary
from .sidebar import session_status_icon
from .target import target_detail_dialog


# ---------------------------------------------------------------------------
# Group header
# ---------------------------------------------------------------------------


def _group_header() -> rx.Component:
    """Header with group name, status badge, and settings."""
    return rx.cond(
        GroupState.current_group,
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.hstack(
                        rx.icon("folder", size=22, color=rx.color("accent", 9)),
                        rx.cond(
                            GroupState.editing_group_name,
                            rx.form(
                                rx.hstack(
                                    rx.input(
                                        name="group_name",
                                        default_value=GroupState.edit_name_value,
                                        size="2",
                                        auto_focus=True,
                                        style={"font_weight": "bold", "font_size": "var(--font-size-5)"},
                                    ),
                                    rx.icon_button(
                                        rx.icon("check", size=14),
                                        type="submit",
                                        size="1",
                                        variant="ghost",
                                        color_scheme="green",
                                    ),
                                    rx.icon_button(
                                        rx.icon("x", size=14),
                                        size="1",
                                        variant="ghost",
                                        color_scheme="gray",
                                        type="button",
                                        on_click=GroupState.cancel_editing_name,
                                    ),
                                    spacing="2",
                                    align="center",
                                ),
                                on_submit=GroupState.save_group_name,
                            ),
                            rx.hstack(
                                rx.heading(
                                    GroupState.current_group.name,
                                    size="5",
                                ),
                                rx.tooltip(
                                    rx.icon_button(
                                        rx.icon("pencil", size=14),
                                        size="1",
                                        variant="ghost",
                                        color_scheme="gray",
                                        on_click=GroupState.start_editing_name,
                                    ),
                                    content="Rename group",
                                ),
                                spacing="2",
                                align="center",
                            ),
                        ),
                        spacing="2",
                        align="center",
                    ),
                    rx.spacer(),
                    rx.match(
                        GroupState.group_status,
                        ("completed", rx.badge("All Passed", color_scheme="green", variant="solid", size="2")),
                        ("failed", rx.badge("Issues Found", color_scheme="red", variant="solid", size="2")),
                        ("running", rx.badge(
                            rx.hstack(
                                rx.icon("loader", size=14, style=styles.spin_style),
                                rx.text("Running"),
                                spacing="1",
                                align="center",
                            ),
                            color_scheme="blue", variant="solid", size="2",
                        )),
                        ("pending", rx.badge("Pending", color_scheme="yellow", variant="solid", size="2")),
                        rx.badge(GroupState.group_status, color_scheme="gray", variant="solid", size="2"),
                    ),
                    width="100%",
                    align="center",
                ),
                rx.hstack(
                    rx.text(
                        GroupState.group_target_counts["sessions"].to(str)
                        + " sessions",
                        size="2", weight="medium", color="gray",
                    ),
                    rx.text("·", color="gray"),
                    rx.text(
                        GroupState.group_target_counts["healthy"].to(str)
                        + " healthy",
                        size="2", weight="medium",
                        color=rx.cond(
                            GroupState.group_target_counts["healthy"].to(int) > 0,
                            rx.color("green", 11),
                            "inherit",
                        ),
                    ),
                    rx.cond(
                        GroupState.group_target_counts["degraded"].to(int) > 0,
                        rx.hstack(
                            rx.text("·", color="gray"),
                            rx.text(
                                GroupState.group_target_counts["degraded"].to(str) + " degraded",
                                size="2", weight="medium", color=rx.color("yellow", 11),
                            ),
                            spacing="2", align="center",
                        ),
                    ),
                    rx.cond(
                        GroupState.group_target_counts["error"].to(int) > 0,
                        rx.hstack(
                            rx.text("·", color="gray"),
                            rx.text(
                                GroupState.group_target_counts["error"].to(str) + " error",
                                size="2", weight="medium", color=rx.color("red", 11),
                            ),
                            spacing="2", align="center",
                        ),
                    ),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                ),
                rx.hstack(
                    rx.badge(
                        GroupState.current_group.check_type,
                        variant="outline", size="1",
                    ),
                    rx.badge(
                        GroupState.current_group.check_mode,
                        variant="outline", size="1",
                    ),
                    rx.cond(
                        GroupState.current_group.babylon_cluster != "",
                        rx.badge(
                            GroupState.current_group.babylon_cluster,
                            variant="outline", size="1", color_scheme="blue",
                        ),
                    ),
                    rx.cond(
                        GroupState.current_group.created_at,
                        rx.text(
                            rx.moment(
                                date=GroupState.current_group.created_at,
                                from_now=True,
                                with_title=True,
                                title_format="MMM D [at] h:mm:ss A",
                            ),
                            size="2", color="gray",
                        ),
                    ),
                    spacing="2",
                    align="center",
                ),
                spacing="3",
                width="100%",
            ),
            **styles.card_style,
        ),
    )


# ---------------------------------------------------------------------------
# Member list
# ---------------------------------------------------------------------------


def _member_item(member: dict) -> rx.Component:
    """A single member row with details, remove button and individual play button."""
    _ellipsis = {
        "overflow": "hidden",
        "text_overflow": "ellipsis",
        "white_space": "nowrap",
    }
    return rx.hstack(
        rx.match(
            member["type"],
            ("rc_guid", rx.badge("ResourceClaim", color_scheme="purple", variant="surface", size="1")),
            ("workshop_guid", rx.badge("Workshop", color_scheme="blue", variant="surface", size="1")),
            ("pool", rx.badge("Pool", color_scheme="orange", variant="surface", size="1")),
            rx.badge(member["type"], variant="surface", size="1"),
        ),
        rx.cond(
            member["has_meta"].to(bool),
            rx.vstack(
                rx.hstack(
                    rx.text(
                        rx.cond(
                            member["display_name"] != "",
                            member["display_name"],
                            member["value"],
                        ),
                        size="2", weight="bold",
                        overflow="hidden",
                        text_overflow="ellipsis",
                        white_space="nowrap",
                        min_width="0",
                    ),
                    rx.cond(
                        member["cluster"] != "",
                        rx.badge(
                            member["cluster"], variant="outline",
                            color_scheme="blue", size="1", flex_shrink="0",
                        ),
                    ),
                    spacing="2",
                    align="center",
                    overflow="hidden",
                    min_width="0",
                    width="100%",
                ),
                rx.cond(
                    (member["display_name"] != "") | (member["resource_namespace"] != ""),
                    rx.hstack(
                        rx.cond(
                            (member["display_name"] != "")
                            & (member["value"] != member["resource_name"]),
                            rx.text(
                                member["value"], size="1", color=rx.color("gray", 10),
                                flex_shrink="0",
                            ),
                        ),
                        rx.cond(
                            member["resource_namespace"] != "",
                            rx.cond(
                                member["catalog_url"] != "",
                                rx.link(
                                    member["resource_namespace"].to(str)
                                    + "/"
                                    + member["resource_name"].to(str),
                                    href=member["catalog_url"],
                                    is_external=True,
                                    size="1",
                                    color=rx.color("accent", 10),
                                    overflow="hidden",
                                    text_overflow="ellipsis",
                                    white_space="nowrap",
                                    min_width="0",
                                ),
                                rx.text(
                                    member["resource_namespace"].to(str)
                                    + "/"
                                    + member["resource_name"].to(str),
                                    size="1", color=rx.color("gray", 10),
                                    overflow="hidden",
                                    text_overflow="ellipsis",
                                    white_space="nowrap",
                                    min_width="0",
                                ),
                            ),
                        ),
                        spacing="2",
                        align="center",
                        overflow="hidden",
                        min_width="0",
                        width="100%",
                    ),
                ),
                spacing="0",
                flex="1",
                min_width="0",
                overflow="hidden",
                width="100%",
            ),
            rx.text(
                member["value"], size="2", weight="medium",
                flex="1", min_width="0",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
            ),
        ),
        rx.spacer(),
        rx.hstack(
            rx.cond(
                GroupState.started_member_keys.contains(
                    member["type"].to(str) + ":" + member["value"].to(str)
                ),
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("check", size=18),
                        size="1",
                        variant="ghost",
                        color_scheme="green",
                        disabled=True,
                    ),
                    content="Check started",
                ),
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("play", size=18),
                        size="1",
                        variant="ghost",
                        color_scheme="green",
                        on_click=GroupState.run_single_member_check(
                            member["type"], member["value"],
                        ),
                    ),
                    content="Run check for this source",
                ),
            ),
            rx.tooltip(
                rx.icon_button(
                    rx.icon("x", size=18),
                    size="1",
                    variant="ghost",
                    color_scheme="red",
                    on_click=GroupState.request_remove_member(
                        member["type"], member["value"],
                    ),
                ),
                content="Remove from group",
            ),
            spacing="1",
            align="center",
            flex_shrink="0",
        ),
        spacing="2",
        align="center",
        padding="0.5em 0.75em",
        border_radius="var(--radius-2)",
        bg=rx.color("gray", 2),
        width="100%",
    )


def _add_member_dialog() -> rx.Component:
    """Modal dialog for adding a member to the group."""
    return rx.dialog.root(
        rx.dialog.trigger(
            rx.button(
                rx.icon("plus", size=14),
                "Add Source",
                size="2",
                variant="outline",
                color_scheme="blue",
            ),
        ),
        rx.dialog.content(
            rx.dialog.title("Add Source"),
            rx.form(
                rx.vstack(
                    rx.el.label("Type", style=styles.label_style),
                    rx.el.select(
                        rx.el.option("Workshop GUID", value="workshop_guid"),
                        rx.el.option("Pool Name", value="pool"),
                        rx.el.option("ResourceClaim GUID", value="rc_guid"),
                        name="member_type",
                        style={
                            "padding": "0.4em 0.5em",
                            "border_radius": "var(--radius-2)",
                            "background": rx.color("gray", 3),
                            "border": f"1px solid {rx.color('gray', 5)}",
                            "color": "inherit",
                            "font_size": "var(--font-size-2)",
                            "width": "100%",
                        },
                    ),
                    rx.el.label("Value", style=styles.label_style),
                    rx.input(
                        placeholder="Enter GUID or pool name",
                        name="member_value",
                        size="2",
                        width="100%",
                        auto_focus=True,
                        **styles.input_style,
                    ),
                    rx.cond(
                        GroupState.add_member_error != "",
                        rx.callout(
                            GroupState.add_member_error,
                            icon="triangle_alert",
                            color_scheme="red",
                            size="1",
                        ),
                    ),
                    rx.flex(
                        rx.dialog.close(
                            rx.button(
                                "Cancel",
                                variant="soft",
                                color_scheme="gray",
                            ),
                        ),
                        rx.button(
                            rx.icon("plus", size=14),
                            "Add",
                            type="submit",
                            color_scheme="blue",
                        ),
                        spacing="3",
                        justify="end",
                        width="100%",
                        margin_top="0.5em",
                    ),
                    spacing="3",
                    width="100%",
                ),
                on_submit=GroupState.add_member,
                reset_on_submit=True,
            ),
            style={"max_width": "420px"},
        ),
        open=GroupState.show_add_member,
        on_open_change=GroupState.set_show_add_member,
    )


def _member_type_badge(summary: dict) -> rx.Component:
    """Compact badge showing count for a single source type."""
    return rx.badge(
        summary["count"].to(str) + " " + summary["label"].to(str),
        color_scheme=summary["color_scheme"],
        variant="surface",
        size="2",
    )


def _member_list() -> rx.Component:
    """Card showing group members with add/remove controls."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.box(
                    rx.hstack(
                        rx.icon("blocks", size=18, color=rx.color("accent", 9), flex_shrink="0"),
                        rx.text(
                            "Sources", size="3", weight="bold",
                            white_space="nowrap",
                        ),
                        rx.badge(
                            GroupState.group_members.length().to(str),
                            variant="soft",
                            size="1",
                            flex_shrink="0",
                        ),
                        rx.icon(
                            rx.cond(GroupState.sources_expanded, "chevron-up", "chevron-down"),
                            size=16,
                            color=rx.color("gray", 9),
                            flex_shrink="0",
                        ),
                        spacing="2",
                        align="center",
                        cursor="pointer",
                    ),
                    on_click=GroupState.toggle_sources_expanded,
                    overflow="hidden",
                    min_width="0",
                    flex="1",
                ),
                rx.hstack(
                    rx.tooltip(
                        rx.icon_button(
                            rx.cond(
                                GroupState.syncing_members,
                                rx.icon("loader", size=14, style=styles.spin_style),
                                rx.icon("refresh-cw", size=14),
                            ),
                            size="1",
                            variant="ghost",
                            color_scheme="gray",
                            on_click=GroupState.sync_member_details,
                            disabled=GroupState.syncing_members,
                        ),
                        content="Sync source details",
                    ),
                    _add_member_dialog(),
                    rx.button(
                        rx.cond(
                            GroupState.group_checking,
                            rx.hstack(
                                rx.icon("loader", size=14, style=styles.spin_style),
                                rx.text("Running…"),
                                spacing="2", align="center",
                            ),
                            rx.hstack(
                                rx.icon("play", size=14),
                                rx.text("Run All Checks"),
                                spacing="2", align="center",
                            ),
                        ),
                        color_scheme="blue",
                        size="2",
                        on_click=GroupState.run_group_checks,
                        disabled=GroupState.group_checking,
                    ),
                    spacing="2",
                    align="center",
                    flex_shrink="0",
                ),
                width="100%",
                align="center",
            ),
            rx.cond(
                GroupState.group_members.length() > 0,
                rx.cond(
                    GroupState.sources_expanded,
                    rx.vstack(
                        rx.foreach(GroupState.group_members, _member_item),
                        spacing="1",
                        width="100%",
                    ),
                    rx.hstack(
                        rx.foreach(GroupState.member_type_summary, _member_type_badge),
                        spacing="2",
                        align="center",
                        flex_wrap="wrap",
                    ),
                ),
                rx.center(
                    rx.text("No sources yet — use 'Add Source' above", size="2", color="gray"),
                    padding="1em",
                ),
            ),
            spacing="3",
            width="100%",
        ),
        **styles.card_style,
    )


# ---------------------------------------------------------------------------
# Run history
# ---------------------------------------------------------------------------


def _session_card(summary: dict) -> rx.Component:
    """Clickable card for a single session within a run — opens the preview drawer."""
    return rx.card(
        rx.hstack(
            session_status_icon(summary["status"]),
            rx.match(
                summary["member_type"],
                ("rc_guid", rx.badge("ResourceClaim", color_scheme="purple", variant="surface", size="1")),
                ("workshop_guid", rx.badge("Workshop", color_scheme="blue", variant="surface", size="1")),
                ("pool", rx.badge("Pool", color_scheme="orange", variant="surface", size="1")),
                rx.badge(summary["member_type"], variant="surface", size="1"),
            ),
            rx.vstack(
                rx.cond(
                    summary["display_name"] != "",
                    rx.text(
                        summary["display_name"], size="2", weight="bold",
                        overflow="hidden",
                        text_overflow="ellipsis",
                        white_space="nowrap",
                    ),
                    rx.text(
                        summary["name"], size="2", weight="medium",
                        overflow="hidden",
                        text_overflow="ellipsis",
                        white_space="nowrap",
                    ),
                ),
                rx.cond(
                    (summary["display_name"] != "") | (summary["resource_namespace"] != ""),
                    rx.hstack(
                        rx.cond(
                            (summary["display_name"] != "")
                            & (summary["member_value"] != summary["resource_name"]),
                            rx.text(
                                summary["member_value"], size="1", color=rx.color("gray", 10),
                                flex_shrink="0",
                            ),
                        ),
                        rx.cond(
                            summary["resource_namespace"] != "",
                            rx.cond(
                                summary["catalog_url"] != "",
                                rx.link(
                                    summary["resource_namespace"].to(str)
                                    + "/"
                                    + summary["resource_name"].to(str),
                                    href=summary["catalog_url"],
                                    is_external=True,
                                    size="1",
                                    color=rx.color("accent", 10),
                                    overflow="hidden",
                                    text_overflow="ellipsis",
                                    white_space="nowrap",
                                    min_width="0",
                                ),
                                rx.text(
                                    summary["resource_namespace"].to(str)
                                    + "/"
                                    + summary["resource_name"].to(str),
                                    size="1", color=rx.color("gray", 10),
                                    overflow="hidden",
                                    text_overflow="ellipsis",
                                    white_space="nowrap",
                                    min_width="0",
                                ),
                            ),
                        ),
                        spacing="2",
                        align="center",
                        overflow="hidden",
                        min_width="0",
                        width="100%",
                    ),
                ),
                spacing="1",
                flex="1",
                min_width="0",
                overflow="hidden",
                width="100%",
            ),
            rx.spacer(),
            rx.hstack(
                rx.text(
                    summary["healthy"].to(str) + " healthy",
                    size="1",
                    color=rx.cond(
                        summary["healthy"].to(int) > 0,
                        rx.color("green", 11),
                        "gray",
                    ),
                ),
                rx.cond(
                    summary["degraded"].to(int) > 0,
                    rx.text(
                        summary["degraded"].to(str) + " degraded",
                        size="1", color=rx.color("yellow", 11),
                    ),
                ),
                rx.cond(
                    summary["error"].to(int) > 0,
                    rx.text(
                        summary["error"].to(str) + " error",
                        size="1", color=rx.color("red", 11),
                    ),
                ),
                rx.text(
                    "/ " + summary["checkable"].to(str) + " targets",
                    size="1", color="gray",
                ),
                spacing="2",
                align="center",
                flex_shrink="0",
            ),
            rx.icon(
                "panel-right-open",
                size=16,
                color=rx.color("gray", 8),
                flex_shrink="0",
            ),
            spacing="2",
            align="center",
            width="100%",
            cursor="pointer",
        ),
        on_click=GroupState.open_session_preview(summary["session_id"].to(str)),
        **styles.card_style,
        _hover={"border_color": rx.color("accent", 7)},
    )


def _sessions_for_run(run_summary: dict) -> rx.Component:
    """Render session cards for a single run using pre-grouped data."""
    return rx.foreach(
        GroupState.group_sessions_by_run[run_summary["run_id"].to(str)],
        _session_card,
    )


def _run_card(run_summary: dict) -> rx.Component:
    """Expandable card for a single group run in the history."""
    return rx.card(
        rx.vstack(
            rx.box(
                rx.hstack(
                    rx.match(
                        run_summary["status"],
                        ("completed", rx.icon("check-circle", size=18, color=rx.color("green", 9))),
                        ("failed", rx.icon("x-circle", size=18, color=rx.color("red", 9))),
                        ("running", rx.icon("loader", size=18, color=rx.color("blue", 9), style=styles.spin_style)),
                        ("pending", rx.icon("clock", size=18, color=rx.color("yellow", 9))),
                        rx.icon("circle", size=18, color=rx.color("gray", 8)),
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.match(
                                run_summary["status"],
                                ("completed", rx.badge("Passed", color_scheme="green", variant="solid", size="1")),
                                ("failed", rx.badge("Failed", color_scheme="red", variant="solid", size="1")),
                                ("running", rx.badge("Running", color_scheme="blue", variant="solid", size="1")),
                                ("pending", rx.badge("Pending", color_scheme="yellow", variant="solid", size="1")),
                                rx.badge(run_summary["status"], variant="solid", size="1"),
                            ),
                            rx.text(
                                run_summary["session_count"].to(str) + " sessions",
                                size="1", color="gray",
                            ),
                            rx.text("·", color="gray"),
                            rx.text(
                                run_summary["healthy_count"].to(str)
                                + "/" + run_summary["target_count"].to(str)
                                + " healthy",
                                size="1", color="gray",
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.cond(
                            run_summary["created_at"] != "",
                            rx.moment(
                                run_summary["created_at"],
                                from_now=True,
                                with_title=True,
                                title_format="MMM D [at] h:mm:ss A",
                            ),
                        ),
                        spacing="0",
                        flex="1",
                        min_width="0",
                    ),
                    rx.icon(
                        rx.cond(run_summary["expanded"].to(bool), "chevron-up", "chevron-down"),
                        size=16,
                        color=rx.color("gray", 9),
                        flex_shrink="0",
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                    cursor="pointer",
                ),
                on_click=GroupState.toggle_run_expand(run_summary["run_id"]),
                width="100%",
            ),
            rx.cond(
                run_summary["expanded"].to(bool),
                rx.box(
                    rx.divider(margin_y="0.5em"),
                    rx.vstack(
                        _sessions_for_run(run_summary),
                        spacing="2",
                        width="100%",
                    ),
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        **styles.card_style,
    )


def _run_history() -> rx.Component:
    """Run history section."""
    return rx.cond(
        GroupState.group_run_summaries.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.icon("history", size=18, color=rx.color("accent", 9)),
                rx.text("Run History", size="3", weight="bold"),
                spacing="2",
                align="center",
            ),
            rx.foreach(GroupState.group_run_summaries, _run_card),
            spacing="3",
            width="100%",
        ),
        rx.center(
            rx.vstack(
                rx.icon("inbox", size=32, color=rx.color("gray", 8)),
                rx.text("No checks run yet", size="3", color="gray"),
                rx.text(
                    "Add sources and click 'Run All Checks' to get started.",
                    size="2", color="gray", text_align="center",
                ),
                spacing="2",
                align="center",
                padding="2em",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Loading / not found
# ---------------------------------------------------------------------------


def _group_loading() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon(
                "activity",
                size=64,
                color=rx.color("accent", 9),
                style=styles.pulse_style,
            ),
            rx.text("Soundcheck", size="5", weight="bold", color=rx.color("accent", 11)),
            rx.text("Loading group…", size="2", color=rx.color("gray", 9)),
            spacing="3",
            align="center",
        ),
        flex="1",
    )


def _group_not_found() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon("circle_x", size=48, color=rx.color("red", 9)),
            rx.heading("Group not found", size="5"),
            rx.text(
                "The group you're looking for doesn't exist or has been removed.",
                size="3", color="gray", text_align="center",
            ),
            spacing="4",
            align="center",
            max_width="400px",
        ),
        flex="1",
    )


# ---------------------------------------------------------------------------
# Confirm remove dialog
# ---------------------------------------------------------------------------


def _confirm_remove_dialog() -> rx.Component:
    """Confirmation dialog for removing a member from the group."""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Remove Source"),
            rx.alert_dialog.description(
                "Are you sure you want to remove this source from the group?",
            ),
            rx.text(
                GroupState.pending_remove_display,
                weight="bold",
                size="2",
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(
                        "Cancel",
                        variant="soft",
                        color_scheme="gray",
                    ),
                ),
                rx.button(
                    "Remove",
                    color_scheme="red",
                    on_click=GroupState.confirm_remove_member,
                ),
                spacing="3",
                justify="end",
                width="100%",
                margin_top="1em",
            ),
            style={"max_width": "450px"},
        ),
        open=GroupState.confirm_remove_open,
        on_open_change=GroupState.set_confirm_remove_open,
    )


# ---------------------------------------------------------------------------
# Session preview drawer
# ---------------------------------------------------------------------------


def _session_preview_drawer() -> rx.Component:
    """Right-side drawer showing full session details without leaving the group page."""
    return rx.drawer.root(
        rx.drawer.overlay(),
        rx.drawer.portal(
            rx.drawer.content(
                rx.vstack(
                    rx.hstack(
                        rx.drawer.close(
                            rx.icon_button(
                                rx.icon("x", size=16),
                                size="1",
                                variant="ghost",
                                color_scheme="gray",
                            ),
                        ),
                        rx.spacer(),
                        rx.tooltip(
                            rx.link(
                                rx.icon_button(
                                    rx.icon("external-link", size=14),
                                    size="1",
                                    variant="ghost",
                                    color_scheme="gray",
                                ),
                                href="/session/" + GroupState.preview_session_id,
                                is_external=True,
                            ),
                            content="Open full session page",
                        ),
                        width="100%",
                        align="center",
                    ),
                    rx.cond(
                        SessionState.session_loading,
                        rx.center(
                            rx.vstack(
                                rx.icon("loader", size=32, color=rx.color("blue", 9), style=styles.spin_style),
                                rx.text("Loading session…", size="2", color="gray"),
                                spacing="2",
                                align="center",
                            ),
                            flex="1",
                        ),
                        rx.box(
                            rx.vstack(
                                session_summary(),
                                check_progress(),
                                targets_list(),
                                spacing="4",
                                width="100%",
                            ),
                            width="100%",
                            overflow_y="auto",
                            flex="1",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                    height="100%",
                ),
                top="auto",
                left="auto",
                height="100%",
                width="min(700px, 90vw)",
                padding="1.25em",
                bg=rx.color("gray", 1),
                border_left=f"1px solid {rx.color('gray', 4)}",
            ),
        ),
        open=GroupState.show_session_preview,
        on_open_change=GroupState.set_session_preview_open,
        direction="right",
    )


# ---------------------------------------------------------------------------
# Main group content
# ---------------------------------------------------------------------------


def group_content() -> rx.Component:
    return rx.el.main(
        rx.cond(
            GroupState.group_loading,
            _group_loading(),
            rx.cond(
                GroupState.current_group,
                rx.vstack(
                    _group_header(),
                    _member_list(),
                    _run_history(),
                    _confirm_remove_dialog(),
                    spacing="4",
                    width="100%",
                ),
                _group_not_found(),
            ),
        ),
        _session_preview_drawer(),
        target_detail_dialog(),
        **styles.content_style,
    )
