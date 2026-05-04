"""worker lease columns on reflection_jobs

Adds the columns the Postgres-backed job queue needs:
  - leased_until: when the worker's lease expires (NULL = unleased)
  - attempts:    increments on each lease pickup; >=3 marks failed
  - payload_json: serialized inputs the worker re-hydrates the coroutine with

Index on (status, leased_until) so the worker's claim query is fast:
  SELECT ... WHERE status='pending' AND (leased_until IS NULL
       OR leased_until < now()) ORDER BY created_at FOR UPDATE SKIP LOCKED

Revision ID: 2026_05_04_0003_worker_lease
Revises: 2026_05_04_0002_composite_indexes
Create Date: 2026-05-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2026_05_04_0003_worker_lease"
down_revision: str | None = "2026_05_04_0002_composite_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reflection_jobs",
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reflection_jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "reflection_jobs",
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_reflection_jobs_claim",
        "reflection_jobs",
        ["status", "leased_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_reflection_jobs_claim", table_name="reflection_jobs")
    op.drop_column("reflection_jobs", "payload_json")
    op.drop_column("reflection_jobs", "attempts")
    op.drop_column("reflection_jobs", "leased_until")
