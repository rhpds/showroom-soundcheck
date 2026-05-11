"""Landing page — form for creating new health check sessions."""

import reflex as rx

from .. import styles
from ..state import SessionFormState, SessionState


def landing_content() -> rx.Component:
    return rx.el.main(
        rx.vstack(
            rx.center(
                rx.vstack(
                    rx.icon("activity", size=48, color=rx.color("accent", 9)),
                    rx.heading("Showroom Health Checks", size="7"),
                    rx.text(
                        "Check the health of showroom environments. "
                        "Provide URLs directly, or use a ResourceClaim or Workshop GUID to auto-discover them.",
                        size="3",
                        color="gray",
                        text_align="center",
                        max_width="600px",
                    ),
                    spacing="3",
                    align="center",
                    padding_bottom="1em",
                ),
            ),
            rx.card(
                rx.form(
                    rx.vstack(
                        rx.el.label("Session Name", html_for="session_name", style=styles.label_style),
                        rx.text("Optional — give this check a friendly name", size="1", color="gray"),
                        rx.input(
                            placeholder="e.g. OCP Workshop — Apr 28",
                            name="session_name",
                            id="session_name",
                            width="100%",
                            **styles.input_style,
                        ),
                        rx.el.label("Showroom URLs", html_for="urls", style=styles.label_style),
                        rx.text("One URL per line", size="1", color="gray"),
                        rx.text_area(
                            placeholder="https://showroom1.example.com\nhttps://showroom2.example.com",
                            name="urls",
                            id="urls",
                            rows="4",
                            width="100%",
                            **styles.input_style,
                        ),
                        rx.el.label("ResourceClaim GUID", html_for="guids", style=styles.label_style),
                        rx.text("A single provision GUID to look up", size="1", color="gray"),
                        rx.input(
                            placeholder="gmltt",
                            name="guids",
                            id="guids",
                            width="100%",
                            **styles.input_style,
                        ),
                        rx.el.label("Workshop GUID", html_for="workshop_guids", style=styles.label_style),
                        rx.text("A single workshop ID — discovers all ResourceClaims in the workshop", size="1", color="gray"),
                        rx.input(
                            placeholder="9ucgv5",
                            name="workshop_guids",
                            id="workshop_guids",
                            width="100%",
                            **styles.input_style,
                        ),
                        rx.el.label("Babylon Cluster", html_for="babylon_cluster", style=styles.label_style),
                        rx.text("Optional — searches all clusters in priority order when omitted", size="1", color="gray"),
                        rx.select(
                            SessionState.cluster_select_options,
                            name="babylon_cluster",
                            id="babylon_cluster",
                            default_value="(auto)",
                        ),
                        rx.hstack(
                            rx.vstack(
                                rx.text("Check Type", size="2", weight="bold"),
                                rx.select(
                                    ["readyz", "healthz"],
                                    name="check_type",
                                    default_value="readyz",
                                ),
                                spacing="1",
                                flex="1",
                            ),
                            rx.vstack(
                                rx.text("Check Mode", size="2", weight="bold"),
                                rx.select(
                                    ["manual", "showroom"],
                                    name="check_mode",
                                    default_value="manual",
                                ),
                                spacing="1",
                                flex="1",
                            ),
                            spacing="3",
                            width="100%",
                        ),
                        rx.text(
                            "Manual: runs checks locally (fetches config, probes tabs). "
                            "Showroom: delegates to the showroom's own health endpoint first.",
                            size="1",
                            color="gray",
                        ),
                        rx.cond(
                            SessionState.form_error != "",
                            rx.callout(
                                SessionState.form_error,
                                icon="triangle_alert",
                                color_scheme="red",
                                size="1",
                            ),
                        ),
                        rx.button(
                            rx.cond(
                                SessionFormState.form_submitting,
                                rx.hstack(
                                    rx.icon("loader", size=16, style=styles.spin_style),
                                    rx.text("Creating session…"),
                                    spacing="2",
                                    align="center",
                                ),
                                rx.hstack(
                                    rx.icon("play", size=16),
                                    rx.text("Run Health Checks"),
                                    spacing="2",
                                    align="center",
                                ),
                            ),
                            type="submit",
                            color_scheme="blue",
                            size="3",
                            width="100%",
                            disabled=SessionFormState.form_submitting,
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    on_submit=SessionFormState.create_session_from_form,
                ),
                max_width="600px",
                margin_x="auto",
                **styles.card_style,
            ),
            rx.accordion.root(
                rx.accordion.item(
                    header="API / Direct Links",
                    content=rx.vstack(
                        rx.text(
                            "Create sessions via URL query parameters:",
                            size="1",
                            color="gray",
                        ),
                        rx.code("/check?urls=https://showroom1.example.com,https://showroom2.example.com", size="1"),
                        rx.code("/check?guid=gmltt", size="1"),
                        rx.code("/check?workshop=9ucgv5", size="1"),
                        rx.code("/check?guid=gmltt&cluster=east", size="1"),
                        rx.code("/check?guid=gmltt&type=healthz&name=My+Workshop", size="1"),
                        rx.code("/check?urls=https://showroom1.example.com&mode=showroom", size="1"),
                        spacing="1",
                        align="center",
                    ),
                ),
                collapsible=True,
                variant="ghost",
                max_width="600px",
                width="100%",
                margin_x="auto",
                margin_top="1em",
            ),
            spacing="4",
            width="100%",
            align="center",
        ),
        **styles.content_style,
    )
