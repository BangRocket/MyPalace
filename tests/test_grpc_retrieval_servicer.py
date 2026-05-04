"""Unit tests for the gRPC RetrievalServicer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from palace.grpc._generated import palace_pb2
from palace.grpc.retrieval_servicer import RetrievalServicer


def _empty_layered_result():
    return {
        "l1_user_profile": {"memories": [], "recent_episodes": [], "active_arcs": []},
        "l2_relevant_context": {"memories": [], "episodes": []},
        "l3_graph_context": None,
        "recent_messages": None,
        "summary": None,
        "char_counts": {"l1": 0, "l2": 0},
    }


@pytest.mark.asyncio
async def test_assemble_layered_empty():
    svc = RetrievalServicer()
    with patch(
        "palace.grpc.retrieval_servicer.layered_retrieval_service.assemble",
        new=AsyncMock(return_value=_empty_layered_result()),
    ):
        req = palace_pb2.AssembleLayeredRequest(user_id="u1", query="hi")
        ctx = MagicMock()
        resp = await svc.AssembleLayered(req, ctx)
        ctx_msg = resp.context
        assert json.loads(ctx_msg.l1_user_profile.memories_json) == []
        assert ctx_msg.has_l3_graph_context is False
        assert ctx_msg.summary == ""
        assert ctx_msg.char_counts.l1 == 0


@pytest.mark.asyncio
async def test_assemble_layered_with_data():
    svc = RetrievalServicer()
    payload = {
        "l1_user_profile": {
            "memories": [{"id": "m1", "content": "x"}],
            "recent_episodes": [{"id": "e1"}],
            "active_arcs": [{"id": "a1"}],
        },
        "l2_relevant_context": {
            "memories": [{"id": "m2"}],
            "episodes": [],
        },
        "l3_graph_context": {
            "related_memories": [{"id": "rm1"}],
            "edges": [{"src": "m1", "dst": "rm1"}],
        },
        "recent_messages": [{"role": "user", "content": "hi"}],
        "summary": "test summary",
        "char_counts": {"l1": 100, "l2": 200},
    }
    with patch(
        "palace.grpc.retrieval_servicer.layered_retrieval_service.assemble",
        new=AsyncMock(return_value=payload),
    ):
        req = palace_pb2.AssembleLayeredRequest(
            user_id="u1", query="hi", include_graph=True,
        )
        ctx = MagicMock()
        resp = await svc.AssembleLayered(req, ctx)
        c = resp.context
        assert c.has_l3_graph_context is True
        assert json.loads(c.l3_graph_context.related_memories_json) == [{"id": "rm1"}]
        assert json.loads(c.l3_graph_context.edges_json) == [
            {"src": "m1", "dst": "rm1"},
        ]
        assert json.loads(c.l1_user_profile.memories_json) == [
            {"id": "m1", "content": "x"},
        ]
        assert c.summary == "test summary"
        assert c.char_counts.l1 == 100
        assert c.char_counts.l2 == 200
        assert json.loads(c.recent_messages_json) == [{"role": "user", "content": "hi"}]
