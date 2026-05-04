"""UI styles for Showroom Soundcheck."""

import reflex as rx

app_theme = rx.theme(
    appearance="inherit",
    has_background=True,
    accent_color="blue",
    radius="large",
    scaling="100%",
)

base_style = {
    "font_family": "Instrument Sans, sans-serif",
    "& code": {
        "white_space": "pre-wrap !important",
        "word_wrap": "break-word !important",
    },
    "& pre": {
        "white_space": "pre-wrap !important",
        "word_wrap": "break-word !important",
    },
    "@keyframes spin": {
        "from": {"transform": "rotate(0deg)"},
        "to": {"transform": "rotate(360deg)"},
    },
}

spin_style = {"animation": "spin 1.5s linear infinite"}

sidebar_style = {
    "bg": rx.color("gray", 2),
    "border_right": f"1px solid {rx.color('gray', 4)}",
    "height": "100%",
    "width": "280px",
    "min_width": "280px",
    "padding": "1em",
    "display": "flex",
    "flex_direction": "column",
    "flex_shrink": "0",
    "overflow_y": "hidden",
}

content_style = {
    "bg": rx.color("gray", 1),
    "height": "100%",
    "flex_grow": "1",
    "padding": "2em",
    "display": "flex",
    "flex_direction": "column",
    "min_width": "0",
    "overflow_y": "auto",
}

card_style = {
    "width": "100%",
    "padding": "1.5em",
}

input_style = {
    "bg": rx.color("gray", 3),
    "border": f"1px solid {rx.color('gray', 5)}",
    "_focus": {
        "border_color": rx.color("accent", 9),
    },
}
