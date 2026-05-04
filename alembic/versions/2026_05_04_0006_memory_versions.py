"""memory_versions table — per-update content snapshots

Append-only change history for memories. Recorded on create, update,
and supersede so the trail is complete from row 1.

Revision ID: 2026_05_04_0006_memory_versions
Revises: 2026_05_04_0005_audit_logs
Create Date: 2026-05-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2026_05_04_0006_memory_versions"
down_revision: str | None = "2026_05_04_0005_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("change_kind", sa.String(length=20), nullable=False),
        sa.Column("actor_key_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_versions_memory_id", "memory_versions", ["memory_id"])
    op.create_index("ix_memory_versions_tenant_id", "memory_versions", ["tenant_id"])
    op.create_index("ix_memory_versions_user_id", "memory_versions", ["user_id"])
    op.create_index(
        "ix_memory_versions_memory_created",
        "memory_versions",
        ["memory_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_versions_memory_created", table_name="memory_versions",
    )
    op.drop_index("ix_memory_versions_user_id", table_name="memory_versions")
    op.drop_index("ix_memory_versions_tenant_id", table_name="memory_versions")
    op.drop_index("ix_memory_versions_memory_id", table_name="memory_versions")
    op.drop_table("memory_versions")
