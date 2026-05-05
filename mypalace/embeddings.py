"""Embedding providers: HuggingFace and OpenAI.

Optional Redis-backed cache wraps the provider so identical (model, text)
inputs skip the expensive inference call. Disabled when Redis is unset
or PALACE_EMBEDDING_CACHE_DISABLED=true.
"""

import asyncio
import hashlib
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dim(self) -> int: ...

    @property
    def model(self) -> str: ...


class HuggingFaceProvider:
    """HuggingFace sentence-transformers embeddings."""

    def __init__(self, model: str, token: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self._model_name = model
        self._model = SentenceTransformer(model, token=token)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        arr = await loop.run_in_executor(None, self._model.encode, texts)
        return arr.tolist()

    @property
    def dim(self) -> int:
        return self._model.get_sentence_embedding_dimension()

    @property
    def model(self) -> str:
        return self._model_name


class OpenAIProvider:
    """OpenAI API embeddings."""

    def __init__(self, model: str, api_key: str) -> None:
        import openai

        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(input=texts, model=self._model)
        return [e.embedding for e in resp.data]

    @property
    def dim(self) -> int:
        return 1536

    @property
    def model(self) -> str:
        return self._model


class CachedEmbedder:
    """Wraps any embedder with a Redis-backed (model, text) → vector cache.

    Cache hits skip the underlying inference entirely. Misses fall through,
    embed, and write back. Cache failures degrade to a plain delegate call
    so embedding never becomes a Redis-availability problem.
    """

    KEY_PREFIX = "palace:embed:"

    def __init__(self, inner: EmbeddingProvider, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    @property
    def dim(self) -> int:
        return self._inner.dim

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses}

    def _key(self, text: str) -> str:
        digest = hashlib.sha256(
            f"{self._inner.model}\0{text}".encode(),
        ).hexdigest()
        return f"{self.KEY_PREFIX}{digest}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from mypalace.cache.client import cache

        # If the underlying cache layer is off we shouldn't even attempt
        # the network round-trip — just delegate.
        if not cache.enabled:
            return await self._inner.embed(texts)

        results: list[list[float] | None] = [None] * len(texts)
        misses_idx: list[int] = []
        for i, text in enumerate(texts):
            cached = await cache.get(self._key(text))
            if cached is not None:
                self._hits += 1
                results[i] = cached
            else:
                self._misses += 1
                misses_idx.append(i)

        if misses_idx:
            miss_texts = [texts[i] for i in misses_idx]
            new_vectors = await self._inner.embed(miss_texts)
            for i, vec in zip(misses_idx, new_vectors, strict=True):
                results[i] = vec
                await cache.set(self._key(texts[i]), vec, ttl=self._ttl)

        return [r for r in results if r is not None]


def _maybe_wrap_with_cache(inner: EmbeddingProvider) -> EmbeddingProvider:
    from mypalace.config import settings

    if settings.embedding_cache_disabled or not settings.redis_url:
        return inner
    return CachedEmbedder(inner, ttl_seconds=settings.embedding_cache_ttl_seconds)


def get_embedder() -> EmbeddingProvider:
    """Factory: return the configured embedding provider, wrapped in the
    Redis cache when enabled (PALACE_EMBEDDING_CACHE_DISABLED=false +
    PALACE_REDIS_URL set)."""
    from mypalace.config import settings

    inner: EmbeddingProvider
    if settings.embedding_provider == "openai":
        inner = OpenAIProvider(settings.embedding_model, settings.openai_api_key)
    else:
        inner = HuggingFaceProvider(settings.embedding_model, settings.hf_token)
    return _maybe_wrap_with_cache(inner)


def make_embedder(
    provider: str, model: str, token: str | None = None,
) -> EmbeddingProvider:
    """Build an embedder for an arbitrary (provider, model) without
    touching the global default. Used by the reembed worker handler in
    phase 6 slice 4. Honors the same cache toggles as ``get_embedder``."""
    inner: EmbeddingProvider
    if provider == "openai":
        inner = OpenAIProvider(model, token or "")
    elif provider == "huggingface":
        inner = HuggingFaceProvider(model, token)
    else:
        raise ValueError(f"unknown embedding provider: {provider!r}")
    return _maybe_wrap_with_cache(inner)
