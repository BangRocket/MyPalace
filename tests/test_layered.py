"""Slice-5 layered retrieval tests (mock-based)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from palace.retrieval.layered import LayeredRetrievalService


def _fake_memory(mid: str, content: str = "fact") -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        user_id="u1",
        agent_id="clara",
        content=content,
        memory_type="semantic",
        importance=1.0,
        created_at=datetime.now(UTC),
        metadata_json=None,
    )


def _fake_arc(aid: str = "a1") -> SimpleNamespace:
    return SimpleNamespace(
        id=aid,
        title="growth",
        summary="career growth arc",
        status="active",
        key_episode_ids=[],
        emotional_trajectory="upward",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Endpoint tests via FastAPI client (uses mock_layered_service)
# ---------------------------------------------------------------------------


def test_layered_endpoint_returns_envelope(client, mock_layered_service):
    resp = client.post(
        "/v1/context/layered",
        json={"user_id": "u1", "query": "career"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "l1_user_profile" in body["data"]
    assert "l2_relevant_context" in body["data"]
    assert body["data"]["char_counts"] == {"l1": 0, "l2": 0}
    mock_layered_service.assemble.assert_awaited_once()


def test_layered_endpoint_passes_options(client, mock_layered_service):
    client.post(
        "/v1/context/layered",
        json={
            "user_id": "u1",
            "query": "growth",
            "agent_id": "clara",
            "session_id": "s-1",
            "use_fsrs": False,
            "max_l1_chars": 500,
            "max_l2_chars": 1000,
            "memory_limit": 7,
            "episode_limit": 3,
            "min_episode_significance": 0.5,
        },
    )
    kwargs = mock_layered_service.assemble.call_args.kwargs
    assert kwargs["use_fsrs"] is False
    assert kwargs["max_l1_chars"] == 500
    assert kwargs["memory_limit"] == 7
    assert kwargs["session_id"] == "s-1"


# ---------------------------------------------------------------------------
# Service-level tests with patched dependencies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_with_fsrs_reranks_l2_by_composite():
    svc = LayeredRetrievalService()
    m_high = _fake_memory("m-high", "long high content")
    m_low = _fake_memory("m-low", "long low content")

    # semantic order: m_low first; FSRS should flip them.
    semantic_results = [(m_low, 0.5), (m_high, 0.4)]

    async def _score(memory_id, user_id, semantic_score):
        if memory_id == "m-high":
            return {
                "composite_score": 0.9, "fsrs_score": 0.95,
                "retrievability": 1.0, "storage_strength": 1.0,
            }
        return {
            "composite_score": 0.3, "fsrs_score": 0.1,
            "retrievability": 0.2, "storage_strength": 0.1,
        }

    with (
        patch("palace.retrieval.layered.memory_service") as mem_mock,
        patch("palace.retrieval.layered.episode_service") as ep_mock,
        patch("palace.retrieval.layered.arc_service") as arc_mock,
        patch("palace.retrieval.layered.dynamics_service") as dyn_mock,
    ):
        mem_mock.search = AsyncMock(side_effect=[
            semantic_results,  # L1
            semantic_results,  # L2
        ])
        ep_mock.get_recent = AsyncMock(return_value=[])
        ep_mock.search = AsyncMock(return_value=[])
        arc_mock.get_active = AsyncMock(return_value=[])
        dyn_mock.score = AsyncMock(side_effect=_score)

        result = await svc.assemble(user_id="u1", query="q", use_fsrs=True)

    l2_mems = result["l2_relevant_context"]["memories"]
    assert l2_mems[0]["id"] == "m-high"
    assert l2_mems[1]["id"] == "m-low"
    assert l2_mems[0]["composite_score"] > l2_mems[1]["composite_score"]


@pytest.mark.asyncio
async def test_assemble_without_fsrs_keeps_semantic_order():
    svc = LayeredRetrievalService()
    m1 = _fake_memory("m1")
    m2 = _fake_memory("m2")
    semantic_results = [(m1, 0.9), (m2, 0.5)]

    with (
        patch("palace.retrieval.layered.memory_service") as mem_mock,
        patch("palace.retrieval.layered.episode_service") as ep_mock,
        patch("palace.retrieval.layered.arc_service") as arc_mock,
        patch("palace.retrieval.layered.dynamics_service") as dyn_mock,
    ):
        mem_mock.search = AsyncMock(return_value=semantic_results)
        ep_mock.get_recent = AsyncMock(return_value=[])
        ep_mock.search = AsyncMock(return_value=[])
        arc_mock.get_active = AsyncMock(return_value=[])
        dyn_mock.score = AsyncMock()

        result = await svc.assemble(user_id="u1", query="q", use_fsrs=False)

    l2_mems = result["l2_relevant_context"]["memories"]
    assert [m["id"] for m in l2_mems] == ["m1", "m2"]
    # No composite_score keys when use_fsrs=False
    assert "composite_score" not in l2_mems[0]
    dyn_mock.score.assert_not_awaited()


@pytest.mark.asyncio
async def test_assemble_pulls_recent_messages_when_session_provided():
    svc = LayeredRetrievalService()

    with (
        patch("palace.retrieval.layered.memory_service") as mem_mock,
        patch("palace.retrieval.layered.episode_service") as ep_mock,
        patch("palace.retrieval.layered.arc_service") as arc_mock,
        patch("palace.retrieval.layered.session_service") as sess_mock,
    ):
        mem_mock.search = AsyncMock(return_value=[])
        ep_mock.get_recent = AsyncMock(return_value=[])
        ep_mock.search = AsyncMock(return_value=[])
        arc_mock.get_active = AsyncMock(return_value=[])
        sess_mock.get = AsyncMock(return_value={
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            "summary": "a chat",
        })

        result = await svc.assemble(
            user_id="u1", query="q", session_id="s-1", use_fsrs=False,
        )

    assert result["recent_messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert result["summary"] == "a chat"


@pytest.mark.asyncio
async def test_assemble_enforces_char_budget_on_l1():
    svc = LayeredRetrievalService()
    big = _fake_memory("big", "x" * 5000)
    medium = _fake_memory("medium", "y" * 200)
    semantic_results = [(big, 0.9), (medium, 0.5)]

    with (
        patch("palace.retrieval.layered.memory_service") as mem_mock,
        patch("palace.retrieval.layered.episode_service") as ep_mock,
        patch("palace.retrieval.layered.arc_service") as arc_mock,
    ):
        mem_mock.search = AsyncMock(return_value=semantic_results)
        ep_mock.get_recent = AsyncMock(return_value=[])
        ep_mock.search = AsyncMock(return_value=[])
        arc_mock.get_active = AsyncMock(return_value=[])

        result = await svc.assemble(
            user_id="u1", query="q", use_fsrs=False,
            max_l1_chars=500, max_l2_chars=500,
        )

    l1 = result["l1_user_profile"]["memories"]
    # First memory exceeds budget but is kept (we always keep at least one),
    # subsequent ones are dropped.
    assert len(l1) == 1
    assert l1[0]["id"] == "big"
    assert result["char_counts"]["l1"] == 5000


@pytest.mark.asyncio
async def test_assemble_reports_char_counts_in_response():
    svc = LayeredRetrievalService()
    m1 = _fake_memory("m1", "abcdef")  # 6 chars
    m2 = _fake_memory("m2", "ghi")  # 3 chars

    with (
        patch("palace.retrieval.layered.memory_service") as mem_mock,
        patch("palace.retrieval.layered.episode_service") as ep_mock,
        patch("palace.retrieval.layered.arc_service") as arc_mock,
    ):
        mem_mock.search = AsyncMock(return_value=[(m1, 0.9), (m2, 0.5)])
        ep_mock.get_recent = AsyncMock(return_value=[])
        ep_mock.search = AsyncMock(return_value=[])
        arc_mock.get_active = AsyncMock(return_value=[])

        result = await svc.assemble(
            user_id="u1", query="q", use_fsrs=False,
            max_l1_chars=100, max_l2_chars=100,
        )

    assert result["char_counts"]["l1"] == 9
    assert result["char_counts"]["l2"] == 9


@pytest.mark.asyncio
async def test_assemble_includes_active_arcs():
    svc = LayeredRetrievalService()
    arc = _fake_arc("a-1")

    with (
        patch("palace.retrieval.layered.memory_service") as mem_mock,
        patch("palace.retrieval.layered.episode_service") as ep_mock,
        patch("palace.retrieval.layered.arc_service") as arc_mock,
    ):
        mem_mock.search = AsyncMock(return_value=[])
        ep_mock.get_recent = AsyncMock(return_value=[])
        ep_mock.search = AsyncMock(return_value=[])
        arc_mock.get_active = AsyncMock(return_value=[arc])

        result = await svc.assemble(user_id="u1", query="q", use_fsrs=False)

    arcs = result["l1_user_profile"]["active_arcs"]
    assert len(arcs) == 1
    assert arcs[0]["id"] == "a-1"
    assert arcs[0]["status"] == "active"
