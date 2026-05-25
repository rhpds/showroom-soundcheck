"""Two-tier health check service for showroom URLs.

Pure async module with no database dependencies.  Both the web UI
and CLI import this module and supply their own progress callbacks.

Tier 1: replicate the nookbag healthz logic locally (fetch config, probe
         content page, probe tab URLs).
Tier 2: legacy Antora showroom fallback (probe root + /content/ paths when
         no nookbag config exists).
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import yaml

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
PROBE_TIMEOUT = 10
CONFIG_FETCH_TIMEOUT = 10
MAX_CONFIG_SIZE = 64 * 1024  # 64 KiB
PROBE_RETRIES = 2
CONFIG_RETRIES = 3
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
    url: str | None
    reachable: bool = False
    status_code: int | None = None
    iframe_blocked: bool = False
    external: bool = False
    error: str | None = None


@dataclass
class ContentProbeResult:
    name: str
    url: str | None
    reachable: bool = False
    status_code: int | None = None
    error: str | None = None


@dataclass
class Tier2Detail:
    config_file: str | None = None
    config_url: str | None = None
    config_found: bool = False
    is_nookbag: bool = False
    root_reachable: bool = False
    root_status_code: int | None = None
    content_probes: list[ContentProbeResult] = field(default_factory=list)
    tabs: list[TabProbeResult] = field(default_factory=list)


@dataclass
class TargetCheckResult:
    url: str
    is_healthy: bool = False
    tier_used: int = 0
    check_type: str = "readyz"
    status_code: int | None = None
    response_time_ms: int = 0
    error_message: str | None = None
    detail: dict[str, Any] | None = None
    no_config: bool = False
    is_degraded: bool = False

    def detail_json(self) -> str | None:
        if self.detail is None:
            return None
        return json.dumps(self.detail, default=str)


class ProgressCallback(Protocol):
    async def __call__(self, url: str, status: str, result: TargetCheckResult | None) -> None: ...


# ---------------------------------------------------------------------------
# URL helpers (ported from nookbag healthz)
# ---------------------------------------------------------------------------


def _apply_tab_defaults(tab: dict) -> dict:
    tab = dict(tab)
    defaults = TAB_TYPE_DEFAULTS.get(tab.get("type", ""), {})
    for key, value in defaults.items():
        tab.setdefault(key, value)
    return tab


def _to_absolute_url(raw: str, base_url: str) -> str | None:
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("/"):
        return f"{base_url}{raw}"
    return None


def _is_proxied_path(path: str | None) -> bool:
    return bool(path) and path != "/"


def _is_external_url(url: str | None, base_url: str) -> bool:
    """True when url points to a third-party site, not the showroom's own services."""
    if not url:
        return False
    if url.startswith(base_url):
        return False
    if url.startswith("http://localhost") or url.startswith("https://localhost"):
        return False
    return url.startswith("http://") or url.startswith("https://")


def resolve_tab_urls(tab: dict, base_url: str) -> list[tuple[str, str | None]]:
    """Return (label, url) pairs for a tab config entry."""
    t = _apply_tab_defaults(tab)
    results: list[tuple[str, str | None]] = []

    url: str | None = None
    if t.get("url"):
        url = _to_absolute_url(t["url"], base_url)
    elif _is_proxied_path(t.get("path")):
        url = f"{base_url}{t['path']}"
    elif t.get("port"):
        proto = "https" if t["port"] in ("443", "8443") else "http"
        url = f"{proto}://localhost:{t['port']}{t.get('path', '')}"
    results.append((t.get("name", "unnamed"), url))

    sec_url: str | None = None
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
                value = lower[len("frame-ancestors") :].strip()
                if value == "'none'":
                    return True
    return False


