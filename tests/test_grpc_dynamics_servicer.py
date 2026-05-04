"""Unit tests for the gRPC DynamicsServicer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.grpc._generated import mypalace_pb2
from mypalace.grpc.dynamics_servicer import DynamicsServicer


def _fake_dynamics(**overrides):
    d = MagicMock()
    d.memory_id = overrides.get("memory_id", "m1")
    d.user_id = overrides.get("user_id", "u1")
    d.stability = overrides.get("stability", 1.0)
    d.difficulty = overrides.get("difficulty", 5.0)
    d.retrieval_strength = overrides.get("retrieval_strength", 1.0)
    d.storage_strength = overrides.get("storage_strength", 0.5)
    d.is_key = overrides.get("is_key", False)
    d.importance_weight = overrides.get("importance_weight", 1.0)
    d.category = overrides.get("category")
    d.tags = overrides.get("tags")
    d.last_accessed_at = overrides.get("last_accessed_at")
    d.access_count = overrides.get("access_count", 0)
    d.created_at = overrides.get("created_at", datetime(2026, 5, 4, tzinfo=UTC))
    d.updated_at = overrides.get("updated_at", datetime(2026, 5, 4, tzinfo=UTC))
    return d


@pytest.mark.asyncio
async def test_promote_memory():
    svc = DynamicsServicer()
    fake = _fake_dynamics(memory_id="m1", access_count=1)
    with patch("mypalace.grpc.dynamics_servicer.dynamics_service.promote",
               new=AsyncMock(return_value=fake)) as mock_promote:
        req = mypalace_pb2.PromoteMemoryRequest(
            memory_id="m1", user_id="u1", grade=3, signal_type="used",
        )
        ctx = MagicMock()
        resp = await svc.PromoteMemory(req, ctx)
        assert resp.dynamics.memory_id == "m1"
        mock_promote.assert_awaited_once()
        assert mock_promote.await_args.kwargs["grade"] == 3


@pytest.mark.asyncio
async def test_promote_invalid_grade():
    svc = DynamicsServicer()
    req = mypalace_pb2.PromoteMemoryRequest(memory_id="m1", user_id="u1", grade=99)
    ctx = MagicMock()
    ctx.abort = AsyncMock(side_effect=Exception("aborted"))
    with pytest.raises(Exception, match="aborted"):
        await svc.PromoteMemory(req, ctx)


@pytest.mark.asyncio
async def test_demote_memory():
    svc = DynamicsServicer()
    fake = _fake_dynamics(memory_id="m1")
    with patch("mypalace.grpc.dynamics_servicer.dynamics_service.demote",
               new=AsyncMock(return_value=fake)):
        req = mypalace_pb2.DemoteMemoryRequest(memory_id="m1", user_id="u1", reason="oops")
        ctx = MagicMock()
        resp = await svc.DemoteMemory(req, ctx)
        assert resp.dynamics.memory_id == "m1"


@pytest.mark.asyncio
async def test_get_dynamics_404():
    svc = DynamicsServicer()
    with patch("mypalace.grpc.dynamics_servicer.dynamics_service.get_dynamics",
               new=AsyncMock(return_value=None)):
        req = mypalace_pb2.GetDynamicsRequest(memory_id="missing", user_id="u1")
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=Exception("aborted"))
        with pytest.raises(Exception, match="aborted"):
            await svc.GetDynamics(req, ctx)


@pytest.mark.asyncio
async def test_get_dynamics_ok():
    svc = DynamicsServicer()
    fake = _fake_dynamics(memory_id="m1")
    with patch("mypalace.grpc.dynamics_servicer.dynamics_service.get_dynamics",
               new=AsyncMock(return_value=fake)):
        req = mypalace_pb2.GetDynamicsRequest(memory_id="m1", user_id="u1")
        ctx = MagicMock()
        resp = await svc.GetDynamics(req, ctx)
        assert resp.dynamics.memory_id == "m1"


@pytest.mark.asyncio
async def test_score_memory():
    svc = DynamicsServicer()
    breakdown = {
        "composite_score": 0.75,
        "fsrs_score": 0.5,
        "retrievability": 0.9,
        "storage_strength": 0.6,
    }
    with patch("mypalace.grpc.dynamics_servicer.dynamics_service.score",
               new=AsyncMock(return_value=breakdown)):
        req = mypalace_pb2.ScoreMemoryRequest(
            memory_id="m1", user_id="u1", semantic_score=0.8,
        )
        ctx = MagicMock()
        resp = await svc.ScoreMemory(req, ctx)
        assert resp.breakdown.composite_score == pytest.approx(0.75)
        assert resp.breakdown.fsrs_score == pytest.approx(0.5)
        assert resp.breakdown.retrievability == pytest.approx(0.9)
