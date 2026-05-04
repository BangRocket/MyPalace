"""End-to-end episode tests with a stubbed LLM."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_reflect_creates_episodes_live(http_client, stub_llm):
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "User shared a small win",
                "topics": ["work"],
                "emotional_tone": "happy",
                "significance": 0.6,
                "start_index": 0,
                "end_index": 1,
            }
        ]
    })

    resp = await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={
            "user_id": "live-ep-1",
            "messages": [
                {"role": "user", "content": "I shipped the migration today!"},
                {"role": "assistant", "content": "Nice — how do you feel?"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["summary"] == "User shared a small win"
    assert data[0]["significance"] == 0.6
    assert data[0]["user_id"] == "live-ep-1"


@pytest.mark.asyncio
async def test_search_episodes_live(http_client, stub_llm):
    """Seed two episodes via reflect, then search and verify they come back."""
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "shipped migration",
                "topics": ["work"],
                "emotional_tone": "happy",
                "significance": 0.7,
                "start_index": 0,
                "end_index": 0,
            },
            {
                "summary": "talked about Vim",
                "topics": ["editor"],
                "emotional_tone": "neutral",
                "significance": 0.4,
                "start_index": 1,
                "end_index": 1,
            },
        ]
    })
    await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={
            "user_id": "live-ep-2",
            "messages": [
                {"role": "user", "content": "Migration done."},
                {"role": "user", "content": "Vim is great."},
            ],
        },
    )

    resp = await http_client.post(
        "/v1/episodes/search",
        json={"query": "production deployment", "user_id": "live-ep-2", "limit": 5},
    )
    assert resp.status_code == 200
    results = resp.json()["data"]
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_recent_episodes_orders_newest_first_live(http_client, stub_llm):
    """Reflect twice; the newer episodes should appear first in /recent."""
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "older",
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
        json={"user_id": "live-ep-3", "messages": [{"role": "user", "content": "first"}]},
    )

    import asyncio
    await asyncio.sleep(0.05)  # ensure timestamp ordering

    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "newer",
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
        json={"user_id": "live-ep-3", "messages": [{"role": "user", "content": "second"}]},
    )

    resp = await http_client.get("/v1/users/live-ep-3/episodes/recent?limit=5")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 2
    assert data[0]["summary"] == "newer"


@pytest.mark.asyncio
async def test_search_filters_by_significance_live(http_client, stub_llm):
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "low sig",
                "topics": [],
                "emotional_tone": "neutral",
                "significance": 0.2,
                "start_index": 0,
                "end_index": 0,
            },
            {
                "summary": "high sig",
                "topics": [],
                "emotional_tone": "neutral",
                "significance": 0.8,
                "start_index": 0,
                "end_index": 0,
            },
        ]
    })
    await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={"user_id": "live-ep-4", "messages": [{"role": "user", "content": "x"}]},
    )

    resp = await http_client.post(
        "/v1/episodes/search",
        json={"query": "anything", "user_id": "live-ep-4", "limit": 5, "min_significance": 0.5},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Only the high-sig episode should be present
    assert all(e["significance"] >= 0.5 for e in data)
