"""Per-request tenant context (phase 12 slice 1).

A single ``ContextVar`` carries the resolved tenant id for the current
request / worker job. Two consumers read it:

- ``mypalace.database`` — installs an ``after_begin`` SQLAlchemy event
  that runs ``SET LOCAL search_path`` when ``settings.tenant_schema_mode``
  is ``"schema"``.
- Any future code that wants to know "which tenant am I serving right
  now" without threading it through every signature.

Default mode (``"table"``) is the existing table-level isolation: the
contextvar is still populated for diagnostics but no SQL behavior
changes. Operators flip the flag in 12.3 once shadow-copied data and
schemas are in place (see docs/per-tenant-schemas-design.md).
"""

from __future__ import annotations

import contextvars
import logging
import re
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import MetaData, text
from sqlalchemy.schema import CreateIndex, CreateTable, DropTable

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

# Per the design doc §2.1: which tables live in per-tenant schemas vs the
# shared `public` catalog. Anything not listed here defaults to public.
PER_TENANT_TABLES: frozenset[str] = frozenset({
    "memories",
    "messages",
    "sessions",
    "narrative_arcs",
    "memory_dynamics",
    "intentions",
    "memory_access_logs",
    "memory_versions",
    "personality_traits",
    "entity_aliases",
    "memory_supersessions",
})

PUBLIC_TABLES: frozenset[str] = frozenset({
    "tenants",
    "api_keys",
    "audit_logs",
    "alembic_version",
    "reflection_jobs",
})

# Default None so callers can distinguish "not set yet" from "explicit
# default tenant" — the latter is a deliberate choice the request made;
# the former means we shouldn't be running a query yet.
_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mypalace_current_tenant", default=None,
)

# Schema names go straight into SQL as identifiers, so we *must* validate
# before composing the SET LOCAL statement. This regex matches the same
# tenant_id rules already enforced in mypalace.auth.tenant.is_valid_tenant_id
# (lowercase letters, digits, underscore, hyphen; 1-32 chars). Kept local
# to avoid an import cycle.
_SCHEMA_NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


def set_current_tenant(tenant_id: str | None) -> contextvars.Token:
    """Install ``tenant_id`` as the current tenant for this context.

    Returns the Token so callers can ``reset(token)`` to restore the
    previous value (rarely needed — request lifetimes are short and
    contextvar values don't leak across asyncio tasks).
    """
    return _current_tenant.set(tenant_id)


def current_tenant() -> str | None:
    """Return the tenant id active for the current context, or None."""
    return _current_tenant.get()


def is_valid_schema_name(tenant_id: str) -> bool:
    """Cheap defence against SQL injection via a malformed tenant_id.

    Tenant ids that pass mypalace.auth.tenant.is_valid_tenant_id will
    also pass this — same character class, same length cap.
    """
    return bool(_SCHEMA_NAME_RE.match(tenant_id))


def _per_tenant_table_objects():
    """Yield the SQLAlchemy Table objects classified as per-tenant.

    Lazy imports both SQLModel and the models module — the latter is the
    side-effect that registers every Table on ``SQLModel.metadata``.
    Skip the model import and metadata.tables comes back empty.
    """
    from sqlmodel import SQLModel

    import mypalace.models  # noqa: F401  — populates SQLModel.metadata
    for table in SQLModel.metadata.tables.values():
        if table.name in PER_TENANT_TABLES:
            yield table


def replicate_per_tenant_schema(tenant_id: str, sync_conn: Connection) -> None:
    """Create schema ``tenant_id`` and CREATE TABLE every per-tenant model into it.

    Idempotent: uses CREATE SCHEMA IF NOT EXISTS + CREATE TABLE
    IF NOT EXISTS so re-running is safe (mirrors mypalace.database.init_db
    semantics on fresh DBs).

    Sync-mode helper — call inside ``await conn.run_sync(...)`` from an
    async context.
    """
    if not is_valid_schema_name(tenant_id):
        raise ValueError(f"invalid tenant_id for schema name: {tenant_id!r}")

    sync_conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{tenant_id}"'))

    target_md = MetaData(schema=tenant_id)
    for table in _per_tenant_table_objects():
        new_table = table.to_metadata(target_md, schema=tenant_id)
        # IF NOT EXISTS is needed because re-creating the same tenant
        # from a snapshot or a retry must not error.
        sync_conn.execute(CreateTable(new_table, if_not_exists=True))
        for ix in new_table.indexes:
            sync_conn.execute(CreateIndex(ix, if_not_exists=True))
    logger.info(
        "tenancy: replicated per-tenant DDL into schema=%s tables=%d",
        tenant_id, len(PER_TENANT_TABLES),
    )


def drop_tenant_schema(tenant_id: str, sync_conn: Connection) -> None:
    """DROP SCHEMA tenant_id CASCADE (sync helper).

    Validates the name first. Caller is responsible for any application-
    level "are you sure" gating — at this layer we just execute.
    """
    if not is_valid_schema_name(tenant_id):
        raise ValueError(f"invalid tenant_id for schema name: {tenant_id!r}")
    sync_conn.execute(text(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE'))
    logger.info("tenancy: dropped schema=%s", tenant_id)


# Keep DropTable re-exported for tests that want to confirm we don't
# accidentally use it on per-tenant tables in `public`.
__all__ = (
    "PER_TENANT_TABLES", "PUBLIC_TABLES",
    "current_tenant", "set_current_tenant", "tenant_scope",
    "is_valid_schema_name",
    "replicate_per_tenant_schema", "drop_tenant_schema",
    "DropTable",  # re-export; used by future migration tools
)


@contextmanager
def tenant_scope(tenant_id: str | None):
    """Context manager: set the current tenant for the duration of the block.

    Useful in worker handlers and tests where there's no AuthMiddleware
    to populate the contextvar automatically.
    """
    token = set_current_tenant(tenant_id)
    try:
        yield
    finally:
        _current_tenant.reset(token)
