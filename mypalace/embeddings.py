"""Embedding providers: HuggingFace and OpenAI."""

import asyncio
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dim(self) -> int: ...


class HuggingFaceProvider:
    """HuggingFace sentence-transformers embeddings."""

    def __init__(self, model: str, token: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model, token=token)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        arr = await loop.run_in_executor(None, self._model.encode, texts)
        return arr.tolist()

    @property
    def dim(self) -> int:
        return self._model.get_sentence_embedding_dimension()


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


def get_embedder() -> EmbeddingProvider:
    """Factory: return the configured embedding provider."""
    from mypalace.config import settings

    if settings.embedding_provider == "openai":
        return OpenAIProvider(settings.embedding_model, settings.openai_api_key)
    return HuggingFaceProvider(settings.embedding_model, settings.hf_token)


def make_embedder(
    provider: str, model: str, token: str | None = None,
) -> EmbeddingProvider:
    """Build an embedder for an arbitrary (provider, model) without
    touching the global default. Used by the reembed worker handler in
    phase 6 slice 4."""
    if provider == "openai":
        return OpenAIProvider(model, token or "")
    if provider == "huggingface":
        return HuggingFaceProvider(model, token)
    raise ValueError(f"unknown embedding provider: {provider!r}")
