"""add babylon_cluster to sessions

Revision ID: f1a2b3c4d5e6
Revises: 63a2980410ce
Create Date: 2026-04-28 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '63a2980410ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('babylon_cluster', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='')
        )


def downgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_column('babylon_cluster')
