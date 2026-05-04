"""Episode storage + LLM-driven reflection service.

Episodes live Qdrant-only (no Postgres table) per design D3. Each Episode is
one Qdrant point in the `palace_episodes` collection: vector = embedding of
`content`; payload = all other fields.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    Range,
)

from palace._llm_utils import strip_json_fences
from palace.embeddings import EmbeddingProvider, get_embedder
from palace.llm import llm
from palace.models import DEFAULT_TENANT_ID
from palace.prompts.reflection import SESSION_REFLECTION_PROMPT
from palace.vector import episode_vector_store


class EpisodeService:
    """Business logic for episode storage and retrieval."""

    def __init__(self) -> None:
        self._embedder: EmbeddingProvider | None = None

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    async def init(self, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Ensure Qdrant collection + payload indexes exist for ``tenant_id``."""
        await episode_vector_store.ensure_collection(self.embedder.dim, tenant_id=tenant_id)
        await episode_vector_store.ensure_payload_indexes({
            "user_id": "keyword",
            "agent_id": "keyword",
            "tenant_id": "keyword",
            "significance": "float",
            "timestamp": "datetime",
        }, tenant_id=tenant_id)

    async def reflect_session(
        self,
        messages: list[dict],
        user_id: str,
        agent_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict]:
        """Call the LLM, parse extracted episodes, write each to Qdrant.
        Returns the list of episodes (as dicts) that were written.

        Raises ValueError if the LLM returns malformed JSON."""
        conversation_text = "\n".join(
            f"[{i}] {m['role']}: {m['content']}" for i, m in enumerate(messages)
        )
        prompt = SESSION_REFLECTION_PROMPT.format(conversation_text=conversation_text)

        raw = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )

        try:
            parsed = json.loads(strip_json_fences(raw))
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned non-JSON for reflection: {e}") from e

        extracted = parsed.get("episodes", [])
        if not isinstance(extracted, list):
            raise ValueError(f"LLM returned non-list 'episodes' field: {type(extracted).__name__}")

        now = datetime.now(UTC)
        episodes: list[dict] = []

        for raw_ep in extracted:
            start = raw_ep.get("start_index", 0)
            end = raw_ep.get("end_index", len(messages) - 1)
            content_slice = messages[start : end + 1]
            content = "\n".join(f"{m['role']}: {m['content']}" for m in content_slice)

            participants = sorted({m.get("role", "user") for m in content_slice})

            ep = {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "content": content,
                "summary": raw_ep.get("summary", ""),
                "participants": participants,
                "topics": raw_ep.get("topics", []),
                "emotional_tone": raw_ep.get("emotional_tone", "neutral"),
                "significance": float(raw_ep.get("significance", 0.5)),
                "timestamp": now.isoformat(),
                "session_id": session_id,
                "message_count": len(content_slice),
            }

            # Embed content and upsert into Qdrant
            vectors = await self.embedder.embed([content])
            await episode_vector_store.upsert(
                memory_id=ep["id"],
                vector=vectors[0],
                payload={k: v for k, v in ep.items() if k != "id"},
                tenant_id=tenant_id,
            )
            episodes.append(ep)

        # Phase 5 slice 1: publish episode.created per written episode.
        from palace.events.broker import broker
        for ep in episodes:
            await broker.publish("episode.created", tenant_id, {
                "episode_id": ep["id"],
                "user_id": ep["user_id"],
                "summary": ep["summary"],
                "significance": ep["significance"],
                "session_id": ep.get("session_id"),
            })

        return episodes

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
        min_significance: float = 0.0,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict]:
        """Semantic search over episodes. Filters: user_id (required),
        significance >= min_significance."""
        vectors = await self.embedder.embed([query])

        conditions: list[Any] = [
            FieldCondition(key="user_id", match=MatchValue(value=user_id)),
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
        ]
        if min_significance > 0.0:
            conditions.append(
                FieldCondition(key="significance", range=Range(gte=min_significance)),
            )

        response = await episode_vector_store.client.query_points(
            collection_name=episode_vector_store.collection,
            query=vectors[0],
            limit=limit,
            query_filter=Filter(must=conditions),
            with_payload=True,
        )

        results: list[dict] = []
        for point in response.points:
            payload = dict(point.payload or {})
            payload["id"] = point.id
            payload["score"] = point.score
            results.append(payload)
        return results

    async def get_recent(
        self,
        user_id: str,
        limit: int = 5,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[dict]:
        """Recent episodes for a user, newest first."""
        # Qdrant scroll with payload filter; we sort client-side because OrderBy
        # on a payload field has uneven version support.
        points, _ = await episode_vector_store.client.scroll(
            collection_name=episode_vector_store.collection,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                ],
            ),
            limit=max(limit * 4, 50),  # over-fetch since we sort client-side
            with_payload=True,
            with_vectors=False,
        )
        items = []
        for p in points:
            payload = dict(p.payload or {})
            payload["id"] = p.id
            items.append(payload)

        # Sort by timestamp desc (timestamps are ISO strings, lex order works for tz-aware ISO)
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items[:limit]


# Singleton
episode_service = EpisodeService()
