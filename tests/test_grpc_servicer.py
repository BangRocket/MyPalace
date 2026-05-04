"""Unit tests for the gRPC MemoryServicer (mocking memory_service)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from palace.grpc._generated import palace_pb2
from palace.grpc.memory_servicer import MemoryServicer


def _fake_memory(**overrides):
    m = MagicMock()
    m.id = overrides.get("id", "m1")
    m.user_id = overrides.get("user_id", "u1")
    m.agent_id = overrides.get("agent_id")
    m.content = overrides.get("content", "hello")
    m.memory_type = overrides.get("memory_type", "semantic")
    m.source = overrides.get("source")
    m.importance = overrides.get("importance", 1.0)
    m.created_at = overrides.get("created_at", datetime(2026, 5, 4, tzinfo=UTC))
    m.updated_at = overrides.get("updated_at", datetime(2026, 5, 4, tzinfo=UTC))
    m.accessed_at = overrides.get("accessed_at")
    m.access_count = overrides.get("access_count", 0)
    m.metadata_json = overrides.get("metadata_json")
    return m


@pytest.mark.asyncio
async def test_create_memory_calls_service():
    svc = MemoryServicer()
    fake = _fake_memory(id="new-1", content="hi")
    with patch("palace.grpc.memory_servicer.memory_service.create",
               new=AsyncMock(return_value=fake)) as mock_create:
        req = palace_pb2.CreateMemoryRequest(
            user_id="u1", content="hi", memory_type="semantic", importance=1.0,
        )
        ctx = MagicMock()
        resp = await svc.CreateMemory(req, ctx)
        assert resp.memory.id == "new-1"
        assert resp.memory.content == "hi"
        mock_create.assert_awaited_once()
        # tenant_id propagated from auth context (test bypass = "test")
        assert mock_create.await_args.kwargs["tenant_id"] == "test"


@pytest.mark.asyncio
async def test_get_memory_returns_proto():
    svc = MemoryServicer()
    fake = _fake_memory(id="m9")
    with patch("palace.grpc.memory_servicer.memory_service.get",
               new=AsyncMock(return_value=fake)):
        req = palace_pb2.GetMemoryRequest(memory_id="m9")
        ctx = MagicMock()
        resp = await svc.GetMemory(req, ctx)
        assert resp.memory.id == "m9"


@pytest.mark.asyncio
async def test_get_memory_404_aborts():
    svc = MemoryServicer()
    with patch("palace.grpc.memory_servicer.memory_service.get",
               new=AsyncMock(return_value=None)):
        req = palace_pb2.GetMemoryRequest(memory_id="missing")
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=Exception("aborted"))
        with pytest.raises(Exception, match="aborted"):
            await svc.GetMemory(req, ctx)


@pytest.mark.asyncio
async def test_delete_memory_returns_deleted_true():
    svc = MemoryServicer()
    with patch("palace.grpc.memory_servicer.memory_service.delete",
               new=AsyncMock(return_value=True)):
        req = palace_pb2.DeleteMemoryRequest(memory_id="m1")
        ctx = MagicMock()
        resp = await svc.DeleteMemory(req, ctx)
        assert resp.deleted is True


@pytest.mark.asyncio
async def test_search_memories_packs_score_and_memory():
    svc = MemoryServicer()
    fake = _fake_memory(id="m1")
    results = [(fake, 0.87)]
    with patch("palace.grpc.memory_servicer.memory_service.search",
               new=AsyncMock(return_value=results)):
        req = palace_pb2.SearchMemoriesRequest(query="hello", limit=5)
        ctx = MagicMock()
        resp = await svc.SearchMemories(req, ctx)
        assert len(resp.results) == 1
        assert resp.results[0].memory.id == "m1"
        assert resp.results[0].score == pytest.approx(0.87)


@pytest.mark.asyncio
async def test_list_memories_returns_list():
    svc = MemoryServicer()
    items = [_fake_memory(id="m1"), _fake_memory(id="m2")]
    with patch("palace.grpc.memory_servicer.memory_service.list_filtered",
               new=AsyncMock(return_value=items)):
        req = palace_pb2.ListMemoriesRequest(limit=10)
        ctx = MagicMock()
        resp = await svc.ListMemories(req, ctx)
        assert [m.id for m in resp.memories] == ["m1", "m2"]


# ----------------------------------------------------------------------
# Auth interceptor
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interceptor_passes_when_auth_disabled(monkeypatch):
    from palace.grpc.auth_interceptor import AuthInterceptor

    monkeypatch.setattr("palace.grpc.auth_interceptor.settings.auth_disabled", True)
    interceptor = AuthInterceptor()

    handler_call_details = MagicMock()
    handler_call_details.method = "/palace.v1.MemoryService/CreateMemory"
    handler_call_details.invocation_metadata = []

    continuation = AsyncMock(return_value="HANDLER")
    result = await interceptor.intercept_service(continuation, handler_call_details)
    assert result == "HANDLER"


@pytest.mark.asyncio
async def test_interceptor_rejects_missing_key(monkeypatch):
    from palace.grpc.auth_interceptor import AuthInterceptor

    monkeypatch.setattr("palace.grpc.auth_interceptor.settings.auth_disabled", False)
    interceptor = AuthInterceptor()

    handler_call_details = MagicMock()
    handler_call_details.method = "/palace.v1.MemoryService/CreateMemory"
    handler_call_details.invocation_metadata = []

    continuation = AsyncMock()
    handler = await interceptor.intercept_service(continuation, handler_call_details)
    # Returns an unary_unary handler that aborts the RPC.
    assert handler is not None
    assert continuation.await_count == 0
