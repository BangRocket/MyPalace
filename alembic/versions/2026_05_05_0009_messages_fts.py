"""messages full-text search index (phase 10 slice 5).

Adds a Postgres GIN index on ``to_tsvector('english', content)`` so VCH
queries (verbatim chat history search) can match against raw message
text efficiently. Uses the expression-index approach instead of a
materialized tsvector column — simpler, no model changes, and the
tsvector is recomputed only at index time.

Revision ID: 2026_05_05_0009_messages_fts
Revises: 2026_05_05_0008_personality_traits
Create Date: 2026-05-05
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_05_05_0009_messages_fts"
down_revision: str | None = "2026_05_05_0008_personality_traits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # GIN index on the english-language tsvector of message content.
    # The expression must match the WHERE clause exactly for the planner
    # to use the index — VCH queries use to_tsvector('english', content).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_content_tsv "
        "ON messages USING gin (to_tsvector('english', content))",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_content_tsv")
