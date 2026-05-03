"""Tests for session endpoints."""

from datetime import datetime


class FakeSession:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeMessage:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


FAKE_SESSION = FakeSession(
    id="sess-123",
    user_id="user-1",
    title="Test Chat",
    summary=None,
    created_at=datetime(2026, 1, 1, 12, 0, 0),
    updated_at=datetime(2026, 1, 1, 12, 0, 0),
)

FAKE_MESSAGE = FakeMessage(
    id="msg-1",
    session_id="sess-123",
    user_id="user-1",
    role="user",
    content="Hello",
    created_at=datetime(2026, 1, 1, 12, 0, 0),
)


def test_create_session(client, mock_session_service):
    mock_session_service.create.return_value = FAKE_SESSION

    resp = client.post("/v1/sessions", json={"user_id": "user-1", "title": "Test Chat"})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == "sess-123"
    assert data["title"] == "Test Chat"


def test_get_session(client, mock_session_service):
    mock_session_service.get.return_value = {
        "id": "sess-123",
        "user_id": "user-1",
        "title": "Test Chat",
        "summary": None,
        "created_at": "2026-01-01T12:00:00",
        "updated_at": "2026-01-01T12:00:00",
        "messages": [{"id": "msg-1", "role": "user", "content": "Hello"}],
    }

    resp = client.get("/v1/sessions/sess-123")

    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "sess-123"
    assert len(resp.json()["data"]["messages"]) == 1


def test_get_session_not_found(client, mock_session_service):
    mock_session_service.get.return_value = None

    resp = client.get("/v1/sessions/bad-id")

    assert resp.status_code == 404


def test_add_message(client, mock_session_service):
    mock_session_service.add_message.return_value = FAKE_MESSAGE

    resp = client.post("/v1/sessions/sess-123/messages", json={
        "user_id": "user-1",
        "role": "user",
        "content": "Hello",
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["content"] == "Hello"


def test_update_session(client, mock_session_service):
    updated = FakeSession(**{**FAKE_SESSION.__dict__, "title": "Updated"})
    mock_session_service.update.return_value = updated

    resp = client.patch("/v1/sessions/sess-123", json={"title": "Updated"})

    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "Updated"


def test_delete_session(client, mock_session_service):
    mock_session_service.delete.return_value = True

    resp = client.delete("/v1/sessions/sess-123")

    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True
