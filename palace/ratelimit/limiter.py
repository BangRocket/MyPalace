"""Sliding-window rate limiter backed by Redis sorted sets.

Algorithm: each (tenant, key, user, bucket) gets a Redis sorted set
where each member is a request timestamp. On each request:
  1. ZREMRANGEBYSCORE — drop entries older than (now - window_sec).
  2. ZCARD — current count in window.
  3. If count >= limit → 429.
  4. Else ZADD now + EXPIRE window_sec.

Atomicity: the four operations are pipelined inside a MULTI/EXEC so
two parallel requests can't both squeak past the limit.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from palace.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    current: int
    limit: int
    retry_after_seconds: int


class RateLimiter:
    """Lazy Redis client. Operations are no-ops when disabled."""

    KEY_PREFIX = "palace:rl:"
    WINDOW_SECONDS = 60

    def __init__(self) -> None:
        self._client = None

    @property
    def enabled(self) -> bool:
        return settings.rate_limit_enabled and bool(settings.redis_url)

    async def _connect(self):
        if self._client is None:
            try:
                import redis.asyncio as redis_async
            except ImportError as e:
                raise RuntimeError(
                    "redis package required for rate limiting",
                ) from e
            self._client = redis_async.from_url(
                settings.redis_url, decode_responses=True,
            )
        return self._client

    @classmethod
    def _key(cls, tenant_id: str, key_id: str, user_id: str, bucket: str) -> str:
        return f"{cls.KEY_PREFIX}{tenant_id}:{key_id}:{user_id}:{bucket}"

    async def check(
        self,
        tenant_id: str,
        key_id: str,
        user_id: str,
        bucket: str,
        limit: int,
    ) -> LimitDecision:
        """Atomically: drop expired, count, allow-or-deny, record."""
        if not self.enabled:
            return LimitDecision(allowed=True, current=0, limit=limit, retry_after_seconds=0)

        try:
            client = await self._connect()
        except Exception:
            logger.warning("rate limiter Redis unavailable; failing open", exc_info=True)
            return LimitDecision(allowed=True, current=0, limit=limit, retry_after_seconds=0)

        now = time.time()
        cutoff = now - self.WINDOW_SECONDS
        key = self._key(tenant_id, key_id, user_id, bucket)

        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zcard(key)
                pipe.zadd(key, {f"{now}:{id(self)}": now})
                pipe.expire(key, self.WINDOW_SECONDS + 1)
                _, current_before_add, _, _ = await pipe.execute()
        except Exception:
            logger.warning("rate limiter pipeline failed; failing open", exc_info=True)
            return LimitDecision(allowed=True, current=0, limit=limit, retry_after_seconds=0)

        # We added an entry unconditionally — if that pushed us over, the
        # decision is "denied", and the next request inside the window
        # will see the same picture. The cost is one extra ZADD per denied
        # request; acceptable for the simplicity of a single pipeline.
        current = int(current_before_add) + 1
        if current > limit:
            return LimitDecision(
                allowed=False, current=current, limit=limit,
                retry_after_seconds=self.WINDOW_SECONDS,
            )
        return LimitDecision(
            allowed=True, current=current, limit=limit, retry_after_seconds=0,
        )


rate_limiter = RateLimiter()
