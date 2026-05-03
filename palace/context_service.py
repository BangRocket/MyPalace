"""Context assembly service — builds prompt context from memories + messages."""

from palace.memory_service import memory_service
from palace.session_service import session_service


class ContextService:
    """Assemble LLM prompt context from relevant memories and recent messages."""

    async def assemble(
        self,
        user_id: str,
        query: str,
        session_id: str | None = None,
        max_memories: int = 10,
        max_messages: int = 20,
    ) -> dict:
        """Build context: semantic memory search + recent session messages."""
        memory_results = await memory_service.search(
            query=query,
            user_id=user_id,
            limit=max_memories,
        )
        memories = [
            {
                "id": m.id,
                "content": m.content,
                "memory_type": m.memory_type,
                "importance": m.importance,
                "score": round(score, 4),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m, score in memory_results
        ]

        messages = []
        summary = None
        if session_id:
            session_data = await session_service.get(session_id)
            if session_data:
                msgs = session_data.get("messages", [])
                messages = msgs[-max_messages:] if len(msgs) > max_messages else msgs
                summary = session_data.get("summary")

        return {
            "memories": memories,
            "recent_messages": messages,
            "summary": summary,
        }


# Singleton
context_service = ContextService()
