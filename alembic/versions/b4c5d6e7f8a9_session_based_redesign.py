"""session-based redesign

Drop old polling tables (git_repos, history_snapshots, commit_records,
showrooms, health_checks, babylon_resources) and create new session-based
tables (sessions, session_targets, check_results).

Revision ID: b4c5d6e7f8a9
Revises: a3b7c8d9e0f1
Create Date: 2026-04-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old tables (order matters due to FK-like relationships)
    op.drop_table("health_checks")
    op.drop_table("commit_records")
    op.drop_table("history_snapshots")
    op.drop_table("showrooms")
    op.drop_table("git_repos")
    op.drop_table("babylon_resources")

    # Create new session-based tables
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("check_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("check_mode", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="manual"),
        sa.Column("source_urls", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source_guids", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_session_id", "sessions", ["session_id"], unique=True)

    op.create_table(
        "session_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("guid", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("tier_used", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("check_started_at", sa.DateTime(), nullable=True),
        sa.Column("check_completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_targets_session_id", "session_targets", ["session_id"])

    op.create_table(
        "check_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("check_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("is_healthy", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=False),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("detail", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_check_results_target_id", "check_results", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_check_results_target_id", table_name="check_results")
    op.drop_table("check_results")
    op.drop_index("ix_session_targets_session_id", table_name="session_targets")
    op.drop_table("session_targets")
    op.drop_index("ix_sessions_session_id", table_name="sessions")
    op.drop_table("sessions")
