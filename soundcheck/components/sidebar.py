"""Sidebar — session and group history list."""

import reflex as rx

from .. import styles
from ..state import GroupState, SessionState


def _status_icon(status: rx.Var[str]) -> rx.Component:
    return rx.match(
        status,
        ("completed", rx.icon("check", size=14, color=rx.color("green", 9))),
        ("failed", rx.icon("x", size=14, color=rx.color("red", 9))),
        ("running", rx.icon("loader", size=14, color=rx.color("blue", 9), style=styles.spin_style)),
        ("pending", rx.icon("clock", size=14, color=rx.color("yellow", 9))),
        rx.icon("circle", size=14, color=rx.color("gray", 8)),
    )


def session_status_icon(status: str) -> rx.Component:
    return _status_icon(status)


def _sidebar_item_label(item: dict) -> rx.Component:
    """Label for a sidebar item (group or session)."""
    truncated_style = {
        "max_width": "180px",
        "overflow": "hidden",
        "text_overflow": "ellipsis",
        "white_space": "nowrap",
    }
    sublabel = rx.cond(
        item["label"] != "",
        rx.tooltip(
            rx.text(item["label"], size="1", color="gray", style=truncated_style),
            content=item["label"],
        ),
        rx.fragment(),
    )
    return rx.cond(
        item["name"] != "",
        rx.vstack(
            rx.tooltip(
                rx.text(item["name"], size="1", weight="medium", style=truncated_style),
                content=item["name"],
            ),
            sublabel,
            spacing="0",
        ),
        sublabel,
    )


def _sidebar_item_icon(item: dict) -> rx.Component:
    """Icon for a sidebar item — folder for groups, status icon for sessions."""
    return rx.cond(
        item["kind"] == "group",
        rx.icon("folder", size=14, color=rx.color("accent", 9)),
        _status_icon(item["status"]),
    )


def _pin_button(item: dict) -> rx.Component:
    """Pin/unpin toggle — visible on hover, always visible when pinned."""
    return rx.icon_button(
        rx.cond(
            item["pinned"].to(bool),
            rx.icon("pin-off", size=12),
            rx.icon("pin", size=12),
        ),
        size="1",
        variant="ghost",
        color_scheme="gray",
        on_click=SessionState.toggle_pin(item["kind"], item["id"]),
        style={
            "opacity": rx.cond(item["pinned"].to(bool), "0.7", "0"),
            "transition": "opacity 0.15s",
            "flex_shrink": "0",
        },
    )


def _sidebar_item(item: dict) -> rx.Component:
    is_active_session = (
        (item["kind"] == "session")
        & (SessionState.current_session_id == item["id"])
    )
    is_active_group = (
        (item["kind"] == "group")
        & (GroupState.current_group_id == item["id"])
    )
    is_active = is_active_session | is_active_group

    href = rx.cond(
        item["kind"] == "group",
        "/group/" + item["id"].to(str),
        rx.cond(item["id"] != "", "/session/" + item["id"].to(str), "/"),
    )

    return rx.hstack(
        rx.link(
            rx.hstack(
                _sidebar_item_icon(item),
                rx.vstack(
                    _sidebar_item_label(item),
                    rx.moment(
                        item["created_at"],
                        from_now=True,
                        with_title=True,
                        title_format="MMM D [at] h:mm:ss A",
                    ),
                    spacing="0",
                ),
                spacing="2",
                align="center",
                flex="1",
                min_width="0",
            ),
            href=href,
            on_click=SessionState.close_sidebar,
            style={"text_decoration": "none", "color": "inherit", "flex": "1", "min_width": "0"},
        ),
        _pin_button(item),
        spacing="1",
        align="center",
        padding="0.5em 0.75em",
        border_radius="var(--radius-2)",
        width="100%",
        bg=rx.cond(is_active, rx.color("accent", 3), "transparent"),
        _hover={
            "bg": rx.cond(is_active, rx.color("accent", 4), rx.color("gray", 4)),
            "& button": {"opacity": "1 !important"},
        },
    )


