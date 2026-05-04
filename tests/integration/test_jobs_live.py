"""End-to-end async job lifecycle tests."""

from __future__ import annotations

import asyncio
import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_async_reflection_job_lifecycle_live(http_client, stub_llm):
    stub_llm.next_response = json.dumps({
        "episodes": [
            {
                "summary": "x",
                "topics": [],
                "emotional_tone": "neutral",
                "significance": 0.5,
                "start_index": 0,
                "end_index": 0,
            }
        ]
    })

    # POST async — returns 202 + job_id immediately
    resp = await http_client.post(
        "/v1/reflection/session",
        json={"user_id": "live-job-1", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 202
    job_id = resp.json()["data"]["job_id"]

    # Poll until completed (or timeout)
    final = None
    for _ in range(40):
        await asyncio.sleep(0.1)
        r = await http_client.get(f"/v1/jobs/{job_id}")
        assert r.status_code == 200
        body = r.json()["data"]
        if body["status"] in {"completed", "failed"}:
            final = body
            break

    assert final is not None, "job did not finish in time"
    assert final["status"] == "completed"
    assert isinstance(final["result"], list)
    assert len(final["result"]) == 1
    assert final["result"][0]["summary"] == "x"


@pytest.mark.asyncio
async def test_async_job_failure_is_recorded_live(http_client, stub_llm):
    """If the LLM returns garbage, the job is marked failed with the error."""
    stub_llm.next_response = "not json at all"

    resp = await http_client.post(
        "/v1/reflection/session",
        json={"user_id": "live-job-2", "messages": [{"role": "user", "content": "x"}]},
    )
    job_id = resp.json()["data"]["job_id"]

    final = None
    for _ in range(40):
        await asyncio.sleep(0.1)
        r = await http_client.get(f"/v1/jobs/{job_id}")
        body = r.json()["data"]
        if body["status"] in {"completed", "failed"}:
            final = body
            break

    assert final is not None
    assert final["status"] == "failed"
    assert "json" in (final["error"] or "").lower() or "value" in (final["error"] or "").lower()


@pytest.mark.asyncio
async def test_get_unknown_job_404(http_client):
    r = await http_client.get("/v1/jobs/missing")
    assert r.status_code == 404
