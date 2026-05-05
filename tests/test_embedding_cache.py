"""Tests for the optional Redis embedding cache (phase 10 slice 4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mypalace.embeddings import (
    CachedEmbedder,
    HuggingFaceProvider,
    _maybe_wrap_with_cache,
    get_embedder,
    make_embedder,
)


class _FakeProvider:
    """Minimal embedder for testing the wrapper without loading models."""

    def __init__(self, model: str = "fake-model", dim: int = 4) -> None:
        self._model = model
        self._dim = dim
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        # Deterministic — return [len(text), 0.1, 0.2, 0.3] per text.
        return [[float(len(t)), 0.1, 0.2, 0.3] for t in texts]

    @property
    def dim(self):
        return self._dim

    @property
    def model(self):
        return self._model


class TestCacheKey:
    def test_key_includes_model_and_text(self):
        a = CachedEmbedder(_FakeProvider("m1"), ttl_seconds=10)
        b = CachedEmbedder(_FakeProvider("m2"), ttl_seconds=10)
        assert a._key("hi") != b._key("hi"), "key must be model-scoped"
        assert a._key("hi") != a._key("hello")
        # Stable on repeat
        assert a._key("hi") == a._key("hi")
        assert a._key("hi").startswith("palace:embed:")


class TestCachedEmbedderEnabled:
    @pytest.mark.asyncio
    async def test_all_misses_calls_inner_once_and_writes_cache(self):
        inner = _FakeProvider()
        wrapper = CachedEmbedder(inner, ttl_seconds=60)

        from mypalace.cache import client as cache_mod
        # Stub out the cache singleton.
        cache_mod.cache.get = AsyncMock(return_value=None)
        cache_mod.cache.set = AsyncMock()
        # enabled is a property; patch it via type-level descriptor.
        with patch.object(
            type(cache_mod.cache), "enabled",
            new_callable=lambda: property(lambda self: True),
        ):
            vectors = await wrapper.embed(["hi", "yo"])

        assert len(vectors) == 2
        assert inner.calls == [["hi", "yo"]]
        # One set per text
        assert cache_mod.cache.set.await_count == 2
        assert wrapper.stats == {"hits": 0, "misses": 2}

    @pytest.mark.asyncio
    async def test_all_hits_skips_inner(self):
        inner = _FakeProvider()
        wrapper = CachedEmbedder(inner, ttl_seconds=60)

        from mypalace.cache import client as cache_mod
        cache_mod.cache.get = AsyncMock(return_value=[1.0, 2.0, 3.0, 4.0])
        cache_mod.cache.set = AsyncMock()
        with patch.object(
            type(cache_mod.cache), "enabled",
            new_callable=lambda: property(lambda self: True),
        ):
            vectors = await wrapper.embed(["a", "b", "c"])

        assert vectors == [[1.0, 2.0, 3.0, 4.0]] * 3
        assert inner.calls == []  # never delegated
        assert cache_mod.cache.set.await_count == 0
        assert wrapper.stats == {"hits": 3, "misses": 0}

    @pytest.mark.asyncio
    async def test_partial_hit_only_embeds_misses(self):
        inner = _FakeProvider()
        wrapper = CachedEmbedder(inner, ttl_seconds=60)

        # "hit" returns a cached vector; everything else misses.
        async def fake_get(key):
            return [9.0, 9.0, 9.0, 9.0] if "hit" in key else None

        from mypalace.cache import client as cache_mod
        cache_mod.cache.get = AsyncMock(side_effect=fake_get)
        cache_mod.cache.set = AsyncMock()

        # Force every key to contain "hit" if the original text starts
        # with "h" — simpler: only one of three is a hit.
        wrapper._key = lambda text: f"k:hit:{text}" if text == "hello" else f"k:miss:{text}"

        with patch.object(
            type(cache_mod.cache), "enabled",
            new_callable=lambda: property(lambda self: True),
        ):
            vectors = await wrapper.embed(["miss-1", "hello", "miss-2"])

        # Position preserved
        assert vectors[1] == [9.0, 9.0, 9.0, 9.0]
        assert vectors[0][0] == float(len("miss-1"))
        assert vectors[2][0] == float(len("miss-2"))
        # Inner was called only with the misses.
        assert inner.calls == [["miss-1", "miss-2"]]
        assert wrapper.stats == {"hits": 1, "misses": 2}


class TestCachedEmbedderDisabled:
    @pytest.mark.asyncio
    async def test_cache_off_delegates_directly(self):
        inner = _FakeProvider()
        wrapper = CachedEmbedder(inner, ttl_seconds=60)

        from mypalace.cache import client as cache_mod
        with patch.object(
            type(cache_mod.cache), "enabled",
            new_callable=lambda: property(lambda self: False),
        ):
            vectors = await wrapper.embed(["x"])

        assert len(vectors) == 1
        assert inner.calls == [["x"]]
        # Wrapper-level counters do NOT increment on this path —
        # we never consulted the cache.
        assert wrapper.stats == {"hits": 0, "misses": 0}


class TestMaybeWrap:
    def test_disabled_flag_returns_inner_unwrapped(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "embedding_cache_disabled", True)
        monkeypatch.setattr(settings, "redis_url", "redis://x")
        inner = _FakeProvider()
        assert _maybe_wrap_with_cache(inner) is inner

    def test_no_redis_url_returns_inner_unwrapped(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "embedding_cache_disabled", False)
        monkeypatch.setattr(settings, "redis_url", None)
        inner = _FakeProvider()
        assert _maybe_wrap_with_cache(inner) is inner

    def test_enabled_wraps(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "embedding_cache_disabled", False)
        monkeypatch.setattr(settings, "redis_url", "redis://x")
        inner = _FakeProvider()
        wrapped = _maybe_wrap_with_cache(inner)
        assert isinstance(wrapped, CachedEmbedder)
        assert wrapped.dim == inner.dim
        assert wrapped.model == inner.model


class TestSettingsExposed:
    def test_defaults(self):
        from mypalace.config import settings
        assert settings.embedding_cache_disabled is False
        assert settings.embedding_cache_ttl_seconds >= 86400  # at least a day


class TestProviderModelProperty:
    """Tripwire: every embedder must expose .model so the cache key is stable."""

    def test_huggingface_model_property(self, monkeypatch):
        # Don't actually load sentence-transformers — patch the class init.
        with patch("mypalace.embeddings.HuggingFaceProvider.__init__", return_value=None):
            p = HuggingFaceProvider.__new__(HuggingFaceProvider)
            p._model_name = "BAAI/bge-large-en-v1.5"
            assert p.model == "BAAI/bge-large-en-v1.5"


class TestFactoriesHonorCacheToggle:
    def test_get_embedder_returns_unwrapped_when_redis_unset(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)
        # Avoid loading a real model — stub the providers so we just
        # observe which one comes back.
        with (
            patch("mypalace.embeddings.HuggingFaceProvider.__init__", return_value=None),
            patch("mypalace.embeddings.OpenAIProvider.__init__", return_value=None),
        ):
            embedder = get_embedder()
        assert not isinstance(embedder, CachedEmbedder)

    def test_make_embedder_wraps_when_redis_set(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "embedding_cache_disabled", False)
        monkeypatch.setattr(settings, "redis_url", "redis://x")
        with patch("mypalace.embeddings.HuggingFaceProvider.__init__", return_value=None):
            embedder = make_embedder("huggingface", "any-model")
        assert isinstance(embedder, CachedEmbedder)
