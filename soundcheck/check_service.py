"""Two-tier health check service for showroom URLs.

Pure async module with no Reflex or database dependencies.  Both the web UI
and CLI import this module and supply their own progress callbacks.

Tier 1: delegate to the showroom's own /readyz or /healthz sidecar.
Tier 2: replicate the nookbag healthz logic locally (fetch config, probe
         content page, probe tab URLs).
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import httpx
import yaml

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
PROBE_TIMEOUT = 5
MAX_CONFIG_SIZE = 1024 * 1024  # 1 MiB
PROBE_RETRIES = 2
RETRY_DELAY = 1.0

DEFAULT_POOL_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30,
)

CONFIG_FILES = ["ui-config.yml", "zero-touch-config.yml"]

TAB_TYPE_DEFAULTS: dict[str, dict[str, str]] = {
    "double-terminal": {
        "path": "/tty-top",
        "port": "443",
        "secondary_path": "/tty-bottom",
        "secondary_port": "443",
    },
    "terminal": {"path": "/tty1", "port": "443"},
    "secondary-terminal": {"path": "/tty2", "port": "443"},
    "codeserver": {"path": "/", "port": "8443"},
    "parasol": {"path": "/", "port": "8005"},
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class TabProbeResult:
    name: str
    url: Optional[str]
    reachable: bool = False
    status_code: Optional[int] = None
    iframe_blocked: bool = False
    external: bool = False
    error: Optional[str] = None


@dataclass
class Tier2Detail:
    config_file: Optional[str] = None
    config_found: bool = False
    content_url: Optional[str] = None
    content_reachable: bool = False
    content_status_code: Optional[int] = None
    content_error: Optional[str] = None
    tabs: list[TabProbeResult] = field(default_factory=list)


@dataclass
class TargetCheckResult:
    url: str
    is_healthy: bool = False
    tier_used: int = 0
    check_type: str = "readyz"
    status_code: Optional[int] = None
    response_time_ms: int = 0
    error_message: Optional[str] = None
    detail: Optional[dict[str, Any]] = None

    def detail_json(self) -> Optional[str]:
        if self.detail is None:
            return None
        return json.dumps(self.detail, default=str)


class ProgressCallback(Protocol):
    async def __call__(self, url: str, status: str, result: Optional[TargetCheckResult]) -> None: ...


# ---------------------------------------------------------------------------
# URL helpers (ported from nookbag healthz)
# ---------------------------------------------------------------------------

def _apply_tab_defaults(tab: dict) -> dict:
    tab = dict(tab)
    defaults = TAB_TYPE_DEFAULTS.get(tab.get("type", ""), {})
    for key, value in defaults.items():
        tab.setdefault(key, value)
    return tab


def _to_absolute_url(raw: str, base_url: str) -> Optional[str]:
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("/"):
        return f"{base_url}{raw}"
    return None


def _is_proxied_path(path: Optional[str]) -> bool:
    return bool(path) and path != "/"


def _is_external_url(url: Optional[str], base_url: str) -> bool:
    """True when url points to a third-party site, not the showroom's own services."""
    if not url:
        return False
    if url.startswith(base_url):
        return False
    if url.startswith("http://localhost") or url.startswith("https://localhost"):
        return False
    return url.startswith("http://") or url.startswith("https://")


def resolve_tab_urls(tab: dict, base_url: str) -> list[tuple[str, Optional[str]]]:
    """Return (label, url) pairs for a tab config entry."""
    t = _apply_tab_defaults(tab)
    results: list[tuple[str, Optional[str]]] = []

    url: Optional[str] = None
    if t.get("url"):
        url = _to_absolute_url(t["url"], base_url)
    elif _is_proxied_path(t.get("path")):
        url = f"{base_url}{t['path']}"
    elif t.get("port"):
        proto = "https" if t["port"] in ("443", "8443") else "http"
        url = f"{proto}://localhost:{t['port']}{t.get('path', '')}"
    results.append((t.get("name", "unnamed"), url))

    sec_url: Optional[str] = None
    if t.get("secondary_url"):
        sec_url = _to_absolute_url(t["secondary_url"], base_url)
    elif _is_proxied_path(t.get("secondary_path")):
        sec_url = f"{base_url}{t['secondary_path']}"
    elif t.get("secondary_path") and (t.get("secondary_port") or t.get("port")):
        port = t.get("secondary_port") or t["port"]
        proto = "https" if port in ("443", "8443") else "http"
        sec_url = f"{proto}://localhost:{port}{t['secondary_path']}"
    if sec_url:
        label = f"{t.get('name', 'unnamed')} ({t.get('secondary_name', 'secondary')})"
        results.append((label, sec_url))

    return results


