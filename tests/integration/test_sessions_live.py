"""End-to-end session/message lifecycle against live postgres."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_session_lifecycle(http_client):
    # Create
    r = await http_client.post("/v1/sessions", json={
        "user_id": "live-s1", "title": "Test chat",
    })
    assert r.status_code == 200
    sid = r.json()["data"]["id"]

    # Add messages
    for role, content in [("user", "Hello"), ("assistant", "Hi there")]:
        r = await http_client.post(f"/v1/sessions/{sid}/messages", json={
            "user_id": "live-s1", "role": role, "content": content,
        })
        assert r.status_code == 200

    # Fetch with messages
    r = await http_client.get(f"/v1/sessions/{sid}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["title"] == "Test chat"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "Hello"

    # Update
    r = await http_client.patch(f"/v1/sessions/{sid}", json={"summary": "S"})
    assert r.json()["data"]["summary"] == "S"

    # Delete (cascades messages)
    r = await http_client.delete(f"/v1/sessions/{sid}")
    assert r.status_code == 200

    # Get → 404
    r = await http_client.get(f"/v1/sessions/{sid}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_assemble_context_with_session(http_client):
    # Seed a memory
    await http_client.post("/v1/memories", json={
        "user_id": "live-s2", "content": "User uses Vim",
        "memory_type": "preference",
    })

    # Create a session and add a message
    r = await http_client.post("/v1/sessions", json={"user_id": "live-s2"})
    sid = r.json()["data"]["id"]
    await http_client.post(f"/v1/sessions/{sid}/messages", json={
        "user_id": "live-s2", "role": "user", "content": "What editor?",
    })

    # Assemble
    r = await http_client.post("/v1/context", json={
        "user_id": "live-s2",
        "query": "editor preferences",
        "session_id": sid,
        "max_memories": 5,
    })
    assert r.status_code == 200
    ctx = r.json()["data"]
    assert len(ctx["memories"]) >= 1
    assert "Vim" in ctx["memories"][0]["content"]
    assert len(ctx["recent_messages"]) == 1
