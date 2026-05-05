"""Tests for LLM provider expansion (phase 14).

Covers:
- Base-URL resolution for openai / openrouter / anthropic / custom
- PALACE_LLM_BASE_URL override precedence
- OpenAI-compatible request shape (URL, Authorization header,
  openrouter HTTP-Referer)
- Anthropic Messages API request shape (URL, x-api-key header, system
  hoisted out of messages, top-level max_tokens)
- Anthropic response parsing (content[0].text)
- Unknown provider fails fast
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from mypalace.llm import LLMClient, _resolve_base_url


class TestResolveBaseUrl:
    def test_openai_default(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)
        assert _resolve_base_url("openai") == "https://api.openai.com/v1"

    def test_openrouter_default(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)
        assert _resolve_base_url("openrouter") == "https://openrouter.ai/api/v1"

    def test_anthropic_default(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)
        assert _resolve_base_url("anthropic") == "https://api.anthropic.com"

    def test_override_wins_over_default(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", "https://my-vllm.local/v1")
        assert _resolve_base_url("openai") == "https://my-vllm.local/v1"
        assert _resolve_base_url("anthropic") == "https://my-vllm.local/v1"
        assert _resolve_base_url("custom") == "https://my-vllm.local/v1"

    def test_override_strips_trailing_slash(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", "https://my-vllm.local/v1/")
        assert _resolve_base_url("openai") == "https://my-vllm.local/v1"

    def test_empty_override_falls_through(self, monkeypatch):
        """Operators may set PALACE_LLM_BASE_URL='' explicitly to clear it."""
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", "")
        assert _resolve_base_url("openai") == "https://api.openai.com/v1"

    def test_unknown_provider_without_override_raises(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)
        with pytest.raises(ValueError, match="unknown LLM provider"):
            _resolve_base_url("custom")

    def test_unknown_provider_with_override_works(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", "https://my-llm.local")
        assert _resolve_base_url("custom") == "https://my-llm.local"


class TestOpenAICompatibleRequest:
    @pytest.mark.asyncio
    async def test_openai_post_shape(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)

        client = LLMClient()
        client.provider = "openai"
        client.model = "gpt-4o"
        client.api_key = "sk-secret"

        captured: dict = {}

        async def fake_post(url, headers, json):  # noqa: A002
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={
                "choices": [{"message": {"content": "hi"}}],
            })
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        result = await client.complete(
            [{"role": "user", "content": "hello"}],
            temperature=0.5, max_tokens=100,
        )
        assert result == "hi"
        assert captured["url"] == "https://api.openai.com/v1/chat/completions"
        assert captured["headers"]["Authorization"] == "Bearer sk-secret"
        assert "HTTP-Referer" not in captured["headers"]
        assert captured["json"]["model"] == "gpt-4o"
        assert captured["json"]["temperature"] == 0.5
        assert captured["json"]["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_openrouter_adds_referer(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)

        client = LLMClient()
        client.provider = "openrouter"

        captured: dict = {}

        async def fake_post(url, headers, json):  # noqa: A002
            captured["headers"] = headers
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={"choices": [{"message": {"content": ""}}]})
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        await client.complete([{"role": "user", "content": "x"}])
        assert "HTTP-Referer" in captured["headers"]

    @pytest.mark.asyncio
    async def test_custom_provider_via_base_url_override(self, monkeypatch):
        """vLLM / TGI / LocalAI: provider=custom + PALACE_LLM_BASE_URL."""
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", "https://my-vllm.local/v1")

        client = LLMClient()
        client.provider = "custom"
        client.api_key = "ignored-by-self-hosted"

        captured: dict = {}

        async def fake_post(url, headers, json):  # noqa: A002
            captured["url"] = url
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={"choices": [{"message": {"content": "ok"}}]})
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        out = await client.complete([{"role": "user", "content": "hi"}])
        assert out == "ok"
        assert captured["url"] == "https://my-vllm.local/v1/chat/completions"


class TestAnthropicRequest:
    @pytest.mark.asyncio
    async def test_anthropic_post_shape(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)

        client = LLMClient()
        client.provider = "anthropic"
        client.model = "claude-3-5-sonnet-latest"
        client.api_key = "sk-ant-secret"

        captured: dict = {}

        async def fake_post(url, headers, json):  # noqa: A002
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={
                "content": [{"type": "text", "text": "hi from claude"}],
            })
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        result = await client.complete(
            [
                {"role": "system", "content": "be terse"},
                {"role": "user", "content": "hello"},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        assert result == "hi from claude"
        # URL + headers
        assert captured["url"] == "https://api.anthropic.com/v1/messages"
        assert captured["headers"]["x-api-key"] == "sk-ant-secret"
        assert captured["headers"]["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in captured["headers"]
        # Body shape
        body = captured["json"]
        assert body["model"] == "claude-3-5-sonnet-latest"
        assert body["max_tokens"] == 200
        assert body["temperature"] == 0.0
        # System hoisted out of messages.
        assert body["system"] == "be terse"
        assert body["messages"] == [{"role": "user", "content": "hello"}]

    @pytest.mark.asyncio
    async def test_anthropic_concatenates_multiple_systems(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)

        client = LLMClient()
        client.provider = "anthropic"

        captured: dict = {}

        async def fake_post(url, headers, json):  # noqa: A002
            captured["body"] = json
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={"content": [{"type": "text", "text": ""}]})
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        await client.complete(
            [
                {"role": "system", "content": "rule one"},
                {"role": "system", "content": "rule two"},
                {"role": "user", "content": "ok"},
            ],
        )
        assert captured["body"]["system"] == "rule one\n\nrule two"

    @pytest.mark.asyncio
    async def test_anthropic_skips_non_text_blocks(self, monkeypatch):
        """If Claude returns a tool_use block before any text, fall
        through to empty rather than crashing."""
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)

        client = LLMClient()
        client.provider = "anthropic"

        async def fake_post(url, headers, json):  # noqa: A002
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={
                "content": [
                    {"type": "tool_use", "id": "x"},
                    {"type": "text", "text": "actual"},
                ],
            })
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        out = await client.complete([{"role": "user", "content": "hi"}])
        assert out == "actual"

    @pytest.mark.asyncio
    async def test_anthropic_no_text_returns_empty(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)

        client = LLMClient()
        client.provider = "anthropic"

        async def fake_post(url, headers, json):  # noqa: A002
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={"content": []})
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        assert await client.complete([{"role": "user", "content": "hi"}]) == ""

    @pytest.mark.asyncio
    async def test_anthropic_via_base_url_override(self, monkeypatch):
        """An Anthropic-compatible proxy works the same way."""
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", "https://anthropic-proxy.local")

        client = LLMClient()
        client.provider = "anthropic"

        captured: dict = {}

        async def fake_post(url, headers, json):  # noqa: A002
            captured["url"] = url
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={"content": [{"type": "text", "text": ""}]})
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        await client.complete([{"role": "user", "content": "hi"}])
        assert captured["url"] == "https://anthropic-proxy.local/v1/messages"


class TestSingletonRoutingHonorsProvider:
    """Tripwire: the module-level singleton's provider attribute drives
    routing. Tests that hot-swap settings at runtime should also rebuild
    the singleton or exercise it via _resolve_base_url directly."""

    @pytest.mark.asyncio
    async def test_singleton_respects_anthropic_provider(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "llm_base_url", None)
        # Build a fresh client so settings changes take effect.
        client = LLMClient()
        client.provider = "anthropic"
        client.model = "claude-3-5-sonnet-latest"
        client.api_key = "sk-ant-x"

        captured = {}

        async def fake_post(url, **_kw):
            captured["url"] = url
            r = MagicMock(spec=httpx.Response)
            r.json = MagicMock(return_value={"content": [{"type": "text", "text": "ok"}]})
            r.raise_for_status = MagicMock()
            return r

        client._client.post = fake_post  # type: ignore[assignment]
        await client.complete([{"role": "user", "content": "hi"}])
        assert "/v1/messages" in captured["url"]


class TestSettingsExposed:
    def test_llm_base_url_default_is_none(self):
        from mypalace.config import settings
        assert settings.llm_base_url is None