# ---------------------------------------------------------------------------
# HTTP probing
# ---------------------------------------------------------------------------

def _check_iframe_headers(headers: httpx.Headers) -> bool:
    xfo = (headers.get("x-frame-options") or "").strip().upper()
    if xfo in ("DENY", "SAMEORIGIN"):
        return True
    for csp_value in headers.get_list("content-security-policy"):
        for directive in csp_value.split(";"):
            lower = directive.strip().lower()
            if lower.startswith("frame-ancestors"):
                value = lower[len("frame-ancestors"):].strip()
                if value == "'none'":
                    return True
    return False


async def _probe_url(client: httpx.AsyncClient, url: str, retries: int = PROBE_RETRIES) -> dict:
    """Probe a URL with HEAD, falling back to GET. Retries on transient failures."""
    last_error: Optional[str] = None
    for attempt in range(retries + 1):
        for method in ("HEAD", "GET"):
            try:
                resp = await client.request(method, url, timeout=PROBE_TIMEOUT)
                if resp.status_code == 405 and method == "HEAD":
                    continue
                if not (200 <= resp.status_code < 400) and method == "HEAD":
                    last_error = f"HTTP {resp.status_code}"
                    continue
                result: dict = {
                    "reachable": 200 <= resp.status_code < 400,
                    "status_code": resp.status_code,
                }
                if _check_iframe_headers(resp.headers):
                    result["iframe_blocked"] = True
                return result
            except httpx.TimeoutException:
                if method == "HEAD":
                    last_error = f"timeout after {PROBE_TIMEOUT}s"
                    continue
                last_error = f"timeout after {PROBE_TIMEOUT}s"
                break
            except httpx.HTTPError as exc:
                if method == "HEAD":
                    last_error = str(exc)[:300]
                    continue
                last_error = str(exc)[:300]
                break
        if attempt < retries:
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))
    return {"reachable": False, "error": last_error or "all probe methods failed"}


# ---------------------------------------------------------------------------
# Tier 1: delegate to showroom's own health endpoint
# ---------------------------------------------------------------------------

async def _run_tier1(
    client: httpx.AsyncClient,
    url: str,
    check_type: str,
) -> TargetCheckResult:
    """Hit the showroom's own /readyz or /healthz endpoint with retry."""
    endpoint = f"{url.rstrip('/')}/{check_type}"
    start = time.monotonic()
    last_error: Optional[str] = None

    for attempt in range(PROBE_RETRIES + 1):
        try:
            resp = await client.get(endpoint, timeout=DEFAULT_TIMEOUT)
            elapsed = int((time.monotonic() - start) * 1000)
            is_healthy = 200 <= resp.status_code < 400
            error = None if is_healthy else f"HTTP {resp.status_code}"

            detail = None
            try:
                detail = resp.json()
            except Exception:
                pass

            return TargetCheckResult(
                url=url,
                is_healthy=is_healthy,
                tier_used=1,
                check_type=check_type,
                status_code=resp.status_code,
                response_time_ms=elapsed,
                error_message=error,
                detail=detail,
            )
        except httpx.TimeoutException:
            last_error = f"Timeout after {DEFAULT_TIMEOUT}s"
        except httpx.ConnectError as e:
            last_error = f"Connection error: {e}"
        except httpx.HTTPError as e:
            last_error = str(e)[:300]

        if attempt < PROBE_RETRIES:
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))

    elapsed = int((time.monotonic() - start) * 1000)
    return TargetCheckResult(
        url=url, tier_used=1, check_type=check_type,
        response_time_ms=elapsed,
        error_message=last_error,
    )


# ---------------------------------------------------------------------------
# Tier 2: local nookbag-style checks
# ---------------------------------------------------------------------------

NOOKBAG_BASES = ["/nookbag", ""]


async def _fetch_config(
    client: httpx.AsyncClient, base_url: str,
) -> tuple[Optional[dict], Optional[str], str, bool]:
    """Fetch and parse the first available config file from nookbag.

    Tries each CONFIG_FILES name under each NOOKBAG_BASES prefix so that
    deployments serving configs at the root (no /nookbag/ prefix) are also
    discovered.

    Returns (config_dict, config_filename, nookbag_base, timed_out).
    When no config is found returns (None, None, "", timed_out) where
    *timed_out* indicates whether any attempt failed due to a timeout.
    """
    saw_timeout = False
    for nookbag_base in NOOKBAG_BASES:
        for filename in CONFIG_FILES:
            url = f"{base_url}{nookbag_base}/{filename}"
            try:
                resp = await client.get(url, timeout=PROBE_TIMEOUT)
                if resp.status_code == 200:
                    data = resp.content
                    if len(data) > MAX_CONFIG_SIZE:
                        logger.warning("config %s exceeds size limit", filename)
                        continue
                    config = yaml.safe_load(data.decode("utf-8"))
                    if isinstance(config, dict):
                        return config, filename, nookbag_base, False
            except httpx.TimeoutException:
                saw_timeout = True
                logger.debug("timeout fetching config %s", filename)
            except (httpx.HTTPError, yaml.YAMLError, UnicodeDecodeError) as exc:
                logger.debug("failed to fetch config %s: %s", filename, exc)
                continue
    return None, None, "", saw_timeout


