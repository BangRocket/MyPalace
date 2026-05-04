"""Event broker — Redis pub/sub when configured, in-process fallback otherwise.

Channel layout: ``palace:events:<tenant_id>``. The websocket handler subscribes
to exactly the tenant the client's API key is bound to (cross-tenant admins
get the channel they explicitly requested).

If Redis is unavailable, the broker falls back to a per-process pubsub
(useful for tests and single-process dev). Cross-process delivery requires
Redis.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from palace.config import settings
from palace.models import utcnow

logger = logging.getLogger(__name__)


def _channel(tenant_id: str) -> str:
    return f"palace:events:{tenant_id}"


class EventBroker:
    """Lazy Redis client + in-process subscriber registry."""

    def __init__(self) -> None:
        self._redis: Any = None
        # tenant_id → list of asyncio.Queue (one per connected subscriber)
        self._inproc: dict[str, list[asyncio.Queue]] = {}

    @property
    def redis_enabled(self) -> bool:
        return bool(settings.redis_url)

    async def _get_redis(self):
        if self._redis is None and self.redis_enabled:
            try:
                import redis.asyncio as redis_async
            except ImportError:
                return None
            self._redis = redis_async.from_url(
                settings.redis_url, decode_responses=True,
            )
        return self._redis

    async def publish(
        self,
        event_type: str,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Fire-and-forget: publish to Redis if configured, otherwise to
        in-process subscribers. Failures log + return — never crash the
        write path that triggered the event."""
        envelope = {
            "type": event_type,
            "tenant_id": tenant_id,
            "payload": payload,
            "occurred_at": utcnow().isoformat(),
        }
        body = json.dumps(envelope, default=str)

        # Always notify in-process subscribers (covers tests + single-process).
        for queue in list(self._inproc.get(tenant_id, [])):
            try:
                queue.put_nowait(body)
            except asyncio.QueueFull:
                # Slow subscriber — drop the event. At-most-once delivery.
                logger.warning("event subscriber queue full; dropping event")

        # Multi-process: also publish to Redis.
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.publish(_channel(tenant_id), body)
            except Exception:
                logger.warning(
                    "event publish to Redis failed for tenant=%s", tenant_id,
                    exc_info=True,
                )

    @asynccontextmanager
    async def subscribe(self, tenant_id: str) -> AsyncIterator[asyncio.Queue]:
        """Yield a queue that will receive every JSON envelope (str) published
        for the given tenant. Cleans up on exit."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._inproc.setdefault(tenant_id, []).append(queue)

        # If Redis is configured, also start a pubsub task that forwards
        # remote events into the same queue.
        forward_task: asyncio.Task | None = None
        redis = await self._get_redis()
        if redis is not None:
            forward_task = asyncio.create_task(
                self._forward_redis(redis, tenant_id, queue),
            )

        try:
            yield queue
        finally:
            self._inproc.get(tenant_id, []).remove(queue)
            if forward_task is not None:
                forward_task.cancel()
                with _suppress_cancelled():
                    await forward_task

    async def _forward_redis(self, redis, tenant_id: str, queue: asyncio.Queue) -> None:
        """Subscribe to the tenant's Redis channel, forward messages into queue."""
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(_channel(tenant_id))
            try:
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", errors="replace")
                    try:
                        queue.put_nowait(data)
                    except asyncio.QueueFull:
                        logger.warning("Redis-forwarded event dropped (queue full)")
            finally:
                await pubsub.unsubscribe(_channel(tenant_id))
                await pubsub.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Redis pubsub forward died for tenant=%s", tenant_id,
                exc_info=True,
            )


class _SuppressCancelled:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is asyncio.CancelledError


_suppress_cancelled = _SuppressCancelled  # backwards-compat alias


broker = EventBroker()
