"""Tests for slice 1 wire-ups: worker-queue routing + event publishers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ----------------------------------------------------------------------
# Worker-queue routing
# ----------------------------------------------------------------------

class TestWorkerQueueRouting:
    def test_async_reflection_uses_run_async_when_flag_off(
        self, client, mock_episode_service, mock_job_service,
    ):
        from palace.config import settings
        with patch.object(settings, "worker_queue_enabled", False):
            mock_job_service.run_async.return_value = MagicMock(id="job-1")
            r = client.post(
                "/v1/reflection/session?mode=async",
                json={"user_id": "u1", "messages": [{"role": "user", "content": "hi"}]},
            )
        assert r.status_code == 202
        mock_job_service.run_async.assert_awaited_once()

    def test_async_reflection_uses_enqueue_when_flag_on(
        self, client, mock_episode_service, mock_job_service,
    ):
        from palace.config import settings
        with patch.object(settings, "worker_queue_enabled", True), \
             patch("palace.api.episodes.enqueue_job",
                   new=AsyncMock(return_value=MagicMock(id="job-2"))) as mock_enq:
            r = client.post(
                "/v1/reflection/session?mode=async",
                json={
                    "user_id": "u1",
                    "messages": [{"role": "user", "content": "hi"}],
                    "agent_id": "clara",
                    "session_id": "s1",
                },
            )
        assert r.status_code == 202
        mock_enq.assert_awaited_once()
        kwargs = mock_enq.await_args.kwargs
        assert kwargs["kind"] == "reflection"
        assert kwargs["payload"]["session_id"] == "s1"
        assert kwargs["payload"]["agent_id"] == "clara"
        # in-process path was NOT taken
        mock_job_service.run_async.assert_not_awaited()

    def test_async_synthesis_uses_enqueue_when_flag_on(
        self, client, mock_arc_service, mock_job_service,
    ):
        from palace.config import settings
        with patch.object(settings, "worker_queue_enabled", True), \
             patch("palace.api.arcs.enqueue_job",
                   new=AsyncMock(return_value=MagicMock(id="job-3"))) as mock_enq:
            r = client.post(
                "/v1/synthesis/narratives?mode=async",
                json={"user_id": "u1", "lookback_episodes": 30},
            )
        assert r.status_code == 202
        mock_enq.assert_awaited_once()
        kwargs = mock_enq.await_args.kwargs
        assert kwargs["kind"] == "synthesis"
        assert kwargs["payload"]["lookback_episodes"] == 30
        mock_job_service.run_async.assert_not_awaited()


# ----------------------------------------------------------------------
# Event publishers
# ----------------------------------------------------------------------

class TestEpisodePublisher:
    @pytest.mark.asyncio
    async def test_episode_created_published_after_reflect(self, monkeypatch):
        """episode_service.reflect_session writes episodes to Qdrant AND
        publishes one episode.created event per written episode."""
        # Stub the LLM to return two episodes.
        from palace import llm as llm_module
        from palace.config import settings
        from palace.episode_service import episode_service
        monkeypatch.setattr(
            llm_module.llm, "complete",
            AsyncMock(return_value=(
                '{"episodes": ['
                '{"start_index": 0, "end_index": 0, "summary": "first",'
                ' "topics": ["t1"], "emotional_tone": "neutral",'
                ' "significance": 0.5},'
                '{"start_index": 1, "end_index": 1, "summary": "second",'
                ' "topics": ["t2"], "emotional_tone": "warm",'
                ' "significance": 0.8}'
                ']}'
            )),
        )
        # Stub the embedder to bypass model load.
        fake_embedder = MagicMock()
        fake_embedder.embed = AsyncMock(return_value=[[0.0] * 384])
        fake_embedder.dim = 384
        monkeypatch.setattr(episode_service, "_embedder", fake_embedder)

        # Stub the vector upsert.
        from palace.vector import episode_vector_store
        monkeypatch.setattr(
            episode_vector_store, "upsert", AsyncMock(),
        )

        # Force in-process broker (no Redis).
        monkeypatch.setattr(settings, "redis_url", None)
        from palace.events.broker import broker
        async with broker.subscribe(tenant_id="t1") as q:
            await episode_service.reflect_session(
                messages=[
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "world"},
                ],
                user_id="u1",
                tenant_id="t1",
            )
            # Drain two events.
            ev1 = await asyncio.wait_for(q.get(), timeout=1.0)
            ev2 = await asyncio.wait_for(q.get(), timeout=1.0)

        import json as _json
        for raw in (ev1, ev2):
            payload = _json.loads(raw)
            assert payload["type"] == "episode.created"
            assert payload["tenant_id"] == "t1"
            assert "episode_id" in payload["payload"]
            assert "summary" in payload["payload"]


class TestIntentionPublisher:
    @pytest.mark.asyncio
    async def test_intention_fired_published_after_check(self, monkeypatch):
        from palace.config import settings
        from palace.intentions.service import IntentionService

        # Fake an intention that matches a keyword trigger.
        from palace.models import Intention
        fake_intention = MagicMock(spec=Intention)
        fake_intention.id = "int-1"
        fake_intention.user_id = "u1"
        fake_intention.agent_id = "clara"
        fake_intention.tenant_id = "t1"
        fake_intention.content = "remind: standup"
        fake_intention.fired = False
        fake_intention.fire_once = True
        fake_intention.priority = 1
        fake_intention.expires_at = None
        fake_intention.source_memory_id = None
        fake_intention.trigger_conditions = {
            "type": "keyword", "keywords": ["meeting"],
        }

        # Stub the DB plumbing.
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = [fake_intention]
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=scalars_result)
        db_mock.delete = AsyncMock()
        db_mock.commit = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "palace.intentions.service.async_session", MagicMock(return_value=cm),
        )

        monkeypatch.setattr(settings, "redis_url", None)
        from palace.events.broker import broker
        svc = IntentionService()
        async with broker.subscribe(tenant_id="t1") as q:
            fired = await svc.check(
                user_id="u1",
                message="time for the standup meeting",
                tenant_id="t1",
            )
            ev = await asyncio.wait_for(q.get(), timeout=1.0)

        assert len(fired) == 1
        import json as _json
        envelope = _json.loads(ev)
        assert envelope["type"] == "intention.fired"
        assert envelope["payload"]["id"] == "int-1"
        assert envelope["payload"]["trigger_type"] == "keyword"


class TestArcPublisher:
    @pytest.mark.asyncio
    async def test_arc_synthesized_published_per_new_arc(self, monkeypatch):
        # Stub the LLM
        from palace import llm as llm_module
        from palace.arc_service import arc_service
        from palace.config import settings
        monkeypatch.setattr(
            llm_module.llm, "complete",
            AsyncMock(return_value=(
                '{"arcs": ['
                '{"title": "A", "summary": "x", "status": "active",'
                ' "key_episode_ids": [], "emotional_trajectory": ""}'
                ']}'
            )),
        )

        # Stub episode_service.get_recent and self.get_active.
        monkeypatch.setattr(
            "palace.arc_service.episode_service.get_recent",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(arc_service, "get_active", AsyncMock(return_value=[]))

        # Stub create() to return a fake arc rather than touching the DB.
        fake_arc = MagicMock()
        fake_arc.id = "arc-1"
        fake_arc.user_id = "u1"
        fake_arc.title = "A"
        fake_arc.status = "active"
        monkeypatch.setattr(
            arc_service, "create", AsyncMock(return_value=fake_arc),
        )

        monkeypatch.setattr(settings, "redis_url", None)
        from palace.events.broker import broker
        async with broker.subscribe(tenant_id="t1") as q:
            await arc_service.synthesize_narratives(
                user_id="u1", tenant_id="t1",
            )
            ev = await asyncio.wait_for(q.get(), timeout=1.0)

        import json as _json
        envelope = _json.loads(ev)
        assert envelope["type"] == "arc.synthesized"
        assert envelope["payload"]["arc_id"] == "arc-1"
        assert envelope["payload"]["title"] == "A"
