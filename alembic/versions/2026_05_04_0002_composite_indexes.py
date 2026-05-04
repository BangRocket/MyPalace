"""composite indexes for hot read paths

Adds (tenant_id, user_id) composite indexes on memories, sessions,
intentions, and memory_dynamics. The single-column indexes from baseline
stay (still useful for tenant-only listings); these speed up the common
"give me X for this user in this tenant" pattern that every search /
list / context call hits.

Also adds (tenant_id, last_accessed_at DESC) on memory_dynamics for
FSRS-based ranking queries that are tenant-scoped.

Revision ID: 2026_05_04_0002_composite_indexes
Revises: 2026_05_04_0001_baseline
Create Date: 2026-05-04
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_05_04_0002_composite_indexes"
down_revision: str | None = "2026_05_04_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_memories_tenant_user", "memories", ["tenant_id", "user_id"],
    )
    op.create_index(
        "ix_sessions_tenant_user", "sessions", ["tenant_id", "user_id"],
    )
    op.create_index(
        "ix_intentions_tenant_user", "intentions", ["tenant_id", "user_id"],
    )
    op.create_index(
        "ix_memory_dynamics_tenant_user",
        "memory_dynamics",
        ["tenant_id", "user_id"],
    )
    # FSRS ranking helper — recent-access-first within a tenant.
    op.create_index(
        "ix_memory_dynamics_tenant_accessed_desc",
        "memory_dynamics",
        ["tenant_id", "last_accessed_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_memory_dynamics_tenant_accessed_desc", table_name="memory_dynamics")
    op.drop_index("ix_memory_dynamics_tenant_user", table_name="memory_dynamics")
    op.drop_index("ix_intentions_tenant_user", table_name="intentions")
    op.drop_index("ix_sessions_tenant_user", table_name="sessions")
    op.drop_index("ix_memories_tenant_user", table_name="memories")
