"""add content_hash to session_groups

Adds a nullable, non-unique content_hash column so POST /api/groups can
recognise a request whose name, sources and babylon_cluster exactly match an
existing group, and return that group instead of creating a duplicate.

Not unique: pre-existing duplicate groups must stay legal, and add_source /
remove_source can coincidentally drive two distinct groups to the same hash
later. The unique guarantee that a caller-supplied key would have given
(this replaces the stable_name column from an earlier, never-released
revision of this change) is intentionally not reinstated -- the matching here
is advisory, and a caller that must force a new group regardless of
duplicates sets force_create=true instead.

Existing rows are backfilled in this migration using the same normalisation
as session_service.compute_content_hash (sorted, blank-stripped source lists;
stripped name/babylon_cluster), so pre-existing groups participate in
matching immediately rather than only after their next edit.

Revision ID: a7b8c9d0e1f2
Revises: e5f6a7b8c9d0
Create Date: 2026-11-12 00:00:00.000000

"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _compute_content_hash(
    *,
    name: str,
    guids: list[str],
    workshop_guids: list[str],
    resource_pools: list[str],
    babylon_cluster: str,
) -> str:
    """Mirrors soundcheck.services.session_service.compute_content_hash.

    Duplicated rather than imported: migrations must not depend on
    application code that can change shape after this revision is written,
    or a later edit to compute_content_hash would silently change what old
    migrations backfill.
    """
    payload = {
        "name": (name or "").strip(),
        "guids": sorted({g.strip() for g in (guids or []) if g.strip()}),
        "workshop_guids": sorted({g.strip() for g in (workshop_guids or []) if g.strip()}),
        "resource_pools": sorted({p.strip() for p in (resource_pools or []) if p.strip()}),
        "babylon_cluster": (babylon_cluster or "").strip(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def upgrade() -> None:
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.add_column(sa.Column("content_hash", sa.String(), nullable=True))
        batch_op.create_index("ix_session_groups_content_hash", ["content_hash"], unique=False)

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, name, source_guids, source_workshop_guids, source_resource_pools, babylon_cluster "
            "FROM session_groups"
        )
    ).fetchall()

    for row in rows:
        content_hash = _compute_content_hash(
            name=row.name,
            guids=row.source_guids,
            workshop_guids=row.source_workshop_guids,
            resource_pools=row.source_resource_pools,
            babylon_cluster=row.babylon_cluster,
        )
        conn.execute(
            sa.text("UPDATE session_groups SET content_hash = :content_hash WHERE id = :id"),
            {"content_hash": content_hash, "id": row.id},
        )


def downgrade() -> None:
    with op.batch_alter_table("session_groups", schema=None) as batch_op:
        batch_op.drop_index("ix_session_groups_content_hash")
        batch_op.drop_column("content_hash")
