"""Tests for memory change history (phase 7 slice 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRecordVersion:
    @pytest.mark.asyncio
    async def test_record_version_inserts_row(self, monkeypatch):
        from palace import memory_service as ms
        from palace.memory_service import _record_version

        captured: dict = {}
        db_mock = MagicMock()
        db_mock.add = lambda obj: captured.setdefault("row", obj)
        db_mock.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))

        await _record_version(
            memory_id="m1",
            tenant_id="acme",
            user_id="u1",
            version_number=3,
            content="hello world",
            metadata={"k": "v"},
            change_kind="updated",
            actor_key_id="key-42",
        )
        row = captured["row"]
        assert row.memory_id == "m1"
        assert row.tenant_id == "acme"
        assert row.user_id == "u1"
        assert row.version_number == 3
        assert row.content == "hello world"
        assert row.metadata_json == {"k": "v"}
        assert row.change_kind == "updated"
        assert row.actor_key_id == "key-42"

    @pytest.mark.asyncio
    async def test_record_version_failure_swallowed(self, monkeypatch):
        from palace import memory_service as ms
        from palace.memory_service import _record_version

        monkeypatch.setattr(
            ms, "async_session",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        # Should NOT raise.
        await _record_version(
            memory_id="m1", tenant_id="acme", user_id="u1",
            version_number=1, content="x", metadata=None,
            change_kind="created",
        )


class TestNextVersionNumber:
    @pytest.mark.asyncio
    async def test_first_version_returns_one(self, monkeypatch):
        from palace import memory_service as ms
        from palace.memory_service import _next_version_number

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=result_mock)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))

        n = await _next_version_number("m1")
        assert n == 1

    @pytest.mark.asyncio
    async def test_increments_existing_max(self, monkeypatch):
        from palace import memory_service as ms
        from palace.memory_service import _next_version_number

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = 7
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=result_mock)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))

        n = await _next_version_number("m1")
        assert n == 8

    @pytest.mark.asyncio
    async def test_failure_returns_safe_fallback(self, monkeypatch):
        from palace import memory_service as ms
        from palace.memory_service import _next_version_number

        monkeypatch.setattr(
            ms, "async_session",
            MagicMock(side_effect=RuntimeError("db down")),
        )
        n = await _next_version_number("m1")
        assert n == 1


class TestHistoryRoute:
    def test_returns_chronological_versions(self, client, monkeypatch):
        from palace.models import MemoryVersion

        rows = [
            MemoryVersion(
                memory_id="m1",
                tenant_id="test",
                user_id="u1",
                version_number=1,
                content="first",
                change_kind="created",
                created_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
            ),
            MemoryVersion(
                memory_id="m1",
                tenant_id="test",
                user_id="u1",
                version_number=2,
                content="second",
                change_kind="updated",
                created_at=datetime(2026, 5, 4, 12, 5, tzinfo=UTC),
            ),
        ]
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = rows
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=scalars_result)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        # The history route imports async_session lazily, patch at source.
        with patch(
            "palace.database.async_session",
            MagicMock(return_value=cm),
        ):
            r = client.get("/v1/memories/m1/history")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2
        assert data[0]["version_number"] == 1
        assert data[0]["content"] == "first"
        assert data[1]["change_kind"] == "updated"

    def test_empty_history_returns_empty_list(self, client):
        from unittest.mock import AsyncMock as _AsyncMock

        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        db_mock = MagicMock()
        db_mock.execute = _AsyncMock(return_value=empty)
        cm = MagicMock()
        cm.__aenter__ = _AsyncMock(return_value=db_mock)
        cm.__aexit__ = _AsyncMock(return_value=None)
        with patch(
            "palace.database.async_session",
            MagicMock(return_value=cm),
        ):
            r = client.get("/v1/memories/missing/history")
        assert r.status_code == 200
        assert r.json()["data"] == []
