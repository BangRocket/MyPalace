"""Alembic env.py — async-aware, reads URL from mypalace.config.settings.

Why async-aware: every other DB call in Palace uses asyncpg + an async
engine. We want to keep that consistent so we don't accidentally introduce
a sync driver dep just for migrations. Alembic itself is sync; we bridge
via `connection.run_sync(do_run_migrations)`.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel  # noqa: E402

# Load all SQLModel tables so autogenerate sees them.
import mypalace.models  # noqa: E402, F401
from alembic import context

# Project on sys.path (alembic.ini sets prepend_sys_path = .)
from mypalace.config import settings  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the URL with the runtime setting so callers don't have to set
# sqlalchemy.url in alembic.ini.
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    from sqlalchemy import text

    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        # Alembic hardcodes alembic_version.version_num as VARCHAR(32), but
        # this project's revision ids exceed 32 chars. Pre-create the table
        # (empty) with a wide column so Alembic reuses it instead of
        # creating the narrow one, and widen an existing narrow column.
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            " version_num VARCHAR(255) NOT NULL,"
            " CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
            ")",
        ))
        connection.execute(text(
            "ALTER TABLE alembic_version "
            "ALTER COLUMN version_num TYPE VARCHAR(255)",
        ))
        context.run_migrations()


async def run_migrations_online() -> None:
    """Live-connection migration path. Uses async engine and bridges to
    Alembic's sync API via run_sync."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
