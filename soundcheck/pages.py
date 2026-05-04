"""Page definitions for Showroom Soundcheck."""

import reflex as rx

from . import styles
from .components import landing_content, session_content, sidebar

_DEFAULT_LIGHT = rx.script(
    "if(!localStorage.getItem('theme')){"
    "document.documentElement.classList.remove('dark');"
    "document.documentElement.classList.add('light');"
    "document.documentElement.style.colorScheme='light';"
    "localStorage.setItem('theme','light');}"
)


def home_page() -> rx.Component:
    return rx.fragment(
        _DEFAULT_LIGHT,
        rx.flex(
            sidebar(),
            landing_content(),
            height="100vh",
            width="100vw",
            flex_direction="row",
        ),
    )


def check_redirect_page() -> rx.Component:
    """Intermediate page that creates a session and redirects."""
    return rx.fragment(
        _DEFAULT_LIGHT,
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
        _DEFAULT_LIGHT,
        rx.flex(
            sidebar(),
            session_content(),
            height="100vh",
            width="100vw",
            flex_direction="row",
        ),
    )
