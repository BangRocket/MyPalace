"""Client tests for emotional-context endpoints using an httpx MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest
from mypalace_client.models import EmotionalContext

from mypalace_client import PalaceClient


def _client(handler) -> PalaceClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://palace.test")
    return PalaceClient(base_url="http://palace.test", api_key="k", client=http)


@pytest.mark.asyncio
async def test_record_emotional_context():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "ec1",
                    "user_id": "u1",
                    "agent_id": "default",
                    "channel_id": "",
                    "channel_name": "#dm",
                    "is_dm": True,
                    "starting_sentiment": -0.4,
                    "ending_sentiment": 0.5,
                    "emotional_arc": "improving",
                    "energy_level": "focused",
                    "topic_summary": "job search",
                    "created_at": "2026-05-31T00:00:00+00:00",
                },
                "meta": {"count": 1},
            },
        )

    pc = _client(handler)
    out = await pc.record_emotional_context(
        user_id="u1",
        messages=["bad", "ok", "good"],
        energy="focused",
        summary="job search",
        is_dm=True,
    )
    assert isinstance(out, EmotionalContext)
    assert out.emotional_arc == "improving"
    assert captured["path"] == "/v1/emotional/record"
    assert captured["body"]["messages"] == ["bad", "ok", "good"]


@pytest.mark.asyncio
async def test_get_emotional_context():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/users/u1/emotional-context"
        return httpx.Response(200, json={"data": [], "meta": {"count": 0}})

    pc = _client(handler)
    out = await pc.get_emotional_context(user_id="u1", limit=3, max_age_days=7)
    assert out == []
