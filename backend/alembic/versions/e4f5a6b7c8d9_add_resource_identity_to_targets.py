"""add resource_name and resource_namespace to session_targets

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-11 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | Sequence[str] | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("session_targets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("resource_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("resource_namespace", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("session_targets", schema=None) as batch_op:
        batch_op.drop_column("resource_namespace")
        batch_op.drop_column("resource_name")
