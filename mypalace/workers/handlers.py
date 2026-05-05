"""Job-kind → handler registry.

Each handler is an async function ``(payload: dict, tenant_id: str) -> dict |
list``. The handler receives the JSON-deserialized payload that the caller
passed to ``enqueue``. The return value is stored in ``result_json``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[[dict, str], Awaitable[Any]]
HANDLER_REGISTRY: dict[str, Handler] = {}


def register_handler(kind: str, handler: Handler) -> None:
    """Idempotent. Last writer wins (useful for tests overriding handlers)."""
    if kind in HANDLER_REGISTRY:
        logger.info("worker handler %r overridden", kind)
    HANDLER_REGISTRY[kind] = handler


async def _reflection_handler(payload: dict, tenant_id: str) -> Any:
    """Run an EpisodeService reflection from a serialized payload."""
    from mypalace.episode_service import episode_service
    return await episode_service.reflect_session(
        messages=payload["messages"],
        user_id=payload["user_id"],
        agent_id=payload.get("agent_id"),
        session_id=payload.get("session_id"),
        tenant_id=tenant_id,
    )


async def _synthesis_handler(payload: dict, tenant_id: str) -> Any:
    """Run an ArcService narrative synthesis from a serialized payload."""
    from mypalace.arc_service import arc_service
    return await arc_service.synthesize_narratives(
        user_id=payload["user_id"],
        agent_id=payload.get("agent_id"),
        lookback_episodes=payload.get("lookback_episodes", 20),
        tenant_id=tenant_id,
    )


async def _cleanup_handler(payload: dict, tenant_id: str) -> Any:
    """Phase 6 slice 3: delete memories whose TTL has elapsed."""
    from mypalace.memory_service import memory_service
    deleted = await memory_service.cleanup_expired(
        tenant_id=tenant_id,
        batch_size=payload.get("batch_size", 500),
    )
    return {"tenant_id": tenant_id, "deleted": deleted}


async def _reembed_handler(payload: dict, tenant_id: str) -> Any:
    """Phase 6 slice 4: re-embed every memory in a tenant under a new model.

    Payload:
      provider: "openai" | "huggingface" (default: huggingface)
      model:    str (required)
      token:    str | None (HF auth token / OpenAI key)
      batch_size: int (default 100)
    """
    from sqlalchemy import select

    from mypalace.database import async_session
    from mypalace.embeddings import make_embedder
    from mypalace.models import Memory
    from mypalace.vector import vector_store

    log = logging.getLogger("mypalace.workers.reembed")
    provider = payload.get("provider", "huggingface")
    model = payload["model"]
    token = payload.get("token")
    batch_size = int(payload.get("batch_size", 100))

    embedder = make_embedder(provider, model, token)
    new_dim = embedder.dim

    # Ensure the per-tenant collection exists at the new dim. If the dim
    # changed from a previous embedding, this writes alongside the old
    # vectors — operators should drop the old collection out-of-band when
    # ready to fully cut over.
    await vector_store.ensure_collection(new_dim, tenant_id=tenant_id)

    total = 0
    failures = 0
    async with async_session() as db:
        offset = 0
        while True:
            stmt = (
                select(Memory)
                .where(Memory.tenant_id == tenant_id)
                .order_by(Memory.id)
                .limit(batch_size)
                .offset(offset)
            )
            result = await db.execute(stmt)
            batch = list(result.scalars().all())
            if not batch:
                break

            try:
                vectors = await embedder.embed([m.content for m in batch])
            except Exception:
                failures += len(batch)
                log.exception(
                    "embedding batch failed (offset=%d, size=%d)",
                    offset, len(batch),
                )
                offset += batch_size
                continue

            for m, vec in zip(batch, vectors, strict=False):
                try:
                    await vector_store.upsert(
                        m.id,
                        vec,
                        {
                            "user_id": m.user_id,
                            "agent_id": m.agent_id,
                            "memory_type": m.memory_type,
                        },
                        tenant_id=tenant_id,
                    )
                    total += 1
                except Exception:
                    failures += 1
                    log.warning("upsert failed for memory_id=%s", m.id, exc_info=True)
            offset += batch_size

    return {
        "tenant_id": tenant_id,
        "provider": provider,
        "model": model,
        "reembedded": total,
        "failures": failures,
        "new_dim": new_dim,
    }


async def _personality_evolve_handler(payload: dict, tenant_id: str) -> Any:
    """Phase 10 slice 2: LLM-driven personality evolution."""
    from mypalace.personality_service import DEFAULT_AGENT_ID, personality_service
    return await personality_service.evaluate_and_apply(
        user_message=payload["user_message"],
        assistant_reply=payload["assistant_reply"],
        agent_id=payload.get("agent_id", DEFAULT_AGENT_ID),
        tenant_id=tenant_id,
    )


# Built-in handlers wired at import time.
register_handler("reflection", _reflection_handler)
register_handler("synthesis", _synthesis_handler)
register_handler("cleanup", _cleanup_handler)
register_handler("reembed", _reembed_handler)
register_handler("personality_evolve", _personality_evolve_handler)
