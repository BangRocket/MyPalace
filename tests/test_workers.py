"""Unit tests for the worker queue + handler registry + runner dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.workers.handlers import HANDLER_REGISTRY, register_handler


class TestHandlerRegistry:
    def test_built_in_handlers_registered(self):
        assert "reflection" in HANDLER_REGISTRY
        assert "synthesis" in HANDLER_REGISTRY

    def test_register_overrides(self):
        async def custom(payload, tenant_id):
            return {"got": payload, "tenant": tenant_id}

        original = HANDLER_REGISTRY.get("test_kind")
        try:
            register_handler("test_kind", custom)
            assert HANDLER_REGISTRY["test_kind"] is custom
        finally:
            if original is not None:
                HANDLER_REGISTRY["test_kind"] = original
            else:
                HANDLER_REGISTRY.pop("test_kind", None)


class TestQueueEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_inserts_pending_row(self):
        from mypalace.workers.queue import enqueue

        mock_session = MagicMock()
        db = mock_session.return_value.__aenter__.return_value
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def refresh(job):
            job.id = "job-123"

        db.refresh = AsyncMock(side_effect=refresh)
        with patch("mypalace.workers.queue.async_session", mock_session):
            job = await enqueue(
                kind="reflection",
                user_id="u1",
                payload={"messages": []},
                tenant_id="t1",
            )

        assert job.kind == "reflection"
        assert job.status == "pending"
        assert job.payload_json == {"messages": []}
        assert job.tenant_id == "t1"


class TestRunnerProcessOne:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_job(self):
        from mypalace.workers import runner

        with patch.object(runner, "claim_next", new=AsyncMock(return_value=None)):
            result = await runner.process_one()
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatches_to_registered_handler(self):
        from mypalace.workers import runner

        fake_job = MagicMock()
        fake_job.id = "j1"
        fake_job.kind = "reflection"
        fake_job.tenant_id = "t1"
        fake_job.payload_json = {"user_id": "u1", "messages": []}
        fake_job.attempts = 1

        handler_called = {}

        async def fake_handler(payload, tenant_id):
            handler_called["payload"] = payload
            handler_called["tenant"] = tenant_id
            return [{"id": "ep-1", "summary": "x"}]

        with patch.object(runner, "claim_next", new=AsyncMock(return_value=fake_job)), \
             patch.dict(runner.HANDLER_REGISTRY, {"reflection": fake_handler}), \
             patch.object(runner, "complete_job", new=AsyncMock()) as mock_complete, \
             patch.object(runner, "fail_job", new=AsyncMock()) as mock_fail:
            assert await runner.process_one() is True
        assert handler_called == {"payload": {"user_id": "u1", "messages": []}, "tenant": "t1"}
        mock_complete.assert_awaited_once()
        mock_fail.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_kind_marks_permanent_failure(self):
        from mypalace.workers import runner

        fake_job = MagicMock()
        fake_job.id = "j1"
        fake_job.kind = "no_such_kind"
        fake_job.tenant_id = "t1"
        fake_job.payload_json = {}
        fake_job.attempts = 1

        with patch.object(runner, "claim_next", new=AsyncMock(return_value=fake_job)), \
             patch.dict(runner.HANDLER_REGISTRY, {}, clear=False), \
             patch.object(runner, "fail_job", new=AsyncMock()) as mock_fail:
            # Make sure the unknown kind isn't accidentally registered.
            runner.HANDLER_REGISTRY.pop("no_such_kind", None)
            assert await runner.process_one() is True
        mock_fail.assert_awaited_once()
        kwargs = mock_fail.await_args.kwargs
        assert kwargs["permanent"] is True

    @pytest.mark.asyncio
    async def test_handler_exception_retries_then_permanent(self):
        from mypalace.workers import runner

        fake_job = MagicMock()
        fake_job.id = "j1"
        fake_job.kind = "reflection"
        fake_job.tenant_id = "t1"
        fake_job.payload_json = {}

        async def boom(payload, tenant_id):
            raise RuntimeError("boom")

        # First failure: attempts < max → not permanent.
        fake_job.attempts = 1
        with patch.object(runner, "claim_next", new=AsyncMock(return_value=fake_job)), \
             patch.dict(runner.HANDLER_REGISTRY, {"reflection": boom}), \
             patch.object(runner, "fail_job", new=AsyncMock()) as mock_fail:
            await runner.process_one()
        assert mock_fail.await_args.kwargs["permanent"] is False

        # Final attempt: attempts == max → permanent.
        from mypalace.config import settings
        fake_job.attempts = settings.worker_max_attempts
        with patch.object(runner, "claim_next", new=AsyncMock(return_value=fake_job)), \
             patch.dict(runner.HANDLER_REGISTRY, {"reflection": boom}), \
             patch.object(runner, "fail_job", new=AsyncMock()) as mock_fail:
            await runner.process_one()
        assert mock_fail.await_args.kwargs["permanent"] is True
