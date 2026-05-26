"""Babylon cluster connections — httpx-based K8s API clients.

Ported from parsec's src/connections/babylon.py. Configured via the
BABYLON_CLUSTERS env var — a JSON array of kubeconfig paths. Array order
determines search priority (first element is tried first during GUID
resolution fallback).  Cluster names are derived from filenames by
stripping any leading ``NN-`` prefix and the ``.kubeconfig`` extension,
e.g. ``/secrets/00-east.kubeconfig`` → ``east``.

Legacy format (JSON object mapping name→path) is still accepted.
"""

import asyncio
import atexit
import json
import logging
import os
import re
import ssl
import tempfile
import threading
from base64 import b64decode
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

_NAME_PREFIX_RE = re.compile(r"^\d+-")


def _parse_kubeconfig(path: str) -> dict[str, Any]:
    """Parse a kubeconfig file and extract server URL, token, and TLS settings.

    Uses the current-context if set, otherwise the first context.
    """
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        raise FileNotFoundError(f"Kubeconfig not found: {expanded}")

    with open(expanded) as f:
        kc = yaml.safe_load(f)

    contexts = kc.get("contexts", [])
    if not contexts:
        raise ValueError(f"No contexts in kubeconfig: {path}")

    current_ctx = kc.get("current-context", "")
    ctx = None
    if current_ctx:
        ctx = next((c for c in contexts if c["name"] == current_ctx), None)
    if not ctx:
        ctx = contexts[0]

    ctx_info = ctx["context"]
    cluster_name = ctx_info["cluster"]
    user_name = ctx_info.get("user", "")

    clusters = kc.get("clusters", [])
    cluster = next((c for c in clusters if c["name"] == cluster_name), None)
    if not cluster:
        raise ValueError(f"Cluster '{cluster_name}' not found in kubeconfig: {path}")

    cluster_data = cluster["cluster"]
    server = cluster_data["server"].rstrip("/")
    verify_ssl = not cluster_data.get("insecure-skip-tls-verify", False)
    ca_data = cluster_data.get("certificate-authority-data", "")

    token = ""  # nosec B105
    client_cert_data = ""
    client_key_data = ""
    if user_name:
        users = kc.get("users", [])
        user = next((u for u in users if u["name"] == user_name), None)
        if user and "user" in user:
            token = user["user"].get("token", "")
            client_cert_data = user["user"].get("client-certificate-data", "")
            client_key_data = user["user"].get("client-key-data", "")

    return {
        "server": server,
        "token": token,
        "verify_ssl": verify_ssl,
        "ca_data": ca_data,
        "client_cert_data": client_cert_data,
        "client_key_data": client_key_data,
    }


def _build_ssl_context(cluster_cfg: dict[str, Any]) -> ssl.SSLContext | bool:
    """Build SSL context from cluster config, including client certificates."""
    has_ca = bool(cluster_cfg.get("ca_data"))
    has_client_cert = bool(cluster_cfg.get("client_cert_data") and cluster_cfg.get("client_key_data"))

    if not cluster_cfg["verify_ssl"] and not has_client_cert:
        return False

    if not has_ca and not has_client_cert:
        return True

    if cluster_cfg["verify_ssl"]:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    if has_ca:
        ca_bytes = b64decode(cluster_cfg["ca_data"])
        ctx.load_verify_locations(cadata=ca_bytes.decode("ascii"))

    if has_client_cert:
        cert_bytes = b64decode(cluster_cfg["client_cert_data"])
        key_bytes = b64decode(cluster_cfg["client_key_data"])

        cert_path = None
        key_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".crt", delete=False, mode="wb") as cf:
                cert_path = cf.name
                os.fchmod(cf.fileno(), 0o600)
                cf.write(cert_bytes)
            with tempfile.NamedTemporaryFile(suffix=".key", delete=False, mode="wb") as kf:
                key_path = kf.name
                os.fchmod(kf.fileno(), 0o600)
                kf.write(key_bytes)
            ctx.load_cert_chain(cert_path, key_path)
        finally:
            for path in (cert_path, key_path):
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    return ctx


def _name_from_path(path: str) -> str:
    """Derive a cluster name from a kubeconfig file path.

    ``/secrets/00-east.kubeconfig`` → ``east``
    ``/secrets/west.kubeconfig``    → ``west``
    """
    basename = os.path.basename(path)
    name = basename.removesuffix(".kubeconfig")
    name = _NAME_PREFIX_RE.sub("", name)
    return name.lower()


def _parse_clusters_env(raw: str) -> list[tuple[str, str]]:
    """Parse BABYLON_CLUSTERS into an ordered list of (name, path) tuples.

    Accepts two formats:
      - JSON array of kubeconfig paths (preferred). Order = priority.
        Names are derived from filenames.
      - Legacy JSON object mapping name → path. Iteration order = priority.
    """
    parsed = json.loads(raw)

    if isinstance(parsed, list):
        pairs: list[tuple[str, str]] = []
        for entry in parsed:
            if not isinstance(entry, str) or not entry:
                continue
            pairs.append((_name_from_path(entry), entry))
        return pairs

    if isinstance(parsed, dict):
        return [(name.lower(), path) for name, path in parsed.items()]

    raise ValueError(f"BABYLON_CLUSTERS must be a JSON array or object, got {type(parsed).__name__}")


