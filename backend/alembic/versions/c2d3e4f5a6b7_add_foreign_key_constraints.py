"""Add foreign key constraints with ON DELETE CASCADE.

Adds UNIQUE constraints on session_groups.group_id, group_runs.run_id,
and sessions.session_id, then creates FK constraints so that deleting
a parent row automatically cascades to child rows. Cleans up any
orphaned rows before adding constraints to avoid FK violations.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-26 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Clean up orphaned rows so FK constraints can be created ---
    conn = op.get_bind()

    conn.execute(sa.text("""
        DELETE FROM check_results
        WHERE target_id NOT IN (SELECT id FROM session_targets)
    """))
    conn.execute(sa.text("""
        DELETE FROM session_targets
        WHERE session_id NOT IN (SELECT session_id FROM sessions)
    """))
    conn.execute(sa.text("""
        DELETE FROM sessions
        WHERE group_id IS NOT NULL
          AND group_id NOT IN (SELECT group_id FROM session_groups)
    """))
    conn.execute(sa.text("""
        UPDATE sessions SET group_run_id = NULL
        WHERE group_run_id IS NOT NULL
          AND group_run_id NOT IN (SELECT run_id FROM group_runs)
    """))
    conn.execute(sa.text("""
        DELETE FROM group_runs
        WHERE group_id NOT IN (SELECT group_id FROM session_groups)
    """))

    # --- Add UNIQUE constraints (required for FK targets) ---
    op.create_unique_constraint("uq_session_groups_group_id", "session_groups", ["group_id"])
    op.create_unique_constraint("uq_group_runs_run_id", "group_runs", ["run_id"])
    op.create_unique_constraint("uq_sessions_session_id", "sessions", ["session_id"])

    # --- Add FK constraints with ON DELETE CASCADE ---
    op.create_foreign_key(
        "fk_group_runs_group_id",
        "group_runs", "session_groups",
        ["group_id"], ["group_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_sessions_group_id",
        "sessions", "session_groups",
        ["group_id"], ["group_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_sessions_group_run_id",
        "sessions", "group_runs",
        ["group_run_id"], ["run_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_session_targets_session_id",
        "session_targets", "sessions",
        ["session_id"], ["session_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_check_results_target_id",
        "check_results", "session_targets",
        ["target_id"], ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_check_results_target_id", "check_results", type_="foreignkey")
    op.drop_constraint("fk_session_targets_session_id", "session_targets", type_="foreignkey")
    op.drop_constraint("fk_sessions_group_run_id", "sessions", type_="foreignkey")
    op.drop_constraint("fk_sessions_group_id", "sessions", type_="foreignkey")
    op.drop_constraint("fk_group_runs_group_id", "group_runs", type_="foreignkey")

    op.drop_constraint("uq_sessions_session_id", "sessions", type_="unique")
    op.drop_constraint("uq_group_runs_run_id", "group_runs", type_="unique")
    op.drop_constraint("uq_session_groups_group_id", "session_groups", type_="unique")
