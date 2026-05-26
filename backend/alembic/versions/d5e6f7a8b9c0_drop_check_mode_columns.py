"""Drop unused check_mode columns from session_groups and sessions.

The check_mode field was never read or written by the application;
it always kept the default value of "manual".

Revision ID: d5e6f7a8b9c0
Revises: c2d3e4f5a6b7
Create Date: 2026-05-26 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("session_groups", "check_mode")
    op.drop_column("sessions", "check_mode")


def downgrade() -> None:
    op.add_column("sessions", sa.Column("check_mode", sa.String(), server_default="manual", nullable=False))
    op.add_column("session_groups", sa.Column("check_mode", sa.String(), server_default="manual", nullable=False))
