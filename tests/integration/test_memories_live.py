"""End-to-end memory CRUD/search/list/delete-all against live postgres + qdrant."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_get_delete_memory(http_client):
    # Create
    r = await http_client.post("/v1/memories", json={
        "user_id": "live-1",
        "content": "User loves dark mode",
        "memory_type": "preference",
        "metadata": {"category": "ui"},
    })
    assert r.status_code == 200
    mem_id = r.json()["data"]["id"]
    assert r.json()["data"]["metadata"] == {"category": "ui"}

    # Get
    r = await http_client.get(f"/v1/memories/{mem_id}")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == mem_id

    # Delete
    r = await http_client.delete(f"/v1/memories/{mem_id}")
    assert r.status_code == 200

    # Get again — should 404
    r = await http_client.get(f"/v1/memories/{mem_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_semantic_search_ranks_relevant_first(http_client):
    await http_client.post("/v1/memories", json={
        "user_id": "live-2", "content": "User uses Vim daily",
        "memory_type": "preference",
    })
    await http_client.post("/v1/memories", json={
        "user_id": "live-2", "content": "User is allergic to peanuts",
        "memory_type": "fact",
    })

    r = await http_client.post("/v1/memories/search", json={
        "query": "text editor preferences",
        "user_id": "live-2",
        "limit": 5,
    })
    assert r.status_code == 200
    results = r.json()["data"]
    assert len(results) >= 1
    assert "Vim" in results[0]["content"]


@pytest.mark.asyncio
async def test_batch_create_and_list(http_client):
    r = await http_client.post("/v1/memories/batch", json={
        "user_id": "live-3", "agent_id": "clara",
        "messages": [
            {"role": "user", "content": "I love dark mode"},
            {"role": "assistant", "content": "Got it"},
        ],
        "memory_type": "episodic",
        "metadata": {"session_id": "sess-1"},
    })
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2

    # List by metadata
    r = await http_client.post("/v1/memories/list", json={
        "user_id": "live-3",
        "metadata": {"session_id": "sess-1"},
    })
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2
    assert all(m["metadata"]["session_id"] == "sess-1" for m in data)


@pytest.mark.asyncio
async def test_list_filter_by_run_id(http_client):
    await http_client.post("/v1/memories/batch", json={
        "user_id": "live-4",
        "messages": [{"role": "user", "content": "x"}],
        "metadata": {"run_id": "r-aaa"},
    })
    await http_client.post("/v1/memories/batch", json={
        "user_id": "live-4",
        "messages": [{"role": "user", "content": "y"}],
        "metadata": {"run_id": "r-bbb"},
    })

    r = await http_client.post("/v1/memories/list", json={
        "user_id": "live-4", "run_id": "r-aaa",
    })
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["content"] == "x"


@pytest.mark.asyncio
async def test_delete_all_for_user(http_client):
    for content in ["a", "b", "c"]:
        await http_client.post("/v1/memories", json={
            "user_id": "live-5", "content": content,
        })

    # Verify they exist
    r = await http_client.get("/v1/users/live-5/memories")
    assert len(r.json()["data"]) == 3

    # Delete all
    r = await http_client.delete("/v1/users/live-5/memories")
    assert r.status_code == 200
    assert r.json()["data"]["deleted"] == 3

    # Verify gone
    r = await http_client.get("/v1/users/live-5/memories")
    assert len(r.json()["data"]) == 0


@pytest.mark.asyncio
async def test_delete_all_with_agent_filter(http_client):
    await http_client.post("/v1/memories", json={
        "user_id": "live-6", "content": "by clara", "agent_id": "clara",
    })
    await http_client.post("/v1/memories", json={
        "user_id": "live-6", "content": "by bob", "agent_id": "bob",
    })

    r = await http_client.delete("/v1/users/live-6/memories?agent_id=clara")
    assert r.json()["data"]["deleted"] == 1

    r = await http_client.get("/v1/users/live-6/memories")
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["agent_id"] == "bob"
