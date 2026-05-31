"""emotional_contexts table — per-conversation emotional summaries.

Source: mypalclara/core/memory/context/emotional.py.

Revision ID: 2026_05_31_0011_emotional_contexts
Revises: 2026_05_05_0010_per_tenant_shadow_copy
Create Date: 2026-05-31
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_05_31_0011_emotional_contexts"
down_revision: str | None = "2026_05_05_0010_per_tenant_shadow_copy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "emotional_contexts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=200), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=False),
        sa.Column("is_dm", sa.Boolean(), nullable=False),
        sa.Column("starting_sentiment", sa.Float(), nullable=False),
        sa.Column("ending_sentiment", sa.Float(), nullable=False),
        sa.Column("emotional_arc", sa.String(length=20), nullable=False),
        sa.Column("energy_level", sa.String(length=50), nullable=False),
        sa.Column("topic_summary", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_emotional_contexts_tenant_user_created",
        "emotional_contexts",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_index(
        "ix_emotional_contexts_user_id", "emotional_contexts", ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_emotional_contexts_user_id", table_name="emotional_contexts")
    op.drop_index(
        "ix_emotional_contexts_tenant_user_created",
        table_name="emotional_contexts",
    )
    op.drop_table("emotional_contexts")
