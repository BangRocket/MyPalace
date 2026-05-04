"""Qdrant vector store wrapper."""

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from palace.config import settings


class VectorStore:
    """Async Qdrant vector store wrapper."""

    def __init__(self, collection: str | None = None) -> None:
        self.client = AsyncQdrantClient(url=settings.qdrant_url)
        self.collection = collection or settings.qdrant_collection
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

        response = await self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            query_filter=Filter(must=conditions) if conditions else None,
            score_threshold=min_score,
        )
        return [(p.id, p.score) for p in response.points]

    async def delete(self, memory_id: str | list[str]) -> None:
        """Remove a vector (or batch of vectors) by memory ID(s)."""
        ids = [memory_id] if isinstance(memory_id, str) else memory_id
        if not ids:
            return
        await self.client.delete(
            collection_name=self.collection,
            points_selector=ids,
        )

    async def ensure_payload_indexes(self, indexes: dict[str, str]) -> None:
        """Create payload indexes if they don't exist.
        indexes maps field name -> qdrant field type (e.g. 'keyword', 'float', 'datetime').
        Idempotent — Qdrant raises if the index exists, we swallow that case."""
        import contextlib

        from qdrant_client.http import models as qmodels

        type_map = {
            "keyword": qmodels.PayloadSchemaType.KEYWORD,
            "float": qmodels.PayloadSchemaType.FLOAT,
            "integer": qmodels.PayloadSchemaType.INTEGER,
            "datetime": qmodels.PayloadSchemaType.DATETIME,
        }
        for field, typ in indexes.items():
            with contextlib.suppress(Exception):
                # Already exists — Qdrant raises 4xx; safe to ignore.
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=type_map[typ],
                )


# Singletons — one for memories (the default collection), one for episodes
vector_store = VectorStore()
episode_vector_store = VectorStore(collection="palace_episodes")
