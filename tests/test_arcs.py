"""Mock-based tests for ArcService."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from palace.arc_service import ArcService


@pytest.mark.asyncio
async def test_synthesize_creates_new_arcs():
    """synthesize_narratives calls the LLM with recent episodes + active arcs,
    parses the response, writes new arc rows."""
    svc = ArcService()

    fake_llm_response = json.dumps({
        "arcs": [
            {
                "title": "Job search",
                "summary": "User is exploring leaving current job.",
                "status": "active",
                "key_episode_ids": ["ep-1", "ep-2"],
                "emotional_trajectory": "frustrated -> determined",
                "existing_id": None,
            },
        ]
    })

    fake_recent_episodes = [
        {"id": "ep-1", "summary": "user shared frustration", "timestamp": "2026-06-01T00:00:00+00:00"},  # noqa: E501
        {"id": "ep-2", "summary": "user named what they want", "timestamp": "2026-06-02T00:00:00+00:00"},  # noqa: E501
    ]

    created_arc_holder: list = []

    class FakeArcServiceCreate:
        async def __call__(self, **fields):
            class FakeArc:
                pass
            arc = FakeArc()
            for k, v in fields.items():
                setattr(arc, k, v)
            arc.id = "arc-new"
            created_arc_holder.append(arc)
            return arc

    with (
        patch("palace.arc_service.episode_service.get_recent", new=AsyncMock(return_value=fake_recent_episodes)),  # noqa: E501
        patch("palace.arc_service.llm.complete", new=AsyncMock(return_value=fake_llm_response)),
        patch.object(svc, "get_active", new=AsyncMock(return_value=[])),
        patch.object(svc, "create", new=FakeArcServiceCreate()),
    ):
        arcs = await svc.synthesize_narratives(user_id="u1")

    assert len(arcs) == 1
    assert created_arc_holder[0].title == "Job search"
    assert created_arc_holder[0].status == "active"


@pytest.mark.asyncio
async def test_synthesize_updates_existing_arcs():
    """If LLM returns existing_id, the matching arc is updated, not created."""
    svc = ArcService()

    fake_llm_response = json.dumps({
        "arcs": [
            {
                "title": "Job search",
                "summary": "Updated summary.",
                "status": "resolved",
                "key_episode_ids": ["ep-1", "ep-2", "ep-3"],
                "emotional_trajectory": "frustrated -> determined -> relieved",
                "existing_id": "arc-existing",
            },
        ]
    })

    update_calls: list = []

    async def fake_update(arc_id, **fields):
        update_calls.append({"arc_id": arc_id, "fields": fields})
        class FakeArc:
            pass
        a = FakeArc()
        a.id = arc_id
        for k, v in fields.items():
            setattr(a, k, v)
        return a

    with (
        patch("palace.arc_service.episode_service.get_recent", new=AsyncMock(return_value=[])),
        patch("palace.arc_service.llm.complete", new=AsyncMock(return_value=fake_llm_response)),
        patch.object(svc, "get_active", new=AsyncMock(return_value=[])),
        patch.object(svc, "update", new=fake_update),
        patch.object(svc, "create", new=AsyncMock()) as mock_create,
    ):
        arcs = await svc.synthesize_narratives(user_id="u1")
        mock_create.assert_not_called()

    assert len(update_calls) == 1
    assert update_calls[0]["arc_id"] == "arc-existing"
    assert update_calls[0]["fields"]["status"] == "resolved"
    assert len(arcs) == 1


@pytest.mark.asyncio
async def test_synthesize_raises_on_garbage_llm():
    svc = ArcService()
    with (
        patch("palace.arc_service.episode_service.get_recent", new=AsyncMock(return_value=[])),
        patch("palace.arc_service.llm.complete", new=AsyncMock(return_value="not json")),
        patch.object(svc, "get_active", new=AsyncMock(return_value=[])),
        pytest.raises(ValueError, match="(?i)json|parse"),
    ):
        await svc.synthesize_narratives(user_id="u1")


class FakeArc:
    def __init__(self, **kw):
        self.id = kw.get("id", "arc-1")
        self.user_id = kw.get("user_id", "u1")
        self.agent_id = kw.get("agent_id")
        self.title = kw.get("title", "T")
        self.summary = kw.get("summary", "S")
        self.status = kw.get("status", "active")
        self.key_episode_ids = kw.get("key_episode_ids", [])
        self.emotional_trajectory = kw.get("emotional_trajectory", "")
        from datetime import UTC, datetime
        self.created_at = kw.get("created_at", datetime.now(UTC))
        self.updated_at = kw.get("updated_at", datetime.now(UTC))


def test_synthesize_narratives_sync(client, mock_arc_service):
    mock_arc_service.synthesize_narratives.return_value = [FakeArc(id="arc-new")]
    resp = client.post(
        "/v1/synthesis/narratives?mode=sync",
        json={"user_id": "u1", "lookback_episodes": 20},
    )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "arc-new"


def test_synthesize_narratives_async(client, mock_arc_service, mock_job_service):
    from unittest.mock import MagicMock
    fake_job = MagicMock()
    fake_job.id = "job-syn"
    mock_job_service.run_async.return_value = fake_job

    resp = client.post("/v1/synthesis/narratives", json={"user_id": "u1"})
    assert resp.status_code == 202
    assert resp.json()["data"]["job_id"] == "job-syn"


def test_active_arcs(client, mock_arc_service):
    mock_arc_service.get_active.return_value = [FakeArc(id="a1", title="Job search")]
    resp = client.get("/v1/users/u1/arcs/active?limit=5")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["title"] == "Job search"


@pytest.mark.asyncio
async def test_synthesize_strips_json_markdown_fence():
    """Same fence-stripping for synthesis path."""
    svc = ArcService()

    fenced = (
        "```json\n"
        + json.dumps({
            "arcs": [{
                "title": "T", "summary": "S", "status": "active",
                "key_episode_ids": [], "emotional_trajectory": "",
                "existing_id": None,
            }]
        })
        + "\n```"
    )

    async def fake_create(**fields):
        class FakeArc:
            pass
        a = FakeArc()
        a.id = "arc-fenced"
        for k, v in fields.items():
            setattr(a, k, v)
        return a

    with (
        patch("palace.arc_service.episode_service.get_recent", new=AsyncMock(return_value=[])),
        patch("palace.arc_service.llm.complete", new=AsyncMock(return_value=fenced)),
        patch.object(svc, "get_active", new=AsyncMock(return_value=[])),
        patch.object(svc, "create", new=fake_create),
    ):
        arcs = await svc.synthesize_narratives(user_id="u1")

    assert len(arcs) == 1
    assert arcs[0].id == "arc-fenced"
