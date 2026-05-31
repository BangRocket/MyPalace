"""EmotionalService — pure arc logic + DB-backed record/get_recent (mocked session)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mypalace import emotional_service as em_mod
from mypalace.emotional_service import EmotionalService, compute_emotional_arc


def _async_cm(target):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=target)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


class TestComputeArc:
    def test_too_few_messages_is_stable(self):
        assert compute_emotional_arc([0.9, -0.9]) == "stable"

    def test_high_variance_is_volatile(self):
        assert compute_emotional_arc([0.9, -0.9, 0.9, -0.9, 0.9]) == "volatile"

    def test_rising_trend_is_improving(self):
        assert compute_emotional_arc([-0.5, -0.5, -0.5, 0.5, 0.5, 0.5]) == "improving"

    def test_falling_trend_is_declining(self):
        assert compute_emotional_arc([0.5, 0.5, 0.5, -0.5, -0.5, -0.5]) == "declining"

    def test_flat_is_stable(self):
        assert compute_emotional_arc([0.1, 0.1, 0.1, 0.1]) == "stable"


class TestRecord:
    @pytest.mark.asyncio
    async def test_record_computes_arc_and_persists(self, monkeypatch):
        svc = EmotionalService()
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        monkeypatch.setattr(em_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        row = await svc.record(
            user_id="u1",
            messages=["I'm so frustrated", "still annoyed", "ok", "feeling better", "great now", "wonderful"],
            energy="focused", summary="job search", channel_name="#dm", is_dm=True,
        )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        assert row.user_id == "u1"
        assert row.emotional_arc in {"stable", "improving", "declining", "volatile"}
        assert row.energy_level == "focused"
        assert row.topic_summary == "job search"

    @pytest.mark.asyncio
    async def test_record_with_no_messages_defaults_zero(self, monkeypatch):
        svc = EmotionalService()
        db = MagicMock(add=MagicMock(), commit=AsyncMock(), refresh=AsyncMock())
        monkeypatch.setattr(em_mod, "async_session", MagicMock(return_value=_async_cm(db)))
        row = await svc.record(user_id="u1", messages=[])
        assert row.starting_sentiment == 0.0
        assert row.ending_sentiment == 0.0
        assert row.emotional_arc == "stable"


class TestGetRecent:
    @pytest.mark.asyncio
    async def test_get_recent_queries_and_returns_rows(self, monkeypatch):
        svc = EmotionalService()
        sentinel = ["row-a", "row-b"]
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=sentinel)
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        monkeypatch.setattr(em_mod, "async_session", MagicMock(return_value=_async_cm(db)))

        out = await svc.get_recent(user_id="u1", limit=2, max_age_days=7)
        assert out == sentinel
        db.execute.assert_awaited_once()
