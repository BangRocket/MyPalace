"""LayeredRetrievalService — multi-tier context assembly (slice 5).

Composes:
- L1 user-profile layer: top semantic memories + recent episodes + active arcs
- L2 relevant-context layer: query-filtered memories (FSRS-reranked when
  ``use_fsrs=True``) + query-filtered episodes
- Optional recent_messages from a session

Returns a structured dict; the caller is responsible for composing this into
LLM prompts. Drops mypalclara's persona/Discord-specific layers (L0 SOUL.md,
channel_context, vault_snapshot) since Palace is generic.

Char budgeting (D2): rough 4-chars-per-token. Memories are added in score
order until the per-layer char budget is exceeded, then truncated.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mypalace.arc_service import arc_service
from mypalace.config import context_budget_l1_chars, context_budget_l2_chars
from mypalace.dynamics.service import dynamics_service
from mypalace.episode_service import episode_service
from mypalace.memory_service import memory_service
from mypalace.models import DEFAULT_TENANT_ID
from mypalace.session_service import session_service


def _memory_to_dict(m: Any, score: float) -> dict[str, Any]:
    return {
        "id": m.id,
        "user_id": m.user_id,
        "agent_id": m.agent_id,
        "content": m.content,
        "memory_type": m.memory_type,
        "importance": m.importance,
        "score": round(score, 4),
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "metadata": m.metadata_json,
    }


def _arc_to_dict(arc: Any) -> dict[str, Any]:
    return {
        "id": arc.id,
        "title": arc.title,
        "summary": arc.summary,
        "status": arc.status,
        "key_episode_ids": arc.key_episode_ids or [],
        "emotional_trajectory": arc.emotional_trajectory or "",
        "created_at": arc.created_at.isoformat() if arc.created_at else None,
        "updated_at": arc.updated_at.isoformat() if arc.updated_at else None,
    }


def _enforce_char_budget(
    items: list[dict[str, Any]],
    budget: int,
    key: str = "content",
) -> tuple[list[dict[str, Any]], int]:
    """Return (kept_items, total_chars). Stops adding once budget exceeded."""
    kept: list[dict[str, Any]] = []
    total = 0
    for item in items:
        text = item.get(key, "") or ""
        size = len(text)
        if total + size > budget and kept:
            break
        kept.append(item)
        total += size
        if total >= budget:
            break
    return kept, total


class LayeredRetrievalService:
    """Assembles a layered context blob for a query."""

    async def assemble(
        self,
        user_id: str,
        query: str,
        agent_id: str | None = None,
        session_id: str | None = None,
        max_l1_chars: int | None = None,
        max_l2_chars: int | None = None,
        max_recent_messages: int = 20,
        use_fsrs: bool = True,
        memory_limit: int = 10,
        episode_limit: int = 5,
        min_episode_significance: float = 0.3,
        tenant_id: str = DEFAULT_TENANT_ID,
        include_graph: bool = False,
        graph_depth: int = 1,
        graph_max_neighbors: int = 50,
    ) -> dict[str, Any]:
        """Parallel-fetch L1 + L2 sources, FSRS-rerank L2 memories, then
        char-budget each layer.

        Per-call budgets fall back to PALACE_CONTEXT_BUDGET_L1/L2_TOKENS
        env vars when None — operators tune defaults globally without
        every caller having to thread the values through.
        """
        l1_budget = (
            max_l1_chars if max_l1_chars is not None else context_budget_l1_chars()
        )
        l2_budget = (
            max_l2_chars if max_l2_chars is not None else context_budget_l2_chars()
        )

        # Parallel fetch all the source data.
        l1_mem_task = memory_service.search(
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            limit=memory_limit,
            tenant_id=tenant_id,
        )
        l1_recent_eps_task = episode_service.get_recent(
            user_id=user_id, limit=episode_limit, tenant_id=tenant_id,
        )
        l1_arcs_task = arc_service.get_active(
            user_id=user_id, limit=5, tenant_id=tenant_id,
        )
        l2_mem_task = memory_service.search(
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            limit=memory_limit * 2,
            tenant_id=tenant_id,
        )
        l2_eps_task = episode_service.search(
            query=query,
            user_id=user_id,
            limit=episode_limit,
            min_significance=min_episode_significance,
            tenant_id=tenant_id,
        )

        (
            l1_mem_results,
            l1_recent_eps,
            l1_arcs,
            l2_mem_results,
            l2_eps,
        ) = await asyncio.gather(
            l1_mem_task,
            l1_recent_eps_task,
            l1_arcs_task,
            l2_mem_task,
            l2_eps_task,
        )

        # L1 memories — straight semantic, no FSRS rerank (these are the "key
        # facts" for the user, sorted by raw similarity to the query).
        l1_memories = [_memory_to_dict(m, score) for m, score in l1_mem_results]

        # L2 memories — optionally FSRS-rerank by composite_score.
        l2_memories: list[dict[str, Any]] = []
        if use_fsrs:
            scored: list[dict[str, Any]] = []
            for m, semantic_score in l2_mem_results:
                breakdown = await dynamics_service.score(
                    memory_id=m.id,
                    user_id=user_id,
                    semantic_score=semantic_score,
                    tenant_id=tenant_id,
                )
                entry = _memory_to_dict(m, semantic_score)
                entry["composite_score"] = round(breakdown["composite_score"], 4)
                entry["fsrs_score"] = round(breakdown["fsrs_score"], 4)
                scored.append(entry)
            scored.sort(key=lambda e: e["composite_score"], reverse=True)
            l2_memories = scored
        else:
            l2_memories = [_memory_to_dict(m, score) for m, score in l2_mem_results]

        # Char-budget each layer.
        l1_kept, l1_chars = _enforce_char_budget(l1_memories, l1_budget)
        l2_kept, l2_chars = _enforce_char_budget(l2_memories, l2_budget)

        # Optional session messages.
        recent_messages: list[dict[str, Any]] | None = None
        summary: str | None = None
        if session_id:
            session_data = await session_service.get(session_id, tenant_id=tenant_id)
            if session_data:
                msgs = session_data.get("messages", [])
                if len(msgs) > max_recent_messages:
                    msgs = msgs[-max_recent_messages:]
                recent_messages = msgs
                summary = session_data.get("summary")

        # Phase 4 slice 6: optionally enrich with graph neighbors of L2 mems.
        l3_graph: dict[str, Any] | None = None
        if include_graph:
            l3_graph = await self._fetch_graph_context(
                memory_ids=[m["id"] for m in l2_kept if m.get("id")],
                tenant_id=tenant_id,
                depth=max(1, min(graph_depth, 2)),
                max_neighbors=max(1, min(graph_max_neighbors, 200)),
            )

        return {
            "l1_user_profile": {
                "memories": l1_kept,
                "recent_episodes": l1_recent_eps,
                "active_arcs": [_arc_to_dict(a) for a in l1_arcs],
            },
            "l2_relevant_context": {
                "memories": l2_kept,
                "episodes": l2_eps,
            },
            "l3_graph_context": l3_graph,
            "recent_messages": recent_messages,
            "summary": summary,
            "char_counts": {"l1": l1_chars, "l2": l2_chars},
        }

    async def _fetch_graph_context(
        self,
        memory_ids: list[str],
        tenant_id: str,
        depth: int,
        max_neighbors: int,
    ) -> dict[str, Any] | None:
        """Walk the graph from each L2 memory id, dedupe nodes/edges, cap.

        Returns ``None`` if the graph layer is disabled (so the API surface
        is "feature off" rather than "empty result"). Returns an empty dict
        if the graph is on but the L2 set has no recorded neighbors.
        """
        from mypalace.graph.service import graph_service
        if not graph_service.enabled or not memory_ids:
            return None

        seen_nodes: dict[str, dict[str, Any]] = {}
        all_edges: list[dict[str, Any]] = []
        for mid in memory_ids:
            if len(seen_nodes) >= max_neighbors:
                break
            try:
                neighborhood = await graph_service.neighbors(
                    node_id=mid, depth=depth, tenant_id=tenant_id,
                )
            except Exception:
                continue  # graph errors are enrichment-best-effort
            for node in neighborhood.get("nodes", []):
                nid = node.get("id")
                if nid and nid not in seen_nodes and nid not in memory_ids:
                    # Skip nodes we already returned in L2.
                    seen_nodes[nid] = node
                    if len(seen_nodes) >= max_neighbors:
                        break
            all_edges.extend(neighborhood.get("edges", []))
        return {
            "related_memories": list(seen_nodes.values()),
            "edges": all_edges,
        }


# Singleton
layered_retrieval_service = LayeredRetrievalService()
