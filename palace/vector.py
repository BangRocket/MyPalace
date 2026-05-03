"""Qdrant vector store wrapper."""

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from palace.config import settings


class VectorStore:
    """Async Qdrant vector store for memory embeddings."""

    def __init__(self) -> None:
        self.client = AsyncQdrantClient(url=settings.qdrant_url)
        self.collection = settings.qdrant_collection
        self._dim: int | None = None

    async def ensure_collection(self, dim: int) -> None:
        """Create collection if it doesn't exist."""
        self._dim = dim
        collections = await self.client.get_collections()
        names = [c.name for c in collections.collections]
        if self.collection not in names:
            await self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    async def upsert(self, memory_id: str, vector: list[float], payload: dict) -> None:
        """Store or update a vector."""
        await self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=memory_id, vector=vector, payload=payload)],
        )

    async def search(
        self,
        vector: list[float],
        limit: int = 10,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: str | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[str, float]]:
        """Semantic search with optional filters. Returns [(memory_id, score)]."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        conditions = []
        if user_id:
            conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))
        if agent_id:
            conditions.append(FieldCondition(key="agent_id", match=MatchValue(value=agent_id)))
        if memory_type:
            conditions.append(
                FieldCondition(key="memory_type", match=MatchValue(value=memory_type)),
            )

        results = await self.client.search(
            collection_name=self.collection,
            query_vector=vector,
            limit=limit,
            query_filter=Filter(must=conditions) if conditions else None,
            score_threshold=min_score,
        )
        return [(r.id, r.score) for r in results]

    async def delete(self, memory_id: str) -> None:
        """Remove a vector by memory ID."""
        await self.client.delete(
            collection_name=self.collection,
            points_selector=[memory_id],
        )


# Singleton
vector_store = VectorStore()
