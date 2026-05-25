"""add provision_status to targets

Revision ID: a1b2c3d4e5f6
Revises: 7ba7129e156f
Create Date: 2026-05-04 09:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7ba7129e156f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('session_targets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('provision_status', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('session_targets', schema=None) as batch_op:
        batch_op.drop_column('provision_status')
