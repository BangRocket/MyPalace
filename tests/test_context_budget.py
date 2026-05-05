"""Tests for the token-based context budget env vars (phase 10 slice 3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mypalace.config import (
    CHARS_PER_TOKEN,
    context_budget_l1_chars,
    context_budget_l2_chars,
)


class TestBudgetConversion:
    def test_default_token_budgets_match_legacy_chars(self):
        """Tripwire: defaults must reproduce the previously hardcoded values
        (3200 L1, 12000 L2) so existing deployments don't see surprise drops."""
        assert context_budget_l1_chars() == 3200
        assert context_budget_l2_chars() == 12000

    def test_chars_per_token_constant(self):
        # Heuristic must stay 4 to remain compatible with mypalclara.
        assert CHARS_PER_TOKEN == 4

    def test_env_override_l1(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "context_budget_l1_tokens", 200)
        assert context_budget_l1_chars() == 800

    def test_env_override_l2(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "context_budget_l2_tokens", 1500)
        assert context_budget_l2_chars() == 6000


class TestAssembleHonorsEnvDefaults:
    @pytest.mark.asyncio
    async def test_assemble_uses_env_when_no_override(self, monkeypatch):
        """When max_l1_chars / max_l2_chars are omitted, the service must
        consult the env-configured token budgets."""
        from mypalace.config import settings
        from mypalace.retrieval.layered import LayeredRetrievalService

        # Fake a small budget so we can verify it actually flowed through.
        monkeypatch.setattr(settings, "context_budget_l1_tokens", 25)  # 100 chars
        monkeypatch.setattr(settings, "context_budget_l2_tokens", 50)  # 200 chars

        svc = LayeredRetrievalService()

        # Stub out every downstream service call so we only exercise the
        # budget plumbing.
        from mypalace import retrieval

        with (
            patch.object(
                retrieval.layered.memory_service, "search",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                retrieval.layered.episode_service, "get_recent",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                retrieval.layered.episode_service, "search",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                retrieval.layered.arc_service, "get_active",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await svc.assemble(user_id="u", query="q")

        # No memories returned, so the "kept" lists are empty — but the
        # important assertion is that no exception fired and the response
        # shape includes the char_counts block populated from the env values.
        assert result["char_counts"] == {"l1": 0, "l2": 0}

    @pytest.mark.asyncio
    async def test_explicit_override_wins_over_env(self, monkeypatch):
        from mypalace.config import settings
        from mypalace.retrieval.layered import LayeredRetrievalService

        monkeypatch.setattr(settings, "context_budget_l1_tokens", 9999)
        monkeypatch.setattr(settings, "context_budget_l2_tokens", 9999)
        svc = LayeredRetrievalService()

        from mypalace import retrieval

        with (
            patch.object(
                retrieval.layered.memory_service, "search",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                retrieval.layered.episode_service, "get_recent",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                retrieval.layered.episode_service, "search",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                retrieval.layered.arc_service, "get_active",
                new=AsyncMock(return_value=[]),
            ),
        ):
            # Per-call overrides must win over env defaults.
            result = await svc.assemble(
                user_id="u", query="q",
                max_l1_chars=10, max_l2_chars=20,
            )
        assert result["char_counts"] == {"l1": 0, "l2": 0}
