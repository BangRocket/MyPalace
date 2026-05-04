"""Tests for the layered context graph wire-up (phase 4 slice 6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from palace.retrieval.layered import LayeredRetrievalService


class TestFetchGraphContext:
    @pytest.mark.asyncio
    async def test_returns_none_when_graph_disabled(self):
        svc = LayeredRetrievalService()
        with patch("palace.graph.service.graph_service") as mock_graph:
            mock_graph.enabled = False
            result = await svc._fetch_graph_context(
                memory_ids=["m1", "m2"], tenant_id="t1",
                depth=1, max_neighbors=50,
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_l2_memory_ids(self):
        svc = LayeredRetrievalService()
        with patch("palace.graph.service.graph_service") as mock_graph:
            mock_graph.enabled = True
            result = await svc._fetch_graph_context(
                memory_ids=[], tenant_id="t1", depth=1, max_neighbors=50,
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_dedupes_neighbors_and_skips_l2_memories(self):
        svc = LayeredRetrievalService()
        with patch("palace.graph.service.graph_service") as mock_graph:
            mock_graph.enabled = True
            # m1's neighbors include m2 (already in L2 — skip), m3, m4.
            # m2's neighbors include m3 (dup) and m5.
            mock_graph.neighbors = AsyncMock(side_effect=[
                {
                    "nodes": [
                        {"id": "m2", "label": "Memory", "properties": {}},
                        {"id": "m3", "label": "Memory", "properties": {}},
                        {"id": "m4", "label": "Memory", "properties": {}},
                    ],
                    "edges": [{"from_node": "1", "to_node": "3", "type": "MENTIONS"}],
                },
                {
                    "nodes": [
                        {"id": "m3", "label": "Memory", "properties": {}},
                        {"id": "m5", "label": "Memory", "properties": {}},
                    ],
                    "edges": [{"from_node": "2", "to_node": "5", "type": "RELATES_TO"}],
                },
            ])

            result = await svc._fetch_graph_context(
                memory_ids=["m1", "m2"], tenant_id="t1",
                depth=1, max_neighbors=50,
            )

        assert result is not None
        ids = {n["id"] for n in result["related_memories"]}
        # m2 was in L2 — excluded
        # m3 appeared twice — deduped to one
        assert ids == {"m3", "m4", "m5"}
        # All edges concatenated
        assert len(result["edges"]) == 2

    @pytest.mark.asyncio
    async def test_caps_at_max_neighbors(self):
        svc = LayeredRetrievalService()

        # Generate 100 distinct neighbor nodes; cap at 5.
        big_neighborhood = {
            "nodes": [
                {"id": f"n{i}", "label": "Memory", "properties": {}}
                for i in range(100)
            ],
            "edges": [],
        }
        with patch("palace.graph.service.graph_service") as mock_graph:
            mock_graph.enabled = True
            mock_graph.neighbors = AsyncMock(return_value=big_neighborhood)
            result = await svc._fetch_graph_context(
                memory_ids=["m1"], tenant_id="t1",
                depth=1, max_neighbors=5,
            )
        assert len(result["related_memories"]) == 5

    @pytest.mark.asyncio
    async def test_swallows_per_node_exceptions(self):
        """A graph error for one memory shouldn't kill the whole walk."""
        svc = LayeredRetrievalService()
        with patch("palace.graph.service.graph_service") as mock_graph:
            mock_graph.enabled = True
            mock_graph.neighbors = AsyncMock(side_effect=[
                RuntimeError("boom"),
                {"nodes": [{"id": "n1", "label": "Memory", "properties": {}}],
                 "edges": []},
            ])
            result = await svc._fetch_graph_context(
                memory_ids=["m1", "m2"], tenant_id="t1",
                depth=1, max_neighbors=50,
            )
        assert result is not None
        assert {n["id"] for n in result["related_memories"]} == {"n1"}


class TestRouteGraphPropagation:
    """The /v1/context/layered route should pass include_graph through."""

    def test_default_include_graph_false(self, client, mock_layered_service):
        r = client.post("/v1/context/layered", json={
            "user_id": "u1", "query": "x",
        })
        assert r.status_code == 200
        kwargs = mock_layered_service.assemble.call_args.kwargs
        assert kwargs["include_graph"] is False
        assert r.json()["data"]["l3_graph_context"] is None

    def test_include_graph_true_propagates(self, client, mock_layered_service):
        # Make the mock return an l3 payload so we exercise serialization.
        mock_layered_service.assemble = AsyncMock(return_value={
            "l1_user_profile": {"memories": [], "recent_episodes": [], "active_arcs": []},
            "l2_relevant_context": {"memories": [], "episodes": []},
            "l3_graph_context": {
                "related_memories": [{"id": "n1", "label": "Memory",
                                      "properties": {"id": "n1"}}],
                "edges": [],
            },
            "recent_messages": None,
            "summary": None,
            "char_counts": {"l1": 0, "l2": 0},
        })
        r = client.post("/v1/context/layered", json={
            "user_id": "u1", "query": "x",
            "include_graph": True, "graph_depth": 2, "graph_max_neighbors": 25,
        })
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["l3_graph_context"] is not None
        assert len(body["l3_graph_context"]["related_memories"]) == 1
        kwargs = mock_layered_service.assemble.call_args.kwargs
        assert kwargs["include_graph"] is True
        assert kwargs["graph_depth"] == 2
        assert kwargs["graph_max_neighbors"] == 25