async def _probe_tabs(
    client: httpx.AsyncClient,
    entries: list[tuple[str, Optional[str]]],
    base_url: str,
) -> list[TabProbeResult]:
    """Probe all tab URLs concurrently."""

    async def _probe_one(label: str, tab_url: Optional[str]) -> TabProbeResult:
        if not tab_url:
            return TabProbeResult(name=label, url=None, error="no url configured")
        probe = await _probe_url(client, tab_url)
        return TabProbeResult(
            name=label,
            url=tab_url,
            reachable=probe.get("reachable", False),
            status_code=probe.get("status_code"),
            iframe_blocked=probe.get("iframe_blocked", False),
            external=_is_external_url(tab_url, base_url),
            error=probe.get("error"),
        )

    return list(await asyncio.gather(*[_probe_one(label, url) for label, url in entries]))


async def _run_tier2(
    client: httpx.AsyncClient,
    url: str,
    check_type: str,
) -> TargetCheckResult:
    """Run local nookbag-style readiness checks."""
    base_url = url.rstrip("/")
    start = time.monotonic()

    tier2 = Tier2Detail()

    config, config_file, nookbag_base, config_timed_out = await _fetch_config(client, base_url)
    tier2.config_file = config_file
    tier2.config_found = config is not None

    if config is None:
        elapsed = int((time.monotonic() - start) * 1000)
        if config_timed_out:
            msg = f"Timed out fetching nookbag config (ui-config.yml / zero-touch-config.yml) after {PROBE_TIMEOUT}s"
        else:
            msg = "No nookbag config found (ui-config.yml / zero-touch-config.yml)"
        return TargetCheckResult(
            url=url, tier_used=2, check_type=check_type,
            response_time_ms=elapsed,
            error_message=msg,
            detail=_tier2_to_dict(tier2),
        )

    antora = config.get("antora", {}) or {}
    is_showroom = config.get("type") == "showroom"
    content_dir = antora.get("dir") or ("www" if is_showroom else "antora")
    content_name = antora.get("name") or "modules"
    version = antora.get("version")

    segments = [content_dir, content_name]
    if version:
        segments.append(version)
    content_path = "/".join(segments)
    content_url = f"{base_url}{nookbag_base}/{content_path}/index.html"
    tier2.content_url = content_url

    content_probe = await _probe_url(client, content_url)
    tier2.content_reachable = content_probe.get("reachable", False)
    tier2.content_status_code = content_probe.get("status_code")
    tier2.content_error = content_probe.get("error")

    tabs_config = config.get("tabs", []) or []
    entries: list[tuple[str, Optional[str]]] = []
    for tab in tabs_config:
        entries.extend(resolve_tab_urls(tab, base_url))

    tier2.tabs = await _probe_tabs(client, entries, base_url)

    all_healthy = (
        tier2.content_reachable
        and (len(tier2.tabs) == 0 or all(
            t.reachable and not t.iframe_blocked for t in tier2.tabs
        ))
    )

    elapsed = int((time.monotonic() - start) * 1000)
    status_code = 200 if all_healthy else 503

    errors = []
    if not tier2.content_reachable:
        errors.append(f"Content unreachable: {tier2.content_error or content_url}")
    for t in tier2.tabs:
        if not t.reachable:
            prefix = "[external] " if t.external else ""
            errors.append(f"{prefix}Tab '{t.name}' unreachable: {t.error or t.url}")
        elif t.iframe_blocked and not t.external:
            errors.append(f"Tab '{t.name}' blocks iframe embedding")

    return TargetCheckResult(
        url=url,
        is_healthy=all_healthy,
        tier_used=2,
        check_type=check_type,
        status_code=status_code,
        response_time_ms=elapsed,
        error_message="; ".join(errors) if errors else None,
        detail=_tier2_to_dict(tier2),
    )


