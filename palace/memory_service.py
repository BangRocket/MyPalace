"""Memory CRUD and semantic search service."""

import json

from sqlalchemy import desc, select

from palace.database import async_session
from palace.embeddings import EmbeddingProvider, get_embedder
from palace.models import Memory, utcnow
from palace.vector import vector_store


class MemoryService:
    """Business logic for memory storage and retrieval."""

    def __init__(self) -> None:
        self._embedder: EmbeddingProvider | None = None

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    async def init(self) -> None:
        """Initialize vector collection. Call on startup."""
        await vector_store.ensure_collection(self.embedder.dim)

    async def create(
        self,
        user_id: str,
        content: str,
        memory_type: str = "semantic",
        agent_id: str | None = None,
        source: str | None = None,
        importance: float = 1.0,
        metadata: dict | None = None,
    ) -> Memory:
        """Create a memory: embed, store in PG, store vector in Qdrant."""
        async with async_session() as db:
            memory = Memory(
                user_id=user_id,
                content=content,
                memory_type=memory_type,
                agent_id=agent_id,
                source=source,
                importance=importance,
                metadata_json=json.dumps(metadata) if metadata else None,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(memory)
            await db.commit()
            await db.refresh(memory)

        # Embed and store in Qdrant (outside PG transaction)
        vectors = await self.embedder.embed([content])
        await vector_store.upsert(
            memory.id,
            vectors[0],
            {"user_id": user_id, "agent_id": agent_id, "memory_type": memory_type},
        )
        return memory

    async def get(self, memory_id: str) -> Memory | None:
        """Fetch a memory by ID and bump its access counter."""
        async with async_session() as db:
            result = await db.execute(select(Memory).where(Memory.id == memory_id))
            memory = result.scalar_one_or_none()
            if memory:
                memory.access_count += 1
                memory.accessed_at = utcnow()
                await db.commit()
            return memory

    async def update(
        self,
        memory_id: str,
        content: str | None = None,
        memory_type: str | None = None,
        importance: float | None = None,
        metadata: dict | None = None,
    ) -> Memory | None:
        """Update a memory. Re-embeds if content changes."""
        async with async_session() as db:
            result = await db.execute(select(Memory).where(Memory.id == memory_id))
            memory = result.scalar_one_or_none()
            if not memory:
                return None

            if content is not None:
                memory.content = content
                vectors = await self.embedder.embed([content])
                await vector_store.upsert(
                    memory.id,
                    vectors[0],
                    {
                        "user_id": memory.user_id,
                        "agent_id": memory.agent_id,
                        "memory_type": memory.memory_type,
                    },
                )
            if memory_type is not None:
                memory.memory_type = memory_type
            if importance is not None:
                memory.importance = importance
            if metadata is not None:
                memory.metadata_json = json.dumps(metadata)
            memory.updated_at = utcnow()
            await db.commit()
            return memory

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory from both PG and Qdrant."""
        async with async_session() as db:
            result = await db.execute(select(Memory).where(Memory.id == memory_id))
            memory = result.scalar_one_or_none()
            if not memory:
                return False
            await db.delete(memory)
            await db.commit()

        await vector_store.delete(memory_id)
        return True

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[tuple[Memory, float]]:
        """Semantic search: embed query, search Qdrant, fetch PG records."""
        vectors = await self.embedder.embed([query])
        results = await vector_store.search(
            vectors[0],
            limit=limit,
            user_id=user_id,
            agent_id=agent_id,
            memory_type=memory_type,
            min_score=min_score,
        )
        if not results:
            return []

        memory_ids = [r[0] for r in results]
        scores = {r[0]: r[1] for r in results}

        async with async_session() as db:
            result = await db.execute(select(Memory).where(Memory.id.in_(memory_ids)))
            memories = result.scalars().all()

            for m in memories:
                m.access_count += 1
                m.accessed_at = utcnow()
            await db.commit()

        memory_map = {m.id: m for m in memories}
        return [(memory_map[mid], scores[mid]) for mid in memory_ids if mid in memory_map]

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[Memory]:
        """List a user's memories by recency."""
        async with async_session() as db:
            result = await db.execute(
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(desc(Memory.created_at))
                .limit(limit),
            )
            return list(result.scalars().all())


# Singleton
memory_service = MemoryService()
