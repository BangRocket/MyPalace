"""shadow-copy data into per-tenant schemas (phase 12.3a).

For every row in ``public.tenants``:
  1. CREATE SCHEMA IF NOT EXISTS "<tenant_id>"
  2. Replicate per-tenant DDL into the schema (CREATE TABLE IF NOT
     EXISTS for every per-tenant model, schema-qualified).
  3. INSERT INTO "<tenant_id>".<table> SELECT ... FROM public.<table>
     WHERE tenant_id = '<tenant_id>' ON CONFLICT DO NOTHING.

After this migration, both copies coexist:
  - Legacy: ``public.<table>`` rows (with tenant_id column).
  - New:    ``<tenant_id>.<table>`` rows (without tenant_id column).

The default ``PALACE_TENANT_SCHEMA_MODE`` stays ``"table"`` — operators
flip to ``"schema"`` only when they're satisfied with the shadow-copy.
**12.3b** in the next minor release flips the default and drops the
legacy ``public.<table>`` rows + ``tenant_id`` columns.

Idempotent: re-running the migration is safe. Re-runs:
  - Skip CREATE SCHEMA via IF NOT EXISTS.
  - Skip CREATE TABLE via IF NOT EXISTS.
  - Skip already-copied rows via ON CONFLICT DO NOTHING (every per-
    tenant table has a single-column PK).

Downgrade: ``DROP SCHEMA "<tenant_id>" CASCADE`` for every tenant.
**Operators MUST flip the flag back to ``"table"`` before downgrading**,
otherwise live writes to per-tenant schemas will be lost.

Revision ID: 2026_05_05_0010_per_tenant_shadow_copy
Revises: 2026_05_05_0009_messages_fts
Create Date: 2026-05-05
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "2026_05_05_0010_per_tenant_shadow_copy"
down_revision: str | None = "2026_05_05_0009_messages_fts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)


def _per_tenant_tables() -> list[str]:
    """Lazy-import to avoid pulling SQLModel metadata at module load.

    Mirrors mypalace.tenancy.PER_TENANT_TABLES verbatim — keeping a
    second copy here so the migration doesn't rot when the live module
    is refactored. Tripwire: if these diverge, the test suite's
    test_no_unclassified_tables will still catch missing classifications,
    and integration tests will surface mismatches.
    """
    from mypalace.tenancy import PER_TENANT_TABLES
    return sorted(PER_TENANT_TABLES)


def _list_tenant_ids(conn) -> list[str]:
    rows = conn.execute(text("SELECT id FROM public.tenants ORDER BY id"))
    return [r[0] for r in rows]


def _replicate_ddl(conn, tenant_id: str) -> None:
    """Lift mypalace.tenancy.replicate_per_tenant_schema with op.execute().

    Uses the same Table.to_metadata() trick so DDL stays in sync with
    the model definitions; never hand-rolls CREATE TABLE statements
    here (they'd drift the moment a column is added upstream).
    """
    from mypalace.tenancy import replicate_per_tenant_schema
    replicate_per_tenant_schema(tenant_id, conn)


def _shadow_copy_tenant(conn, tenant_id: str) -> None:
    """Copy every per-tenant row from public.<table> into <tenant_id>.<table>.

    Uses INSERT ... SELECT with ON CONFLICT DO NOTHING so re-running the
    migration is a no-op for already-copied rows. Excludes the
    ``tenant_id`` column from both sides — it's redundant in the
    schema-qualified target and will be dropped entirely in 12.3b.
    """
    for table_name in _per_tenant_tables():
        # Discover the column list at runtime so the query stays in
        # sync with whatever Alembic head defines.
        cols_rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t "
                "  AND column_name <> 'tenant_id' "
                "ORDER BY ordinal_position",
            ),
            {"t": table_name},
        )
        cols = [r[0] for r in cols_rows]
        if not cols:
            # Table doesn't exist in public — fresh DB, nothing to copy.
            continue
        col_list = ", ".join(f'"{c}"' for c in cols)
        conn.execute(
            text(
                f'INSERT INTO "{tenant_id}".{table_name} ({col_list}) '
                f"SELECT {col_list} FROM public.{table_name} "
                f"WHERE tenant_id = :tid "
                f"ON CONFLICT DO NOTHING",
            ),
            {"tid": tenant_id},
        )


def upgrade() -> None:
    bind = op.get_bind()
    tenant_ids = _list_tenant_ids(bind)
    logger.info(
        "phase 12.3a: shadow-copying %d tenant(s) into per-tenant schemas",
        len(tenant_ids),
    )
    for tenant_id in tenant_ids:
        logger.info("  → tenant=%s: replicate DDL + shadow-copy", tenant_id)
        _replicate_ddl(bind, tenant_id)
        _shadow_copy_tenant(bind, tenant_id)
    logger.info(
        "phase 12.3a complete. Legacy public.* data preserved. "
        "Set PALACE_TENANT_SCHEMA_MODE=schema to start serving from "
        "per-tenant schemas; flip back to 'table' to revert.",
    )


def downgrade() -> None:
    bind = op.get_bind()
    tenant_ids = _list_tenant_ids(bind)
    logger.warning(
        "phase 12.3a downgrade: DROPPING %d per-tenant schemas. "
        "Operators MUST set PALACE_TENANT_SCHEMA_MODE=table BEFORE "
        "running this — live writes to per-tenant schemas will be lost.",
        len(tenant_ids),
    )
    for tenant_id in tenant_ids:
        bind.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))
