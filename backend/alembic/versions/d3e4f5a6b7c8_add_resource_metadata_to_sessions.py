"""add resource metadata columns to sessions

Revision ID: d3e4f5a6b7c8
Revises: c1d2e3f4a5b6
Create Date: 2026-05-10 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("resource_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("resource_namespace", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("resource_kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("resource_display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("resource_metadata", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("resource_metadata")
        batch_op.drop_column("resource_display_name")
        batch_op.drop_column("resource_kind")
        batch_op.drop_column("resource_namespace")
        batch_op.drop_column("resource_name")
