"""Unit tests for the init_db Alembic-stamp helper.

These mock the SQLAlchemy connection to verify the SQL we issue, without
spinning up a real DB. Live migration runs are exercised in
tests/integration/test_alembic_live.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.database import LATEST_ALEMBIC_REVISION, _ensure_alembic_stamp


@pytest.mark.asyncio
async def test_stamp_inserts_when_empty():
    conn = MagicMock()
    no_row = MagicMock()
    no_row.scalar_one_or_none.return_value = None

    # CREATE TABLE, ALTER COLUMN (widen), SELECT, then INSERT.
    conn.execute = AsyncMock(side_effect=[
        MagicMock(),       # CREATE TABLE IF NOT EXISTS
        MagicMock(),       # ALTER COLUMN version_num TYPE VARCHAR(255)
        no_row,            # SELECT — empty
        MagicMock(),       # INSERT
    ])
    await _ensure_alembic_stamp(conn)

    assert conn.execute.await_count == 4
    insert_call = conn.execute.await_args_list[3]
    sql_text = str(insert_call.args[0])
    params = insert_call.args[1]
    assert "INSERT INTO alembic_version" in sql_text
    assert params == {"rev": LATEST_ALEMBIC_REVISION}


@pytest.mark.asyncio
async def test_stamp_skips_when_revision_present():
    conn = MagicMock()
    has_row = MagicMock()
    has_row.scalar_one_or_none.return_value = LATEST_ALEMBIC_REVISION

    conn.execute = AsyncMock(side_effect=[
        MagicMock(),  # CREATE TABLE IF NOT EXISTS
        MagicMock(),  # ALTER COLUMN version_num TYPE VARCHAR(255)
        has_row,      # SELECT — current
    ])
    await _ensure_alembic_stamp(conn)

    # CREATE + ALTER + SELECT — no INSERT.
    assert conn.execute.await_count == 3


@pytest.mark.asyncio
async def test_stamp_warns_on_outdated_revision(caplog):
    import logging

    conn = MagicMock()
    has_row = MagicMock()
    has_row.scalar_one_or_none.return_value = "2026_05_04_0001_baseline"  # older

    conn.execute = AsyncMock(side_effect=[MagicMock(), MagicMock(), has_row])

    with caplog.at_level(logging.INFO):
        await _ensure_alembic_stamp(conn)

    assert any("Run 'alembic upgrade head'" in r.message for r in caplog.records)
    assert conn.execute.await_count == 3  # CREATE + ALTER + SELECT, no auto-upgrade


@pytest.mark.asyncio
async def test_init_db_calls_stamp():
    """init_db should both create tables and stamp."""
    with patch("mypalace.database._ensure_alembic_stamp",
               new=AsyncMock()) as mock_stamp, \
         patch("mypalace.database.engine") as mock_engine:
        # engine.begin() returns an async context manager yielding a connection
        conn = MagicMock()
        conn.run_sync = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.begin = MagicMock(return_value=ctx)

        from mypalace.database import init_db
        await init_db()

        conn.run_sync.assert_awaited_once()  # SQLModel.metadata.create_all
        mock_stamp.assert_awaited_once_with(conn)
