"""Live test: run alembic upgrade head against a fresh Postgres and
assert the schema matches what services expect."""

from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.integration

# Repo root = three levels up from this file (tests/integration/<file>).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Invoke alembic via the current interpreter so it resolves to the venv's
# install regardless of PATH (the bare `alembic` binary may not be on PATH).
_ALEMBIC = [sys.executable, "-m", "alembic"]


async def test_alembic_upgrade_head_creates_full_schema(fresh_db_url):
    """Run alembic upgrade head from scratch; assert all expected tables
    + alembic_version exist."""
    # Run alembic in a subprocess so it picks up the env var cleanly.
    import subprocess
    env = {**os.environ, "PALACE_DATABASE_URL": fresh_db_url}

    result = subprocess.run(
        [*_ALEMBIC, "upgrade", "head"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic upgrade failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    # Verify the schema by querying information_schema.
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(fresh_db_url)
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name",
        ))
        tables = {row[0] for row in result.all()}
    await engine.dispose()

    expected = {
        "alembic_version",
        "api_keys",
        "intentions",
        "memories",
        "memory_access_logs",
        "memory_dynamics",
        "memory_supersessions",
        "messages",
        "narrative_arcs",
        "reflection_jobs",
        "sessions",
        "tenants",
    }
    missing = expected - tables
    assert not missing, f"missing tables after upgrade head: {missing}"


async def test_alembic_downgrade_then_upgrade_is_clean(fresh_db_url):
    """Round-trip: upgrade head, downgrade base, upgrade head. Confirms
    downgrade() implementations are correct."""
    import subprocess
    env = {**os.environ, "PALACE_DATABASE_URL": fresh_db_url}

    for cmd in (["upgrade", "head"], ["downgrade", "base"], ["upgrade", "head"]):
        r = subprocess.run(
            [*_ALEMBIC, *cmd],
            cwd=_REPO_ROOT,
            env=env, capture_output=True, text=True, check=False,
        )
        assert r.returncode == 0, f"alembic {cmd} failed: {r.stderr}"


async def test_init_db_stamps_revision(palace_app):
    """After lifespan startup, alembic_version should hold the latest revision."""
    from sqlalchemy import text

    from mypalace.database import LATEST_ALEMBIC_REVISION, async_session

    async with async_session() as db:
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        row = result.scalar_one_or_none()
    assert row == LATEST_ALEMBIC_REVISION
