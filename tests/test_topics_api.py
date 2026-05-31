"""Contract tests for /v1/topics routes (service + job mocked via conftest)."""

from __future__ import annotations


def test_extract_returns_202_with_job(client, mock_job_service):
    job = type("J", (), {"id": "job-1"})()
    mock_job_service.run_async.return_value = job
    resp = client.post(
        "/v1/topics/extract",
        json={
            "user_id": "u1",
            "conversation_text": "x" * 60,
            "conversation_sentiment": -0.2,
        },
    )
    assert resp.status_code == 202
    assert resp.json()["data"]["job_id"] == "job-1"


def test_topic_recurrence_returns_list(client, mock_topic_service):
    mock_topic_service.get_recurrence.return_value = [
        {
            "topic": "job search",
            "topic_type": "theme",
            "mention_count": 3,
            "first_mentioned": "3 days ago",
            "last_mentioned": "yesterday",
            "sentiment_trend": "declining",
            "avg_emotional_weight": "heavy",
            "pattern_note": "recurring concern (3 mentions)",
            "channels": ["#dm"],
        }
    ]
    resp = client.get(
        "/v1/users/u1/topic-recurrence",
        params={"lookback_days": 14, "min_mentions": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["topic"] == "job search"
    mock_topic_service.get_recurrence.assert_awaited_once()
