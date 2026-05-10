"""Shared utilities for Showroom Soundcheck.

Contains GUID extraction, input parsing/validation, display label
generation, URL allowlist enforcement, and datetime helpers used
across the application.
"""

import fnmatch
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

GUID_RE = re.compile(
    r"(?:"
    r"-([a-z0-9]{4,6})(?:-\d+)?\.apps\."
    r"|"
    r"\.cluster-([a-z0-9]+)\."
    r")"
)


def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


VALID_CHECK_TYPES = ("readyz", "healthz")
VALID_CHECK_MODES = ("manual", "showroom")

# ---------------------------------------------------------------------------
# URL allowlist (SSRF prevention)
# ---------------------------------------------------------------------------

_URL_ALLOWLIST: list[str] = []


def _load_url_allowlist() -> list[str]:
    """Parse ALLOWED_URL_PATTERNS env var into a list of hostname globs.

    Raises RuntimeError at startup when the variable is missing or empty.
    """
    raw = os.environ.get("ALLOWED_URL_PATTERNS", "")
    patterns = [p.strip() for p in raw.split(",") if p.strip()]
    if not patterns:
        raise RuntimeError(
            "ALLOWED_URL_PATTERNS env var is required. "
            "Set to a comma-separated list of hostname globs "
            "(e.g. '*.redhat.com,*.opentlc.com,localhost')."
        )
    return patterns


def init_url_allowlist() -> None:
    """Load the URL allowlist from the environment. Call once at startup."""
    global _URL_ALLOWLIST  # noqa: PLW0603
    _URL_ALLOWLIST = _load_url_allowlist()
    logger.info("URL allowlist loaded: %s", _URL_ALLOWLIST)


def is_url_allowed(url: str) -> bool:
    """Check if a URL's hostname matches any allowed pattern."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    for pattern in _URL_ALLOWLIST:
        if fnmatch.fnmatch(hostname, pattern):
            return True
    return False


def extract_guid_from_url(url: str) -> Optional[str]:
    """Extract a GUID from a showroom/bastion URL hostname."""
    m = GUID_RE.search(url)
    if not m:
        return None
    return m.group(1) or m.group(2)


def make_display_label(
    urls: list[str],
    guids: list[str],
    workshop_guids: Optional[list[str]] = None,
) -> str:
    """Build a human-friendly label for the sidebar.

    Prefers GUIDs when available. For bare URLs, tries to pull the GUID out of
    the ``cluster-<guid>`` hostname component; falls back to the raw URL.
    """
    parts: list[str] = []
    if workshop_guids:
        parts.extend(f"ws:{g}" for g in workshop_guids)
    if guids:
        parts.extend(guids)
    if parts:
        return ", ".join(parts)
    items: list[str] = []
    for url in urls:
        extracted = extract_guid_from_url(url)
        items.append(extracted if extracted else url)
    return ", ".join(items)


def normalize_check_type(raw: str) -> str:
    return raw if raw in VALID_CHECK_TYPES else "readyz"


def normalize_check_mode(raw: str) -> str:
    return raw if raw in VALID_CHECK_MODES else "manual"


@dataclass
class ParsedSessionInput:
    """Validated and normalized session creation input."""

    session_name: str = ""
    urls: list[str] = field(default_factory=list)
    guids: list[str] = field(default_factory=list)
    workshop_guids: list[str] = field(default_factory=list)
    check_type: str = "readyz"
    check_mode: str = "manual"
    babylon_cluster: str = ""


class InputValidationError(Exception):
    """Raised when user-supplied session input fails validation."""


def parse_check_params(
    *,
    raw_urls: str,
    raw_guids: str,
    raw_ws_guids: str,
    check_type: str = "readyz",
    check_mode: str = "manual",
    session_name: str = "",
    cluster: str = "",
    url_separator: str = ",",
) -> ParsedSessionInput:
    """Parse and validate raw input from either query params or form data.

    Raises InputValidationError on invalid input.
    """
    urls = [u.strip() for u in raw_urls.split(url_separator) if u.strip()] if raw_urls else []
    guids = [g.strip() for g in raw_guids.replace(",", "\n").split("\n") if g.strip()] if raw_guids else []
    workshop_guids = [g.strip() for g in raw_ws_guids.replace(",", "\n").split("\n") if g.strip()] if raw_ws_guids else []

    if not urls and not guids and not workshop_guids:
        raise InputValidationError("Provide at least one URL, GUID, or Workshop GUID")

    valid_prefixes = ("https://", "http://")
    for url in urls:
        if not url.startswith(valid_prefixes):
            raise InputValidationError(
                f"Invalid URL (must start with http:// or https://): {url}"
            )
        if not is_url_allowed(url):
            raise InputValidationError(
                f"URL hostname not in allowlist: {url}"
            )

    return ParsedSessionInput(
        session_name=session_name.strip(),
        urls=urls,
        guids=guids,
        workshop_guids=workshop_guids,
        check_type=normalize_check_type(check_type.strip()),
        check_mode=normalize_check_mode(check_mode.strip()),
        babylon_cluster=cluster.strip() if cluster.strip() != "(auto)" else "",
    )
