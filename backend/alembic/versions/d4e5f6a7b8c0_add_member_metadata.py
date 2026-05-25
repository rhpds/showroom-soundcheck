"""add member_metadata to session_groups

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
Create Date: 2026-05-13 08:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c0"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.add_column(sa.Column("member_metadata", sa.String(), nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.drop_column("member_metadata")
