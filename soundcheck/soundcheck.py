"""Showroom Soundcheck — App entry point.

Configures logging and registers Reflex pages.
Babylon cluster clients are initialized lazily on first access.
All application logic lives in state.py and components/.
"""

import logging

import reflex as rx

from . import styles
from .pages import check_redirect_page, group_page, group_redirect_page, home_page, session_page
from .state import GroupFormState, GroupState, SessionFormState, SessionState

logging.basicConfig(
    level=logging.INFO,
    force=True,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = rx.App(
    style=styles.base_style,
    head_components=[
        rx.el.link(rel="icon", href="/favicon.svg", type="image/svg+xml"),
        rx.el.style(
            ".rt-BaseDialogOverlay, .rt-DialogContent { z-index: 100 !important; }"
        ),
    ],
)
app.add_page(
    home_page,
    route="/",
    on_load=SessionState.on_home_load,
    title="Soundcheck",
)
app.add_page(
    check_redirect_page,
    route="/check",
    on_load=SessionFormState.handle_check_page,
    title="Creating Session | Soundcheck",
)
app.add_page(
    session_page,
    route="/session/[session_id]",
    on_load=SessionState.on_session_load,
    title="Session | Soundcheck",
)
app.add_page(
    group_redirect_page,
    route="/group/new",
    on_load=GroupFormState.handle_group_page,
    title="Creating Group | Soundcheck",
)
app.add_page(
    group_page,
    route="/group/[group_id]",
    on_load=GroupState.on_group_load,
    title="Group | Soundcheck",
)
