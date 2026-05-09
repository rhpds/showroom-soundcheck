import os

import reflex as rx
from reflex.plugins.sitemap import SitemapPlugin


def _default_db_url() -> str:
    return (
        f"postgresql://{os.environ.get('POSTGRES_USER', 'soundcheck')}"
        f":{os.environ.get('POSTGRES_PASSWORD', 'soundcheck_dev')}"
        f"@{os.environ.get('POSTGRES_HOST', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ.get('POSTGRES_DB', 'soundcheck')}"
    )


def _derive_async_db_url(db_url: str | None) -> str | None:
    """Convert a sync PostgreSQL DB URL to its asyncpg equivalent.

    Returns None for non-PostgreSQL URLs (e.g. sqlite) so the caller
    can fall back gracefully.
    """
    if not db_url or "://" not in db_url:
        return None
    scheme, tail = db_url.split("://", 1)
    if scheme == "postgresql+asyncpg":
        return db_url
    if scheme in ("postgres", "postgresql") or scheme.startswith("postgresql+"):
        return f"postgresql+asyncpg://{tail}"
    return None


def _configured_async_db_url(db_url: str | None) -> str | None:
    explicit = (
        os.environ.get("ASYNC_DATABASE_URL")
        or os.environ.get("ASYNC_DB_URL")
        or os.environ.get("REFLEX_ASYNC_DB_URL")
    )
    if explicit:
        return explicit
    return _derive_async_db_url(db_url)


_db_url = os.environ.get("DATABASE_URL", _default_db_url())
_theme = rx.theme(
    appearance="light",
    has_background=True,
    accent_color="blue",
    radius="large",
    scaling="100%",
)

_config_kwargs: dict = dict(
    app_name="soundcheck",
    disable_plugins=[SitemapPlugin],
    plugins=[rx.plugins.RadixThemesPlugin(theme=_theme)],
    db_url=_db_url,
    async_db_url=_configured_async_db_url(_db_url),
)

if os.environ.get("API_URL"):
    _config_kwargs["api_url"] = os.environ["API_URL"]

config = rx.Config(**_config_kwargs)
