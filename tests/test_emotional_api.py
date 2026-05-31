"""Contract tests for /v1/emotional routes (service mocked via conftest)."""
from __future__ import annotations

from datetime import UTC, datetime

from mypalace.models import EmotionalContext


def test_record_returns_200_and_calls_service(client, mock_emotional_service):
    mock_emotional_service.record.return_value = EmotionalContext(
        id="ec1", tenant_id="test", user_id="u1", agent_id="default",
        channel_id="", channel_name="#dm", is_dm=True,
        starting_sentiment=-0.4, ending_sentiment=0.5, emotional_arc="improving",
        energy_level="focused", topic_summary="job search",
        created_at=datetime(2026, 5, 31, tzinfo=UTC),
    )
    resp = client.post("/v1/emotional/record", json={
        "user_id": "u1", "messages": ["bad", "ok", "good"],
        "energy": "focused", "summary": "job search", "is_dm": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["emotional_arc"] == "improving"
    mock_emotional_service.record.assert_awaited_once()


def test_get_emotional_context_returns_list(client, mock_emotional_service):
    mock_emotional_service.get_recent.return_value = []
    resp = client.get("/v1/users/u1/emotional-context", params={"limit": 3, "max_age_days": 7})
    assert resp.status_code == 200
    assert resp.json()["data"] == []
    mock_emotional_service.get_recent.assert_awaited_once()
