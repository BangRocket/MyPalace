"""Episode storage + LLM-driven reflection service.

Episodes live Qdrant-only (no Postgres table) per design D3. Each Episode is
one Qdrant point in the `palace_episodes` collection: vector = embedding of
`content`; payload = all other fields.
"""

from __future__ import annotations

from palace.embeddings import EmbeddingProvider, get_embedder
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

    async def init(self) -> None:
        """Ensure Qdrant collection + payload indexes exist."""
        await episode_vector_store.ensure_collection(self.embedder.dim)
        await episode_vector_store.ensure_payload_indexes({
            "user_id": "keyword",
            "agent_id": "keyword",
            "significance": "float",
            "timestamp": "datetime",
        })

    # reflect_session, search, get_recent — implemented in Task 4


# Singleton
episode_service = EpisodeService()
