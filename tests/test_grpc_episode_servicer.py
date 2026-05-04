"""Unit tests for the gRPC EpisodeServicer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.grpc._generated import mypalace_pb2
from mypalace.grpc.episode_servicer import EpisodeServicer


def _fake_episode(**overrides):
    return {
        "id": overrides.get("id", "ep1"),
        "user_id": overrides.get("user_id", "u1"),
        "agent_id": overrides.get("agent_id"),
        "content": overrides.get("content", "ep content"),
        "summary": overrides.get("summary", "ep summary"),
        "participants": overrides.get("participants", ["user", "assistant"]),
        "topics": overrides.get("topics", ["t1"]),
        "emotional_tone": overrides.get("emotional_tone", "neutral"),
        "significance": overrides.get("significance", 0.5),
        "timestamp": overrides.get("timestamp", "2026-05-04T00:00:00+00:00"),
        "session_id": overrides.get("session_id"),
        "message_count": overrides.get("message_count", 2),
    }


@pytest.mark.asyncio
async def test_reflect_session_sync_returns_episodes():
    svc = EpisodeServicer()
    with patch("mypalace.grpc.episode_servicer.episode_service.reflect_session",
               new=AsyncMock(return_value=[_fake_episode(id="e1")])):
        req = mypalace_pb2.ReflectSessionRequest(
            user_id="u1",
            messages=[mypalace_pb2.ReflectionMessage(role="user", content="hi")],
            mode="sync",
        )
        ctx = MagicMock()
        resp = await svc.ReflectSession(req, ctx)
        assert resp.WhichOneof("result") == "episodes"
        assert len(resp.episodes.episodes) == 1
        assert resp.episodes.episodes[0].id == "e1"


@pytest.mark.asyncio
async def test_reflect_session_async_returns_pending(monkeypatch):
    svc = EpisodeServicer()
    monkeypatch.setattr(
        "mypalace.grpc.episode_servicer.settings.worker_queue_enabled", False,
    )
    fake_job = MagicMock()
    fake_job.id = "job-1"
    with patch("mypalace.grpc.episode_servicer.job_service.run_async",
               new=AsyncMock(return_value=fake_job)):
        req = mypalace_pb2.ReflectSessionRequest(
            user_id="u1",
            messages=[mypalace_pb2.ReflectionMessage(role="user", content="hi")],
            mode="async",
        )
        ctx = MagicMock()
        resp = await svc.ReflectSession(req, ctx)
        assert resp.WhichOneof("result") == "pending"
        assert resp.pending.job_id == "job-1"
        assert resp.pending.status == "pending"


@pytest.mark.asyncio
async def test_reflect_session_async_with_worker_queue(monkeypatch):
    svc = EpisodeServicer()
    monkeypatch.setattr(
        "mypalace.grpc.episode_servicer.settings.worker_queue_enabled", True,
    )
    fake_job = MagicMock()
    fake_job.id = "job-q1"
    with patch("mypalace.grpc.episode_servicer.enqueue_job",
               new=AsyncMock(return_value=fake_job)) as mock_enq:
        req = mypalace_pb2.ReflectSessionRequest(
            user_id="u1",
            messages=[mypalace_pb2.ReflectionMessage(role="user", content="hi")],
            mode="async",
        )
        ctx = MagicMock()
        resp = await svc.ReflectSession(req, ctx)
        assert resp.WhichOneof("result") == "pending"
        assert resp.pending.job_id == "job-q1"
        mock_enq.assert_awaited_once()
        assert mock_enq.await_args.kwargs["kind"] == "reflection"


@pytest.mark.asyncio
async def test_reflect_session_invalid_mode():
    svc = EpisodeServicer()
    req = mypalace_pb2.ReflectSessionRequest(user_id="u1", mode="bogus")
    ctx = MagicMock()
    ctx.abort = AsyncMock(side_effect=Exception("aborted"))
    with pytest.raises(Exception, match="aborted"):
        await svc.ReflectSession(req, ctx)


@pytest.mark.asyncio
async def test_search_episodes():
    svc = EpisodeServicer()
    with patch("mypalace.grpc.episode_servicer.episode_service.search",
               new=AsyncMock(return_value=[_fake_episode(id="e2", score=0.8)])):
        req = mypalace_pb2.SearchEpisodesRequest(query="q", user_id="u1", limit=5)
        ctx = MagicMock()
        resp = await svc.SearchEpisodes(req, ctx)
        assert len(resp.episodes) == 1
        assert resp.episodes[0].id == "e2"


@pytest.mark.asyncio
async def test_get_recent_episodes():
    svc = EpisodeServicer()
    items = [_fake_episode(id="e1"), _fake_episode(id="e2")]
    with patch("mypalace.grpc.episode_servicer.episode_service.get_recent",
               new=AsyncMock(return_value=items)):
        req = mypalace_pb2.GetRecentEpisodesRequest(user_id="u1", limit=5)
        ctx = MagicMock()
        resp = await svc.GetRecentEpisodes(req, ctx)
        assert [e.id for e in resp.episodes] == ["e1", "e2"]
