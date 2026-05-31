"""topic_mentions table — extracted topic mentions for recurrence tracking.

Source: mypalclara/core/memory/context/topics.py.

Revision ID: 2026_05_31_0012_topic_mentions
Revises: 2026_05_31_0011_emotional_contexts
Create Date: 2026-05-31
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_05_31_0012_topic_mentions"
down_revision: str | None = "2026_05_31_0011_emotional_contexts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topic_mentions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("topic_type", sa.String(length=20), nullable=False),
        sa.Column("context_snippet", sa.String(length=200), nullable=False),
        sa.Column("emotional_weight", sa.String(length=20), nullable=False),
        sa.Column("sentiment", sa.Float(), nullable=False),
        sa.Column("channel_id", sa.String(length=200), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=False),
        sa.Column("is_dm", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_topic_mentions_tenant_user_topic_created",
        "topic_mentions",
        ["tenant_id", "user_id", "topic", "created_at"],
    )
    op.create_index("ix_topic_mentions_user_id", "topic_mentions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_topic_mentions_user_id", table_name="topic_mentions")
    op.drop_index(
        "ix_topic_mentions_tenant_user_topic_created", table_name="topic_mentions",
    )
    op.drop_table("topic_mentions")
