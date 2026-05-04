"""Live layered-retrieval tests against real postgres + qdrant."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_layered_context_assembles_all_layers_live(http_client, stub_llm):
    """Seed memories + episodes + arcs, then POST /v1/context/layered and
    verify each section is populated."""
    user_id = "live-layered-1"

    # Seed three memories.
    for content in (
        "Joshua works at Acme Corp",
        "Joshua prefers Python over Java",
        "Joshua likes hiking on weekends",
    ):
        r = await http_client.post("/v1/memories", json={
            "user_id": user_id,
            "content": content,
            "memory_type": "semantic",
        })
        assert r.status_code == 200, r.text

    # Reflect a session to seed an episode.
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "Discussion about hiking plans",
                "topics": ["hiking", "weekend"],
                "emotional_tone": "positive",
                "significance": 0.7,
                "start_index": 0,
                "end_index": 1,
            },
        ],
    })
    r = await http_client.post(
        "/v1/reflection/session?mode=sync",
        json={
            "user_id": user_id,
            "messages": [
                {"role": "user", "content": "Going hiking this weekend"},
                {"role": "assistant", "content": "Sounds great!"},
            ],
        },
    )
    assert r.status_code == 200, r.text

    # Synthesize an arc from the episode.
    stub_llm.next_response = json.dumps({
        "arcs": [
            {
                "title": "Outdoor recreation",
                "summary": "Joshua enjoys hiking",
                "status": "active",
                "key_episode_ids": [],
                "emotional_trajectory": "positive",
            },
        ],
    })
    r = await http_client.post(
        "/v1/synthesis/narratives?mode=sync",
        json={"user_id": user_id, "lookback_episodes": 5},
    )
    assert r.status_code == 200, r.text

    # Now request layered context.
    r = await http_client.post("/v1/context/layered", json={
        "user_id": user_id,
        "query": "weekend plans",
        "use_fsrs": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert "l1_user_profile" in body
    assert "l2_relevant_context" in body
    assert len(body["l1_user_profile"]["memories"]) > 0
    assert len(body["l1_user_profile"]["active_arcs"]) == 1
    assert body["l1_user_profile"]["active_arcs"][0]["title"] == "Outdoor recreation"
    # Char counts should reflect the kept memories.
    assert body["char_counts"]["l1"] > 0


@pytest.mark.asyncio
async def test_layered_context_fsrs_reranks_when_enabled_live(http_client):
    """Seed two near-duplicate memories, promote one, ask layered with
    use_fsrs=true — the promoted one should rank higher in L2."""
    user_id = "live-layered-2"

    # Two semantically similar memories.
    r = await http_client.post("/v1/memories", json={
        "user_id": user_id,
        "content": "Joshua loves coffee in the morning",
        "memory_type": "preference",
    })
    assert r.status_code == 200
    promoted_id = r.json()["data"]["id"]

    r = await http_client.post("/v1/memories", json={
        "user_id": user_id,
        "content": "Joshua enjoys coffee with breakfast",
        "memory_type": "preference",
    })
    assert r.status_code == 200
    other_id = r.json()["data"]["id"]

    # Promote one with a high grade — high stability + storage_strength.
    r = await http_client.post(
        f"/v1/memories/{promoted_id}/promote",
        json={"user_id": user_id, "grade": 4, "signal_type": "used_in_response"},
    )
    assert r.status_code == 200, r.text

    # Layered with FSRS on.
    r = await http_client.post("/v1/context/layered", json={
        "user_id": user_id,
        "query": "coffee morning routine",
        "use_fsrs": True,
        "memory_limit": 5,
    })
    assert r.status_code == 200, r.text
    l2_mems = r.json()["data"]["l2_relevant_context"]["memories"]
    # Both memories should appear in L2.
    assert {m["id"] for m in l2_mems} >= {promoted_id, other_id}

    promoted_pos = next(i for i, m in enumerate(l2_mems) if m["id"] == promoted_id)
    other_pos = next(i for i, m in enumerate(l2_mems) if m["id"] == other_id)
    # Promoted should rank ahead of the un-promoted near-duplicate.
    assert promoted_pos < other_pos
    # Composite scores were computed.
    assert l2_mems[promoted_pos]["composite_score"] is not None
