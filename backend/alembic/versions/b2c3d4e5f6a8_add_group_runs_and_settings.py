"""add group runs and group settings

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-05-12 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "b2c3d4e5f6a8"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("check_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="readyz")
        )
        batch_op.add_column(
            sa.Column("check_mode", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="manual")
        )
        batch_op.add_column(
            sa.Column("babylon_cluster", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("source_guids", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("source_workshop_guids", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("source_resource_pools", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pending")
        )

    op.create_table(
        "group_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("group_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_group_runs_run_id"), "group_runs", ["run_id"], unique=False)
    op.create_index(op.f("ix_group_runs_group_id"), "group_runs", ["group_id"], unique=False)

    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("group_run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index("ix_sessions_group_run_id", ["group_run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_sessions_group_run_id")
        batch_op.drop_column("group_run_id")
    op.drop_index(op.f("ix_group_runs_group_id"), table_name="group_runs")
    op.drop_index(op.f("ix_group_runs_run_id"), table_name="group_runs")
    op.drop_table("group_runs")
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.drop_column("status")
        batch_op.drop_column("source_resource_pools")
        batch_op.drop_column("source_workshop_guids")
        batch_op.drop_column("source_guids")
        batch_op.drop_column("babylon_cluster")
        batch_op.drop_column("check_mode")
        batch_op.drop_column("check_type")
