"""Graph service: domain operations on the per-tenant graph."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mypalace.config import settings
from mypalace.graph.client import FalkorClient
from mypalace.models import DEFAULT_TENANT_ID

logger = logging.getLogger(__name__)


def _safe_str(v: Any) -> str:
    """Cypher-safe quote: replace single quotes."""
    return str(v).replace("'", "\\'")


class GraphService:
    """High-level graph operations. Every method is fire-and-forget safe:
    failures log a WARNING and never raise, so write-path callers can
    schedule them via `asyncio.create_task` without try/except.
    """

    def __init__(self, client: FalkorClient | None = None) -> None:
        self._client = client or FalkorClient(settings.falkordb_url)

    @property
    def enabled(self) -> bool:
        return self._client.enabled

    @property
    def client(self) -> FalkorClient:
        return self._client

    # ------------------------------------------------------------------
    # Node upserts
    # ------------------------------------------------------------------

    async def upsert_memory_node(
        self,
        memory_id: str,
        user_id: str,
        content: str,
        memory_type: str,
        importance: float,
        tenant_id: str = DEFAULT_TENANT_ID,
        agent_id: str | None = None,
    ) -> None:
        cypher = (
            "MERGE (m:Memory {id: $id}) "
            "SET m.user_id = $user_id, m.agent_id = $agent_id, "
            "    m.content = $content, m.memory_type = $memory_type, "
            "    m.importance = $importance"
        )
        params = {
            "id": memory_id,
            "user_id": user_id,
            "agent_id": agent_id or "",
            "content": content[:500],  # truncate to keep graph nodes lean
            "memory_type": memory_type,
            "importance": importance,
        }
        await self._client.query(tenant_id, cypher, params)

    async def upsert_episode_node(
        self,
        episode_id: str,
        user_id: str,
        summary: str,
        significance: float,
        tenant_id: str = DEFAULT_TENANT_ID,
        timestamp: str | None = None,
    ) -> None:
        cypher = (
            "MERGE (e:Episode {id: $id}) "
            "SET e.user_id = $user_id, e.summary = $summary, "
            "    e.significance = $significance, e.timestamp = $timestamp"
        )
        params = {
            "id": episode_id,
            "user_id": user_id,
            "summary": summary[:500],
            "significance": significance,
            "timestamp": timestamp or "",
        }
        await self._client.query(tenant_id, cypher, params)

    async def upsert_arc_node(
        self,
        arc_id: str,
        user_id: str,
        title: str,
        status: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        cypher = (
            "MERGE (a:Arc {id: $id}) "
            "SET a.user_id = $user_id, a.title = $title, a.status = $status"
        )
        params = {
            "id": arc_id,
            "user_id": user_id,
            "title": title,
            "status": status,
        }
        await self._client.query(tenant_id, cypher, params)

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    async def add_supersedes_edge(
        self,
        new_memory_id: str,
        old_memory_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        reason: str = "",
    ) -> None:
        cypher = (
            "MATCH (new:Memory {id: $new_id}), (old:Memory {id: $old_id}) "
            "MERGE (new)-[r:SUPERSEDES]->(old) "
            "SET r.reason = $reason"
        )
        params = {
            "new_id": new_memory_id,
            "old_id": old_memory_id,
            "reason": reason,
        }
        await self._client.query(tenant_id, cypher, params)

    async def add_episode_arc_edge(
        self,
        episode_id: str,
        arc_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        cypher = (
            "MATCH (e:Episode {id: $eid}), (a:Arc {id: $aid}) "
            "MERGE (e)-[:PARTICIPATES_IN]->(a)"
        )
        await self._client.query(tenant_id, cypher, {"eid": episode_id, "aid": arc_id})

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        tenant_id: str = DEFAULT_TENANT_ID,
        edge_type: str | None = None,
    ) -> dict:
        """Return n-hop neighbors. Result format:
            {nodes: [{id, label, properties}, ...],
             edges: [{from, to, type}, ...]}
        Empty dict if graph disabled or node not found.
        """
        if not self.enabled:
            return {"nodes": [], "edges": []}
        depth = max(1, min(depth, 3))  # safety cap
        edge_clause = f":{edge_type}" if edge_type else ""
        cypher = (
            f"MATCH (start {{id: $id}})-[r{edge_clause}*1..{depth}]-(n) "
            "RETURN start, r, n"
        )
        result = await self._client.query(tenant_id, cypher, {"id": node_id})
        return _result_to_dict(result)

    # ------------------------------------------------------------------
    # Fire-and-forget helper
    # ------------------------------------------------------------------

    def schedule(self, coro: Any, kind: str = "write") -> asyncio.Task | None:
        """Schedule a graph write fire-and-forget. Returns None if disabled.
        Closes the unawaited coroutine on the disabled path to avoid
        RuntimeWarning. Increments per-kind counters; failures bump
        ``palace_graph_failures_total``."""
        from mypalace.observability.metrics import graph_failures, graph_writes

        if not self.enabled:
            if hasattr(coro, "close"):
                coro.close()
            return None

        graph_writes.labels(kind=kind).inc()

        async def _wrap():
            try:
                await coro
            except Exception:
                graph_failures.inc()
                logger.exception("graph write task failed")

        return asyncio.create_task(_wrap())


def _result_to_dict(result: Any) -> dict:
    """Convert a FalkorDB QueryResult into a JSON-friendly nodes+edges dict."""
    if result is None or not getattr(result, "result_set", None):
        return {"nodes": [], "edges": []}
    nodes_by_id: dict[str, dict] = {}
    edges: list[dict] = []
    for row in result.result_set:
        for cell in row:
            # FalkorDB returns Node / Edge / lists for variable-length paths.
            for item in _flatten(cell):
                if hasattr(item, "labels"):  # Node
                    props = dict(item.properties or {})
                    nid = props.get("id") or str(item.id)
                    if nid not in nodes_by_id:
                        nodes_by_id[nid] = {
                            "id": nid,
                            "label": list(item.labels)[0] if item.labels else "",
                            "properties": props,
                        }
                elif hasattr(item, "src_node"):  # Edge
                    edges.append({
                        "from_node": str(item.src_node),
                        "to_node": str(item.dest_node),
                        "type": item.relation,
                    })
    return {"nodes": list(nodes_by_id.values()), "edges": edges}


def _flatten(item: Any):
    if isinstance(item, list):
        for sub in item:
            yield from _flatten(sub)
    else:
        yield item


graph_service = GraphService()
