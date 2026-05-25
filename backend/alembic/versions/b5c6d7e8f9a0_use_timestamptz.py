"""use timestamptz

Switch all datetime columns from TIMESTAMP WITHOUT TIME ZONE to
TIMESTAMP WITH TIME ZONE.  Existing values are already UTC by
convention, so PostgreSQL interprets them correctly during the cast
(the server timezone defaults to UTC).

Revision ID: b5c6d7e8f9a0
Revises: a1b2c3d4e5f6
Create Date: 2026-05-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = [
    ("sessions", "created_at"),
    ("sessions", "completed_at"),
    ("session_targets", "check_started_at"),
    ("session_targets", "check_completed_at"),
    ("check_results", "checked_at"),
]


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL timezone = 'UTC'"))
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            existing_nullable=column != "created_at" and column != "checked_at",
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=column != "created_at" and column != "checked_at",
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
