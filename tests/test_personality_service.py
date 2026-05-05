"""Tests for the personality evolution service (phase 10 slice 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace import personality_service as ps_mod
from mypalace.models import PersonalityTrait
from mypalace.personality_service import (
    DEFAULT_AGENT_ID,
    PersonalityService,
    _format_traits_for_prompt,
    _parse_llm_json,
    maybe_enqueue_evolution,
)


def _async_cm(target):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=target)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _trait(
    *, id: str = "t1", category: str = "interests",
    trait_key: str = "music", content: str = "loves jazz",
) -> PersonalityTrait:
    now = datetime(2026, 5, 5, tzinfo=UTC)
    return PersonalityTrait(
        id=id, tenant_id="default", agent_id=DEFAULT_AGENT_ID,
        category=category, trait_key=trait_key, content=content,
        source="self", reason=None, active=True,
        created_at=now, updated_at=now,
    )


class TestFormatTraitsForPrompt:
    def test_empty_returns_placeholder(self):
        assert _format_traits_for_prompt([]) == "No evolved traits yet."

    def test_groups_by_category_with_ids(self):
        traits = [
            _trait(id="t1", category="interests", trait_key="jazz", content="A"),
            _trait(id="t2", category="values", trait_key="kindness", content="B"),
        ]
        out = _format_traits_for_prompt(traits)
        assert "id=t1" in out
        assert "id=t2" in out
        assert "[interests/jazz]" in out
        assert "[values/kindness]" in out


class TestParseLlmJson:
    def test_plain(self):
        assert _parse_llm_json('{"a": 1}') == {"a": 1}

    def test_strips_fence(self):
        assert _parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_garbage_returns_none(self):
        assert _parse_llm_json("not json") is None

    def test_array_returns_none(self):
        assert _parse_llm_json("[1,2,3]") is None


class TestEvaluateAndApply:
    @pytest.mark.asyncio
    async def test_no_evolution_short_circuits(self, monkeypatch):
        svc = PersonalityService()

        # list_active returns nothing — keeps the prompt small.
        async def empty_list(*a, **k):
            return []

        monkeypatch.setattr(svc, "list_active", empty_list)

        with patch.object(
            ps_mod.llm, "complete",
            new=AsyncMock(return_value='{"evolve": false}'),
        ):
            result = await svc.evaluate_and_apply("hi", "hello")

        assert result["evolve"] is False
        assert result["applied"] is False

    @pytest.mark.asyncio
    async def test_add_action_applies(self, monkeypatch):
        svc = PersonalityService()

        async def empty_list(*a, **k):
            return []
        monkeypatch.setattr(svc, "list_active", empty_list)

        added: dict = {}

        async def fake_add(**kwargs):
            added.update(kwargs)
            return _trait()

        monkeypatch.setattr(svc, "add", fake_add)

        decision_json = (
            '{"evolve": true, "action": "add", "category": "interests", '
            '"trait_key": "jazz", "content": "loves jazz", "reason": "asked"}'
        )
        with patch.object(ps_mod.llm, "complete", new=AsyncMock(return_value=decision_json)):
            result = await svc.evaluate_and_apply("u", "a")

        assert result["applied"] is True
        assert added["category"] == "interests"
        assert added["trait_key"] == "jazz"
        assert added["source"] == "evolution"

    @pytest.mark.asyncio
    async def test_update_action_applies(self, monkeypatch):
        svc = PersonalityService()

        async def empty_list(*a, **k):
            return []
        monkeypatch.setattr(svc, "list_active", empty_list)

        update_calls = []

        async def fake_update(**kwargs):
            update_calls.append(kwargs)
            return _trait()

        monkeypatch.setattr(svc, "update", fake_update)

        with patch.object(
            ps_mod.llm, "complete",
            new=AsyncMock(return_value=(
                '{"evolve": true, "action": "update", "trait_id": "tx", '
                '"content": "updated", "reason": "refined"}'
            )),
        ):
            result = await svc.evaluate_and_apply("u", "a")

        assert result["applied"] is True
        assert update_calls[0]["trait_id"] == "tx"
        assert update_calls[0]["content"] == "updated"

    @pytest.mark.asyncio
    async def test_unknown_action_returns_not_applied(self, monkeypatch):
        svc = PersonalityService()

        async def empty_list(*a, **k):
            return []
        monkeypatch.setattr(svc, "list_active", empty_list)

        with patch.object(
            ps_mod.llm, "complete",
            new=AsyncMock(return_value='{"evolve": true, "action": "ponder"}'),
        ):
            result = await svc.evaluate_and_apply("u", "a")
        assert result["applied"] is False
        assert result["error"] == "unknown_action"

    @pytest.mark.asyncio
    async def test_llm_failure_swallowed(self, monkeypatch):
        svc = PersonalityService()

        async def empty_list(*a, **k):
            return []
        monkeypatch.setattr(svc, "list_active", empty_list)

        with patch.object(
            ps_mod.llm, "complete",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            result = await svc.evaluate_and_apply("u", "a")
        assert result == {"evolve": False, "applied": False, "error": "llm_failed"}


class TestMaybeEnqueueEvolution:
    def test_chance_zero_does_not_enqueue(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "personality_evolution_chance", 0.0)
        # Should not even attempt to import workers.queue.
        assert maybe_enqueue_evolution("u", "a", "user-1") is False

    def test_chance_one_always_enqueues(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "personality_evolution_chance", 1.0)

        # Don't actually run the asyncio.create_task target — capture it.
        captured = {}

        def fake_create_task(coro):
            captured["coro"] = coro
            coro.close()  # avoid RuntimeWarning: coroutine never awaited
            return MagicMock()

        monkeypatch.setattr("asyncio.create_task", fake_create_task)
        assert maybe_enqueue_evolution("u", "a", "user-1") is True
        assert "coro" in captured

    def test_chance_zero_with_random_zero_still_skips(self, monkeypatch):
        """Tripwire: the early-exit on chance<=0 must short-circuit before random()."""
        from mypalace.config import settings
        monkeypatch.setattr(settings, "personality_evolution_chance", 0.0)
        # If random.random were consulted, this stub would force enqueue.
        with patch("random.random", return_value=0.0):
            assert maybe_enqueue_evolution("u", "a", "user-1") is False


class TestRemove:
    @pytest.mark.asyncio
    async def test_remove_already_inactive_returns_false(self, monkeypatch):
        svc = PersonalityService()
        row = _trait()
        row.active = False

        scalar = MagicMock()
        scalar.scalar_one_or_none.return_value = row
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        db.commit = AsyncMock()
        monkeypatch.setattr(ps_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        assert await svc.remove("t1") is False

    @pytest.mark.asyncio
    async def test_remove_active_marks_inactive(self, monkeypatch):
        svc = PersonalityService()
        row = _trait()

        scalar = MagicMock()
        scalar.scalar_one_or_none.return_value = row
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        db.commit = AsyncMock()
        monkeypatch.setattr(ps_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        assert await svc.remove("t1", reason="bad trait") is True
        assert row.active is False
        assert row.reason == "bad trait"
