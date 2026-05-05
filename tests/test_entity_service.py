"""Tests for the entity resolver service (phase 10 slice 1).

Mocks `async_session` so we can exercise the cache + resolve/register
contract without a live database. The LLM extraction path is exercised
via a stubbed `llm.complete`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace import entity_service as es_mod
from mypalace.entity_service import (
    EntityService,
    _parse_llm_json,
    strip_platform_prefix,
)
from mypalace.models import EntityAlias


def _async_cm(target):
    """Build an async-context-manager mock yielding ``target`` on enter."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=target)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _row(identifier: str, name: str, tenant_id: str = "default") -> EntityAlias:
    now = datetime(2026, 5, 5, tzinfo=UTC)
    return EntityAlias(
        id=f"id-{identifier}", tenant_id=tenant_id,
        identifier=identifier, canonical_name=name,
        source="manual", created_at=now, updated_at=now,
    )


class TestPlatformPrefix:
    def test_strips_known_platforms(self):
        assert strip_platform_prefix("discord-123") == "123"
        assert strip_platform_prefix("teams-abc-def") == "abc-def"
        assert strip_platform_prefix("slack-x") == "x"
        assert strip_platform_prefix("matrix-@user:server") == "@user:server"

    def test_returns_none_for_bare_identifier(self):
        assert strip_platform_prefix("just_a_name") is None
        assert strip_platform_prefix("github-user") is None  # not a platform we strip


class TestResolve:
    @pytest.mark.asyncio
    async def test_exact_hit(self, monkeypatch):
        svc = EntityService()

        db = MagicMock()
        result = MagicMock()
        result.all = MagicMock(return_value=[("discord-123", "Josh")])
        db.execute = AsyncMock(return_value=result)
        monkeypatch.setattr(es_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        assert await svc.resolve("discord-123") == "Josh"

    @pytest.mark.asyncio
    async def test_falls_back_to_bare_id(self, monkeypatch):
        """Single canonical mapping under the bare id covers prefixed lookups."""
        svc = EntityService()

        db = MagicMock()
        result = MagicMock()
        result.all = MagicMock(return_value=[("Josh", "Joshua")])
        db.execute = AsyncMock(return_value=result)
        monkeypatch.setattr(es_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        # discord-Josh isn't registered explicitly, but bare "Josh" is.
        assert await svc.resolve("discord-Josh") == "Joshua"

    @pytest.mark.asyncio
    async def test_unknown_identifier_returns_unchanged(self, monkeypatch):
        svc = EntityService()

        db = MagicMock()
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        db.execute = AsyncMock(return_value=result)
        monkeypatch.setattr(es_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        assert await svc.resolve("unknown-xyz") == "unknown-xyz"

    @pytest.mark.asyncio
    async def test_cache_avoids_second_db_load(self, monkeypatch):
        svc = EntityService()

        db = MagicMock()
        result = MagicMock()
        result.all = MagicMock(return_value=[("a", "Alpha")])
        db.execute = AsyncMock(return_value=result)
        sess_factory = MagicMock(return_value=_async_cm(db))
        monkeypatch.setattr(es_mod, "async_session", sess_factory)

        await svc.resolve("a")
        await svc.resolve("a")
        await svc.resolve("a")
        # Only one tenant load should have happened.
        assert sess_factory.call_count == 1

    @pytest.mark.asyncio
    async def test_per_tenant_isolation(self, monkeypatch):
        svc = EntityService()

        loads = []

        def fake_session():
            tenant_rows = {
                "acme": [("u1", "Alice")],
                "globex": [("u1", "Bob")],
            }
            db = MagicMock()
            result = MagicMock()
            # Pop the next pending tenant's rows in registration order.
            result.all = MagicMock(return_value=tenant_rows[loads.pop(0)])
            db.execute = AsyncMock(return_value=result)
            return _async_cm(db)

        monkeypatch.setattr(es_mod, "async_session", fake_session)

        loads.append("acme")
        assert await svc.resolve("u1", tenant_id="acme") == "Alice"
        loads.append("globex")
        assert await svc.resolve("u1", tenant_id="globex") == "Bob"


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_upserts_and_updates_cache(self, monkeypatch):
        svc = EntityService()
        # Pre-warm the cache so we can assert it gets updated.
        svc._cache["acme"] = {}

        captured = {}
        db = MagicMock()
        db.commit = AsyncMock()

        async def fake_execute(stmt):
            r = MagicMock()
            r.scalar_one = MagicMock(return_value=_row("u1", "Alice", "acme"))
            captured["stmt"] = stmt
            return r

        db.execute = AsyncMock(side_effect=fake_execute)
        monkeypatch.setattr(es_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        row = await svc.register("u1", "Alice", tenant_id="acme")
        assert row.canonical_name == "Alice"
        assert svc._cache["acme"]["u1"] == "Alice"
        db.commit.assert_awaited_once()


class TestListForCanonical:
    @pytest.mark.asyncio
    async def test_returns_all_identifiers(self, monkeypatch):
        svc = EntityService()
        svc._cache["default"] = {
            "discord-1": "Josh",
            "slack-2": "josh",
            "teams-3": "Other",
        }
        result = await svc.list_for_canonical("Josh")
        assert result == ["discord-1", "slack-2"]


class TestLLMExtraction:
    @pytest.mark.asyncio
    async def test_register_from_conversation_persists_user_name(self, monkeypatch):
        svc = EntityService()
        svc._cache["default"] = {}

        with patch.object(
            es_mod.llm, "complete",
            new=AsyncMock(return_value='{"user_name": "Josh", "mentioned_people": []}'),
        ):
            register_calls = []

            async def fake_register(identifier, name, tenant_id="default", source="manual"):
                register_calls.append((identifier, name, tenant_id, source))
                return _row(identifier, name, tenant_id)

            monkeypatch.setattr(svc, "register", fake_register)
            extracted = await svc.register_from_conversation(
                [{"role": "user", "content": "hi I'm Josh"}], user_id="discord-9",
            )

        assert extracted == {"user_name": "Josh", "mentioned_people": []}
        assert register_calls == [("discord-9", "Josh", "default", "conversation")]

    @pytest.mark.asyncio
    async def test_empty_messages_short_circuits(self):
        svc = EntityService()
        # No LLM call should fire — if it did, the test would hit a real network.
        assert await svc.register_from_conversation([], user_id="u") == {}

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self, monkeypatch):
        svc = EntityService()
        with patch.object(
            es_mod.llm, "complete",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            assert await svc.register_from_conversation(
                [{"role": "user", "content": "hi"}], user_id="u",
            ) == {}


class TestParseLlmJson:
    def test_plain_json(self):
        assert _parse_llm_json('{"a": 1}') == {"a": 1}

    def test_strips_markdown_fence(self):
        raw = '```json\n{"a": 1}\n```'
        assert _parse_llm_json(raw) == {"a": 1}

    def test_returns_none_for_garbage(self):
        assert _parse_llm_json("not json at all") is None

    def test_returns_none_for_non_object(self):
        assert _parse_llm_json("[1,2,3]") is None
