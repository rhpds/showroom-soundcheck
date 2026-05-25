"""add pinned columns

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
Create Date: 2026-05-12 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b9"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("pinned")
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.drop_column("pinned")
