"""Qdrant vector store wrapper with per-tenant collection support."""

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from palace.config import settings
from palace.models import DEFAULT_TENANT_ID


class VectorStore:
    """Async Qdrant vector store wrapper.

    Phase 3 slice 2: each tenant gets its own collection
    (`{base_collection}_{tenant_id}`). The base collection name still comes
    from settings; tenant_id is appended. ``ensure_collection`` is per-tenant
    lazy — call it once per (dim, tenant_id) pair.
    """

    def __init__(self, base_collection: str | None = None) -> None:
        self.client = AsyncQdrantClient(url=settings.qdrant_url)
        self.base_collection = base_collection or settings.qdrant_collection
        self._ensured: set[str] = set()
        self._dim: int | None = None

    @property
    def collection(self) -> str:
        """Backwards-compatible default collection (default tenant).

        Used by integration test cleanup that drops the singleton's collection.
        Most call paths should use ``self._collection_for(tenant_id)``.
        """
        return self._collection_for(settings.default_tenant_id)

    def _collection_for(self, tenant_id: str) -> str:
        return f"{self.base_collection}_{tenant_id}"

    async def ensure_collection(
        self, dim: int, tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Create the per-tenant collection if it doesn't already exist."""
        self._dim = dim
        coll = self._collection_for(tenant_id)
        if coll in self._ensured:
            return
        collections = await self.client.get_collections()
        names = [c.name for c in collections.collections]
        if coll not in names:
            await self.client.create_collection(
                collection_name=coll,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        self._ensured.add(coll)

    async def upsert(
        self,
        memory_id: str,
        vector: list[float],
        payload: dict,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Store or update a vector under ``tenant_id``.

        Lazily ensures the collection on first write so callers don't have
        to remember per-tenant init.
        """
        if self._dim is not None:
            await self.ensure_collection(self._dim, tenant_id)
        # Always include tenant_id in payload for defense-in-depth queries.
        payload = {**payload, "tenant_id": tenant_id}
        await self.client.upsert(
            collection_name=self._collection_for(tenant_id),
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
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[tuple[str, float]]:
        """Semantic search inside ``tenant_id``'s collection."""
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
        # Belt + suspenders: filter by tenant_id even though the collection
        # is per-tenant. Catches accidentally-cross-tenant payloads.
        conditions.append(FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)))

        coll = self._collection_for(tenant_id)
        if coll not in self._ensured:
            # Empty collection / no vectors yet for this tenant.
            try:
                response = await self.client.query_points(
                    collection_name=coll,
                    query=vector,
                    limit=limit,
                    query_filter=Filter(must=conditions),
                    score_threshold=min_score,
                )
            except Exception:
                return []
        else:
            response = await self.client.query_points(
                collection_name=coll,
                query=vector,
                limit=limit,
                query_filter=Filter(must=conditions),
                score_threshold=min_score,
            )
        return [(p.id, p.score) for p in response.points]

    async def delete(
        self,
        memory_id: str | list[str],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Remove a vector (or batch) from a tenant's collection."""
        ids = [memory_id] if isinstance(memory_id, str) else memory_id
        if not ids:
            return
        await self.client.delete(
            collection_name=self._collection_for(tenant_id),
            points_selector=ids,
        )

    async def ensure_payload_indexes(
        self,
        indexes: dict[str, str],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Create payload indexes for a tenant's collection. Idempotent."""
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
                await self.client.create_payload_index(
                    collection_name=self._collection_for(tenant_id),
                    field_name=field,
                    field_schema=type_map[typ],
                )


# Singletons — one for memories, one for episodes.
vector_store = VectorStore()
episode_vector_store = VectorStore(base_collection="palace_episodes")
