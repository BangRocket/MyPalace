"""Tests for /v1/graph/neighbors route."""

from __future__ import annotations

from unittest.mock import patch


class TestNeighborsRoute:
    def test_503_when_graph_disabled(self, client):
        # mock_graph_service is wired in conftest with enabled=False by default
        with patch("palace.api.graph.graph_service") as mock_graph:
            mock_graph.enabled = False
            r = client.get("/v1/graph/neighbors?node_id=m1")
            assert r.status_code == 503

    def test_returns_neighbors_when_enabled(self, client):
        from unittest.mock import AsyncMock

        with patch("palace.api.graph.graph_service") as mock_graph:
            mock_graph.enabled = True
            mock_graph.neighbors = AsyncMock(return_value={
                "nodes": [{"id": "m1", "label": "Memory", "properties": {}}],
                "edges": [],
            })
            r = client.get("/v1/graph/neighbors?node_id=m1&depth=2")
            assert r.status_code == 200
            assert len(r.json()["data"]["nodes"]) == 1
            mock_graph.neighbors.assert_awaited_once()
            call_kwargs = mock_graph.neighbors.await_args.kwargs
            assert call_kwargs["node_id"] == "m1"
            assert call_kwargs["depth"] == 2
            assert call_kwargs["tenant_id"] == "test"

    def test_rejects_depth_too_high(self, client):
        # Pydantic ge/le validation on Query
        r = client.get("/v1/graph/neighbors?node_id=m1&depth=10")
        assert r.status_code == 422

    def test_rejects_depth_too_low(self, client):
        r = client.get("/v1/graph/neighbors?node_id=m1&depth=0")
        assert r.status_code == 422

    def test_rejects_missing_node_id(self, client):
        r = client.get("/v1/graph/neighbors")
        assert r.status_code == 422
