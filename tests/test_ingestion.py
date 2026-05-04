"""Slice-5 smart ingestion tests (mock-based).

Covers:
- Heuristic contradiction detection (deterministic regression net)
- Dedup decision paths: skip/similar/supersede/write
- Manual supersede + supersedes-history endpoints
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mypalace.retrieval.ingestion import SmartIngestionService


def _fake_memory(mid: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        user_id="u1",
        agent_id="clara",
        content=content,
        memory_type="semantic",
        importance=1.0,
        source=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        accessed_at=None,
        access_count=0,
        metadata_json=None,
    )


# ---------------------------------------------------------------------------
# Contradiction heuristic
# ---------------------------------------------------------------------------


def test_contradiction_clear_negation_with_overlap():
    svc = SmartIngestionService()
    contradicts, conf, reason = svc._check_contradiction(
        "Joshua loves coffee",
        "Joshua does not love coffee",
    )
    assert contradicts is True
    assert conf > 0.0
    assert "negation" in reason


def test_contradiction_no_overlap_returns_false():
    svc = SmartIngestionService()
    contradicts, _, _ = svc._check_contradiction(
        "Joshua loves coffee",
        "Bob does not enjoy hiking",
    )
    assert contradicts is False


def test_contradiction_both_negated_returns_false():
    """Both negated — could still be aligned. Heuristic should not flag."""
    svc = SmartIngestionService()
    contradicts, _, _ = svc._check_contradiction(
        "Joshua does not like tea",
        "Joshua never drinks tea",
    )
    assert contradicts is False


def test_contradiction_no_negation_returns_false():
    """Two positive statements with overlap — not a contradiction."""
    svc = SmartIngestionService()
    contradicts, _, _ = svc._check_contradiction(
        "Joshua loves coffee",
        "Joshua enjoys coffee daily",
    )
    assert contradicts is False


def test_contradiction_single_word_overlap_too_weak():
    """One-word overlap (just the noun) is too weak — should not contradict."""
    svc = SmartIngestionService()
    contradicts, _, why = svc._check_contradiction(
        "Joshua works at Acme",
        "Bob does not work at Microsoft",
    )
    # Subject is different ('joshua' vs 'bob'); only 'work' overlaps.
    assert contradicts is False
    assert "overlap" in why or "no signal" in why or "insufficient" in why


# ---------------------------------------------------------------------------
# Dedup decision paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_skips_when_score_above_skip_threshold():
    svc = SmartIngestionService()
    candidates = [{"content": "Joshua loves coffee", "importance": 1.0}]

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[[0.0] * 4])

    with (
        patch("mypalace.retrieval.ingestion.vector_store") as vs,
        patch("mypalace.retrieval.ingestion.memory_service") as mem,
        patch.object(SmartIngestionService, "embedder", embedder),
    ):
        vs.search = AsyncMock(return_value=[("existing-id", 0.97)])
        mem.create = AsyncMock()

        written, supers, skipped = await svc.dedup_and_write(
            candidates=candidates, user_id="u1", agent_id="clara",
        )

    assert written == []
    assert supers == []
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "duplicate"
    mem.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedup_writes_when_no_neighbor():
    svc = SmartIngestionService()
    candidates = [{"content": "fresh fact", "importance": 1.0}]

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[[0.0] * 4])
    new_mem = _fake_memory("new-1", "fresh fact")

    with (
        patch("mypalace.retrieval.ingestion.vector_store") as vs,
        patch("mypalace.retrieval.ingestion.memory_service") as mem,
        patch.object(SmartIngestionService, "embedder", embedder),
    ):
        vs.search = AsyncMock(return_value=[])
        mem.create = AsyncMock(return_value=new_mem)

        written, supers, skipped = await svc.dedup_and_write(
            candidates=candidates, user_id="u1", agent_id="clara",
        )

    assert len(written) == 1
    assert written[0].id == "new-1"
    assert supers == []
    assert skipped == []


@pytest.mark.asyncio
async def test_dedup_supersedes_when_contradiction_detected():
    svc = SmartIngestionService()
    # Using identical noun-set to maximize overlap so confidence > 0.7.
    candidates = [{"content": "Joshua does not enjoy coffee mornings", "importance": 1.0}]

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[[0.0] * 4])
    existing = _fake_memory("old-1", "Joshua enjoys coffee mornings")
    new_mem = _fake_memory("new-1", "Joshua does not enjoy coffee mornings")

    with (
        patch("mypalace.retrieval.ingestion.vector_store") as vs,
        patch("mypalace.retrieval.ingestion.memory_service") as mem,
        patch("mypalace.retrieval.ingestion.async_session") as sess,
        patch("mypalace.retrieval.ingestion.dynamics_service") as dyn,
        patch.object(SmartIngestionService, "embedder", embedder),
    ):
        vs.search = AsyncMock(return_value=[("old-1", 0.85)])
        mem.get = AsyncMock(return_value=existing)
        mem.create = AsyncMock(return_value=new_mem)
        # async_session() context manager. db.add is sync; the others are awaited.
        from unittest.mock import MagicMock as _MagicMock
        fake_db = _MagicMock()
        fake_db.add = _MagicMock()
        fake_db.commit = AsyncMock()
        fake_db.refresh = AsyncMock()
        sess.return_value.__aenter__ = AsyncMock(return_value=fake_db)
        sess.return_value.__aexit__ = AsyncMock(return_value=None)
        dyn.demote = AsyncMock()

        written, supers, skipped = await svc.dedup_and_write(
            candidates=candidates, user_id="u1", agent_id="clara",
        )

    assert len(written) == 1
    assert len(supers) == 1
    assert supers[0]["superseded_id"] == "old-1"
    assert supers[0]["new_id"] == "new-1"
    assert "contradiction" in supers[0]["reason"]
    assert skipped == []


@pytest.mark.asyncio
async def test_dedup_skips_similar_when_no_contradiction():
    """Score is in the UPDATE band but content is just similar — should
    skip rather than supersede."""
    svc = SmartIngestionService()
    candidates = [{"content": "Joshua enjoys coffee daily", "importance": 1.0}]

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[[0.0] * 4])
    existing = _fake_memory("old-1", "Joshua loves coffee")

    with (
        patch("mypalace.retrieval.ingestion.vector_store") as vs,
        patch("mypalace.retrieval.ingestion.memory_service") as mem,
        patch.object(SmartIngestionService, "embedder", embedder),
    ):
        vs.search = AsyncMock(return_value=[("old-1", 0.80)])
        mem.get = AsyncMock(return_value=existing)
        mem.create = AsyncMock()

        written, supers, skipped = await svc.dedup_and_write(
            candidates=candidates, user_id="u1", agent_id="clara",
        )

    assert written == []
    assert supers == []
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "similar"
    mem.create.assert_not_awaited()


# ---------------------------------------------------------------------------
# Endpoint tests (mock fixture)
# ---------------------------------------------------------------------------


def test_supersede_endpoint_returns_record(client, mock_ingestion_service):
    mock_ingestion_service.supersede_memory = AsyncMock(return_value={
        "superseded_id": "old", "new_id": "new", "reason": "manual_correction",
    })
    resp = client.post(
        "/v1/memories/old/supersede",
        json={"user_id": "u1", "new_content": "updated fact"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["superseded_id"] == "old"
    assert body["data"]["new_id"] == "new"


def test_supersede_endpoint_404_when_missing(client, mock_ingestion_service):
    mock_ingestion_service.supersede_memory = AsyncMock(return_value=None)
    resp = client.post(
        "/v1/memories/missing/supersede",
        json={"user_id": "u1", "new_content": "x"},
    )
    assert resp.status_code == 404


def test_get_supersessions_endpoint(client, mock_ingestion_service):
    mock_ingestion_service.get_supersessions = AsyncMock(return_value=[
        {
            "superseded_id": "a", "new_id": "b",
            "reason": "manual_correction", "similarity_score": None,
            "created_at": "2026-05-03T00:00:00+00:00",
        },
    ])
    resp = client.get("/v1/memories/a/supersedes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["count"] == 1
    assert body["data"][0]["superseded_id"] == "a"
