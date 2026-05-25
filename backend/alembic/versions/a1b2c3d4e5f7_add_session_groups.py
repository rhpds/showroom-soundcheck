"""add session groups

Revision ID: a1b2c3d4e5f7
Revises: f5a6b7c8d9e0
Create Date: 2026-05-12 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_session_groups_group_id"), "session_groups", ["group_id"], unique=False)

    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("group_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index("ix_sessions_group_id", ["group_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_sessions_group_id")
        batch_op.drop_column("group_id")
    op.drop_index(op.f("ix_session_groups_group_id"), table_name="session_groups")
    op.drop_table("session_groups")
