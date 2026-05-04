"""Event broker + WebSocket auth/topic-filter tests."""

from __future__ import annotations

import asyncio
import json

import pytest

from palace.events.broker import EventBroker
from palace.events.types import KNOWN_EVENT_TYPES, MEMORY_CREATED


class TestEventTypes:
    def test_known_set_is_complete(self):
        assert MEMORY_CREATED in KNOWN_EVENT_TYPES
        assert "memory.deleted" in KNOWN_EVENT_TYPES
        assert "intention.fired" in KNOWN_EVENT_TYPES

    def test_event_types_are_dotted(self):
        for t in KNOWN_EVENT_TYPES:
            assert "." in t


class TestBrokerInProcess:
    @pytest.mark.asyncio
    async def test_publish_then_subscribe_receives(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)  # force in-process

        broker = EventBroker()
        async with broker.subscribe(tenant_id="t1") as q:
            await broker.publish(
                event_type=MEMORY_CREATED,
                tenant_id="t1",
                payload={"memory_id": "m1"},
            )
            envelope = await asyncio.wait_for(q.get(), timeout=1.0)

        parsed = json.loads(envelope)
        assert parsed["type"] == MEMORY_CREATED
        assert parsed["tenant_id"] == "t1"
        assert parsed["payload"]["memory_id"] == "m1"
        assert "occurred_at" in parsed

    @pytest.mark.asyncio
    async def test_other_tenant_events_not_received(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)

        broker = EventBroker()
        async with broker.subscribe(tenant_id="t1") as q:
            await broker.publish(MEMORY_CREATED, "t2", {"memory_id": "m1"})
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(q.get(), timeout=0.2)

    @pytest.mark.asyncio
    async def test_two_subscribers_both_receive(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)

        broker = EventBroker()
        async with broker.subscribe(tenant_id="t1") as q1, \
                   broker.subscribe(tenant_id="t1") as q2:
            await broker.publish(MEMORY_CREATED, "t1", {"k": "v"})
            a = await asyncio.wait_for(q1.get(), timeout=1.0)
            b = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert json.loads(a)["type"] == MEMORY_CREATED
        assert json.loads(b)["type"] == MEMORY_CREATED

    @pytest.mark.asyncio
    async def test_subscribe_unregisters_on_exit(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)

        broker = EventBroker()
        async with broker.subscribe(tenant_id="t1"):
            assert len(broker._inproc.get("t1", [])) == 1
        assert len(broker._inproc.get("t1", [])) == 0

    @pytest.mark.asyncio
    async def test_full_queue_drops_event(self, monkeypatch):
        """A slow subscriber whose queue is full should not block publishers
        (events drop, log warning)."""
        from palace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)

        broker = EventBroker()
        # Manually wire a tiny queue
        tiny = asyncio.Queue(maxsize=1)
        broker._inproc.setdefault("t1", []).append(tiny)

        await broker.publish(MEMORY_CREATED, "t1", {"i": 1})  # fills it
        # Second publish should NOT raise even though queue is full.
        await broker.publish(MEMORY_CREATED, "t1", {"i": 2})

        # Only the first event made it through.
        assert tiny.qsize() == 1


class TestEventsRoute:
    """The WebSocket itself needs a TestClient that supports websockets;
    starlette's TestClient does. We exercise the auth/topic-filter path."""

    def test_unauthenticated_rejected(self, client):
        # When auth is disabled (test bypass), no key still works.
        # Re-enable auth via attribute patch to test the rejection path.
        from unittest.mock import patch

        from starlette.websockets import WebSocketDisconnect

        from palace.config import settings

        with patch.object(settings, "auth_disabled", False), \
             pytest.raises(WebSocketDisconnect), \
             client.websocket_connect("/v1/events"):
            pass

    def test_subscribes_with_disabled_auth(self, client):
        """In test bypass mode, opening the websocket succeeds and we
        immediately receive a hello frame."""
        with client.websocket_connect("/v1/events") as ws:
            hello = ws.receive_json()
            assert "hello" in hello
            assert hello["hello"]["topics"] == "*"
            assert hello["hello"]["tenant_id"] == "test"

    def test_topic_filter_in_hello(self, client):
        with client.websocket_connect(
            "/v1/events?topics=memory.created,memory.deleted",
        ) as ws:
            hello = ws.receive_json()
            assert set(hello["hello"]["topics"]) == {"memory.created", "memory.deleted"}

    def test_unknown_topics_ignored(self, client):
        with client.websocket_connect(
            "/v1/events?topics=memory.created,bogus.event",
        ) as ws:
            hello = ws.receive_json()
            # bogus.event filtered out, only known topic remains
            assert "memory.created" in hello["hello"]["topics"]
            assert "bogus.event" not in hello["hello"]["topics"]
