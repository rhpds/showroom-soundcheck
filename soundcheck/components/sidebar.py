"""Sidebar — session history list (LibreChat-style)."""

import reflex as rx

from .. import styles
from ..models import CheckSession
from ..state import SessionState


def session_status_icon(status: str) -> rx.Component:
    return rx.match(
        status,
        ("completed", rx.icon("check", size=14, color=rx.color("green", 9))),
        ("failed", rx.icon("x", size=14, color=rx.color("red", 9))),
        ("running", rx.icon("loader", size=14, color=rx.color("blue", 9), style=styles.spin_style)),
        ("pending", rx.icon("clock", size=14, color=rx.color("yellow", 9))),
        rx.icon("circle", size=14, color=rx.color("gray", 8)),
    )


def _session_label(s: CheckSession) -> rx.Component:
    """Display label for a session with tooltip showing full content on hover."""
    label = s.display_label
    truncated_style = {
        "max_width": "180px",
        "overflow": "hidden",
        "text_overflow": "ellipsis",
        "white_space": "nowrap",
    }
    sublabel = rx.cond(
        label != "",
        rx.tooltip(
            rx.text(label, size="1", color="gray", style=truncated_style),
            content=label,
        ),
        rx.tooltip(
            rx.text(s.source_urls, size="1", color="gray", style=truncated_style),
            content=s.source_urls,
        ),
    )
    return rx.cond(
        s.name != "",
        rx.vstack(
            rx.tooltip(
                rx.text(s.name, size="1", weight="medium", style=truncated_style),
                content=s.name,
            ),
            sublabel,
            spacing="0",
        ),
        sublabel,
    )


def session_entry(s: CheckSession) -> rx.Component:
    return rx.link(
        rx.hstack(
            session_status_icon(s.status),
            rx.vstack(
                _session_label(s),
                rx.moment(
                    s.created_at,
                    from_now=True,
                    with_title=True,
                    title_format="MMM D [at] h:mm:ss A",
                ),
                spacing="0",
            ),
            spacing="2",
            align="center",
            padding="0.5em 0.75em",
            border_radius="var(--radius-2)",
            width="100%",
            _hover={"bg": rx.color("gray", 4)},
        ),
        href=rx.cond(
            s.session_id != "",
            "/session/" + s.session_id,
            "/",
        ),
        style={"text_decoration": "none", "color": "inherit", "width": "100%"},
    )


def session_group(title: str, sessions: rx.Var) -> rx.Component:
    return rx.cond(
        sessions.length() > 0,
        rx.vstack(
            rx.text(title, size="1", color="gray", weight="bold", padding_left="0.75em"),
            rx.foreach(sessions, session_entry),
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


def sidebar() -> rx.Component:
    return rx.el.nav(
        rx.vstack(
            rx.hstack(
                rx.icon("terminal", size=22),
                rx.heading("Soundcheck", size="4", as_="div"),
                spacing="2",
                align="center",
                width="100%",
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
            ),
            rx.divider(margin_y="0.75em"),
            rx.box(
                rx.vstack(
                    session_group("Recent", SessionState.today_sessions),
                    session_group("Earlier", SessionState.yesterday_sessions),
                    session_group("Older", SessionState.older_sessions),
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
        ),
        aria_label="Session history",
        **styles.sidebar_style,
    )
