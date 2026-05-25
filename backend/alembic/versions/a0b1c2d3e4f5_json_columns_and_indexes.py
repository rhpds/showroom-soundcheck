"""Convert JSON-in-string columns to native JSON and add performance indexes.

Revision ID: a0b1c2d3e4f5
Revises: d4e5f6a7b8c0
Create Date: 2026-05-24 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "d4e5f6a7b8c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMNS = [
    ("sessions", "source_urls", "[]"),
    ("sessions", "source_guids", "[]"),
    ("sessions", "source_workshop_guids", "[]"),
    ("sessions", "source_resource_pools", "[]"),
    ("sessions", "resource_metadata", "{}"),
    ("session_groups", "source_guids", "[]"),
    ("session_groups", "source_workshop_guids", "[]"),
    ("session_groups", "source_resource_pools", "[]"),
    ("session_groups", "member_metadata", "{}"),
]


def upgrade() -> None:
    for table, column, default in JSON_COLUMNS:
        op.execute(sa.text(f'ALTER TABLE {table} ALTER COLUMN "{column}" DROP DEFAULT'))
        op.execute(sa.text(f'ALTER TABLE {table} ALTER COLUMN "{column}" TYPE JSON USING "{column}"::json'))
        op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN \"{column}\" SET DEFAULT '{default}'::json"))

    op.create_index("ix_sessions_status", "sessions", ["status"])
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_created_at", table_name="sessions")
    op.drop_index("ix_sessions_status", table_name="sessions")

    for table, column, default in JSON_COLUMNS:
        op.execute(sa.text(f'ALTER TABLE {table} ALTER COLUMN "{column}" TYPE VARCHAR USING "{column}"::text'))
        op.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN \"{column}\" SET DEFAULT '{default}'"))
