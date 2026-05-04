"""Mock-based tests for JobService."""

from __future__ import annotations

import asyncio

import pytest

from mypalace.job_service import JobService


@pytest.mark.asyncio
async def test_create_persists_pending_job():
    svc = JobService()
    # We use real DB here? No — that's an integration concern. Mock the session.
    # For slice 2 we test with the integration suite; this mock test just verifies
    # the public surface exists and the run_async helper schedules a task.
    # Actual persistence behavior is exercised in tests/integration/test_jobs_live.py.

    async def fake_coro():
        return [{"x": 1}]

    # Patch async_session to a no-op for this surface check
    from unittest.mock import AsyncMock, MagicMock, patch
    fake_db = MagicMock()
    fake_db.add = MagicMock()
    fake_db.commit = AsyncMock()
    fake_db.refresh = AsyncMock()

    class FakeAsyncSession:
        async def __aenter__(self): return fake_db
        async def __aexit__(self, *args): return None

    with patch("mypalace.job_service.async_session", lambda: FakeAsyncSession()):
        await svc.create(kind="reflection", user_id="u1")

    fake_db.add.assert_called_once()
    fake_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_run_async_schedules_task_and_returns_pending():
    """run_async creates the job + schedules the coroutine as a task."""
    svc = JobService()

    completed_event = asyncio.Event()
    captured_results: list = []

    async def fake_coro():
        captured_results.append("ran")
        return [{"x": 1}]

    from unittest.mock import AsyncMock, MagicMock, patch

    fake_job = MagicMock()
    fake_job.id = "job-1"

    def _set_event(*a, **kw):
        completed_event.set()

    with (
        patch.object(svc, "create", new=AsyncMock(return_value=fake_job)),
        patch.object(svc, "complete", new=AsyncMock(side_effect=_set_event)),
        patch.object(svc, "fail", new=AsyncMock()),
    ):
        job = await svc.run_async(kind="reflection", user_id="u1", coro_factory=fake_coro)

        assert job.id == "job-1"
        # Wait for the spawned task to complete
        await asyncio.wait_for(completed_event.wait(), timeout=2.0)
        assert captured_results == ["ran"]


@pytest.mark.asyncio
async def test_run_async_records_failure_when_coro_raises():
    svc = JobService()

    failed_event = asyncio.Event()
    captured_errors: list = []

    async def bad_coro():
        raise RuntimeError("kaboom")

    from unittest.mock import AsyncMock, MagicMock, patch

    fake_job = MagicMock()
    fake_job.id = "job-2"

    async def fake_fail(job_id, error, tenant_id="default"):
        captured_errors.append((job_id, error))
        failed_event.set()

    with (
        patch.object(svc, "create", new=AsyncMock(return_value=fake_job)),
        patch.object(svc, "complete", new=AsyncMock()),
        patch.object(svc, "fail", new=fake_fail),
    ):
        await svc.run_async(kind="reflection", user_id="u1", coro_factory=bad_coro)

        await asyncio.wait_for(failed_event.wait(), timeout=2.0)
        assert captured_errors[0][0] == "job-2"
        assert "kaboom" in captured_errors[0][1]


def test_get_job_found(client, mock_job_service):
    from datetime import UTC, datetime
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.id = "j1"
    fake.kind = "reflection"
    fake.user_id = "u1"
    fake.status = "completed"
    fake.created_at = datetime.now(UTC)
    fake.completed_at = datetime.now(UTC)
    fake.result_json = [{"x": 1}]
    fake.error = None
    mock_job_service.get.return_value = fake

    resp = client.get("/v1/jobs/j1")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "completed"
    assert data["result"] == [{"x": 1}]


def test_get_job_404(client, mock_job_service):
    mock_job_service.get.return_value = None
    resp = client.get("/v1/jobs/missing")
    assert resp.status_code == 404
