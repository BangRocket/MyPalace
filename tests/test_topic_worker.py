"""The topic_extract worker handler dispatches to TopicService."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mypalace.workers.handlers import HANDLER_REGISTRY


@pytest.mark.asyncio
async def test_topic_extract_handler_registered_and_dispatches():
    assert "topic_extract" in HANDLER_REGISTRY
    handler = HANDLER_REGISTRY["topic_extract"]
    with patch("mypalace.topic_service.topic_service.extract_and_store",
               new=AsyncMock(return_value=[])) as m:
        await handler(
            {"user_id": "u1", "conversation_text": "x" * 60, "conversation_sentiment": -0.2,
             "agent_id": "default", "channel_id": "", "channel_name": "#dm", "is_dm": True},
            "test",
        )
    m.assert_awaited_once()
    assert m.call_args.kwargs["user_id"] == "u1"
    assert m.call_args.kwargs["tenant_id"] == "test"
