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

from palace.arc_service import arc_service
from palace.dynamics.service import dynamics_service
from palace.episode_service import episode_service
from palace.memory_service import memory_service
from palace.session_service import session_service


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
        max_l1_chars: int = 3200,
        max_l2_chars: int = 12000,
        max_recent_messages: int = 20,
        use_fsrs: bool = True,
        memory_limit: int = 10,
        episode_limit: int = 5,
        min_episode_significance: float = 0.3,
    ) -> dict[str, Any]:
        """Parallel-fetch L1 + L2 sources, FSRS-rerank L2 memories, then
        char-budget each layer."""

        # Parallel fetch all the source data.
        l1_mem_task = memory_service.search(
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            limit=memory_limit,
        )
        l1_recent_eps_task = episode_service.get_recent(
            user_id=user_id, limit=episode_limit,
        )
        l1_arcs_task = arc_service.get_active(user_id=user_id, limit=5)
        l2_mem_task = memory_service.search(
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            limit=memory_limit * 2,
        )
        l2_eps_task = episode_service.search(
            query=query,
            user_id=user_id,
            limit=episode_limit,
            min_significance=min_episode_significance,
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
                    memory_id=m.id, user_id=user_id, semantic_score=semantic_score,
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
        l1_kept, l1_chars = _enforce_char_budget(l1_memories, max_l1_chars)
        l2_kept, l2_chars = _enforce_char_budget(l2_memories, max_l2_chars)

        # Optional session messages.
        recent_messages: list[dict[str, Any]] | None = None
        summary: str | None = None
        if session_id:
            session_data = await session_service.get(session_id)
            if session_data:
                msgs = session_data.get("messages", [])
                if len(msgs) > max_recent_messages:
                    msgs = msgs[-max_recent_messages:]
                recent_messages = msgs
                summary = session_data.get("summary")

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
            "recent_messages": recent_messages,
            "summary": summary,
            "char_counts": {"l1": l1_chars, "l2": l2_chars},
        }


# Singleton
layered_retrieval_service = LayeredRetrievalService()
