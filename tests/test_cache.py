"""Unit tests for the Redis cache wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mypalace.cache.client import Cache, cache
from mypalace.cache.decorator import _to_jsonable, cached_call


class TestEnabledGate:
    def test_disabled_when_no_redis_url(self):
        # In test env settings.redis_url defaults to None
        from mypalace.config import settings
        with patch.object(settings, "redis_url", None):
            assert cache.enabled is False

    def test_disabled_when_explicitly_disabled(self):
        from mypalace.config import settings
        with patch.object(settings, "redis_url", "redis://localhost"), \
             patch.object(settings, "cache_disabled", True):
            assert cache.enabled is False

    def test_enabled_with_url_and_not_disabled(self):
        from mypalace.config import settings
        with patch.object(settings, "redis_url", "redis://localhost"), \
             patch.object(settings, "cache_disabled", False):
            assert cache.enabled is True


class TestKeyDerivation:
    def test_key_includes_tenant(self):
        k = Cache.derive_key("ns", {"tenant_id": "acme", "q": "x"})
        assert k.startswith("palace:cache:acme:ns:")

    def test_key_default_tenant_when_absent(self):
        k = Cache.derive_key("ns", {"q": "x"})
        assert ":default:ns:" in k

    def test_key_stable_for_same_input(self):
        a = Cache.derive_key("ns", {"tenant_id": "t1", "q": "x", "limit": 10})
        b = Cache.derive_key("ns", {"limit": 10, "q": "x", "tenant_id": "t1"})
        assert a == b

    def test_key_changes_with_input(self):
        a = Cache.derive_key("ns", {"tenant_id": "t1", "q": "x"})
        b = Cache.derive_key("ns", {"tenant_id": "t1", "q": "y"})
        assert a != b


class TestCacheGetSetNoOp:
    @pytest.mark.asyncio
    async def test_get_returns_none_when_disabled(self):
        from mypalace.config import settings
        with patch.object(settings, "redis_url", None):
            assert await cache.get("any_key") is None

    @pytest.mark.asyncio
    async def test_set_swallowed_when_disabled(self):
        from mypalace.config import settings
        with patch.object(settings, "redis_url", None):
            await cache.set("k", {"a": 1}, ttl=60)  # no-op, no exception


class TestCachedCall:
    @pytest.mark.asyncio
    async def test_loader_called_on_miss(self):
        loader = AsyncMock(return_value={"x": 1})
        with patch.object(cache, "get", new=AsyncMock(return_value=None)), \
             patch.object(cache, "set", new=AsyncMock()):
            result = await cached_call(
                "ns", {"tenant_id": "t1", "q": "x"}, ttl=60, loader=loader,
            )
            assert result == {"x": 1}
            loader.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_loader_skipped_on_hit(self):
        loader = AsyncMock()
        with patch.object(cache, "get", new=AsyncMock(return_value={"cached": True})), \
             patch.object(cache, "set", new=AsyncMock()):
            result = await cached_call(
                "ns", {"tenant_id": "t1", "q": "x"}, ttl=60, loader=loader,
            )
            assert result == {"cached": True}
            loader.assert_not_awaited()


class TestToJsonable:
    def test_plain_dict_passes_through(self):
        assert _to_jsonable({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}

    def test_list_of_dicts(self):
        assert _to_jsonable([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_pydantic_model_dumped(self):
        from pydantic import BaseModel

        class Thing(BaseModel):
            x: int
            y: str

        assert _to_jsonable(Thing(x=1, y="hi")) == {"x": 1, "y": "hi"}

    def test_tuple_becomes_list(self):
        assert _to_jsonable(("a", "b")) == ["a", "b"]
