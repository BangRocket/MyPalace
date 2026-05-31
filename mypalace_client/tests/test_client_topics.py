"""Client tests for topic endpoints using an httpx MockTransport."""
from __future__ import annotations

import httpx
import pytest

from mypalace_client import PalaceClient
from mypalace_client.models import JobPending, TopicRecurrence


def _client(handler) -> PalaceClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://palace.test")
    return PalaceClient(base_url="http://palace.test", api_key="k", client=http)


@pytest.mark.asyncio
async def test_extract_topics_returns_job():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/topics/extract"
        return httpx.Response(202, json={"data": {"job_id": "job-1"}, "meta": {"count": 1}})

    pc = _client(handler)
    out = await pc.extract_topics(user_id="u1", conversation_text="x" * 60, conversation_sentiment=-0.2)
    assert isinstance(out, JobPending)
    assert out.job_id == "job-1"


@pytest.mark.asyncio
async def test_get_topic_recurrence():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/users/u1/topic-recurrence"
        return httpx.Response(200, json={"data": [{
            "topic": "job search", "topic_type": "theme", "mention_count": 3,
            "first_mentioned": "3 days ago", "last_mentioned": "yesterday",
            "sentiment_trend": "declining", "avg_emotional_weight": "heavy",
            "pattern_note": "recurring concern (3 mentions)", "channels": ["#dm"],
        }], "meta": {"count": 1}})

    pc = _client(handler)
    out = await pc.get_topic_recurrence(user_id="u1", lookback_days=14, min_mentions=2)
    assert len(out) == 1
    assert isinstance(out[0], TopicRecurrence)
    assert out[0].topic == "job search"
