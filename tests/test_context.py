"""Tests for context assembly endpoint."""


def test_assemble_context(client, mock_context_service):
    mock_context_service.assemble.return_value = {
        "memories": [
            {"id": "m1", "content": "User likes Python", "score": 0.95},
        ],
        "recent_messages": [
            {"role": "user", "content": "What lang should I use?"},
        ],
        "summary": "Discussing programming languages",
    }

    resp = client.post("/v1/context", json={
        "user_id": "user-1",
        "query": "programming preferences",
        "session_id": "sess-123",
    })

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["memories"]) == 1
    assert len(data["recent_messages"]) == 1
    assert data["summary"] == "Discussing programming languages"