async def _probe_url(client: httpx.AsyncClient, url: str, retries: int = PROBE_RETRIES) -> dict:
    """Probe a URL with HEAD, falling back to GET. Retries on transient 5xx."""
    last_error: str | None = None
    last_status: int | None = None
    for attempt in range(retries + 1):
        for method in ("HEAD", "GET"):
            try:
                resp = await client.request(method, url, timeout=PROBE_TIMEOUT)
                if resp.status_code == 405 and method == "HEAD":
                    continue
                if not (200 <= resp.status_code < 400) and method == "HEAD":
                    last_error = f"HTTP {resp.status_code}"
                    continue
                if 200 <= resp.status_code < 400:
                    result: dict = {
                        "reachable": True,
                        "status_code": resp.status_code,
                    }
                    if _check_iframe_headers(resp.headers):
                        result["iframe_blocked"] = True
                    return result
                last_status = resp.status_code
                if resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}"
                    break  # 5xx on GET — retry after backoff
                # 4xx is definitive, no point retrying
                return {"reachable": False, "status_code": resp.status_code}
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
    return {"reachable": False, "status_code": last_status, "error": last_error or "all probe methods failed"}


# ---------------------------------------------------------------------------
# Tier 1: local nookbag-style checks
# ---------------------------------------------------------------------------

NOOKBAG_BASES = ["/nookbag", ""]

NOOKBAG_FINGERPRINTS = ['id="root"', "<title>Showroom</title>"]


async def _detect_nookbag(
    client: httpx.AsyncClient,
    base_url: str,
) -> tuple[bool, bool, int | None]:
    """Fetch the root page and decide whether this is a nookbag (React) showroom.

    Returns (is_nookbag, root_reachable, root_status_code).
    Retries on transient failures (timeout, 5xx) to avoid misclassification.
    """
    last_status: int | None = None
    for attempt in range(PROBE_RETRIES + 1):
        try:
            resp = await client.get(base_url + "/", timeout=PROBE_TIMEOUT)
            last_status = resp.status_code
            reachable = 200 <= resp.status_code < 400
            if reachable:
                body = resp.text[:4096]
                is_nookbag = any(fp in body for fp in NOOKBAG_FINGERPRINTS)
                return is_nookbag, True, resp.status_code
            if resp.status_code < 500:
                return False, False, resp.status_code
            logger.debug(
                "nookbag detection attempt %d/%d got HTTP %d",
                attempt + 1,
                PROBE_RETRIES + 1,
                resp.status_code,
            )
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.debug(
                "nookbag detection attempt %d/%d failed: %s",
                attempt + 1,
                PROBE_RETRIES + 1,
                exc,
            )
        if attempt < PROBE_RETRIES:
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))

    return False, False, last_status


async def _fetch_config(
    client: httpx.AsyncClient,
    base_url: str,
) -> tuple[dict | None, str | None, str, bool]:
    """Fetch and parse the first available config file from nookbag.

    Tries each CONFIG_FILES name under each NOOKBAG_BASES prefix so that
    deployments serving configs at the root (no /nookbag/ prefix) are also
    discovered.  Each URL is attempted up to CONFIG_RETRIES times with a
    CONFIG_FETCH_TIMEOUT per attempt to handle transient failures.

    Returns (config_dict, config_filename, nookbag_base, timed_out).
    When no config is found returns (None, None, "", timed_out) where
    *timed_out* indicates whether any attempt failed due to a timeout.
    """
    saw_timeout = False
    for nookbag_base in NOOKBAG_BASES:
        for filename in CONFIG_FILES:
            url = f"{base_url}{nookbag_base}/{filename}"
            for attempt in range(CONFIG_RETRIES):
                try:
                    resp = await client.get(url, timeout=CONFIG_FETCH_TIMEOUT)
                    if resp.status_code == 200:
                        data = resp.content
                        if len(data) > MAX_CONFIG_SIZE:
                            logger.warning("config %s exceeds size limit", filename)
                            break
                        config = yaml.safe_load(data.decode("utf-8"))
                        if isinstance(config, dict):
                            return config, filename, nookbag_base, False
                        break
                    if resp.status_code == 404:
                        break
                    logger.debug(
                        "config %s attempt %d/%d returned HTTP %d",
                        filename,
                        attempt + 1,
                        CONFIG_RETRIES,
                        resp.status_code,
                    )
                except httpx.TimeoutException:
                    saw_timeout = True
                    logger.debug(
                        "timeout fetching config %s attempt %d/%d",
                        filename,
                        attempt + 1,
                        CONFIG_RETRIES,
                    )
                except (httpx.HTTPError, yaml.YAMLError, UnicodeDecodeError) as exc:
                    logger.debug(
                        "failed to fetch config %s attempt %d/%d: %s",
                        filename,
                        attempt + 1,
                        CONFIG_RETRIES,
                        exc,
                    )
                if attempt < CONFIG_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
    return None, None, "", saw_timeout


