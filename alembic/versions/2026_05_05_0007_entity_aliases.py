"""entity_aliases table — platform ID → human name mapping (phase 10 slice 1).

Backs the entity resolver service. Source: mypalclara/core/memory/entity_resolver.py.

Revision ID: 2026_05_05_0007_entity_aliases
Revises: 2026_05_04_0006_memory_versions
Create Date: 2026-05-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_05_05_0007_entity_aliases"
down_revision: str | None = "2026_05_04_0006_memory_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=False),
        sa.Column("identifier", sa.String(length=200), nullable=False),
        sa.Column("canonical_name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_entity_aliases_tenant_identifier",
        "entity_aliases",
        ["tenant_id", "identifier"],
        unique=True,
    )
    op.create_index(
        "ix_entity_aliases_tenant_canonical",
        "entity_aliases",
        ["tenant_id", "canonical_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entity_aliases_tenant_canonical", table_name="entity_aliases",
    )
    op.drop_index(
        "uq_entity_aliases_tenant_identifier", table_name="entity_aliases",
    )
    op.drop_table("entity_aliases")
