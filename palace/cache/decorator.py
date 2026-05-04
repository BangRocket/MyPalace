"""Helpers to apply read-through caching to specific service-layer calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from palace.cache.client import cache


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
    """
    key = cache.derive_key(namespace, key_parts)
    cached_value = await cache.get(key)
    if cached_value is not None:
        return cached_value
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