async def _probe_tabs(
    client: httpx.AsyncClient,
    entries: list[tuple[str, str | None]],
    base_url: str,
) -> list[TabProbeResult]:
    """Probe all tab URLs concurrently."""

    async def _probe_one(label: str, tab_url: str | None) -> TabProbeResult:
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


async def _run_tier1(
    client: httpx.AsyncClient,
    url: str,
    check_type: str,
) -> TargetCheckResult:
    """Run local nookbag-style readiness checks."""
    base_url = url.rstrip("/")
    start = time.monotonic()

    tier2 = Tier2Detail()

    is_nookbag, root_reachable, root_status = await _detect_nookbag(client, base_url)
    tier2.is_nookbag = is_nookbag
    tier2.root_reachable = root_reachable
    tier2.root_status_code = root_status

    config, config_file, nookbag_base, config_timed_out = await _fetch_config(client, base_url)
    tier2.config_file = config_file
    tier2.config_url = f"{base_url}{nookbag_base}/{config_file}" if config_file else None
    tier2.config_found = config is not None

    if config is None:
        elapsed = int((time.monotonic() - start) * 1000)
        if config_timed_out:
            msg = (
                f"Timed out fetching nookbag config (ui-config.yml / zero-touch-config.yml)"
                f" after {CONFIG_RETRIES} attempts ({CONFIG_FETCH_TIMEOUT}s each)"
            )
        elif is_nookbag:
            msg = "Nookbag showroom detected but config missing (ui-config.yml / zero-touch-config.yml)"
        elif root_reachable:
            msg = "Non-nookbag showroom detected, no config available"
        else:
            msg = "Showroom root unreachable, no config available"
        # Only fall back to Tier 2 for non-nookbag showrooms where root is
        # reachable (legacy Antora) or root is unreachable (unknown).
        # Nookbag showrooms *must* have a config — missing config is an error.
        no_config_fallback = not config_timed_out and not is_nookbag
        return TargetCheckResult(
            url=url,
            tier_used=1,
            check_type=check_type,
            response_time_ms=elapsed,
            error_message=msg,
            detail=_tier2_to_dict(tier2),
            no_config=no_config_fallback,
        )

    antora = config.get("antora", {}) or {}
    is_showroom = config.get("type") == "showroom"
    content_dir = antora.get("dir") or ("www" if is_showroom else "antora")
    content_name = antora.get("name") or "modules"
    version = antora.get("version")
    antora_modules = antora.get("modules") or []

    segments = [content_dir, content_name]
    if version:
        segments.append(version)
    content_path = "/".join(segments)

    if antora_modules:
        content_urls = []
        for mod in antora_modules:
            mod_name = mod if isinstance(mod, str) else mod.get("name", "")
            mod_label = mod_name if isinstance(mod, str) else mod.get("label", mod_name)
            if mod_name:
                mod_url = f"{base_url}{nookbag_base}/{content_path}/{mod_name}.html"
                content_urls.append((mod_label or mod_name, mod_url))
        if not content_urls:
            fallback_url = f"{base_url}{nookbag_base}/{content_path}/index.html"
            content_urls.append(("content", fallback_url))
    else:
        fallback_url = f"{base_url}{nookbag_base}/{content_path}/index.html"
        content_urls = [("content", fallback_url)]

    content_probe_tasks = []
    for _label, curl in content_urls:
        content_probe_tasks.append(_probe_url(client, curl))
    content_probe_results = await asyncio.gather(*content_probe_tasks)

    for (label, curl), probe in zip(content_urls, content_probe_results, strict=True):
        tier2.content_probes.append(
            ContentProbeResult(
                name=label,
                url=curl,
                reachable=probe.get("reachable", False),
                status_code=probe.get("status_code"),
                error=probe.get("error"),
            )
        )

    tabs_config = config.get("tabs", []) or []
    entries: list[tuple[str, str | None]] = []
    for tab in tabs_config:
        entries.extend(resolve_tab_urls(tab, base_url))

    tier2.tabs = await _probe_tabs(client, entries, base_url)

    all_content_reachable = bool(tier2.content_probes) and all(c.reachable for c in tier2.content_probes)
    all_tabs_ok = len(tier2.tabs) == 0 or all(t.reachable and (not t.iframe_blocked or t.external) for t in tier2.tabs)
    all_healthy = all_content_reachable and all_tabs_ok
    some_tabs_ok = any(t.reachable and (not t.iframe_blocked or t.external) for t in tier2.tabs)
    is_degraded = all_content_reachable and not all_tabs_ok and some_tabs_ok

    elapsed = int((time.monotonic() - start) * 1000)
    status_code = 200 if all_healthy else 503

    errors = []
    for c in tier2.content_probes:
        if not c.reachable:
            errors.append(f"Content '{c.name}' unreachable: {c.error or c.url}")
    for t in tier2.tabs:
        if not t.reachable:
            prefix = "[external] " if t.external else ""
            errors.append(f"{prefix}Tab '{t.name}' unreachable: {t.error or t.url}")
        elif t.iframe_blocked and not t.external:
            errors.append(f"Tab '{t.name}' blocks iframe embedding")

    return TargetCheckResult(
        url=url,
        is_healthy=all_healthy,
        is_degraded=is_degraded,
        tier_used=1,
        check_type=check_type,
        status_code=status_code,
        response_time_ms=elapsed,
        error_message="; ".join(errors) if errors else None,
        detail=_tier2_to_dict(tier2),
    )


