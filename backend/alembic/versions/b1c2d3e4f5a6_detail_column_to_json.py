"""Convert check_results.detail from VARCHAR to native JSON.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-05-26 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            'ALTER TABLE check_results ALTER COLUMN "detail" TYPE JSON'
            ' USING CASE WHEN "detail" IS NOT NULL THEN "detail"::json ELSE NULL END'
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            'ALTER TABLE check_results ALTER COLUMN "detail" TYPE VARCHAR'
            ' USING "detail"::text'
        )
    )
