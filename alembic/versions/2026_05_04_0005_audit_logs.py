"""audit_logs table

Append-only audit trail of admin / maintenance API calls. Recorded
fire-and-forget by AuditMiddleware. Body content is hashed (SHA256)
rather than stored verbatim — audit answers "did this happen" without
leaking secrets.

Revision ID: 2026_05_04_0005_audit_logs
Revises: 2026_05_04_0004_memory_expires_at
Create Date: 2026-05-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_05_04_0005_audit_logs"
down_revision: str | None = "2026_05_04_0004_memory_expires_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(length=32), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("status_class", sa.String(length=4), nullable=False),
        sa.Column("request_body_hash", sa.String(length=64), nullable=True),
        sa.Column("response_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_key_id", "audit_logs", ["key_id"])
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index(
        "ix_audit_logs_key_created", "audit_logs", ["key_id", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_path_created", "audit_logs", ["path", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_path_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_key_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_key_id", table_name="audit_logs")
    op.drop_table("audit_logs")
