import reflex as rx
from reflex.plugins.sitemap import SitemapPlugin
import os

_config_kwargs: dict = dict(
    app_name="soundcheck",
    disable_plugins=[SitemapPlugin],
    db_url=os.environ.get(
        "DATABASE_URL",
        f"postgresql://{os.environ.get('POSTGRES_USER', 'soundcheck')}"
        f":{os.environ.get('POSTGRES_PASSWORD', 'soundcheck_dev')}"
        f"@{os.environ.get('POSTGRES_HOST', 'localhost')}"
        f":{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ.get('POSTGRES_DB', 'soundcheck')}",
    ),
)

if os.environ.get("API_URL"):
    _config_kwargs["api_url"] = os.environ["API_URL"]

config = rx.Config(**_config_kwargs)
