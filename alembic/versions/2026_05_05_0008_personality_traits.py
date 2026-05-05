"""personality_traits table — agent self-evolving traits (phase 10 slice 2).

Source: mypalclara/db/models.py:PersonalityTrait. Soft-delete via the
``active`` flag — preserves history without a dedicated table.

Revision ID: 2026_05_05_0008_personality_traits
Revises: 2026_05_05_0007_entity_aliases
Create Date: 2026-05-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_05_05_0008_personality_traits"
down_revision: str | None = "2026_05_05_0007_entity_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personality_traits",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("trait_key", sa.String(length=100), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personality_traits_tenant_agent_active",
        "personality_traits",
        ["tenant_id", "agent_id", "active"],
    )
    op.create_index(
        "ix_personality_traits_tenant_agent_category",
        "personality_traits",
        ["tenant_id", "agent_id", "category"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_personality_traits_tenant_agent_category",
        table_name="personality_traits",
    )
    op.drop_index(
        "ix_personality_traits_tenant_agent_active",
        table_name="personality_traits",
    )
    op.drop_table("personality_traits")
