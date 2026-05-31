"""TopicService — pure helpers + DB/LLM-mocked extract/recurrence."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace import topic_service as tp_mod
from mypalace.models import TopicMention
from mypalace.topic_service import (
    TopicService,
    _dedupe_topics,
    _parse_llm_json,
    _validate_topics,
    compute_topic_pattern,
)


def _async_cm(target):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=target)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _mention(topic, sentiment, weight, when):
    return TopicMention(
        id=f"id-{when.isoformat()}", tenant_id="test", user_id="u1", agent_id="default",
        topic=topic, topic_type="theme", context_snippet="", emotional_weight=weight,
        sentiment=sentiment, channel_id="", channel_name="#dm", is_dm=True, created_at=when,
    )


class TestValidate:
    def test_drops_invalid_and_normalizes(self):
        raw = [
            {"topic": "Job Search", "topic_type": "bogus", "emotional_weight": "x"},
            {"topic": "", "topic_type": "theme"},
        ]
        out = _validate_topics(raw)
        assert out == [{
            "topic": "job search", "topic_type": "theme",
            "context_snippet": "", "emotional_weight": "moderate",
        }]


class TestDedupe:
    def test_keeps_heaviest_weight(self):
        out = _dedupe_topics([
            {"topic": "mom", "topic_type": "entity", "context_snippet": "", "emotional_weight": "light"},
            {"topic": "mom", "topic_type": "entity", "context_snippet": "", "emotional_weight": "heavy"},
        ])
        assert len(out) == 1
        assert out[0]["emotional_weight"] == "heavy"


class TestPattern:
    def test_declining_and_recurring(self):
        p = compute_topic_pattern([
            {"sentiment": 0.5, "emotional_weight": "moderate"},
            {"sentiment": 0.0, "emotional_weight": "moderate"},
            {"sentiment": -0.5, "emotional_weight": "heavy"},
        ])
        assert p["mention_count"] == 3
        assert p["sentiment_trend"] == "declining"
        assert "getting heavier" in p["pattern_note"] or "recurring" in p["pattern_note"]


class TestExtractAndStore:
    @pytest.mark.asyncio
    async def test_short_text_skips_llm(self):
        svc = TopicService()
        assert await svc.extract_and_store(user_id="u1", conversation_text="hi") == []

    @pytest.mark.asyncio
    async def test_extracts_dedupes_and_persists(self, monkeypatch):
        svc = TopicService()
        db = MagicMock(add=MagicMock(), commit=AsyncMock(), refresh=AsyncMock())
        monkeypatch.setattr(tp_mod, "async_session", MagicMock(return_value=_async_cm(db)))
        llm_json = '{"topics": [{"topic": "Job Search", "topic_type": "theme", "context_snippet": "interviews", "emotional_weight": "heavy"}]}'
        with patch.object(tp_mod.llm, "complete", new=AsyncMock(return_value=llm_json)):
            rows = await svc.extract_and_store(
                user_id="u1",
                conversation_text="we talked at length about the job search and interviews not going well " * 2,
                conversation_sentiment=-0.3,
            )
        assert len(rows) == 1
        assert rows[0].topic == "job search"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self, monkeypatch):
        svc = TopicService()
        monkeypatch.setattr(tp_mod, "async_session", MagicMock(return_value=_async_cm(MagicMock())))
        with patch.object(tp_mod.llm, "complete", new=AsyncMock(side_effect=RuntimeError("boom"))):
            assert await svc.extract_and_store(
                user_id="u1", conversation_text="x" * 60,
            ) == []


class TestRecurrence:
    @pytest.mark.asyncio
    async def test_groups_and_filters_min_mentions(self, monkeypatch):
        svc = TopicService()
        now = datetime(2026, 5, 31, tzinfo=UTC)
        rows = [
            _mention("job search", -0.2, "heavy", now - timedelta(days=2)),
            _mention("job search", -0.5, "heavy", now - timedelta(days=1)),
            _mention("weather", 0.1, "light", now - timedelta(days=1)),
        ]
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=rows)
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        db = MagicMock(execute=AsyncMock(return_value=result))
        monkeypatch.setattr(tp_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        out = await svc.get_recurrence(user_id="u1", min_mentions=2)
        assert len(out) == 1
        assert out[0]["topic"] == "job search"
        assert out[0]["mention_count"] == 2


class TestParseLlmJson:
    def test_plain_and_fenced(self):
        assert _parse_llm_json('{"a": 1}') == {"a": 1}
        assert _parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_garbage_is_none(self):
        assert _parse_llm_json("not json") is None
