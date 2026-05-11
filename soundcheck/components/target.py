"""Target status display, detail dialog, and check result row."""

import reflex as rx

from .. import styles
from ..models import CheckResult, SessionTarget
from ..state import SessionState, TargetDetailState


def target_status_badge(status: str) -> rx.Component:
    return rx.match(
        status,
        ("healthy", rx.badge("Healthy", color_scheme="green", variant="soft", radius="full")),
        ("checking", rx.badge(
            rx.hstack(rx.icon("loader", size=12, style=styles.spin_style), rx.text("Checking"), spacing="1", align="center"),
            color_scheme="blue", variant="soft", radius="full",
        )),
        ("provisioning", rx.badge(
            rx.hstack(rx.icon("loader", size=12, style=styles.spin_style), rx.text("Provisioning"), spacing="1", align="center"),
            color_scheme="indigo", variant="soft", radius="full",
        )),
        ("pending", rx.badge("Pending", color_scheme="yellow", variant="soft", radius="full")),
        ("unhealthy", rx.badge("Unhealthy", color_scheme="orange", variant="soft", radius="full")),
        ("degraded", rx.badge("Degraded", color_scheme="amber", variant="soft", radius="full")),
        ("error", rx.badge("Error", color_scheme="red", variant="soft", radius="full")),
        rx.badge(status, color_scheme="gray", variant="soft", radius="full"),
    )


def _target_url_or_provision_message(target: SessionTarget) -> rx.Component:
    """Show the URL when available, or a provisioning/error message for placeholder targets."""
    return rx.cond(
        target.url != "",
        rx.text(target.url, size="1", color="gray", style={
            "overflow": "hidden", "text_overflow": "ellipsis", "white_space": "nowrap",
        }),
        rx.cond(
            target.status == "error",
            rx.text("No showroom", size="1", color="red", weight="medium"),
            rx.text("Waiting for showroom...", size="1", color=rx.color("indigo", 9), style={
                "font_style": "italic",
            }),
        ),
    )


def _check_summary_badges(target: SessionTarget) -> rx.Component:
    """Compact Content N/M and Tabs N/M badges from check detail data."""
    summary = SessionState.target_check_summaries[target.id.to(int)]
    return rx.cond(
        SessionState.target_check_summaries.contains(target.id.to(int)),
        rx.hstack(
            rx.cond(
                summary["is_legacy"].to(bool),
                rx.badge(
                    rx.hstack(
                        rx.icon("history", size=10),
                        "Legacy",
                        spacing="1",
                        align="center",
                    ),
                    color_scheme="amber",
                    variant="outline",
                    size="1",
                ),
            ),
            rx.cond(
                summary["content_total"].to(int) > 0,
                rx.badge(
                    rx.hstack(
                        rx.icon("file-text", size=10),
                        "Content " + summary["content_ok"].to(str) + "/" + summary["content_total"].to(str),
                        spacing="1",
                        align="center",
                    ),
                    color_scheme=rx.cond(
                        summary["content_ok"].to(int) == summary["content_total"].to(int),
                        "green",
                        "red",
                    ),
                    variant="soft",
                    size="1",
                ),
            ),
            rx.cond(
                summary["tabs_total"].to(int) > 0,
                rx.badge(
                    rx.hstack(
                        rx.icon("layout-grid", size=10),
                        "Tabs " + summary["tabs_ok"].to(str) + "/" + summary["tabs_total"].to(str),
                        spacing="1",
                        align="center",
                    ),
                    color_scheme=rx.cond(
                        summary["tabs_ok"].to(int) == summary["tabs_total"].to(int),
                        "green",
                        "red",
                    ),
                    variant="soft",
                    size="1",
                ),
            ),
            spacing="1",
            align="center",
        ),
    )


