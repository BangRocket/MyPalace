"""Async database engine, session, and Alembic-aware schema bootstrap."""

import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from mypalace.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=settings.db_pool_pre_ping,
)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(SyncSession, "after_begin")
def _set_search_path_after_begin(session, transaction, connection):  # noqa: ARG001
    """Phase 12: SET LOCAL search_path at the start of each transaction
    when tenant_schema_mode == "schema".

    Fires synchronously on the underlying sync session that AsyncSession
    wraps; ``connection`` is the live DBAPI-level connection inside the
    transaction. ``SET LOCAL`` is transaction-scoped — auto-resets at
    commit/rollback so a returned-to-pool connection never carries a
    stale search_path.

    No-op when:
      - the schema-mode flag isn't set
      - no current tenant is in the contextvar (background task without
        a request — they should set tenant_scope() explicitly)
      - the tenant id is malformed (defensive against SQL injection)
    """
    if settings.tenant_schema_mode != "schema":
        return

    from mypalace.tenancy import current_tenant, is_valid_schema_name
    tid = current_tenant()
    if tid is None:
        return
    if not is_valid_schema_name(tid):
        logger.warning(
            "tenancy: refusing to set search_path for invalid tenant_id=%r",
            tid,
        )
        return

    # Schema names are pre-validated above, so direct interpolation is
    # safe. Postgres requires identifier quoting (the regex restricts to
    # safe chars but the quotes also handle the all-numeric edge case).
    connection.execute(text(f'SET LOCAL search_path TO "{tid}", public'))

# Bumped each time we add a new alembic revision. Lifespan stamps this
# revision on a fresh DB so future ``alembic upgrade head`` calls find a
# known starting point.
LATEST_ALEMBIC_REVISION = "2026_05_05_0009_messages_fts"


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create tables on a fresh DB and stamp Alembic to the latest revision.

    Behavior matrix:
      - Empty DB → create all SQLModel tables + create alembic_version
        table + insert latest revision. Future ``alembic upgrade head``
        is a no-op.
      - DB with existing schema and no alembic_version → create the
        alembic_version table + insert latest revision (stamp). Same
        outcome as the Alembic ``stamp`` command, performed in-process so
        operators don't have to remember to run it.
      - DB with existing alembic_version → leave it alone. Operators
        manage migrations via ``alembic upgrade head``.

    Net result: fresh deploys work zero-config; pre-Alembic upgrades get
    auto-stamped on next boot; Alembic-managed deploys don't have their
    version overwritten.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await _ensure_alembic_stamp(conn)


async def _ensure_alembic_stamp(conn) -> None:
    # Use raw SQL — we avoid importing alembic here to keep this hot path
    # cheap and to skip env.py side effects.
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        " version_num VARCHAR(32) NOT NULL,"
        " CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
        ")",
    ))
    result = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    existing = result.scalar_one_or_none()
    if existing is None:
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
            {"rev": LATEST_ALEMBIC_REVISION},
        )
        logger.info("Alembic stamped fresh DB at revision %s", LATEST_ALEMBIC_REVISION)
    elif existing != LATEST_ALEMBIC_REVISION:
        logger.info(
            "Alembic version is %s; expected %s. Run 'alembic upgrade head' "
            "to migrate.", existing, LATEST_ALEMBIC_REVISION,
        )
