"""Mock-based tests for EpisodeService and routes."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.episode_service import EpisodeService


@pytest.mark.asyncio
async def test_reflect_session_calls_llm_and_writes_episodes():
    """reflect_session should call the LLM, parse JSON, write 1+ episodes
    to Qdrant, and return the parsed list."""
    svc = EpisodeService()

    fake_llm_response = json.dumps({
        "episodes": [
            {
                "summary": "User shared career frustration",
                "topics": ["career", "growth"],
                "emotional_tone": "frustrated",
                "significance": 0.7,
                "start_index": 0,
                "end_index": 1,
            },
        ]
    })

    messages = [
        {"role": "user", "content": "I haven't grown in two years."},
        {"role": "assistant", "content": "What would change that?"},
    ]

    fake_embedder = MagicMock(embed=AsyncMock(return_value=[[0.1] * 384]))
    with (
        patch("mypalace.episode_service.llm.complete",
              new=AsyncMock(return_value=fake_llm_response)),
        patch.object(svc, "_embedder", create=True, new=fake_embedder),
        patch("mypalace.episode_service.episode_vector_store.upsert",
              new=AsyncMock()) as mock_upsert,
    ):
        episodes = await svc.reflect_session(
            messages=messages, user_id="u1", agent_id="clara", session_id="s-123",
        )

    assert len(episodes) == 1
    ep = episodes[0]
    assert ep["summary"] == "User shared career frustration"
    assert ep["user_id"] == "u1"
    assert ep["agent_id"] == "clara"
    assert ep["session_id"] == "s-123"
    assert ep["topics"] == ["career", "growth"]
    assert ep["significance"] == 0.7
    assert "id" in ep
    assert mock_upsert.called


@pytest.mark.asyncio
async def test_reflect_session_raises_on_llm_returns_garbage():
    """If the LLM returns non-JSON, we raise — no silent fallback (Joshua's
    'fail loudly' rule)."""
    svc = EpisodeService()

    with (
        patch("mypalace.episode_service.llm.complete",
              new=AsyncMock(return_value="not json at all")),
        patch.object(svc, "_embedder", create=True, new=MagicMock(embed=AsyncMock())),
        pytest.raises(ValueError, match="(?i)json|parse"),
    ):
        await svc.reflect_session(messages=[{"role": "user", "content": "hi"}], user_id="u1")


@pytest.mark.asyncio
async def test_search_episodes_filters_by_significance():
    """search() should pass min_significance into the Qdrant query."""
    svc = EpisodeService()

    fake_results = [
        ("ep-1", 0.95),
        ("ep-2", 0.81),
    ]
    fake_payloads = {  # noqa: E501
        "ep-1": {"summary": "one", "user_id": "u1", "significance": 0.7, "content": "x", "timestamp": "2026-01-01T00:00:00+00:00", "agent_id": None, "session_id": None, "participants": [], "topics": [], "emotional_tone": "neutral", "message_count": 0},  # noqa: E501
        "ep-2": {"summary": "two", "user_id": "u1", "significance": 0.5, "content": "x", "timestamp": "2026-01-01T00:00:00+00:00", "agent_id": None, "session_id": None, "participants": [], "topics": [], "emotional_tone": "neutral", "message_count": 0},  # noqa: E501
    }

    async def fake_query_points(**kwargs):
        # Verify min_significance was applied in the filter
        f = kwargs.get("query_filter")
        assert f is not None  # filter applied
        # Return points with payloads
        from types import SimpleNamespace
        return SimpleNamespace(points=[
            SimpleNamespace(id=eid, score=score, payload=fake_payloads[eid])
            for eid, score in fake_results
        ])

    fake_embedder = MagicMock(embed=AsyncMock(return_value=[[0.1] * 384]))
    qp_path = "mypalace.episode_service.episode_vector_store.client.query_points"
    with (
        patch.object(svc, "_embedder", create=True, new=fake_embedder),
        patch(qp_path, new=fake_query_points),
    ):
        results = await svc.search(query="career", user_id="u1", min_significance=0.3, limit=5)

    assert len(results) == 2
    assert results[0]["id"] == "ep-1"


@pytest.mark.asyncio
async def test_get_recent_orders_by_timestamp_desc():
    """get_recent should return episodes newest-first."""
    svc = EpisodeService()

    older = "2026-01-01T00:00:00+00:00"
    newer = "2026-06-01T00:00:00+00:00"

    fake_payloads = [
        {"id": "ep-old", "summary": "old", "user_id": "u1", "timestamp": older, "content": "x", "significance": 0.5, "agent_id": None, "session_id": None, "participants": [], "topics": [], "emotional_tone": "neutral", "message_count": 0},  # noqa: E501
        {"id": "ep-new", "summary": "new", "user_id": "u1", "timestamp": newer, "content": "x", "significance": 0.5, "agent_id": None, "session_id": None, "participants": [], "topics": [], "emotional_tone": "neutral", "message_count": 0},  # noqa: E501
    ]

    async def fake_scroll(**kwargs):
        from types import SimpleNamespace
        points = [SimpleNamespace(id=p["id"], payload=p) for p in fake_payloads]
        return (points, None)  # qdrant scroll returns (points, next_offset)

    with patch("mypalace.episode_service.episode_vector_store.client.scroll", new=fake_scroll):
        results = await svc.get_recent(user_id="u1", limit=5)

    assert len(results) == 2
    # Newest first
    assert results[0]["id"] == "ep-new"
    assert results[1]["id"] == "ep-old"


def test_reflect_session_sync_returns_episodes(client, mock_episode_service):
    """POST /v1/reflection/session?mode=sync calls service and returns episodes."""
    mock_episode_service.reflect_session.return_value = [
        {
            "id": "ep-1", "user_id": "u1", "agent_id": "clara",
            "content": "x", "summary": "s",
            "participants": ["user"], "topics": ["t"],
            "emotional_tone": "neutral", "significance": 0.5,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "session_id": "s-1", "message_count": 1,
        }
    ]

    resp = client.post(
        "/v1/reflection/session?mode=sync",
        json={
            "user_id": "u1",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == "ep-1"
    mock_episode_service.reflect_session.assert_awaited_once()


def test_reflect_session_async_returns_job_id(client, mock_episode_service, mock_job_service):
    """Default async mode returns 202 + job_id."""
    fake_job = MagicMock()
    fake_job.id = "job-abc"
    mock_job_service.run_async.return_value = fake_job

    resp = client.post(
        "/v1/reflection/session",
        json={
            "user_id": "u1",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data["job_id"] == "job-abc"
    assert data["status"] == "pending"
    mock_job_service.run_async.assert_awaited_once()


def test_search_episodes(client, mock_episode_service):
    mock_episode_service.search.return_value = [
        {
            "id": "ep-1", "user_id": "u1", "agent_id": None,
            "content": "x", "summary": "s",
            "participants": [], "topics": [],
            "emotional_tone": "neutral", "significance": 0.5,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "session_id": None, "message_count": 0, "score": 0.95,
        }
    ]
    resp = client.post(
        "/v1/episodes/search",
        json={"query": "career", "user_id": "u1", "limit": 5, "min_significance": 0.3},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data[0]["score"] == 0.95


def test_recent_episodes(client, mock_episode_service):
    mock_episode_service.get_recent.return_value = [
        {
            "id": "ep-x", "user_id": "u1", "agent_id": None,
            "content": "x", "summary": "s",
            "participants": [], "topics": [],
            "emotional_tone": "neutral", "significance": 0.5,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "session_id": None, "message_count": 0,
        }
    ]
    resp = client.get("/v1/users/u1/episodes/recent?limit=10")
    assert resp.status_code == 200
    assert resp.json()["meta"]["count"] == 1


@pytest.mark.asyncio
async def test_reflect_strips_json_markdown_fence():
    """LLM that wraps response in ```json ... ``` should still parse cleanly."""
    svc = EpisodeService()

    fenced_response = (
        "```json\n"
        + json.dumps({
            "episodes": [{
                "summary": "fenced response",
                "topics": ["x"],
                "emotional_tone": "neutral",
                "significance": 0.5,
                "start_index": 0,
                "end_index": 0,
            }]
        })
        + "\n```"
    )

    fake_embedder = MagicMock(embed=AsyncMock(return_value=[[0.1] * 384]))
    with (
        patch("mypalace.episode_service.llm.complete", new=AsyncMock(return_value=fenced_response)),
        patch.object(svc, "_embedder", create=True, new=fake_embedder),
        patch("mypalace.episode_service.episode_vector_store.upsert", new=AsyncMock()),
    ):
        episodes = await svc.reflect_session(
            messages=[{"role": "user", "content": "x"}], user_id="u1",
        )

    assert len(episodes) == 1
    assert episodes[0]["summary"] == "fenced response"
