"""add stable_name idempotency key to session_groups

Adds a nullable, unique `stable_name` column so external API consumers can
re-POST /api/groups and get the same group back instead of creating a
duplicate.

Nullable rather than NOT NULL DEFAULT '': a UNIQUE constraint permits any
number of NULLs but only a single empty string, so a default of '' would
make the second group that omits stable_name fail to insert.

Revision ID: a7b8c9d0e1f2
Revises: e5f6a7b8c9d0
Create Date: 2026-11-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stable_name", sa.String(), nullable=True))
        batch_op.create_unique_constraint("uq_session_groups_stable_name", ["stable_name"])
        batch_op.create_index("ix_session_groups_stable_name", ["stable_name"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.drop_index("ix_session_groups_stable_name")
        batch_op.drop_constraint("uq_session_groups_stable_name", type_="unique")
        batch_op.drop_column("stable_name")
