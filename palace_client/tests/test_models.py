"""Wire-model parsing smoke test — ensures datetimes are tz-aware."""

from datetime import datetime

from palace_client.models import Memory, ScoredMemory


def test_memory_parses_iso_datetime():
    m = Memory.model_validate({
        "id": "m1",
        "user_id": "u1",
        "content": "x",
        "memory_type": "semantic",
        "importance": 1.0,
        "created_at": "2026-05-03T19:33:40.210487+00:00",
        "metadata": {"k": "v"},
    })
    assert isinstance(m.created_at, datetime)
    assert m.created_at.tzinfo is not None
    assert m.metadata == {"k": "v"}


def test_scored_memory_minimal():
    s = ScoredMemory.model_validate({
        "id": "m1",
        "content": "x",
        "memory_type": "semantic",
        "importance": 1.0,
        "score": 0.95,
    })
    assert s.score == 0.95
