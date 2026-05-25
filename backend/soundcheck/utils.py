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
from datetime import UTC, datetime
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
    return datetime.now(UTC)


def escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters in user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


VALID_CHECK_TYPES = ("readyz", "healthz")

# ---------------------------------------------------------------------------
# Error message sanitization
# ---------------------------------------------------------------------------

_K8S_URL_RE = re.compile(r"https?://[^\s'\"]+/apis?/[^\s'\"]*")
_FILE_PATH_RE = re.compile(r"(?:/[\w.-]+){3,}")


def sanitize_error(msg: str | None) -> str | None:
    """Strip internal details from error messages before exposing to clients.

    Removes K8s API server URLs and absolute file paths that could leak
    infrastructure topology or deployment internals.
    """
    if not msg:
        return msg
    msg = _K8S_URL_RE.sub("<k8s-api>", msg)
    msg = _FILE_PATH_RE.sub("<path>", msg)
    return msg

# ---------------------------------------------------------------------------
# URL allowlist (SSRF prevention)
# ---------------------------------------------------------------------------

_URL_ALLOWLIST: list[str] | None = None


def _get_url_allowlist() -> list[str]:
    """Return the cached allowlist, loading it lazily on first access.

    Lazy loading avoids crashing at import time when runtime env vars
    aren't available.
    """
    global _URL_ALLOWLIST  # noqa: PLW0603
    if _URL_ALLOWLIST is not None:
        return _URL_ALLOWLIST

    raw = os.environ.get("ALLOWED_URL_PATTERNS", "")
    patterns = [p.strip() for p in raw.split(",") if p.strip()]
    if not patterns:
        raise RuntimeError(
            "ALLOWED_URL_PATTERNS env var is required. "
            "Set to a comma-separated list of hostname globs "
            "(e.g. '*.redhat.com,*.opentlc.com,localhost')."
        )
    _URL_ALLOWLIST = patterns
    logger.info("URL allowlist loaded: %s", _URL_ALLOWLIST)
    return _URL_ALLOWLIST


def is_url_allowed(url: str) -> bool:
    """Check if a URL's hostname matches any allowed pattern.

    Rejects non-HTTP schemes and URLs without a valid hostname
    as defense-in-depth against SSRF.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname or ""
    if not hostname:
        return False
    return any(fnmatch.fnmatch(hostname, pattern) for pattern in _get_url_allowlist())


def extract_guid_from_url(url: str) -> str | None:
    """Extract a GUID from a showroom/bastion URL hostname."""
    m = GUID_RE.search(url)
    if not m:
        return None
    return m.group(1) or m.group(2)


def make_display_label(
    urls: list[str],
    guids: list[str],
    workshop_guids: list[str] | None = None,
    resource_pools: list[str] | None = None,
) -> str:
    """Build a human-friendly label for the sidebar.

    Prefers GUIDs when available. For bare URLs, tries to pull the GUID out of
    the ``cluster-<guid>`` hostname component; falls back to the raw URL.
    """
    parts: list[str] = []
    if resource_pools:
        parts.extend(f"pool:{p}" for p in resource_pools)
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


@dataclass
class ParsedSessionInput:
    """Validated and normalized session creation input."""

    session_name: str = ""
    urls: list[str] = field(default_factory=list)
    guids: list[str] = field(default_factory=list)
    workshop_guids: list[str] = field(default_factory=list)
    resource_pools: list[str] = field(default_factory=list)
    check_type: str = "readyz"
    babylon_cluster: str = ""


class InputValidationError(Exception):
    """Raised when user-supplied session input fails validation."""


def parse_check_params(
    *,
    raw_urls: str,
    raw_guids: str,
    raw_ws_guids: str,
    raw_resource_pools: str = "",
    check_type: str = "readyz",
    session_name: str = "",
    cluster: str = "",
    url_separator: str = ",",
) -> ParsedSessionInput:
    """Parse and validate raw input from either query params or form data.

    A session accepts exactly one of:
      - One or more URLs
      - A single ResourceClaim GUID
      - A single Workshop GUID
      - A single ResourcePool name

    Raises InputValidationError on invalid input.
    """
    urls = [u.strip() for u in raw_urls.split(url_separator) if u.strip()] if raw_urls else []
    guids = [g.strip() for g in raw_guids.replace(",", "\n").split("\n") if g.strip()] if raw_guids else []
    workshop_guids = (
        [g.strip() for g in raw_ws_guids.replace(",", "\n").split("\n") if g.strip()] if raw_ws_guids else []
    )
    resource_pools = (
        [p.strip() for p in raw_resource_pools.replace(",", "\n").split("\n") if p.strip()]
        if raw_resource_pools
        else []
    )

    if not urls and not guids and not workshop_guids and not resource_pools:
        raise InputValidationError("Provide at least one URL, GUID, Workshop GUID, or ResourcePool name")

    input_kinds = sum(bool(x) for x in (urls, guids, workshop_guids, resource_pools))
    if input_kinds > 1:
        raise InputValidationError("Provide only one of: URLs, ResourceClaim GUID, Workshop GUID, or ResourcePool name")

    if len(guids) > 1:
        raise InputValidationError("Only one ResourceClaim GUID per session is supported")

    if len(workshop_guids) > 1:
        raise InputValidationError("Only one Workshop GUID per session is supported")

    if len(resource_pools) > 1:
        raise InputValidationError("Only one ResourcePool name per session is supported")

    valid_prefixes = ("https://", "http://")
    for url in urls:
        if not url.startswith(valid_prefixes):
            raise InputValidationError(f"Invalid URL (must start with http:// or https://): {url}")
        if not is_url_allowed(url):
            raise InputValidationError(f"URL hostname not in allowlist: {url}")

    return ParsedSessionInput(
        session_name=session_name.strip(),
        urls=urls,
        guids=guids,
        workshop_guids=workshop_guids,
        resource_pools=resource_pools,
        check_type=normalize_check_type(check_type.strip()),
        babylon_cluster=cluster.strip() if cluster.strip() != "(auto)" else "",
    )
