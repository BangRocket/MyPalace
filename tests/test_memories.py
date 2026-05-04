"""Tests for memory endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock
from unittest.mock import patch as patch_obj

import pytest


class FakeMemory:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


FAKE_MEMORY = FakeMemory(
    id="mem-123",
    user_id="user-1",
    agent_id=None,
    content="User likes dark mode",
    memory_type="preference",
    source=None,
    importance=2.0,
    created_at=datetime(2026, 1, 1, 12, 0, 0),
    updated_at=datetime(2026, 1, 1, 12, 0, 0),
    accessed_at=None,
    access_count=0,
    metadata_json=None,
)


def test_create_memory(client, mock_memory_service):
    mock_memory_service.create.return_value = FAKE_MEMORY

    resp = client.post("/v1/memories", json={
        "user_id": "user-1",
        "content": "User likes dark mode",
        "memory_type": "preference",
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == "mem-123"
    assert data["content"] == "User likes dark mode"
    mock_memory_service.create.assert_called_once()


def test_search_memories(client, mock_memory_service):
    mock_memory_service.search.return_value = [(FAKE_MEMORY, 0.92)]

    resp = client.post("/v1/memories/search", json={
        "query": "user preferences",
        "user_id": "user-1",
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["score"] == 0.92


def test_get_memory_found(client, mock_memory_service):
    mock_memory_service.get.return_value = FAKE_MEMORY

    resp = client.get("/v1/memories/mem-123")

    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "mem-123"


def test_get_memory_not_found(client, mock_memory_service):
    mock_memory_service.get.return_value = None

    resp = client.get("/v1/memories/bad-id")

    assert resp.status_code == 404


def test_update_memory(client, mock_memory_service):
    updated = FakeMemory(**{**FAKE_MEMORY.__dict__, "content": "Updated content"})
    mock_memory_service.update.return_value = updated

    resp = client.patch("/v1/memories/mem-123", json={"content": "Updated content"})

    assert resp.status_code == 200
    assert resp.json()["data"]["content"] == "Updated content"


def test_delete_memory(client, mock_memory_service):
    mock_memory_service.delete.return_value = True

    resp = client.delete("/v1/memories/mem-123")

    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_list_user_memories(client, mock_memory_service):
    mock_memory_service.list_for_user.return_value = [FAKE_MEMORY]

    resp = client.get("/v1/users/user-1/memories")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["user_id"] == "user-1"


def test_create_memory_with_dict_metadata(client, mock_memory_service):
    """Slice-1 contract: metadata is a dict on the wire AND in the model.
    No more json.loads at the API boundary."""
    memory_with_meta = FakeMemory(
        id="mem-meta-1",
        user_id="user-1",
        agent_id=None,
        content="With metadata",
        memory_type="preference",
        source=None,
        importance=1.0,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        updated_at=datetime(2026, 1, 1, 12, 0, 0),
        accessed_at=None,
        access_count=0,
        metadata_json={"category": "ui", "confidence": 0.9},
    )
    mock_memory_service.create.return_value = memory_with_meta

    resp = client.post("/v1/memories", json={
        "user_id": "user-1",
        "content": "With metadata",
        "metadata": {"category": "ui", "confidence": 0.9},
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["metadata"] == {"category": "ui", "confidence": 0.9}


def test_batch_create_memories(client, mock_memory_service):
    """One memory per input message, role merged into per-memory metadata."""
    m1 = FakeMemory(
        id="m-batch-1", user_id="u1", agent_id="clara",
        content="I love dark mode", memory_type="episodic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0,
        metadata_json={"role": "user", "session_id": "s1"},
    )
    m2 = FakeMemory(
        id="m-batch-2", user_id="u1", agent_id="clara",
        content="Got it", memory_type="episodic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0,
        metadata_json={"role": "assistant", "session_id": "s1"},
    )
    mock_memory_service.create_batch = AsyncMock(
        return_value={"memories": [m1, m2], "supersessions": [], "skipped": []},
    )

    resp = client.post("/v1/memories/batch", json={
        "user_id": "u1",
        "agent_id": "clara",
        "messages": [
            {"role": "user", "content": "I love dark mode"},
            {"role": "assistant", "content": "Got it"},
        ],
        "memory_type": "episodic",
        "metadata": {"session_id": "s1"},
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 2
    assert data[0]["content"] == "I love dark mode"
    assert data[0]["metadata"] == {"role": "user", "session_id": "s1"}
    assert data[1]["metadata"] == {"role": "assistant", "session_id": "s1"}


def test_batch_create_per_message_keys_win(client, mock_memory_service):
    """Per-message metadata keys override request-level metadata on collision."""
    m = FakeMemory(
        id="m-batch-3", user_id="u1", agent_id=None,
        content="hi", memory_type="episodic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0,
        metadata_json={"role": "user", "session_id": "from_message"},
    )
    mock_memory_service.create_batch = AsyncMock(
        return_value={"memories": [m], "supersessions": [], "skipped": []},
    )

    resp = client.post("/v1/memories/batch", json={
        "user_id": "u1",
        "messages": [{"role": "user", "content": "hi", "session_id": "from_message"}],
        "metadata": {"session_id": "from_request"},
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data[0]["metadata"]["session_id"] == "from_message"


@pytest.mark.asyncio
async def test_create_batch_merges_metadata_per_message_keys_win():
    """Direct unit test of MemoryService.create_batch: per-message keys
    must win over request-level metadata when keys collide."""
    from mypalace.memory_service import MemoryService

    svc = MemoryService()
    captured_calls = []

    async def fake_create(**kwargs):
        captured_calls.append(kwargs)
        return FakeMemory(
            id=f"m-{len(captured_calls)}",
            user_id=kwargs["user_id"],
            agent_id=kwargs.get("agent_id"),
            content=kwargs["content"],
            memory_type=kwargs.get("memory_type", "semantic"),
            source=kwargs.get("source"),
            importance=kwargs.get("importance", 1.0),
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            accessed_at=None,
            access_count=0,
            metadata_json=kwargs.get("metadata"),
        )

    with patch_obj.object(svc, "create", side_effect=fake_create):
        await svc.create_batch(
            user_id="u1",
            messages=[
                {"role": "user", "content": "hi", "session_id": "from_message"},
                {"role": "assistant", "content": "hey"},
            ],
            metadata={"session_id": "from_request", "shared": "x"},
        )

    # Per-message session_id wins; shared still inherited from request
    assert captured_calls[0]["metadata"] == {
        "session_id": "from_message", "shared": "x", "role": "user",
    }
    # Second message has no session_id, so request value is used
    assert captured_calls[1]["metadata"] == {
        "session_id": "from_request", "shared": "x", "role": "assistant",
    }


def test_batch_create_infer_calls_smart_ingestion(client, mock_memory_service):
    """Slice 5: ``infer=True`` activates the smart-ingestion path. The
    service receives infer=True and returns a {memories, supersessions,
    skipped} envelope; the route flattens that into data + meta."""
    m = FakeMemory(
        id="m-batch-4", user_id="u1", agent_id=None,
        content="hi", memory_type="episodic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0,
        metadata_json={"role": "user"},
    )
    mock_memory_service.create_batch = AsyncMock(return_value={
        "memories": [m],
        "supersessions": [
            {"superseded_id": "old", "new_id": "m-batch-4",
             "similarity": 0.78, "reason": "contradiction:negation:overlap"},
        ],
        "skipped": [{"reason": "duplicate", "similarity": 0.97}],
    })

    resp = client.post("/v1/memories/batch", json={
        "user_id": "u1",
        "messages": [{"role": "user", "content": "hi"}],
        "infer": True,
    })

    assert resp.status_code == 200
    # The route should pass infer=True through.
    kwargs = mock_memory_service.create_batch.call_args.kwargs
    assert kwargs.get("infer") is True
    body = resp.json()
    assert body["meta"]["supersessions"][0]["superseded_id"] == "old"
    assert body["meta"]["skipped"][0]["reason"] == "duplicate"


def test_list_memories_no_filters(client, mock_memory_service):
    m = FakeMemory(
        id="m-list-1", user_id="u1", agent_id=None,
        content="x", memory_type="semantic",
        source=None, importance=1.0,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        accessed_at=None, access_count=0, metadata_json=None,
    )
    mock_memory_service.list_filtered = AsyncMock(return_value=[m])

    resp = client.post("/v1/memories/list", json={})

    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1
    # Defaults: limit=50, offset=0, all filters None
    kwargs = mock_memory_service.list_filtered.call_args.kwargs
    assert kwargs == {
        "user_id": None, "agent_id": None, "run_id": None,
        "memory_type": None, "metadata": None,
        "limit": 50, "offset": 0, "tenant_id": "test",
    }


def test_list_memories_with_filters(client, mock_memory_service):
    mock_memory_service.list_filtered = AsyncMock(return_value=[])

    resp = client.post("/v1/memories/list", json={
        "user_id": "u1",
        "agent_id": "clara",
        "run_id": "session-123",
        "memory_type": "preference",
        "metadata": {"category": "ui"},
        "limit": 25,
        "offset": 100,
    })

    assert resp.status_code == 200
    kwargs = mock_memory_service.list_filtered.call_args.kwargs
    assert kwargs["user_id"] == "u1"
    assert kwargs["agent_id"] == "clara"
    assert kwargs["run_id"] == "session-123"
    assert kwargs["memory_type"] == "preference"
    assert kwargs["metadata"] == {"category": "ui"}
    assert kwargs["limit"] == 25
    assert kwargs["offset"] == 100


def test_list_memories_clamps_limit(client, mock_memory_service):
    """limit > 500 is server-clamped to 500."""
    mock_memory_service.list_filtered = AsyncMock(return_value=[])

    resp = client.post("/v1/memories/list", json={"limit": 9999})

    assert resp.status_code == 200
    kwargs = mock_memory_service.list_filtered.call_args.kwargs
    assert kwargs["limit"] == 500


def test_delete_user_memories_no_filters(client, mock_memory_service):
    mock_memory_service.delete_for_user = AsyncMock(return_value=12)

    resp = client.delete("/v1/users/u1/memories")

    assert resp.status_code == 200
    assert resp.json()["data"] == {"deleted": 12}
    kwargs = mock_memory_service.delete_for_user.call_args.kwargs
    assert kwargs["user_id"] == "u1"
    assert kwargs["agent_id"] is None
    assert kwargs["run_id"] is None


def test_delete_user_memories_with_filters(client, mock_memory_service):
    mock_memory_service.delete_for_user = AsyncMock(return_value=0)

    resp = client.delete("/v1/users/u1/memories?agent_id=clara&run_id=s-123")

    assert resp.status_code == 200
    assert resp.json()["data"] == {"deleted": 0}
    kwargs = mock_memory_service.delete_for_user.call_args.kwargs
    assert kwargs["agent_id"] == "clara"
    assert kwargs["run_id"] == "s-123"
