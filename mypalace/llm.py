"""Minimal async LLM client for OpenAI-compatible APIs + Anthropic.

Phase 14: adds Anthropic Messages API support and a generic
``PALACE_LLM_BASE_URL`` override so operators can point at custom
OpenAI-compatible endpoints (vLLM, TGI, LocalAI, Together, OpenRouter
mirrors) or Anthropic-compatible proxies without code changes.

Provider matrix:

| ``llm_provider`` | Default base URL                  | Auth header        |
|------------------|-----------------------------------|--------------------|
| ``openrouter``   | https://openrouter.ai/api/v1      | ``Authorization``  |
| ``openai``       | https://api.openai.com/v1         | ``Authorization``  |
| ``anthropic``    | https://api.anthropic.com         | ``x-api-key``      |
| ``custom``       | (must set ``PALACE_LLM_BASE_URL``) | ``Authorization``  |
"""

from __future__ import annotations

import httpx

from mypalace.config import settings

# OpenAI-compatible providers — same chat-completions wire format,
# differ only in URL and (for openrouter) one extra header.
_OPENAI_DEFAULT_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
}

ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


def _resolve_base_url(provider: str) -> str:
    """Pick the effective base URL for ``provider``.

    Precedence: explicit ``PALACE_LLM_BASE_URL`` > provider default.
    Raises if ``provider`` is unknown and no override is set — better
    to fail fast at first use than to silently route requests to the
    wrong endpoint.
    """
    override = (settings.llm_base_url or "").strip().rstrip("/")
    if override:
        return override
    if provider in _OPENAI_DEFAULT_URLS:
        return _OPENAI_DEFAULT_URLS[provider]
    if provider == "anthropic":
        return ANTHROPIC_DEFAULT_URL
    raise ValueError(
        f"unknown LLM provider {provider!r}; set PALACE_LLM_BASE_URL or "
        f"choose one of: {sorted({*_OPENAI_DEFAULT_URLS, 'anthropic', 'custom'})}",
    )


class LLMClient:
    """Async LLM client via httpx.

    Defers the base-URL lookup to first call so a settings change after
    import (test fixtures, env reload) takes effect.
    """

    def __init__(self) -> None:
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self._client = httpx.AsyncClient(timeout=60.0)

    def _get_base_url(self) -> str:
        return _resolve_base_url(self.provider)

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        """Send chat completion request.

        Routes to the Anthropic Messages API when ``provider ==
        "anthropic"``; otherwise uses the OpenAI chat-completions
        wire format (which works for openrouter, openai, and any
        custom OpenAI-compatible endpoint via PALACE_LLM_BASE_URL).
        """
        if self.provider == "anthropic":
            return await self._complete_anthropic(
                messages, model=model, temperature=temperature, max_tokens=max_tokens,
            )
        return await self._complete_openai_compatible(
            messages, model=model, temperature=temperature, max_tokens=max_tokens,
        )

    async def _complete_openai_compatible(
        self,
        messages: list[dict],
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
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

    async def _complete_anthropic(
        self,
        messages: list[dict],
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Anthropic Messages API.

        Differences from OpenAI's wire format:
        - URL is /v1/messages (not /chat/completions).
        - Auth via x-api-key header (not Bearer token).
        - System prompts are a top-level ``system`` field, NOT a
          message with role=system.
        - Response shape is ``content[0].text`` (not ``choices[0].message.content``).
        - ``max_tokens`` is required (not optional like OpenAI).
        """
        url = f"{self._get_base_url()}/v1/messages"
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

        # Hoist any system messages out of the array — Anthropic wants
        # them on a top-level field. Multiple system messages get
        # concatenated with double newlines (matches Claude's docs).
        system_parts: list[str] = []
        non_system: list[dict] = []
        for m in messages:
            if m.get("role") == "system":
                content = m.get("content", "")
                if content:
                    system_parts.append(content)
            else:
                non_system.append(m)

        body: dict = {
            "model": model or self.model,
            "messages": non_system,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)

        resp = await self._client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        # content is a list of content blocks; the first text block is
        # what we want. Anthropic may also return tool_use blocks but
        # mypalace doesn't use tool calling today.
        for block in data.get("content", []):
            if block.get("type") == "text":
                return block.get("text", "")
        # Fall through: empty response.
        return ""


# Singleton
llm = LLMClient()