def _tier2_to_dict(t: Tier2Detail) -> dict[str, Any]:
    return {
        "config_file": t.config_file,
        "config_found": t.config_found,
        "content": {
            "url": t.content_url,
            "reachable": t.content_reachable,
            "status_code": t.content_status_code,
            "error": t.content_error,
        },
        "tabs": [
            {
                "name": tab.name,
                "url": tab.url,
                "reachable": tab.reachable,
                "status_code": tab.status_code,
                "iframe_blocked": tab.iframe_blocked,
                "external": tab.external,
                "error": tab.error,
            }
            for tab in t.tabs
        ],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def _run_healthz(
    client: httpx.AsyncClient,
    url: str,
) -> TargetCheckResult:
    """Simple liveness check with retry — just confirm the base URL is reachable."""
    base_url = url.rstrip("/")
    start = time.monotonic()
    last_error: Optional[str] = None

    for attempt in range(PROBE_RETRIES + 1):
        try:
            resp = await client.get(base_url, timeout=PROBE_TIMEOUT)
            elapsed = int((time.monotonic() - start) * 1000)
            is_healthy = 200 <= resp.status_code < 400
            return TargetCheckResult(
                url=url,
                is_healthy=is_healthy,
                tier_used=2,
                check_type="healthz",
                status_code=resp.status_code,
                response_time_ms=elapsed,
                error_message=None if is_healthy else f"HTTP {resp.status_code}",
            )
        except httpx.TimeoutException:
            last_error = f"Timeout after {PROBE_TIMEOUT}s"
        except httpx.HTTPError as e:
            last_error = str(e)[:300]

        if attempt < PROBE_RETRIES:
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))

    elapsed = int((time.monotonic() - start) * 1000)
    return TargetCheckResult(
        url=url, tier_used=2, check_type="healthz",
        response_time_ms=elapsed,
        error_message=last_error,
    )


def create_client(
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    limits: Optional[httpx.Limits] = None,
) -> httpx.AsyncClient:
    """Create a configured httpx.AsyncClient for health checks."""
    return httpx.AsyncClient(
        follow_redirects=True,
        verify=verify_ssl,
        timeout=httpx.Timeout(timeout, connect=10.0),
        limits=limits or DEFAULT_POOL_LIMITS,
    )


async def check_single_target(
    url: str,
    check_type: str = "readyz",
    check_mode: str = "manual",
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    client: Optional[httpx.AsyncClient] = None,
) -> TargetCheckResult:
    """Run health check against a single showroom URL.

    check_type controls what is checked:
      "healthz"  - Liveness probe (just confirm the URL is reachable)
      "readyz"   - Readiness probe (full config + tab check)

    check_mode controls the strategy:
      "manual"   - Tier 2 only (local nookbag-style checks, skip showroom sidecar)
      "showroom" - Tier 1 first (delegate to showroom /readyz or /healthz),
                   fall back to Tier 2 if the sidecar is unavailable
      "auto"     - same as "showroom" (try Tier 1, fall back to Tier 2)

    If client is provided, it will be reused (caller manages lifecycle).
    Otherwise a new client is created and closed per-call.
    """
    owns_client = client is None
    if owns_client:
        client = create_client(timeout=timeout, verify_ssl=verify_ssl)

    try:
        if check_mode == "manual":
            if check_type == "healthz":
                return await _run_healthz(client, url)
            return await _run_tier2(client, url, check_type)

        result = await _run_tier1(client, url, check_type)

        tier1_is_404 = result.status_code == 404
        tier1_conn_error = result.error_message and "Connection error" in result.error_message

        if result.is_healthy:
            return result

        if tier1_is_404 or tier1_conn_error:
            logger.info(
                "Tier 1 unavailable for %s (status=%s), falling back to Tier 2",
                url, result.status_code,
            )
            return await _run_tier2(client, url, check_type)

        return result
    finally:
        if owns_client:
            await client.aclose()


async def check_targets(
    urls: list[str],
    check_type: str = "readyz",
    check_mode: str = "manual",
    concurrency: int = 10,
    verify_ssl: bool = True,
    on_progress: Optional[ProgressCallback] = None,
) -> list[TargetCheckResult]:
    """Check multiple targets with concurrency control and shared connection pool.

    on_progress(url, status, result) is called for each target as it
    transitions through statuses: "checking" then "done".
    """
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1 (got {concurrency})")

    semaphore = asyncio.Semaphore(concurrency)

    async with create_client(verify_ssl=verify_ssl) as client:
        async def _check_one(target_url: str) -> TargetCheckResult:
            if on_progress:
                await on_progress(target_url, "checking", None)
            async with semaphore:
                result = await check_single_target(
                    target_url, check_type, check_mode, client=client,
                )
            if on_progress:
                await on_progress(target_url, "done", result)
            return result

        tasks = [_check_one(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)
