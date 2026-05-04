"""Live smart-ingestion + supersede tests against real postgres + qdrant."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_smart_ingest_dedups_via_vector_similarity_live(http_client, stub_llm):
    """Two batch calls with infer=True extract the same memory; second
    call should record a duplicate skip rather than write a second copy."""
    user_id = "live-ingest-1"

    # Stub LLM to extract one memory each call.
    extract_response = json.dumps({
        "memories": [
            {
                "content": "Joshua works at Acme Corp as a senior engineer",
                "category": "fact",
                "importance": 0.8,
                "sensitivity": "low",
            },
        ],
    })

    stub_llm.next_response = extract_response
    r = await http_client.post("/v1/memories/batch", json={
        "user_id": user_id,
        "messages": [
            {"role": "user", "content": "I started at Acme as a senior engineer"},
        ],
        "infer": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["data"]) == 1
    written_id = body["data"][0]["id"]
    assert body["meta"]["skipped"] == []

    # Second call with the same extracted memory.
    stub_llm.next_response = extract_response
    r = await http_client.post("/v1/memories/batch", json={
        "user_id": user_id,
        "messages": [
            {"role": "user", "content": "I work at Acme as a senior engineer"},
        ],
        "infer": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Either skipped as duplicate or as similar; not written again.
    assert body["data"] == [] or all(m["id"] != written_id for m in body["data"])
    skipped_reasons = {s["reason"] for s in body["meta"]["skipped"]}
    assert skipped_reasons & {"duplicate", "similar"}, body["meta"]


@pytest.mark.asyncio
async def test_manual_supersede_creates_supersession_record_live(http_client):
    """Create a memory, manually supersede it, then GET supersedes and
    verify the audit row exists."""
    user_id = "live-ingest-2"

    r = await http_client.post("/v1/memories", json={
        "user_id": user_id,
        "content": "Joshua's favorite color is blue",
        "memory_type": "preference",
    })
    assert r.status_code == 200, r.text
    old_id = r.json()["data"]["id"]

    r = await http_client.post(
        f"/v1/memories/{old_id}/supersede",
        json={
            "user_id": user_id,
            "new_content": "Joshua's favorite color is green",
            "reason": "manual_correction",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["superseded_id"] == old_id
    new_id = body["new_id"]
    assert new_id != old_id
    assert body["reason"] == "manual_correction"

    # GET supersedes for the new memory should also return the row.
    r = await http_client.get(f"/v1/memories/{new_id}/supersedes")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert len(rows) == 1
    assert rows[0]["superseded_id"] == old_id
    assert rows[0]["new_id"] == new_id

    # GET supersedes for the old memory should return the same row.
    r = await http_client.get(f"/v1/memories/{old_id}/supersedes")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert len(rows) == 1
    assert rows[0]["superseded_id"] == old_id
