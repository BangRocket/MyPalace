"""Tests for memory endpoints."""

from datetime import datetime


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