def target_row(target: SessionTarget) -> rx.Component:
    _ellipsis = {"overflow": "hidden", "text_overflow": "ellipsis", "white_space": "nowrap"}
    is_provisioning = target.status == "provisioning"
    return rx.box(
        rx.hstack(
            target_status_badge(target.status),
            rx.vstack(
                rx.text(target.label, size="2", weight="medium", style=_ellipsis),
                rx.hstack(
                    _target_url_or_provision_message(target),
                    spacing="2",
                    align="center",
                    min_width="0",
                    width="100%",
                ),
                _check_summary_badges(target),
                spacing="0",
                min_width="0",
                overflow="hidden",
                flex="1",
            ),
            rx.cond(
                ~is_provisioning,
                rx.hstack(
                    rx.cond(
                        target.workshop_guid,
                        rx.badge("ws:" + target.workshop_guid, variant="outline", color_scheme="teal", size="1"),
                    ),
                    rx.cond(
                        target.guid,
                        rx.badge(target.guid, variant="outline", color_scheme="purple", size="1"),
                    ),
                    rx.cond(
                        target.tier_used,
                        rx.badge(
                            "Tier " + target.tier_used.to(str),
                            variant="outline",
                            color_scheme="gray",
                            size="1",
                        ),
                    ),
                    rx.cond(
                        target.response_time_ms,
                        rx.text(target.response_time_ms.to(str) + "ms", size="1", color="gray"),
                    ),
                    rx.icon("chevron-right", size=14, color=rx.color("gray", 8)),
                    spacing="2",
                    align="center",
                    flex_shrink="0",
                ),
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        rx.cond(
            target.error_message,
            rx.box(
                rx.text(target.error_message, size="1", color="red", style={
                    "white_space": "pre-wrap", "word_wrap": "break-word",
                }),
                padding_left="2em",
                padding_top="0.25em",
            ),
        ),
        padding="0.75em 1em",
        border_bottom=f"1px solid {rx.color('gray', 4)}",
        width="100%",
        cursor=rx.cond(is_provisioning, "default", "pointer"),
        _hover={"bg": rx.cond(is_provisioning, "inherit", rx.color("gray", 3))},
        transition="background 0.15s",
        role="button",
        tab_index=0,
        on_click=TargetDetailState.open_target_detail(target.id),
    )


def _detail_endpoint_row(tab: rx.Var[dict]) -> rx.Component:
    """Render a single endpoint/tab probe result in the detail view."""
    reachable = tab["reachable"]
    name = tab["name"]
    url = tab["url"]
    status_code = tab["status_code"]
    status_ok = tab["status_ok"]
    error = tab["error"]
    iframe_blocked = tab["iframe_blocked"]
    external = tab["external"]

    is_ok = reachable & (~iframe_blocked | external)

    return rx.box(
        rx.hstack(
            rx.cond(
                is_ok,
                rx.icon("circle-check", size=14, color=rx.color("green", 9)),
                rx.icon("circle-x", size=14, color=rx.color("red", 9)),
            ),
            rx.text(name, size="2", weight="medium", min_width="120px"),
            rx.cond(
                status_code,
                rx.badge(
                    status_code.to(str),
                    color_scheme=rx.cond(status_ok, "green", "red"),
                    variant="soft",
                    size="1",
                ),
            ),
            rx.text(url.to(str), size="1", color="gray", style={
                "max_width": "350px", "overflow": "hidden",
                "text_overflow": "ellipsis", "white_space": "nowrap",
            }),
            rx.spacer(),
            rx.cond(
                iframe_blocked & external,
                rx.badge(
                    rx.hstack(rx.icon("external-link", size=10), "pop-out", spacing="1", align="center"),
                    color_scheme="blue", variant="soft", size="1",
                ),
                rx.cond(
                    iframe_blocked,
                    rx.badge("iframe blocked", color_scheme="orange", variant="soft", size="1"),
                ),
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        rx.cond(
            error,
            rx.text(error.to(str), size="1", color="red", padding_left="1.75em", style={
                "white_space": "pre-wrap", "word_wrap": "break-word",
            }),
        ),
        padding_y="0.4em",
        border_bottom=f"1px solid {rx.color('gray', 3)}",
        width="100%",
    )


def _check_result_row(result: CheckResult) -> rx.Component:
    """A single check attempt in the results history."""
    return rx.hstack(
        rx.cond(
            result.is_healthy,
            rx.icon("circle-check", size=14, color=rx.color("green", 9)),
            rx.icon("circle-x", size=14, color=rx.color("red", 9)),
        ),
        rx.badge(result.check_type, variant="outline", color_scheme="gray", size="1"),
        rx.badge("Tier " + result.tier.to(str), variant="outline", color_scheme="gray", size="1"),
        rx.cond(
            result.status_code,
            rx.badge(
                result.status_code.to(str),
                color_scheme=rx.cond(
                    result.is_healthy,
                    "green",
                    "red",
                ),
                variant="soft",
                size="1",
            ),
        ),
        rx.text(result.response_time_ms.to(str) + "ms", size="1", color="gray"),
        rx.cond(
            result.error_message,
            rx.text(result.error_message, size="1", color="red", style={
                "max_width": "200px", "overflow": "hidden",
                "text_overflow": "ellipsis", "white_space": "nowrap",
            }),
        ),
        spacing="2",
        align="center",
        padding_y="0.3em",
        width="100%",
    )


# ---------------------------------------------------------------------------
# Dialog sub-components (broken out from the monolithic target_detail_dialog)
# ---------------------------------------------------------------------------


def _target_header() -> rx.Component:
    """Target identity, status badge, tier, timing, and GUID badges."""
    return rx.box(
        rx.hstack(
            target_status_badge(TargetDetailState.selected_target.status),
            rx.text(
                TargetDetailState.selected_target.label,
                size="3", weight="medium",
            ),
            spacing="2",
            align="center",
        ),
        rx.text(
            TargetDetailState.selected_target.url,
            size="2", color="gray", style={"word_wrap": "break-word"},
        ),
        rx.hstack(
            rx.cond(
                TargetDetailState.selected_target.tier_used,
                rx.badge(
                    "Tier " + TargetDetailState.selected_target.tier_used.to(str),
                    variant="outline", color_scheme="gray", size="1",
                ),
            ),
            rx.cond(
                TargetDetailState.selected_target.response_time_ms,
                rx.text(
                    TargetDetailState.selected_target.response_time_ms.to(str) + "ms",
                    size="1", color="gray",
                ),
            ),
            rx.cond(
                TargetDetailState.selected_target.workshop_guid,
                rx.badge(
                    "ws:" + TargetDetailState.selected_target.workshop_guid,
                    variant="outline", color_scheme="teal", size="1",
                ),
            ),
            rx.cond(
                TargetDetailState.selected_target.guid,
                rx.badge(
                    TargetDetailState.selected_target.guid,
                    variant="outline", color_scheme="purple", size="1",
                ),
            ),
            spacing="2",
            padding_top="0.5em",
        ),
        padding_bottom="1em",
        border_bottom=f"1px solid {rx.color('gray', 4)}",
        width="100%",
    )


def _readyz_detail_section() -> rx.Component:
    """Readyz check detail: status badge, config file, content probe, tab probes."""
    return rx.cond(
        TargetDetailState.has_detail,
        rx.vstack(
            rx.hstack(
                rx.cond(
                    TargetDetailState.detail_is_legacy,
                    rx.hstack(
                        rx.text("Legacy Showroom Check", size="3", weight="bold"),
                        rx.badge("legacy", variant="outline", color_scheme="amber", size="1"),
                        spacing="2", align="center",
                    ),
                    rx.text("Readyz Check Detail", size="3", weight="bold"),
                ),
                rx.spacer(),
                rx.cond(
                    TargetDetailState.detail_status != "",
                    rx.badge(
                        TargetDetailState.detail_status,
                        color_scheme=rx.cond(
                            TargetDetailState.detail_status == "ok",
                            "green",
                            "red",
                        ),
                        variant="solid",
                        size="1",
                    ),
                ),
                width="100%",
                align="center",
            ),
            rx.cond(
                TargetDetailState.detail_config_file != "",
                rx.hstack(
                    rx.text("Config:", size="1", color="gray", weight="bold"),
                    rx.cond(
                        TargetDetailState.detail_config_url != "",
                        rx.link(
                            rx.code(TargetDetailState.detail_config_file, size="1"),
                            href=TargetDetailState.detail_config_url,
                            is_external=True,
                        ),
                        rx.code(TargetDetailState.detail_config_file, size="1"),
                    ),
                    spacing="2",
                ),
            ),
            rx.cond(
                TargetDetailState.detail_has_content,
                rx.box(
                    rx.text("Content", size="2", weight="bold", padding_bottom="0.25em"),
                    rx.foreach(TargetDetailState.detail_content_list, _detail_endpoint_row),
                    width="100%",
                ),
            ),
            rx.cond(
                TargetDetailState.detail_has_tabs,
                rx.box(
                    rx.text("Endpoints / Tabs", size="2", weight="bold", padding_bottom="0.25em"),
                    rx.foreach(TargetDetailState.detail_tabs, _detail_endpoint_row),
                    width="100%",
                ),
            ),
            spacing="3",
            width="100%",
            padding_top="1em",
        ),
        rx.cond(
            TargetDetailState.selected_target.status != "pending",
            rx.box(
                rx.text(
                    "No detailed probe data available for this target.",
                    size="2", color="gray",
                ),
                rx.text(
                    "Detail is captured when the readyz endpoint returns structured JSON "
                    "or when Tier 2/3 checks are run.",
                    size="1", color="gray",
                ),
                padding_top="1em",
            ),
        ),
    )


def _check_attempts_section() -> rx.Component:
    """Historical check attempt rows."""
    return rx.cond(
        TargetDetailState.selected_target_results.length() > 0,
        rx.box(
            rx.text("Check Attempts", size="2", weight="bold", padding_bottom="0.5em"),
            rx.foreach(TargetDetailState.selected_target_results, _check_result_row),
            width="100%",
            padding_top="1em",
            border_top=f"1px solid {rx.color('gray', 4)}",
        ),
    )


def target_detail_dialog() -> rx.Component:
    """Modal dialog showing readyz check detail for a selected target."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.hstack(
                    rx.text("Target Details", size="5", weight="bold"),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.button(
                            rx.icon("x", size=16),
                            variant="ghost",
                            color_scheme="gray",
                            size="1",
                        ),
                    ),
                    width="100%",
                    align="center",
                ),
            ),
            rx.dialog.description(
                "Detailed readiness and check history for the selected target.",
                size="2",
                color="gray",
            ),
            rx.cond(
                TargetDetailState.selected_target,
                rx.vstack(
                    _target_header(),
                    rx.cond(
                        TargetDetailState.selected_target.error_message,
                        rx.callout(
                            TargetDetailState.selected_target.error_message,
                            icon="triangle_alert",
                            color_scheme="red",
                            size="1",
                            width="100%",
                        ),
                    ),
                    _readyz_detail_section(),
                    _check_attempts_section(),
                    spacing="3",
                    width="100%",
                ),
            ),
            max_width="700px",
            max_height="80vh",
            overflow_y="auto",
        ),
        open=TargetDetailState.show_target_detail,
        on_open_change=TargetDetailState.set_target_detail_open,
    )
