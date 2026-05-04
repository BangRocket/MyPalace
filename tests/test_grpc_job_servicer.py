"""Unit tests for the gRPC JobServicer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.grpc._generated import mypalace_pb2
from mypalace.grpc.job_servicer import JobServicer


def _fake_job(**overrides):
    j = MagicMock()
    j.id = overrides.get("id", "job-1")
    j.kind = overrides.get("kind", "reflection")
    j.user_id = overrides.get("user_id", "u1")
    j.status = overrides.get("status", "completed")
    j.created_at = overrides.get("created_at", datetime(2026, 5, 4, tzinfo=UTC))
    j.completed_at = overrides.get("completed_at", datetime(2026, 5, 4, tzinfo=UTC))
    j.result_json = overrides.get("result_json", [{"id": "ep1"}])
    j.error = overrides.get("error")
    return j


@pytest.mark.asyncio
async def test_get_job():
    svc = JobServicer()
    fake = _fake_job(id="job-1")
    with patch("mypalace.grpc.job_servicer.job_service.get",
               new=AsyncMock(return_value=fake)):
        req = mypalace_pb2.GetJobRequest(job_id="job-1")
        ctx = MagicMock()
        resp = await svc.GetJob(req, ctx)
        assert resp.job.id == "job-1"
        assert resp.job.kind == "reflection"
        assert resp.job.status == "completed"
        assert json.loads(resp.job.result_json) == [{"id": "ep1"}]


@pytest.mark.asyncio
async def test_get_job_404():
    svc = JobServicer()
    with patch("mypalace.grpc.job_servicer.job_service.get",
               new=AsyncMock(return_value=None)):
        req = mypalace_pb2.GetJobRequest(job_id="missing")
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=Exception("aborted"))
        with pytest.raises(Exception, match="aborted"):
            await svc.GetJob(req, ctx)


@pytest.mark.asyncio
async def test_get_job_no_result():
    svc = JobServicer()
    fake = _fake_job(status="pending", completed_at=None, result_json=None)
    with patch("mypalace.grpc.job_servicer.job_service.get",
               new=AsyncMock(return_value=fake)):
        req = mypalace_pb2.GetJobRequest(job_id="job-1")
        ctx = MagicMock()
        resp = await svc.GetJob(req, ctx)
        assert resp.job.completed_at == ""
        assert resp.job.result_json == ""
