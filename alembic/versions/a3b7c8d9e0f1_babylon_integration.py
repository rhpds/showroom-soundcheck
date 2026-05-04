"""babylon integration

Revision ID: a3b7c8d9e0f1
Revises: 650f970b9d23
Create Date: 2026-03-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = "a3b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "650f970b9d23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "babylon_resources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "resource_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("namespace", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("cluster", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "health_check_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("discovered_urls", sa.Integer(), nullable=False),
        sa.Column(
            "error_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column(
        "showrooms",
        sa.Column(
            "health_check_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
    )
    op.add_column(
        "showrooms",
        sa.Column("babylon_resource_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "showrooms",
        sa.Column(
            "babylon_managed", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("showrooms", "babylon_managed")
    op.drop_column("showrooms", "babylon_resource_id")
    op.drop_column("showrooms", "health_check_url")
    op.drop_table("babylon_resources")
