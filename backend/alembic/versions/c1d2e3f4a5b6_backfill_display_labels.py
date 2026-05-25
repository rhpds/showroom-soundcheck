"""backfill display_labels

Data migration: populate display_label for any existing sessions that
have an empty value.  This logic was previously run on every page load
inside the load_sessions event handler.

Revision ID: c1d2e3f4a5b6
Revises: b5c6d7e8f9a0
Create Date: 2026-05-10 00:00:00.000000

"""

import json
import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUID_RE = re.compile(r"(?:-([a-z0-9]{4,6})(?:-\d+)?\.apps\.|\.cluster-([a-z0-9]+)\.)")


def _extract_guid(url: str) -> str | None:
    m = _GUID_RE.search(url)
    return (m.group(1) or m.group(2)) if m else None


def _make_label(source_urls: str, source_guids: str, source_workshop_guids: str) -> str:
    urls = json.loads(source_urls) if source_urls else []
    guids = json.loads(source_guids) if source_guids else []
    ws_guids = json.loads(source_workshop_guids) if source_workshop_guids else []

    parts: list[str] = []
    parts.extend(f"ws:{g}" for g in ws_guids)
    parts.extend(guids)
    if parts:
        return ", ".join(parts)

    items: list[str] = []
    for url in urls:
        extracted = _extract_guid(url)
        items.append(extracted if extracted else url)
    return ", ".join(items)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, source_urls, source_guids, source_workshop_guids "
            "FROM sessions WHERE display_label IS NULL OR display_label = ''"
        )
    ).fetchall()

    for row in rows:
        label = _make_label(row.source_urls, row.source_guids, row.source_workshop_guids)
        if label:
            conn.execute(
                sa.text("UPDATE sessions SET display_label = :label WHERE id = :id"),
                {"label": label, "id": row.id},
            )


def downgrade() -> None:
    pass
