"""Tests for memory TTL + cleanup (phase 6 slice 3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestNotExpiredClause:
    def test_clause_constructable(self):
        from mypalace.memory_service import _not_expired_clause
        # Just verify it builds without error — the actual SQL is tested
        # against a live DB in tests/integration/test_memory_ttl_live.py.
        clause = _not_expired_clause()
        assert clause is not None


class TestCreateRoutePropagatesTtl:
    def test_create_with_ttl(self, client, mock_memory_service):
        # Build a fake Memory return shape that MemoryOut.from_memory accepts.
        fake = MagicMock()
        fake.id = "m-ttl"
        fake.user_id = "u1"
        fake.agent_id = None
        fake.content = "vanishing"
        fake.memory_type = "session"
        fake.source = None
        fake.importance = 1.0
        fake.created_at = datetime(2026, 5, 4, tzinfo=UTC)
        fake.updated_at = datetime(2026, 5, 4, tzinfo=UTC)
        fake.accessed_at = None
        fake.access_count = 0
        fake.expires_at = datetime(2026, 5, 4, 1, 0, tzinfo=UTC)
        fake.metadata_json = None
        mock_memory_service.create.return_value = fake

        r = client.post("/v1/memories", json={
            "user_id": "u1",
            "content": "vanishing",
            "memory_type": "session",
            "ttl_seconds": 3600,
        })
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["expires_at"] == "2026-05-04T01:00:00+00:00"
        kwargs = mock_memory_service.create.call_args.kwargs
        assert kwargs["ttl_seconds"] == 3600

    def test_create_without_ttl_passes_none(self, client, mock_memory_service):
        fake = MagicMock()
        fake.id = "m-ok"
        fake.user_id = "u1"
        fake.agent_id = None
        fake.content = "permanent"
        fake.memory_type = "semantic"
        fake.source = None
        fake.importance = 1.0
        fake.created_at = datetime(2026, 5, 4, tzinfo=UTC)
        fake.updated_at = datetime(2026, 5, 4, tzinfo=UTC)
        fake.accessed_at = None
        fake.access_count = 0
        fake.expires_at = None
        fake.metadata_json = None
        mock_memory_service.create.return_value = fake

        r = client.post("/v1/memories", json={
            "user_id": "u1", "content": "permanent",
        })
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["expires_at"] is None
        kwargs = mock_memory_service.create.call_args.kwargs
        assert kwargs["ttl_seconds"] is None


class TestCreateServiceComputesExpiresAt:
    @pytest.mark.asyncio
    async def test_ttl_seconds_becomes_expires_at(self, monkeypatch):
        from mypalace import memory_service as ms
        from mypalace.memory_service import MemoryService

        # Stub embedder + vector + graph + cache + broker so we exercise
        # only the create() arithmetic.
        fake_embedder = MagicMock()
        fake_embedder.embed = AsyncMock(return_value=[[0.0] * 384])
        fake_embedder.dim = 384

        captured: dict = {}

        class FakeDb:
            def add(self, obj):
                # Phase 7 slice 2 also writes MemoryVersion rows through the
                # same patched session — capture only the Memory row.
                from mypalace.models import Memory as _Memory
                if isinstance(obj, _Memory):
                    captured["row"] = obj
            async def commit(self):
                pass
            async def refresh(self, obj):
                obj.id = "m-1"
            async def execute(self, *a, **kw):
                # _next_version_number does a SELECT; return None so it
                # falls back to version 1.
                result = MagicMock()
                result.scalar_one_or_none.return_value = None
                return result

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=FakeDb())
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))
        monkeypatch.setattr(ms.vector_store, "upsert", AsyncMock())

        # Disable graph + cache + broker so create() doesn't fan out.
        from mypalace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)
        from mypalace.graph.service import graph_service
        monkeypatch.setattr(graph_service, "_client",
                            MagicMock(enabled=False, url=None))

        svc = MemoryService()
        svc._embedder = fake_embedder

        before = datetime.now(UTC)
        result = await svc.create(
            user_id="u1", content="x", ttl_seconds=120, tenant_id="t1",
        )
        after = datetime.now(UTC)

        # The Memory row's expires_at should be ~now+120s.
        assert captured["row"].expires_at is not None
        delta = captured["row"].expires_at - before
        assert timedelta(seconds=119) <= delta <= timedelta(seconds=121) + (after - before)
        # And the returned memory carries it through.
        assert result.expires_at is not None

    @pytest.mark.asyncio
    async def test_no_ttl_means_null_expires_at(self, monkeypatch):
        from mypalace import memory_service as ms
        from mypalace.memory_service import MemoryService

        fake_embedder = MagicMock()
        fake_embedder.embed = AsyncMock(return_value=[[0.0] * 384])
        fake_embedder.dim = 384

        captured: dict = {}

        class FakeDb:
            def add(self, obj):
                # Phase 7 slice 2 also writes MemoryVersion rows through the
                # same patched session — capture only the Memory row.
                from mypalace.models import Memory as _Memory
                if isinstance(obj, _Memory):
                    captured["row"] = obj
            async def commit(self):
                pass
            async def refresh(self, obj):
                obj.id = "m-1"
            async def execute(self, *a, **kw):
                # _next_version_number does a SELECT; return None so it
                # falls back to version 1.
                result = MagicMock()
                result.scalar_one_or_none.return_value = None
                return result

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=FakeDb())
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))
        monkeypatch.setattr(ms.vector_store, "upsert", AsyncMock())
        from mypalace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)
        from mypalace.graph.service import graph_service
        monkeypatch.setattr(graph_service, "_client",
                            MagicMock(enabled=False, url=None))

        svc = MemoryService()
        svc._embedder = fake_embedder
        await svc.create(user_id="u1", content="x", tenant_id="t1")

        assert captured["row"].expires_at is None


class TestCleanupExpiredService:
    @pytest.mark.asyncio
    async def test_cleanup_returns_count_and_deletes_vectors(self, monkeypatch):
        from mypalace import memory_service as ms
        from mypalace.memory_service import MemoryService

        # Stub the SQL DELETE returning two ids.
        deleted_rows = MagicMock()
        deleted_rows.all.return_value = [("m-1",), ("m-2",)]
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=deleted_rows)
        db_mock.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))

        vector_delete = AsyncMock()
        monkeypatch.setattr(ms.vector_store, "delete", vector_delete)
        # Cache disabled
        from mypalace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)

        svc = MemoryService()
        n = await svc.cleanup_expired(tenant_id="acme", batch_size=10)
        assert n == 2
        vector_delete.assert_awaited_once()
        # The chunk passed to vector_store.delete should be the ids list.
        called_ids, called_kwargs = (
            vector_delete.await_args.args, vector_delete.await_args.kwargs,
        )
        assert called_ids[0] == ["m-1", "m-2"]
        assert called_kwargs["tenant_id"] == "acme"

    @pytest.mark.asyncio
    async def test_cleanup_with_no_expired_returns_zero(self, monkeypatch):
        from mypalace import memory_service as ms
        from mypalace.memory_service import MemoryService

        empty = MagicMock()
        empty.all.return_value = []
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=empty)
        db_mock.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))
        vector_delete = AsyncMock()
        monkeypatch.setattr(ms.vector_store, "delete", vector_delete)

        svc = MemoryService()
        n = await svc.cleanup_expired(tenant_id="acme")
        assert n == 0
        vector_delete.assert_not_awaited()


class TestCleanupHandler:
    def test_cleanup_handler_registered(self):
        from mypalace.workers.handlers import HANDLER_REGISTRY
        assert "cleanup" in HANDLER_REGISTRY

    @pytest.mark.asyncio
    async def test_cleanup_handler_calls_service(self, monkeypatch):
        from mypalace.workers.handlers import _cleanup_handler

        with patch("mypalace.memory_service.memory_service.cleanup_expired",
                   new=AsyncMock(return_value=42)) as mock_cleanup:
            result = await _cleanup_handler(
                {"batch_size": 100}, tenant_id="acme",
            )
        assert result == {"tenant_id": "acme", "deleted": 42}
        mock_cleanup.assert_awaited_once_with(tenant_id="acme", batch_size=100)
