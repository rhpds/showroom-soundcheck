"""add resource pool support

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-12 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source_resource_pools", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="[]")
        )
    with op.batch_alter_table("session_targets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("resource_pool_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("session_targets", schema=None) as batch_op:
        batch_op.drop_column("resource_pool_name")
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("source_resource_pools")
