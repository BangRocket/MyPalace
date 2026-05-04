"""Unit tests for the gRPC ArcServicer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.grpc._generated import mypalace_pb2
from mypalace.grpc.arc_servicer import ArcServicer


def _fake_arc(**overrides):
    a = MagicMock()
    a.id = overrides.get("id", "a1")
    a.user_id = overrides.get("user_id", "u1")
    a.agent_id = overrides.get("agent_id")
    a.title = overrides.get("title", "title")
    a.summary = overrides.get("summary", "summary")
    a.status = overrides.get("status", "active")
    a.key_episode_ids = overrides.get("key_episode_ids", ["ep1", "ep2"])
    a.emotional_trajectory = overrides.get("emotional_trajectory", "rising")
    a.created_at = overrides.get("created_at", datetime(2026, 5, 4, tzinfo=UTC))
    a.updated_at = overrides.get("updated_at", datetime(2026, 5, 4, tzinfo=UTC))
    return a


@pytest.mark.asyncio
async def test_synthesize_sync_returns_arcs():
    svc = ArcServicer()
    with patch("mypalace.grpc.arc_servicer.arc_service.synthesize_narratives",
               new=AsyncMock(return_value=[_fake_arc(id="a1")])):
        req = mypalace_pb2.SynthesizeNarrativesRequest(user_id="u1", mode="sync")
        ctx = MagicMock()
        resp = await svc.SynthesizeNarratives(req, ctx)
        assert resp.WhichOneof("result") == "arcs"
        assert len(resp.arcs.arcs) == 1
        assert resp.arcs.arcs[0].title == "title"


@pytest.mark.asyncio
async def test_synthesize_async_returns_pending(monkeypatch):
    svc = ArcServicer()
    monkeypatch.setattr(
        "mypalace.grpc.arc_servicer.settings.worker_queue_enabled", False,
    )
    fake_job = MagicMock()
    fake_job.id = "job-2"
    with patch("mypalace.grpc.arc_servicer.job_service.run_async",
               new=AsyncMock(return_value=fake_job)):
        req = mypalace_pb2.SynthesizeNarrativesRequest(user_id="u1", mode="async")
        ctx = MagicMock()
        resp = await svc.SynthesizeNarratives(req, ctx)
        assert resp.WhichOneof("result") == "pending"
        assert resp.pending.job_id == "job-2"


@pytest.mark.asyncio
async def test_synthesize_async_with_worker_queue(monkeypatch):
    svc = ArcServicer()
    monkeypatch.setattr(
        "mypalace.grpc.arc_servicer.settings.worker_queue_enabled", True,
    )
    fake_job = MagicMock()
    fake_job.id = "job-q2"
    with patch("mypalace.grpc.arc_servicer.enqueue_job",
               new=AsyncMock(return_value=fake_job)) as mock_enq:
        req = mypalace_pb2.SynthesizeNarrativesRequest(user_id="u1", mode="async")
        ctx = MagicMock()
        resp = await svc.SynthesizeNarratives(req, ctx)
        assert resp.WhichOneof("result") == "pending"
        assert resp.pending.job_id == "job-q2"
        mock_enq.assert_awaited_once()


@pytest.mark.asyncio
async def test_synthesize_invalid_mode():
    svc = ArcServicer()
    req = mypalace_pb2.SynthesizeNarrativesRequest(user_id="u1", mode="weird")
    ctx = MagicMock()
    ctx.abort = AsyncMock(side_effect=Exception("aborted"))
    with pytest.raises(Exception, match="aborted"):
        await svc.SynthesizeNarratives(req, ctx)


@pytest.mark.asyncio
async def test_get_active_arcs():
    svc = ArcServicer()
    arcs = [_fake_arc(id="a1"), _fake_arc(id="a2")]
    with patch("mypalace.grpc.arc_servicer.arc_service.get_active",
               new=AsyncMock(return_value=arcs)):
        req = mypalace_pb2.GetActiveArcsRequest(user_id="u1", limit=10)
        ctx = MagicMock()
        resp = await svc.GetActiveArcs(req, ctx)
        assert [a.id for a in resp.arcs] == ["a1", "a2"]
        assert resp.arcs[0].key_episode_ids == ["ep1", "ep2"]
