"""Unit tests for GraphService — mocking the FalkorDB client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from palace.graph.client import FalkorClient
from palace.graph.service import GraphService, _result_to_dict


class TestEnabledGate:
    def test_no_url_means_disabled(self):
        client = FalkorClient(url=None)
        svc = GraphService(client=client)
        assert svc.enabled is False

    def test_with_url_means_enabled(self):
        client = FalkorClient(url="redis://localhost:6379")
        svc = GraphService(client=client)
        assert svc.enabled is True

    @pytest.mark.asyncio
    async def test_disabled_neighbors_returns_empty(self):
        svc = GraphService(client=FalkorClient(url=None))
        result = await svc.neighbors(node_id="x", depth=1)
        assert result == {"nodes": [], "edges": []}

    @pytest.mark.asyncio
    async def test_disabled_schedule_returns_none(self):
        svc = GraphService(client=FalkorClient(url=None))

        async def dummy():
            pass

        assert svc.schedule(dummy()) is None


@pytest.mark.asyncio
async def test_upsert_memory_node_calls_query():
    client = MagicMock(spec=FalkorClient)
    client.enabled = True
    client.query = AsyncMock(return_value=None)
    svc = GraphService(client=client)

    await svc.upsert_memory_node(
        memory_id="m1", user_id="u1", content="hello",
        memory_type="semantic", importance=1.0, tenant_id="t1",
    )
    assert client.query.await_count == 1
    args = client.query.await_args
    assert args.args[0] == "t1"
    assert "MERGE (m:Memory {id: $id})" in args.args[1]
    assert args.args[2]["id"] == "m1"
    assert args.args[2]["content"] == "hello"


@pytest.mark.asyncio
async def test_upsert_episode_node():
    client = MagicMock(spec=FalkorClient)
    client.enabled = True
    client.query = AsyncMock(return_value=None)
    svc = GraphService(client=client)
    await svc.upsert_episode_node(
        episode_id="e1", user_id="u1", summary="x",
        significance=0.5, tenant_id="t1",
    )
    args = client.query.await_args
    assert "MERGE (e:Episode" in args.args[1]
    assert args.args[2]["significance"] == 0.5


@pytest.mark.asyncio
async def test_supersedes_edge_uses_match():
    client = MagicMock(spec=FalkorClient)
    client.enabled = True
    client.query = AsyncMock(return_value=None)
    svc = GraphService(client=client)
    await svc.add_supersedes_edge(
        new_memory_id="m2", old_memory_id="m1", tenant_id="t1", reason="newer",
    )
    args = client.query.await_args
    assert "MATCH (new:Memory" in args.args[1]
    assert "SUPERSEDES" in args.args[1]
    assert args.args[2]["new_id"] == "m2"
    assert args.args[2]["old_id"] == "m1"
    assert args.args[2]["reason"] == "newer"


@pytest.mark.asyncio
async def test_neighbors_caps_depth():
    client = MagicMock(spec=FalkorClient)
    client.enabled = True
    client.query = AsyncMock(return_value=None)
    svc = GraphService(client=client)
    # Request depth 99, expect capped to 3 in cypher.
    await svc.neighbors(node_id="x", depth=99, tenant_id="t1")
    args = client.query.await_args
    assert "1..3" in args.args[1]


@pytest.mark.asyncio
async def test_neighbors_with_edge_type():
    client = MagicMock(spec=FalkorClient)
    client.enabled = True
    client.query = AsyncMock(return_value=None)
    svc = GraphService(client=client)
    await svc.neighbors(node_id="x", depth=1, edge_type="MENTIONS", tenant_id="t1")
    cypher = client.query.await_args.args[1]
    assert ":MENTIONS" in cypher


def test_result_to_dict_handles_none():
    assert _result_to_dict(None) == {"nodes": [], "edges": []}
    empty = MagicMock()
    empty.result_set = []
    assert _result_to_dict(empty) == {"nodes": [], "edges": []}


def test_result_to_dict_extracts_nodes_and_edges():
    class FakeNode:
        def __init__(self, _id, labels, properties):
            self.id = _id
            self.labels = labels
            self.properties = properties

    class FakeEdge:
        def __init__(self, src, dest, relation):
            self.src_node = src
            self.dest_node = dest
            self.relation = relation

    node1 = FakeNode(1, ["Memory"], {"id": "m1", "content": "x"})
    node2 = FakeNode(2, ["Memory"], {"id": "m2", "content": "y"})
    edge = FakeEdge(1, 2, "SUPERSEDES")

    result = MagicMock()
    result.result_set = [[node1, [edge], node2]]
    out = _result_to_dict(result)
    assert len(out["nodes"]) == 2
    assert {n["id"] for n in out["nodes"]} == {"m1", "m2"}
    assert out["edges"] == [{"from_node": "1", "to_node": "2", "type": "SUPERSEDES"}]
