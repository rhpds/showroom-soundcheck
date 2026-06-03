"""Drop check_type columns from sessions, session_groups, and check_results.

The healthz check type is removed; only readyz is supported going forward.
Any sessions with check_type='healthz' are deleted (FK cascades clean up
their targets and results).

Revision ID: e5f6a7b8c9d0
Revises: d5e6f7a8b9c0
Create Date: 2026-06-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM sessions WHERE check_type = 'healthz'"))

    op.drop_column("sessions", "check_type")
    op.drop_column("session_groups", "check_type")
    op.drop_column("check_results", "check_type")


def downgrade() -> None:
    op.add_column("check_results", sa.Column("check_type", sa.String(), server_default="", nullable=False))
    op.add_column("session_groups", sa.Column("check_type", sa.String(), server_default="readyz", nullable=False))
    op.add_column("sessions", sa.Column("check_type", sa.String(), server_default="readyz", nullable=False))
