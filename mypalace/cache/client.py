"""Async Redis cache wrapper with key derivation + JSON serialization."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from mypalace.config import settings

logger = logging.getLogger(__name__)


class Cache:
    """Lazy async Redis cache.

    No-op when ``settings.redis_url`` is unset or ``settings.cache_disabled``.
    Failures (connection refused, key error, etc.) log at WARNING and degrade
    to a miss — Palace stays correct, just slower.
    """

    KEY_PREFIX = "palace:cache:"

    def __init__(self) -> None:
        self._client: Any = None
        self._hits = 0
        self._misses = 0

    @property
    def enabled(self) -> bool:
        return bool(settings.redis_url) and not settings.cache_disabled

    async def _connect(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as redis_async
            except ImportError as e:
                raise RuntimeError("redis package required for cache layer") from e
            self._client = redis_async.from_url(
                settings.redis_url, decode_responses=True,
            )
        return self._client

    @staticmethod
    def derive_key(namespace: str, parts: dict[str, Any]) -> str:
        """Derive a stable cache key from a dict of params.

        Always includes ``tenant_id`` if present in parts. Hashes the JSON
        encoding so keys stay short and don't leak query content into Redis
        key space.
        """
        encoded = json.dumps(parts, sort_keys=True, default=str)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
        tenant = parts.get("tenant_id", "default")
        return f"{Cache.KEY_PREFIX}{tenant}:{namespace}:{digest}"

    async def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        try:
            client = await self._connect()
            raw = await client.get(key)
            if raw is None:
                self._misses += 1
                return None
            self._hits += 1
            return json.loads(raw)
        except Exception:
            logger.warning("cache get failed for key=%s", key, exc_info=True)
            self._misses += 1
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if not self.enabled:
            return
        try:
            client = await self._connect()
            await client.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception:
            logger.warning("cache set failed for key=%s", key, exc_info=True)

    async def invalidate_pattern(self, pattern: str) -> int:
        """Delete all keys matching ``pattern`` (Redis glob).

        Uses SCAN to avoid blocking. Returns the count deleted (best-effort).
        """
        if not self.enabled:
            return 0
        try:
            client = await self._connect()
            count = 0
            async for key in client.scan_iter(match=pattern, count=100):
                await client.delete(key)
                count += 1
            return count
        except Exception:
            logger.warning("cache invalidate failed pattern=%s", pattern, exc_info=True)
            return 0

    async def invalidate_tenant_namespace(self, tenant_id: str, namespace: str) -> int:
        """Drop all cached entries for one (tenant, namespace) tuple."""
        return await self.invalidate_pattern(
            f"{Cache.KEY_PREFIX}{tenant_id}:{namespace}:*",
        )

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses}


cache = Cache()