def _tier2_to_dict(t: Tier2Detail) -> dict[str, Any]:
    content_list = [
        {
            "name": c.name,
            "url": c.url,
            "reachable": c.reachable,
            "status_code": c.status_code,
            "error": c.error,
        }
        for c in t.content_probes
    ]
    # Backward-compatible: single-probe results also get a flat "content" key
    single_content: dict[str, Any] = {}
    if len(content_list) == 1:
        single_content = content_list[0]

    result = {
        "config_file": t.config_file,
        "config_url": t.config_url,
        "config_found": t.config_found,
        "is_nookbag": t.is_nookbag,
        "root_reachable": t.root_reachable,
        "root_status_code": t.root_status_code,
        "content": single_content,
        "content_pages": content_list,
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
    return result


# ---------------------------------------------------------------------------
# Tier 2: legacy Antora showroom checks
# ---------------------------------------------------------------------------

LEGACY_CONTENT_PATHS = ["/content/"]


async def _run_tier2(
    client: httpx.AsyncClient,
    url: str,
    check_type: str,
) -> TargetCheckResult:
    """Probe legacy (pre-nookbag) Antora showrooms.

    These deployments serve a static nginx + Antora site without
    ui-config.yml.  We verify that both the showroom frame (root URL) and the
    Antora content (``/content/``) are reachable.
    """
    base_url = url.rstrip("/")
    start = time.monotonic()

    probe_entries: list[tuple[str, str]] = [
        ("showroom", base_url + "/"),
    ]
    for path in LEGACY_CONTENT_PATHS:
        probe_entries.append(("content", base_url + path))

    probe_results = await asyncio.gather(*[_probe_url(client, purl) for _, purl in probe_entries])

    content_probes: list[ContentProbeResult] = []
    for (label, purl), probe in zip(probe_entries, probe_results, strict=True):
        content_probes.append(
            ContentProbeResult(
                name=label,
                url=purl,
                reachable=probe.get("reachable", False),
                status_code=probe.get("status_code"),
                error=probe.get("error"),
            )
        )

    all_healthy = bool(content_probes) and all(c.reachable for c in content_probes)
    elapsed = int((time.monotonic() - start) * 1000)

    errors = []
    for c in content_probes:
        if not c.reachable:
            errors.append(f"Legacy probe '{c.name}' unreachable: {c.error or c.url}")

    detail: dict[str, Any] = {
        "config_found": False,
        "legacy": True,
        "content": {},
        "content_pages": [
            {
                "name": c.name,
                "url": c.url,
                "reachable": c.reachable,
                "status_code": c.status_code,
                "error": c.error,
            }
            for c in content_probes
        ],
        "tabs": [],
    }

    return TargetCheckResult(
        url=url,
        is_healthy=all_healthy,
        tier_used=2,
        check_type=check_type,
        status_code=200 if all_healthy else 503,
        response_time_ms=elapsed,
        error_message="; ".join(errors) if errors else None,
        detail=detail,
    )


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
    last_error: str | None = None

    for attempt in range(PROBE_RETRIES + 1):
        try:
            resp = await client.get(base_url, timeout=PROBE_TIMEOUT)
            elapsed = int((time.monotonic() - start) * 1000)
            is_healthy = 200 <= resp.status_code < 400
            return TargetCheckResult(
                url=url,
                is_healthy=is_healthy,
                tier_used=1,
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
        url=url,
        tier_used=1,
        check_type="healthz",
        response_time_ms=elapsed,
        error_message=last_error,
    )


def create_client(
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    limits: httpx.Limits | None = None,
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
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    client: httpx.AsyncClient | None = None,
) -> TargetCheckResult:
    """Run health check against a single showroom URL.

    check_type controls what is checked:
      "healthz"  - Liveness probe (just confirm the URL is reachable)
      "readyz"   - Readiness probe (full config + tab check)

    Strategy:
      Tier 1 first (local nookbag-style config + tab probing), then
      Tier 2 (legacy Antora fallback) if no config is found.

    If client is provided, it will be reused (caller manages lifecycle).
    Otherwise a new client is created and closed per-call.
    """
    from ..utils import is_url_allowed

    if not is_url_allowed(url):
        return TargetCheckResult(
            url=url,
            error_message=f"URL hostname not in allowlist: {url}",
        )

    owns_client = client is None
    if owns_client:
        client = create_client(timeout=timeout, verify_ssl=verify_ssl)

    try:
        if check_type == "healthz":
            return await _run_healthz(client, url)
        result = await _run_tier1(client, url, check_type)
        if result.no_config:
            logger.info(
                "Tier 1: no config for %s, falling back to Tier 2 (legacy)",
                url,
            )
            return await _run_tier2(client, url, check_type)
        return result
    finally:
        if owns_client:
            await client.aclose()


async def check_targets(
    urls: list[str],
    check_type: str = "readyz",
    concurrency: int = 10,
    verify_ssl: bool = True,
    on_progress: ProgressCallback | None = None,
) -> list[TargetCheckResult]:
    """Check multiple targets with concurrency control and shared connection pool.

    on_progress(url, status, result) is called for each target as it
    transitions through statuses: "running" then "done".
    """
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1 (got {concurrency})")

    semaphore = asyncio.Semaphore(concurrency)

    async with create_client(verify_ssl=verify_ssl) as client:

        async def _check_one(target_url: str) -> TargetCheckResult:
            if on_progress:
                await on_progress(target_url, "running", None)
            async with semaphore:
                result = await check_single_target(
                    target_url,
                    check_type,
                    client=client,
                )
            if on_progress:
                await on_progress(target_url, "done", result)
            return result

        tasks = [_check_one(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)
