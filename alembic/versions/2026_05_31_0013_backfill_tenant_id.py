"""backfill tenant_id in per-tenant schema tables (phase 12.3b).

0010 shadow-copied rows into ``<tenant>.<table>`` but excluded the
``tenant_id`` column, leaving it NULL for historical rows. v0.12.0
(Approach A) keeps the ``tenant_id`` columns + the ~288 ``WHERE
tenant_id = ...`` filters as defense-in-depth, so those NULLs would make
the filters under-count. This migration sets ``tenant_id`` to the owning
schema's tenant for every per-tenant table.

Idempotent: only touches rows where ``tenant_id IS NULL``. Safe to
re-run. Skips tables/columns that don't exist (fresh DB, or a table not
yet replicated into a given schema).

Downgrade: no-op — there's no safe way to re-NULL only the rows this set,
and the column is staying anyway (the column drop is v0.13.0).

Revision ID: 2026_05_31_0013_backfill_tenant_id
Revises: 2026_05_31_0012_topic_mentions
Create Date: 2026-05-31
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "2026_05_31_0013_backfill_tenant_id"
down_revision: str | None = "2026_05_31_0012_topic_mentions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)


def _per_tenant_tables() -> list[str]:
    """Mirror mypalace.tenancy.PER_TENANT_TABLES (lazy import)."""
    from mypalace.tenancy import PER_TENANT_TABLES
    return sorted(PER_TENANT_TABLES)


def _list_tenant_ids(conn) -> list[str]:
    rows = conn.execute(text("SELECT id FROM public.tenants ORDER BY id"))
    return [r[0] for r in rows]


def _has_tenant_id_column(conn, schema: str, table: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t "
            "  AND column_name = 'tenant_id' LIMIT 1",
        ),
        {"s": schema, "t": table},
    ).first()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()
    tenant_ids = _list_tenant_ids(bind)
    logger.info(
        "phase 12.3b: backfilling tenant_id across %d tenant schema(s)",
        len(tenant_ids),
    )
    for tenant_id in tenant_ids:
        for table_name in _per_tenant_tables():
            if not _has_tenant_id_column(bind, tenant_id, table_name):
                continue
            bind.execute(
                text(
                    f'UPDATE "{tenant_id}".{table_name} '
                    f"SET tenant_id = :tid WHERE tenant_id IS NULL",
                ),
                {"tid": tenant_id},
            )
    logger.info("phase 12.3b backfill complete.")


def downgrade() -> None:
    # No-op: the column stays (dropped in v0.13.0) and re-NULLing only the
    # rows this set is not reconstructable.
    pass
