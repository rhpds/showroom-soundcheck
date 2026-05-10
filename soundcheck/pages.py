"""Page definitions for Showroom Soundcheck."""

import reflex as rx

from . import styles
from .components import (
    landing_content,
    mobile_sidebar_drawer,
    mobile_sidebar_trigger,
    session_content,
    sidebar,
)


def _mobile_header() -> rx.Component:
    """Top bar with hamburger menu, shown only on mobile."""
    return rx.hstack(
        mobile_sidebar_trigger(),
        rx.hstack(
            rx.icon("terminal", size=18),
            rx.heading("Soundcheck", size="3", as_="div"),
            spacing="2",
            align="center",
        ),
        spacing="2",
        align="center",
        padding="0.5em 1em",
        border_bottom=f"1px solid {rx.color('gray', 4)}",
        bg=rx.color("gray", 2),
        width="100%",
        flex_shrink="0",
        display=rx.breakpoints(initial="flex", md="none"),
    )


def home_page() -> rx.Component:
    return rx.fragment(
        rx.flex(
            sidebar(),
            rx.flex(
                _mobile_header(),
                landing_content(),
                direction="column",
                flex="1",
                min_width="0",
            ),
            height="100vh",
            width="100vw",
            flex_direction="row",
        ),
        mobile_sidebar_drawer(),
    )


def check_redirect_page() -> rx.Component:
    """Intermediate page that creates a session and redirects."""
    return rx.fragment(
        rx.center(
            rx.vstack(
                rx.icon("loader", size=32, color=rx.color("blue", 9), style=styles.spin_style),
                rx.text("Creating session...", size="3", color="gray"),
                spacing="3",
                align="center",
            ),
            height="100vh",
            width="100vw",
        ),
    )


def session_page() -> rx.Component:
    return rx.fragment(
        rx.flex(
            sidebar(),
            rx.flex(
                _mobile_header(),
                session_content(),
                direction="column",
                flex="1",
                min_width="0",
            ),
            height="100vh",
            width="100vw",
            flex_direction="row",
        ),
        mobile_sidebar_drawer(),
    )
