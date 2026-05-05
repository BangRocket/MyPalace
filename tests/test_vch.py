"""Tests for VCH (verbatim chat history) search (phase 10 slice 5).

Mocks async_session — Postgres FTS itself is exercised in integration
tests when added. These verify SQL parameter shapes, dedupe, error
swallowing, formatting, and the API surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mypalace import vch_service as vch_mod
from mypalace.vch_service import VCHService, format_for_context


def _async_cm(target):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=target)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _row(
    msg_id: str = "m1",
    session_id: str = "s1",
    content: str = "the matched message",
    role: str = "user",
    created_at: datetime | None = None,
    rank: float = 0.42,
) -> tuple:
    return (
        msg_id,
        session_id,
        content,
        role,
        created_at or datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        rank,
    )


class TestSearch:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_immediately(self):
        svc = VCHService()
        assert await svc.search("", "u1") == []
        assert await svc.search("   ", "u1") == []

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty(self, monkeypatch):
        svc = VCHService()
        match_result = MagicMock()
        match_result.fetchall.return_value = []

        db = MagicMock()
        db.execute = AsyncMock(return_value=match_result)
        monkeypatch.setattr(vch_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        assert await svc.search("anything", "u1") == []

    @pytest.mark.asyncio
    async def test_match_returns_snippet_with_context(self, monkeypatch):
        svc = VCHService()

        match_result = MagicMock()
        match_result.fetchall.return_value = [_row()]

        ctx_result = MagicMock()
        ctx_result.fetchall.return_value = [
            ("user", "earlier", datetime(2026, 5, 5, 11, 58, tzinfo=UTC)),
            ("assistant", "the matched message", datetime(2026, 5, 5, 12, 0, tzinfo=UTC)),
            ("user", "follow-up", datetime(2026, 5, 5, 12, 2, tzinfo=UTC)),
        ]

        # Same db.execute mock returns matches first, context next.
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[match_result, ctx_result])
        monkeypatch.setattr(vch_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        snippets = await svc.search("hello", "u1", limit=1)
        assert len(snippets) == 1
        s = snippets[0]
        assert s["matched_content"] == "the matched message"
        assert s["rank"] == 0.42
        assert len(s["messages"]) == 3
        assert s["messages"][0]["content"] == "earlier"
        assert "T" in s["messages"][0]["timestamp"]  # ISO

    @pytest.mark.asyncio
    async def test_dedupes_close_session_matches(self, monkeypatch):
        """Two matches in the same 10-minute bucket of one session
        collapse to a single snippet (overlapping context windows)."""
        svc = VCHService()

        ts = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
        match_result = MagicMock()
        match_result.fetchall.return_value = [
            _row(msg_id="a", session_id="s1", created_at=ts),
            _row(msg_id="b", session_id="s1", created_at=ts),  # same bucket
            _row(
                msg_id="c", session_id="s1",
                created_at=datetime(2026, 5, 5, 13, 0, tzinfo=UTC),  # different bucket
            ),
        ]
        ctx_result = MagicMock()
        ctx_result.fetchall.return_value = []

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[match_result, ctx_result, ctx_result])
        monkeypatch.setattr(vch_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        snippets = await svc.search("anything", "u1", limit=10)
        # 3 matches → 2 snippets (one bucket collapsed).
        assert len(snippets) == 2

    @pytest.mark.asyncio
    async def test_db_error_swallowed_returns_empty(self, monkeypatch):
        """FTS index missing on a fresh DB or Postgres unreachable —
        VCH must degrade silently so retrieval still works."""
        svc = VCHService()

        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("missing index"))
        monkeypatch.setattr(vch_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        assert await svc.search("hi", "u1") == []

    @pytest.mark.asyncio
    async def test_passes_tenant_id_to_query(self, monkeypatch):
        svc = VCHService()

        captured: dict = {}

        async def fake_execute(stmt, params=None):
            captured["params"] = params
            r = MagicMock()
            r.fetchall.return_value = []
            return r

        db = MagicMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        monkeypatch.setattr(vch_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        await svc.search("q", "u1", tenant_id="acme")
        assert captured["params"]["tenant_id"] == "acme"
        assert captured["params"]["user_id"] == "u1"
        assert captured["params"]["query"] == "q"


class TestFormatForContext:
    def test_empty_returns_empty_string(self):
        assert format_for_context([]) == ""

    def test_assistant_label_default(self):
        snippets = [{
            "messages": [
                {"role": "assistant", "content": "hello", "timestamp": "2026-05-05T00:00:00"},
            ],
            "matched_content": "hello",
            "rank": 0.5,
            "timestamp": "2026-05-05T00:00:00",
        }]
        out = format_for_context(snippets)
        assert "Assistant: hello" in out
        assert "[2026-05-05]" in out

    def test_max_chars_stops_adding_blocks(self):
        long_content = "x" * 1000
        snippets = [
            {
                "messages": [{"role": "user", "content": long_content, "timestamp": ""}],
                "matched_content": long_content, "rank": 0.5, "timestamp": "",
            },
            {
                "messages": [{"role": "user", "content": "second", "timestamp": ""}],
                "matched_content": "second", "rank": 0.4, "timestamp": "",
            },
        ]
        out = format_for_context(snippets, max_chars=500)
        assert "second" not in out  # second block must be skipped


class TestApiSurface:
    def test_route_required_scope_is_read(self):
        from mypalace.auth.scopes import required_scope
        # /v1/context/* should resolve to read scope.
        assert required_scope("POST", "/v1/context/vch") == "read"

    def test_post_returns_snippets(self, client, monkeypatch):
        from mypalace.api import vch as api

        async def fake_search(**kwargs):
            return [{
                "messages": [
                    {"role": "user", "content": "hi", "timestamp": "2026-05-05T00:00:00"},
                ],
                "matched_content": "hi",
                "rank": 0.9,
                "timestamp": "2026-05-05T00:00:00",
            }]

        monkeypatch.setattr(api.vch_service, "search", fake_search)

        r = client.post(
            "/v1/context/vch",
            json={"user_id": "u1", "query": "hi"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["matched_content"] == "hi"
        assert data[0]["rank"] == 0.9

    def test_empty_query_rejected_by_validator(self, client):
        r = client.post(
            "/v1/context/vch",
            json={"user_id": "u1", "query": ""},
        )
        assert r.status_code == 422
