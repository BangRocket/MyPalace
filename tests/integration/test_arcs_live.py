"""End-to-end narrative arc tests with a stubbed LLM."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_synthesize_creates_arcs_live(http_client, stub_llm):
    # First seed an episode so synthesize_narratives has something to look at
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "user shared career frustration",
                "topics": ["career"],
                "emotional_tone": "frustrated",
                "significance": 0.7,
                "start_index": 0,
                "end_index": 0,
            },
        ]
    })
    seed_resp = await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={
            "user_id": "live-arc-1",
            "messages": [{"role": "user", "content": "I'm stuck at this job."}],
        },
    )
    assert seed_resp.status_code == 200

    # Now synthesize
    stub_llm.next_response = json.dumps({
        "arcs": [
            {
                "title": "Job search",
                "summary": "User is exploring leaving their current role.",
                "status": "active",
                "key_episode_ids": [seed_resp.json()["data"][0]["id"]],
                "emotional_trajectory": "frustrated",
                "existing_id": None,
            }
        ]
    })
    resp = await http_client.post(
        "/v1/synthesis/narratives?mode=sync",
        json={"user_id": "live-arc-1", "lookback_episodes": 20},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Job search"


@pytest.mark.asyncio
async def test_active_arcs_filters_by_status_live(http_client, stub_llm):
    """Create one active and one resolved arc; only active should show in /active."""
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "x",
                "topics": [],
                "emotional_tone": "neutral",
                "significance": 0.5,
                "start_index": 0,
                "end_index": 0,
            }
        ]
    })
    await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={"user_id": "live-arc-2", "messages": [{"role": "user", "content": "x"}]},
    )

    stub_llm.next_response = json.dumps({
        "arcs": [
            {
                "title": "Active arc",
                "summary": "S",
                "status": "active",
                "key_episode_ids": [],
                "emotional_trajectory": "",
                "existing_id": None,
            },
            {
                "title": "Resolved arc",
                "summary": "S",
                "status": "resolved",
                "key_episode_ids": [],
                "emotional_trajectory": "",
                "existing_id": None,
            },
        ]
    })
    await http_client.post(
        "/v1/synthesis/narratives?mode=sync",
        json={"user_id": "live-arc-2"},
    )

    resp = await http_client.get("/v1/users/live-arc-2/arcs/active?limit=10")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert all(a["status"] == "active" for a in data)
    titles = [a["title"] for a in data]
    assert "Active arc" in titles
    assert "Resolved arc" not in titles
