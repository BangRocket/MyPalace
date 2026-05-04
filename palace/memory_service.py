"""Memory CRUD and semantic search service."""

from sqlalchemy import and_, desc, select
from sqlalchemy import delete as sa_delete

from palace.database import async_session
from palace.embeddings import EmbeddingProvider, get_embedder
from palace.models import DEFAULT_TENANT_ID, Memory, utcnow
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

    async def init(self, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Initialize vector collection for ``tenant_id``. Per-tenant
        collections are also created lazily on first upsert."""
        await vector_store.ensure_collection(self.embedder.dim, tenant_id=tenant_id)

    async def create(
        self,
        user_id: str,
        content: str,
        memory_type: str = "semantic",
        agent_id: str | None = None,
        source: str | None = None,
        importance: float = 1.0,
        metadata: dict | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Memory:
        """Create a memory: embed, store in PG, store vector in Qdrant."""
        async with async_session() as db:
            memory = Memory(
                tenant_id=tenant_id,
                user_id=user_id,
                content=content,
                memory_type=memory_type,
                agent_id=agent_id,
                source=source,
                importance=importance,
                metadata_json=metadata,
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
            tenant_id=tenant_id,
        )

        # Phase 3 slice 3: fire-and-forget graph upsert.
        from palace.graph.service import graph_service
        graph_service.schedule(graph_service.upsert_memory_node(
            memory_id=memory.id,
            user_id=user_id,
            agent_id=agent_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            tenant_id=tenant_id,
        ))

        # Phase 3 slice 4: bust cached search/context entries for this tenant.
        await self._bust_cache(tenant_id)
        # Phase 4 slice 5: publish memory.created event.
        await self._publish_event("memory.created", tenant_id, {
            "memory_id": memory.id, "user_id": user_id,
            "agent_id": agent_id, "memory_type": memory_type,
        })
        return memory

    @staticmethod
    async def _bust_cache(tenant_id: str) -> None:
        from palace.cache.client import cache as _cache
        if not _cache.enabled:
            return
        for ns in ("memories_search", "context_layered"):
            await _cache.invalidate_tenant_namespace(tenant_id, ns)

    @staticmethod
    async def _publish_event(event_type: str, tenant_id: str, payload: dict) -> None:
        from palace.events.broker import broker
        await broker.publish(event_type, tenant_id, payload)

    async def create_batch(
        self,
        user_id: str,
        messages: list[dict],
        agent_id: str | None = None,
        memory_type: str = "episodic",
        metadata: dict | None = None,
        source: str | None = None,
        infer: bool = False,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> dict:
        """Batch-create memories.

        ``infer=False`` (default): one memory per message, verbatim. Per-message
        keys (other than 'content') merge into metadata, with per-message keys
        winning over request-level metadata on key collision.

        ``infer=True`` (slice 5): runs the smart-ingestion pipeline — LLM
        extraction + vector dedup + heuristic supersede.

        Returns a dict ``{"memories": [...], "supersessions": [...],
        "skipped": [...]}``. Caller flattens as appropriate.
        """
        base_metadata = metadata or {}

        if infer:
            # Lazy import to avoid circular dependency at module load.
            from palace.retrieval.ingestion import smart_ingestion_service

            candidates = await smart_ingestion_service.extract_memories(
                messages=messages,
                user_id=user_id,
                agent_id=agent_id,
                tenant_id=tenant_id,
            )
            written, supersessions, skipped = await smart_ingestion_service.dedup_and_write(
                candidates=candidates,
                user_id=user_id,
                agent_id=agent_id,
                memory_type=memory_type,
                source=source,
                base_metadata=base_metadata,
                tenant_id=tenant_id,
            )
            return {
                "memories": written,
                "supersessions": supersessions,
                "skipped": skipped,
            }

        results: list[Memory] = []
        for msg in messages:
            content = msg["content"]
            extra = {k: v for k, v in msg.items() if k != "content"}
            merged = {**base_metadata, **extra}
            mem = await self.create(
                user_id=user_id,
                content=content,
                memory_type=memory_type,
                agent_id=agent_id,
                source=source,
                importance=1.0,
                metadata=merged or None,
                tenant_id=tenant_id,
            )
            results.append(mem)
        return {"memories": results, "supersessions": [], "skipped": []}

    async def get(
        self,
        memory_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Memory | None:
        """Fetch a memory by ID and bump its access counter."""
        async with async_session() as db:
            result = await db.execute(
                select(Memory).where(
                    Memory.id == memory_id,
                    Memory.tenant_id == tenant_id,
                ),
            )
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
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> Memory | None:
        """Update a memory. Re-embeds if content changes."""
        async with async_session() as db:
            result = await db.execute(
                select(Memory).where(
                    Memory.id == memory_id,
                    Memory.tenant_id == tenant_id,
                ),
            )
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
                    tenant_id=tenant_id,
                )
            if memory_type is not None:
                memory.memory_type = memory_type
            if importance is not None:
                memory.importance = importance
            if metadata is not None:
                memory.metadata_json = metadata
            memory.updated_at = utcnow()
            await db.commit()
        await self._bust_cache(tenant_id)
        await self._publish_event("memory.updated", tenant_id, {
            "memory_id": memory_id, "user_id": memory.user_id,
        })
        return memory

    async def delete(
        self,
        memory_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> bool:
        """Delete a memory from both PG and Qdrant."""
        async with async_session() as db:
            result = await db.execute(
                select(Memory).where(
                    Memory.id == memory_id,
                    Memory.tenant_id == tenant_id,
                ),
            )
            memory = result.scalar_one_or_none()
            if not memory:
                return False
            await db.delete(memory)
            await db.commit()

        await vector_store.delete(memory_id, tenant_id=tenant_id)
        await self._bust_cache(tenant_id)
        await self._publish_event("memory.deleted", tenant_id, {
            "memory_id": memory_id,
        })
        return True

    async def delete_for_user(
        self,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> int:
        """Delete all memories for a user (optionally filtered by agent/run).
        Removes from postgres AND from Qdrant. Returns count deleted."""
        clauses = [
            Memory.tenant_id == tenant_id,
            Memory.user_id == user_id,
        ]
        if agent_id is not None:
            clauses.append(Memory.agent_id == agent_id)
        if run_id is not None:
            clauses.append(Memory.metadata_json.op("@>")({"run_id": run_id}))

        async with async_session() as db:
            stmt = sa_delete(Memory).where(and_(*clauses)).returning(Memory.id)
            result = await db.execute(stmt)
            ids = [row[0] for row in result.all()]
            await db.commit()

        # Remove vectors in batches of 500
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            if chunk:
                await vector_store.delete(chunk, tenant_id=tenant_id)
        await self._bust_cache(tenant_id)
        return len(ids)

    async def search(
        self,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
        tenant_id: str = DEFAULT_TENANT_ID,
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
            tenant_id=tenant_id,
        )
        if not results:
            return []

        memory_ids = [r[0] for r in results]
        scores = {r[0]: r[1] for r in results}

        async with async_session() as db:
            result = await db.execute(
                select(Memory).where(
                    Memory.id.in_(memory_ids),
                    Memory.tenant_id == tenant_id,
                ),
            )
            memories = result.scalars().all()

            for m in memories:
                m.access_count += 1
                m.accessed_at = utcnow()
            await db.commit()

        memory_map = {m.id: m for m in memories}
        return [(memory_map[mid], scores[mid]) for mid in memory_ids if mid in memory_map]

    async def list_for_user(
        self,
        user_id: str,
        limit: int = 50,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[Memory]:
        """List a user's memories by recency."""
        async with async_session() as db:
            result = await db.execute(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.tenant_id == tenant_id,
                )
                .order_by(desc(Memory.created_at))
                .limit(limit),
            )
            return list(result.scalars().all())

    async def list_filtered(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        memory_type: str | None = None,
        metadata: dict | None = None,
        limit: int = 50,
        offset: int = 0,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[Memory]:
        """List memories with filters. Metadata matching uses JSONB
        containment (`@>`)."""
        clauses = [Memory.tenant_id == tenant_id]
        if user_id is not None:
            clauses.append(Memory.user_id == user_id)
        if agent_id is not None:
            clauses.append(Memory.agent_id == agent_id)
        if memory_type is not None:
            clauses.append(Memory.memory_type == memory_type)
        if run_id is not None:
            clauses.append(Memory.metadata_json.op("@>")({"run_id": run_id}))
        if metadata:
            clauses.append(Memory.metadata_json.op("@>")(metadata))

        stmt = select(Memory).where(and_(*clauses))
        stmt = stmt.order_by(desc(Memory.created_at)).limit(limit).offset(offset)

        async with async_session() as db:
            result = await db.execute(stmt)
            return list(result.scalars().all())


# Singleton
memory_service = MemoryService()
