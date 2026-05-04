"""memory.expires_at + index for cleanup queries

Adds optional TTL to memories. Null = never expires (matches the
default for every existing row). The cleanup worker handler scans
``WHERE expires_at IS NOT NULL AND expires_at <= now()`` so the
partial index keeps that scan cheap.

Revision ID: 2026_05_04_0004_memory_expires_at
Revises: 2026_05_04_0003_worker_lease
Create Date: 2026-05-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_05_04_0004_memory_expires_at"
down_revision: str | None = "2026_05_04_0003_worker_lease"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index — only rows with a TTL get indexed; existing
    # never-expires rows don't bloat the index.
    op.create_index(
        "ix_memories_expires_not_null",
        "memories",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_memories_expires_not_null", table_name="memories")
    op.drop_column("memories", "expires_at")