class BabylonClientManager:
    """Manages Babylon cluster httpx clients and kubeconfig parsing.

    Wraps the previously module-level mutable state into a class for
    testability and isolation. The module-level functions below delegate
    to a default singleton instance.
    """

    def __init__(self) -> None:
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._cluster_configs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._initialized = False

    def init_clients(self) -> None:
        """Initialize from the BABYLON_CLUSTERS env var. No-op after first call.

        This performs synchronous file I/O (kubeconfig reading + YAML parsing).
        In async contexts, prefer :meth:`init_clients_async` which offloads
        the blocking work to a thread.
        """
        if self._initialized:
            return
        self._initialized = True

        raw = os.environ.get("BABYLON_CLUSTERS") or "[]"
        try:
            clusters = _parse_clusters_env(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("BABYLON_CLUSTERS is not valid: %s — %s", raw[:200], exc)
            return

        if not clusters:
            logger.info("No Babylon clusters configured (BABYLON_CLUSTERS is empty)")
            return

        for name, kubeconfig_path in clusters:
            if not kubeconfig_path:
                logger.warning("Babylon cluster '%s' has no kubeconfig path", name)
                continue
            try:
                parsed_cfg = _parse_kubeconfig(kubeconfig_path)
                self._cluster_configs[name] = parsed_cfg
                logger.info(
                    "Babylon cluster '%s' configured (server=%s)",
                    name,
                    parsed_cfg["server"],
                )
            except (FileNotFoundError, ValueError, KeyError, yaml.YAMLError):
                logger.exception("Failed to parse kubeconfig for Babylon cluster '%s'", name)

        logger.info("Babylon: %d cluster(s) configured", len(self._cluster_configs))
        atexit.register(self._sync_close_clients)

    async def init_clients_async(self) -> None:
        """Async wrapper around :meth:`init_clients`.

        Offloads the blocking kubeconfig file I/O and YAML parsing to a
        thread so the event loop is not blocked during startup.
        """
        if self._initialized:
            return
        await asyncio.to_thread(self.init_clients)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self.init_clients()

    async def get_client(self, cluster_name: str) -> httpx.AsyncClient:
        """Get or create an httpx client for a Babylon cluster (thread-safe)."""
        self._ensure_initialized()
        if cluster_name in self._clients:
            return self._clients[cluster_name]

        with self._lock:
            if cluster_name in self._clients:
                return self._clients[cluster_name]

            if cluster_name not in self._cluster_configs:
                raise ValueError(
                    f"Unknown Babylon cluster: '{cluster_name}'. Configured: {list(self._cluster_configs.keys())}"
                )

            cluster_cfg = self._cluster_configs[cluster_name]
            verify = _build_ssl_context(cluster_cfg)

            headers: dict[str, str] = {"Accept": "application/json"}
            if cluster_cfg.get("token"):
                headers["Authorization"] = f"Bearer {cluster_cfg['token']}"

            client = httpx.AsyncClient(
                base_url=cluster_cfg["server"],
                headers=headers,
                verify=verify,
                timeout=30.0,
            )
            self._clients[cluster_name] = client
            return client

    def get_configured_clusters(self) -> list[str]:
        """Return list of configured Babylon cluster names."""
        self._ensure_initialized()
        return list(self._cluster_configs.keys())

    def _sync_close_clients(self) -> None:
        """Synchronous shutdown hook — closes all httpx clients at interpreter exit."""
        if not self._clients:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.close_clients())
        except RuntimeError:
            asyncio.run(self.close_clients())

    async def close_clients(self) -> None:
        """Close all httpx clients."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


# ---------------------------------------------------------------------------
# Default singleton and module-level convenience functions
# ---------------------------------------------------------------------------

_default_manager = BabylonClientManager()


def get_configured_clusters() -> list[str]:
    """Return list of configured Babylon cluster names."""
    return _default_manager.get_configured_clusters()


# ---------------------------------------------------------------------------
# Babylon catalog URL mapping (cluster name → UI base URL)
# ---------------------------------------------------------------------------

_catalog_urls: dict[str, str] | None = None


def _load_catalog_urls() -> dict[str, str]:
    global _catalog_urls
    if _catalog_urls is not None:
        return _catalog_urls
    raw = os.environ.get("BABYLON_CATALOG_URLS", "")
    if not raw:
        _catalog_urls = {}
        return _catalog_urls
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("expected JSON object")
        _catalog_urls = {k.lower(): v.rstrip("/") for k, v in parsed.items()}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("BABYLON_CATALOG_URLS is not valid: %s — %s", raw[:200], exc)
        _catalog_urls = {}
    return _catalog_urls


def get_catalog_url(cluster: str) -> str:
    """Return the catalog UI base URL for a cluster, or empty string."""
    return _load_catalog_urls().get(cluster.lower(), "")


async def k8s_get_resource(
    cluster_name: str,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
) -> dict:
    """Get a single custom resource by name."""
    if group:
        path = f"/apis/{group}/{version}/namespaces/{namespace}/{plural}/{name}"
    else:
        path = f"/api/{version}/namespaces/{namespace}/{plural}/{name}"

    client = await _default_manager.get_client(cluster_name)
    resp = await client.get(path)
    resp.raise_for_status()
    return resp.json()


async def k8s_list_cluster_wide(
    cluster_name: str,
    group: str,
    version: str,
    plural: str,
    label_selector: str = "",
    limit: int = 0,
) -> dict:
    """List custom resources across all namespaces (cluster-wide)."""
    path = f"/apis/{group}/{version}/{plural}" if group else f"/api/{version}/{plural}"

    params: dict[str, str | int] = {}
    if label_selector:
        params["labelSelector"] = label_selector
    if limit:
        params["limit"] = limit

    client = await _default_manager.get_client(cluster_name)
    resp = await client.get(path, params=params)
    resp.raise_for_status()
    return resp.json()
