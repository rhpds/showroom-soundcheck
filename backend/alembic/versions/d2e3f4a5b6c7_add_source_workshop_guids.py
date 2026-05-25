"""add source_workshop_guids to sessions

Revision ID: d2e3f4a5b6c7
Revises: c0724c485086
Create Date: 2026-05-03 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c0724c485086'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('source_workshop_guids', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='[]')
        )


def downgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_column('source_workshop_guids')
