"""Helpers to apply read-through caching to specific service-layer calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mypalace.cache.client import cache
from mypalace.observability.metrics import cache_hits, cache_misses


async def cached_call(
    namespace: str,
    key_parts: dict[str, Any],
    ttl: int,
    loader: Callable[[], Awaitable[Any]],
) -> Any:
    """Read-through cache helper.

    1. Compute key from (namespace, key_parts).
    2. Try cache GET.
    3. On miss, call ``loader``, cache the result, return it.

    Always increments the relevant Prometheus counter, even when the cache
    is disabled (counted as a miss) so dashboards can spot misconfiguration.
    """
    key = cache.derive_key(namespace, key_parts)
    cached_value = await cache.get(key)
    if cached_value is not None:
        cache_hits.labels(namespace=namespace).inc()
        return cached_value
    cache_misses.labels(namespace=namespace).inc()
    fresh = await loader()
    # Pydantic models / nested objects need json-serializable form.
    await cache.set(key, _to_jsonable(fresh), ttl)
    return fresh


def _to_jsonable(value: Any) -> Any:
    """Coerce common non-JSON-serializable values into JSON-friendly form."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value
