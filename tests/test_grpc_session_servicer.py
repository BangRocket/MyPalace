"""Unit tests for the gRPC SessionServicer (mocking session_service)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.grpc._generated import mypalace_pb2
from mypalace.grpc.session_servicer import SessionServicer


def _fake_session(**overrides):
    s = MagicMock()
    s.id = overrides.get("id", "s1")
    s.user_id = overrides.get("user_id", "u1")
    s.title = overrides.get("title", "test session")
    s.summary = overrides.get("summary")
    s.created_at = overrides.get("created_at", datetime(2026, 5, 4, tzinfo=UTC))
    s.updated_at = overrides.get("updated_at", datetime(2026, 5, 4, tzinfo=UTC))
    return s


def _fake_message(**overrides):
    m = MagicMock()
    m.id = overrides.get("id", "msg1")
    m.user_id = overrides.get("user_id", "u1")
    m.role = overrides.get("role", "user")
    m.content = overrides.get("content", "hi")
    m.created_at = overrides.get("created_at", datetime(2026, 5, 4, tzinfo=UTC))
    return m


@pytest.mark.asyncio
async def test_create_session_calls_service():
    svc = SessionServicer()
    fake = _fake_session(id="new-1", title="hello")
    with patch("mypalace.grpc.session_servicer.session_service.create",
               new=AsyncMock(return_value=fake)) as mock_create:
        req = mypalace_pb2.CreateSessionRequest(user_id="u1", title="hello")
        ctx = MagicMock()
        resp = await svc.CreateSession(req, ctx)
        assert resp.session.id == "new-1"
        assert resp.session.title == "hello"
        mock_create.assert_awaited_once()
        assert mock_create.await_args.kwargs["tenant_id"] == "test"


@pytest.mark.asyncio
async def test_get_session_returns_with_messages():
    svc = SessionServicer()
    data = {
        "id": "s1",
        "user_id": "u1",
        "title": "t",
        "summary": None,
        "created_at": "2026-05-04T00:00:00+00:00",
        "updated_at": "2026-05-04T00:00:00+00:00",
        "messages": [
            {"id": "m1", "user_id": "u1", "role": "user", "content": "hi",
             "created_at": "2026-05-04T00:00:00+00:00"},
        ],
    }
    with patch("mypalace.grpc.session_servicer.session_service.get",
               new=AsyncMock(return_value=data)):
        req = mypalace_pb2.GetSessionRequest(session_id="s1")
        ctx = MagicMock()
        resp = await svc.GetSession(req, ctx)
        assert resp.data.session.id == "s1"
        assert len(resp.data.messages) == 1
        assert resp.data.messages[0].content == "hi"


@pytest.mark.asyncio
async def test_get_session_404():
    svc = SessionServicer()
    with patch("mypalace.grpc.session_servicer.session_service.get",
               new=AsyncMock(return_value=None)):
        req = mypalace_pb2.GetSessionRequest(session_id="missing")
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=Exception("aborted"))
        with pytest.raises(Exception, match="aborted"):
            await svc.GetSession(req, ctx)


@pytest.mark.asyncio
async def test_add_message_returns_proto():
    svc = SessionServicer()
    fake = _fake_message(id="m9", content="hello")
    with patch("mypalace.grpc.session_servicer.session_service.add_message",
               new=AsyncMock(return_value=fake)):
        req = mypalace_pb2.AddMessageRequest(
            session_id="s1", user_id="u1", role="user", content="hello",
        )
        ctx = MagicMock()
        resp = await svc.AddMessage(req, ctx)
        assert resp.message.id == "m9"
        assert resp.message.content == "hello"


@pytest.mark.asyncio
async def test_update_session_404():
    svc = SessionServicer()
    with patch("mypalace.grpc.session_servicer.session_service.update",
               new=AsyncMock(return_value=None)):
        req = mypalace_pb2.UpdateSessionRequest(session_id="missing", title="new")
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=Exception("aborted"))
        with pytest.raises(Exception, match="aborted"):
            await svc.UpdateSession(req, ctx)


@pytest.mark.asyncio
async def test_update_session_ok():
    svc = SessionServicer()
    fake = _fake_session(id="s1", title="updated")
    with patch("mypalace.grpc.session_servicer.session_service.update",
               new=AsyncMock(return_value=fake)):
        req = mypalace_pb2.UpdateSessionRequest(session_id="s1", title="updated")
        ctx = MagicMock()
        resp = await svc.UpdateSession(req, ctx)
        assert resp.session.title == "updated"


@pytest.mark.asyncio
async def test_delete_session_returns_deleted_true():
    svc = SessionServicer()
    with patch("mypalace.grpc.session_servicer.session_service.delete",
               new=AsyncMock(return_value=True)):
        req = mypalace_pb2.DeleteSessionRequest(session_id="s1")
        ctx = MagicMock()
        resp = await svc.DeleteSession(req, ctx)
        assert resp.deleted is True


@pytest.mark.asyncio
async def test_delete_session_404():
    svc = SessionServicer()
    with patch("mypalace.grpc.session_servicer.session_service.delete",
               new=AsyncMock(return_value=False)):
        req = mypalace_pb2.DeleteSessionRequest(session_id="missing")
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=Exception("aborted"))
        with pytest.raises(Exception, match="aborted"):
            await svc.DeleteSession(req, ctx)