def _sidebar_group(title: str, items: rx.Var, icon_name: str = "") -> rx.Component:
    header = (
        rx.hstack(
            rx.icon(icon_name, size=12, color="gray"),
            rx.text(title, size="1", color="gray", weight="bold"),
            spacing="1",
            align="center",
            padding_left="0.75em",
        )
        if icon_name
        else rx.text(title, size="1", color="gray", weight="bold", padding_left="0.75em")
    )
    return rx.cond(
        items.length() > 0,
        rx.vstack(
            header,
            rx.foreach(items, _sidebar_item),
            spacing="1",
            width="100%",
        ),
    )


def _color_mode_toggle() -> rx.Component:
    return rx.tooltip(
        rx.icon_button(
            rx.color_mode_cond(
                light=rx.icon("moon", size=16),
                dark=rx.icon("sun", size=16),
            ),
            on_click=rx.toggle_color_mode,
            variant="ghost",
            size="2",
            cursor="pointer",
            color_scheme="gray",
            aria_label=rx.color_mode_cond(
                light="Switch to dark mode",
                dark="Switch to light mode",
            ),
        ),
        content=rx.color_mode_cond(
            light="Switch to dark mode",
            dark="Switch to light mode",
        ),
    )


def _sidebar_inner() -> rx.Component:
    """Shared sidebar content used by both the desktop sidebar and mobile drawer."""
    return rx.vstack(
        rx.link(
            rx.hstack(
                rx.icon("terminal", size=22),
                rx.heading("Soundcheck", size="4", as_="div"),
                spacing="2",
                align="center",
                width="100%",
            ),
            href="/",
            on_click=SessionState.close_sidebar,
            style={"text_decoration": "none", "color": "inherit", "width": "100%"},
            flex_shrink="0",
        ),
        rx.divider(margin_y="0.75em"),
        rx.link(
            rx.button(
                rx.icon("plus", size=16),
                rx.text("New Check", size="2"),
                width="100%",
                color_scheme="blue",
                variant="solid",
            ),
            href="/",
            width="100%",
            style={"text_decoration": "none"},
            on_click=SessionState.close_sidebar,
        ),
        rx.divider(margin_y="0.75em"),
        rx.box(
            rx.vstack(
                _sidebar_group("Pinned", SessionState.sidebar_pinned, icon_name="pin"),
                _sidebar_group("Recent", SessionState.sidebar_today),
                _sidebar_group("Earlier", SessionState.sidebar_yesterday),
                _sidebar_group("Older", SessionState.sidebar_older),
                spacing="3",
                width="100%",
            ),
            overflow_y="auto",
            flex_grow="1",
            width="100%",
        ),
        rx.divider(margin_y="0.75em"),
        rx.hstack(
            rx.text("Theme", size="1", color="gray", weight="medium"),
            rx.spacer(),
            _color_mode_toggle(),
            width="100%",
            align="center",
            padding="0 0.25em",
        ),
        align_items="start",
        justify_content="flex-start",
        height="100%",
        width="100%",
        flex="1",
    )


def sidebar() -> rx.Component:
    """Desktop sidebar — hidden below the mobile breakpoint."""
    return rx.el.nav(
        _sidebar_inner(),
        aria_label="Session history",
        **styles.sidebar_style,
    )


def mobile_sidebar_trigger() -> rx.Component:
    """Hamburger button shown only on mobile to open the sidebar drawer."""
    return rx.icon_button(
        rx.icon("menu", size=20),
        on_click=SessionState.open_sidebar,
        variant="ghost",
        size="2",
        color_scheme="gray",
        aria_label="Open navigation",
    )


def mobile_sidebar_drawer() -> rx.Component:
    """Drawer-based sidebar for narrow viewports."""
    return rx.drawer.root(
        rx.drawer.overlay(),
        rx.drawer.portal(
            rx.drawer.content(
                rx.el.nav(
                    _sidebar_inner(),
                    aria_label="Session history",
                    style={"height": "100%"},
                ),
                style={
                    "height": "100%",
                    "width": "280px",
                    "padding": "1em",
                    "bg": rx.color("gray", 2),
                },
            ),
        ),
        direction="left",
        open=SessionState.sidebar_open,
        on_open_change=SessionState.set_sidebar_open,
    )
