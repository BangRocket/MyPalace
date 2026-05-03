"""Minimal async LLM client for OpenAI-compatible APIs."""

import httpx

from palace.config import settings


class LLMClient:
    """Async LLM client via httpx. Supports OpenRouter, OpenAI, and custom endpoints."""

    def __init__(self) -> None:
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self._client = httpx.AsyncClient(timeout=60.0)

    def _get_base_url(self) -> str:
        urls = {
            "openrouter": "https://openrouter.ai/api/v1",
            "openai": "https://api.openai.com/v1",
        }
        return urls.get(self.provider, urls["openrouter"])

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        """Send chat completion request."""
        url = f"{self._get_base_url()}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/palace-memory"

        resp = await self._client.post(
            url,
            headers=headers,
            json={
                "model": model or self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# Singleton
llm = LLMClient()
