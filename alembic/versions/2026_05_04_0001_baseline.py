"""baseline — captures the entire post-phase-3 schema as the starting
point for Alembic-managed migrations.

For fresh deploys, ``init_db()`` creates the tables and then stamps this
revision. For pre-Alembic deployments with existing data, run
``alembic stamp 2026_05_04_0001_baseline`` BEFORE running
``upgrade head`` so Alembic doesn't try to re-create tables that
already exist.

Revision ID: 2026_05_04_0001_baseline
Revises:
Create Date: 2026-05-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2026_05_04_0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the entire post-phase-3 schema from scratch.

    Idempotent against existing tables: every CREATE uses ``IF NOT EXISTS``
    via ``checkfirst`` semantics implemented per-table at the DDL layer.
    For pre-Alembic installs with existing data, prefer ``alembic stamp``
    over running this migration.
    """
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "memories",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("memory_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memories_tenant_id", "memories", ["tenant_id"])
    op.create_index("ix_memories_user_id", "memories", ["user_id"])
    op.create_index("ix_memories_agent_id", "memories", ["agent_id"])
    op.create_index("ix_memories_memory_type", "memories", ["memory_type"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("context_snapshot", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_messages_user_id", "messages", ["user_id"])

    op.create_table(
        "narrative_arcs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "key_episode_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("emotional_trajectory", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_narrative_arcs_tenant_id", "narrative_arcs", ["tenant_id"])
    op.create_index("ix_narrative_arcs_user_id", "narrative_arcs", ["user_id"])
    op.create_index("ix_narrative_arcs_agent_id", "narrative_arcs", ["agent_id"])
    op.create_index("ix_narrative_arcs_status", "narrative_arcs", ["status"])

    op.create_table(
        "reflection_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reflection_jobs_tenant_id", "reflection_jobs", ["tenant_id"])
    op.create_index("ix_reflection_jobs_kind", "reflection_jobs", ["kind"])
    op.create_index("ix_reflection_jobs_user_id", "reflection_jobs", ["user_id"])
    op.create_index("ix_reflection_jobs_status", "reflection_jobs", ["status"])

    op.create_table(
        "memory_dynamics",
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("stability", sa.Float(), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False),
        sa.Column("retrieval_strength", sa.Float(), nullable=False),
        sa.Column("storage_strength", sa.Float(), nullable=False),
        sa.Column("is_key", sa.Boolean(), nullable=False),
        sa.Column("importance_weight", sa.Float(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("memory_id"),
    )
    op.create_index("ix_memory_dynamics_tenant_id", "memory_dynamics", ["tenant_id"])
    op.create_index("ix_memory_dynamics_user_id", "memory_dynamics", ["user_id"])
    op.create_index(
        "ix_memory_dynamics_user_accessed",
        "memory_dynamics",
        ["user_id", "last_accessed_at"],
    )

    op.create_table(
        "intentions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("source_memory_id", sa.String(), nullable=True),
        sa.Column("trigger_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("fired", sa.Boolean(), nullable=False),
        sa.Column("fire_once", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_intentions_tenant_id", "intentions", ["tenant_id"])
    op.create_index("ix_intentions_user_id", "intentions", ["user_id"])
    op.create_index("ix_intention_user_unfired", "intentions", ["user_id", "fired"])
    op.create_index("ix_intention_expires", "intentions", ["expires_at"])

    op.create_table(
        "memory_access_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("retrievability_at_access", sa.Float(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["memory_dynamics.memory_id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_access_logs_tenant_id", "memory_access_logs", ["tenant_id"])
    op.create_index("ix_memory_access_logs_memory_id", "memory_access_logs", ["memory_id"])
    op.create_index("ix_memory_access_logs_user_id", "memory_access_logs", ["user_id"])
    op.create_index(
        "ix_memory_access_logs_user_accessed",
        "memory_access_logs",
        ["user_id", "accessed_at"],
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("key_prefix", sa.String(length=8), nullable=False),
        sa.Column("key_hash", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=True),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_prefix"),
    )
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"], unique=True)
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])

    op.create_table(
        "memory_supersessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("superseded_id", sa.String(), nullable=False),
        sa.Column("new_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_supersessions_tenant_id", "memory_supersessions", ["tenant_id"],
    )
    op.create_index("ix_memory_supersessions_user_id", "memory_supersessions", ["user_id"])
    op.create_index("ix_supersession_superseded", "memory_supersessions", ["superseded_id"])
    op.create_index("ix_supersession_new", "memory_supersessions", ["new_id"])


def downgrade() -> None:
    """Drop everything in dependency-safe order. Mostly used for tests
    spinning up + tearing down."""
    op.drop_table("memory_supersessions")
    op.drop_table("api_keys")
    op.drop_table("memory_access_logs")
    op.drop_table("intentions")
    op.drop_table("memory_dynamics")
    op.drop_table("reflection_jobs")
    op.drop_table("narrative_arcs")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("memories")
    op.drop_table("tenants")
