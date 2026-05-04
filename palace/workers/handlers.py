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
    from palace.episode_service import episode_service
    return await episode_service.reflect_session(
        messages=payload["messages"],
        user_id=payload["user_id"],
        agent_id=payload.get("agent_id"),
        session_id=payload.get("session_id"),
        tenant_id=tenant_id,
    )


async def _synthesis_handler(payload: dict, tenant_id: str) -> Any:
    """Run an ArcService narrative synthesis from a serialized payload."""
    from palace.arc_service import arc_service
    return await arc_service.synthesize_narratives(
        user_id=payload["user_id"],
        agent_id=payload.get("agent_id"),
        lookback_episodes=payload.get("lookback_episodes", 20),
        tenant_id=tenant_id,
    )


async def _cleanup_handler(payload: dict, tenant_id: str) -> Any:
    """Phase 6 slice 3: delete memories whose TTL has elapsed."""
    from palace.memory_service import memory_service
    deleted = await memory_service.cleanup_expired(
        tenant_id=tenant_id,
        batch_size=payload.get("batch_size", 500),
    )
    return {"tenant_id": tenant_id, "deleted": deleted}


# Built-in handlers wired at import time.
register_handler("reflection", _reflection_handler)
register_handler("synthesis", _synthesis_handler)
register_handler("cleanup", _cleanup_handler)
