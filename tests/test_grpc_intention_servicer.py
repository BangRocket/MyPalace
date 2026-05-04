"""Unit tests for the gRPC IntentionServicer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from palace.grpc._generated import palace_pb2
from palace.grpc.intention_servicer import IntentionServicer


def _fake_intention(**overrides):
    i = MagicMock()
    i.id = overrides.get("id", "i1")
    i.user_id = overrides.get("user_id", "u1")
    i.agent_id = overrides.get("agent_id", "clara")
    i.content = overrides.get("content", "remind me")
    i.source_memory_id = overrides.get("source_memory_id")
    i.trigger_conditions = overrides.get(
        "trigger_conditions", {"type": "keyword", "keywords": ["test"]},
    )
    i.priority = overrides.get("priority", 5)
    i.fired = overrides.get("fired", False)
    i.fire_once = overrides.get("fire_once", True)
    i.created_at = overrides.get("created_at", datetime(2026, 5, 4, tzinfo=UTC))
    i.expires_at = overrides.get("expires_at")
    i.fired_at = overrides.get("fired_at")
    return i


@pytest.mark.asyncio
async def test_set_intention_calls_service():
    svc = IntentionServicer()
    fake = _fake_intention(id="new-i", priority=7)
    with patch("palace.grpc.intention_servicer.intention_service.set",
               new=AsyncMock(return_value=fake)) as mock_set:
        trigger = {"type": "keyword", "keywords": ["foo"]}
        req = palace_pb2.SetIntentionRequest(
            user_id="u1",
            content="remind me",
            trigger_conditions_json=json.dumps(trigger),
            priority=7,
            fire_once=True,
        )
        ctx = MagicMock()
        resp = await svc.SetIntention(req, ctx)
        assert resp.intention.id == "new-i"
        assert resp.intention.priority == 7
        mock_set.assert_awaited_once()
        assert mock_set.await_args.kwargs["trigger_conditions"] == trigger


@pytest.mark.asyncio
async def test_set_intention_invalid_trigger():
    svc = IntentionServicer()
    req = palace_pb2.SetIntentionRequest(
        user_id="u1",
        content="x",
        trigger_conditions_json="",  # missing
    )
    ctx = MagicMock()
    ctx.abort = AsyncMock(side_effect=Exception("aborted"))
    with pytest.raises(Exception, match="aborted"):
        await svc.SetIntention(req, ctx)


@pytest.mark.asyncio
async def test_check_intentions_returns_fired():
    svc = IntentionServicer()
    fired = [
        {
            "id": "i1",
            "content": "do thing",
            "trigger_type": "keyword",
            "priority": 3,
            "match_details": {"matched": ["foo"]},
            "source_memory_id": None,
        },
    ]
    with patch("palace.grpc.intention_servicer.intention_service.check",
               new=AsyncMock(return_value=fired)):
        req = palace_pb2.CheckIntentionsRequest(user_id="u1", message="foo")
        ctx = MagicMock()
        resp = await svc.CheckIntentions(req, ctx)
        assert len(resp.fired) == 1
        assert resp.fired[0].id == "i1"
        assert json.loads(resp.fired[0].match_details_json) == {"matched": ["foo"]}


@pytest.mark.asyncio
async def test_format_intentions_returns_text():
    svc = IntentionServicer()
    with patch(
        "palace.grpc.intention_servicer.intention_service.format_for_prompt",
        return_value="## Reminders\n- do thing",
    ):
        req = palace_pb2.FormatIntentionsRequest(
            intentions_json=json.dumps([{"content": "do thing"}]), max=3,
        )
        ctx = MagicMock()
        resp = await svc.FormatIntentions(req, ctx)
        assert resp.text == "## Reminders\n- do thing"


@pytest.mark.asyncio
async def test_format_intentions_invalid_json():
    svc = IntentionServicer()
    req = palace_pb2.FormatIntentionsRequest(
        intentions_json='{"not": "a list"}', max=3,
    )
    ctx = MagicMock()
    ctx.abort = AsyncMock(side_effect=Exception("aborted"))
    with pytest.raises(Exception, match="aborted"):
        await svc.FormatIntentions(req, ctx)


@pytest.mark.asyncio
async def test_list_intentions():
    svc = IntentionServicer()
    intentions = [_fake_intention(id="i1"), _fake_intention(id="i2")]
    with patch("palace.grpc.intention_servicer.intention_service.list_for_user",
               new=AsyncMock(return_value=intentions)):
        req = palace_pb2.ListIntentionsRequest(user_id="u1", fired="false")
        ctx = MagicMock()
        resp = await svc.ListIntentions(req, ctx)
        assert [i.id for i in resp.intentions] == ["i1", "i2"]


@pytest.mark.asyncio
async def test_list_intentions_invalid_fired_filter():
    svc = IntentionServicer()
    req = palace_pb2.ListIntentionsRequest(user_id="u1", fired="bogus")
    ctx = MagicMock()
    ctx.abort = AsyncMock(side_effect=Exception("aborted"))
    with pytest.raises(Exception, match="aborted"):
        await svc.ListIntentions(req, ctx)


@pytest.mark.asyncio
async def test_delete_intention():
    svc = IntentionServicer()
    with patch("palace.grpc.intention_servicer.intention_service.delete",
               new=AsyncMock(return_value=True)):
        req = palace_pb2.DeleteIntentionRequest(intention_id="i1")
        ctx = MagicMock()
        resp = await svc.DeleteIntention(req, ctx)
        assert resp.deleted is True


@pytest.mark.asyncio
async def test_delete_intention_404():
    svc = IntentionServicer()
    with patch("palace.grpc.intention_servicer.intention_service.delete",
               new=AsyncMock(return_value=False)):
        req = palace_pb2.DeleteIntentionRequest(intention_id="missing")
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=Exception("aborted"))
        with pytest.raises(Exception, match="aborted"):
            await svc.DeleteIntention(req, ctx)
