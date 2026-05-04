"""Unit tests for the gRPC IngestionServicer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from palace.grpc._generated import palace_pb2
from palace.grpc.ingestion_servicer import IngestionServicer


@pytest.mark.asyncio
async def test_supersede_memory():
    svc = IngestionServicer()
    result = {
        "superseded_id": "old1",
        "new_id": "new1",
        "reason": "manual_correction",
    }
    with patch(
        "palace.grpc.ingestion_servicer.smart_ingestion_service.supersede_memory",
        new=AsyncMock(return_value=result),
    ):
        req = palace_pb2.SupersedeMemoryRequest(
            memory_id="old1", user_id="u1", new_content="updated",
        )
        ctx = MagicMock()
        resp = await svc.SupersedeMemory(req, ctx)
        assert resp.supersession.superseded_id == "old1"
        assert resp.supersession.new_id == "new1"
        assert resp.supersession.has_similarity_score is False


@pytest.mark.asyncio
async def test_supersede_memory_404():
    svc = IngestionServicer()
    with patch(
        "palace.grpc.ingestion_servicer.smart_ingestion_service.supersede_memory",
        new=AsyncMock(return_value=None),
    ):
        req = palace_pb2.SupersedeMemoryRequest(
            memory_id="missing", user_id="u1", new_content="x",
        )
        ctx = MagicMock()
        ctx.abort = AsyncMock(side_effect=Exception("aborted"))
        with pytest.raises(Exception, match="aborted"):
            await svc.SupersedeMemory(req, ctx)


@pytest.mark.asyncio
async def test_get_supersessions():
    svc = IngestionServicer()
    rows = [
        {
            "superseded_id": "old1",
            "new_id": "new1",
            "reason": "auto_contradiction",
            "similarity_score": 0.91,
            "created_at": "2026-05-04T00:00:00+00:00",
        },
    ]
    with patch(
        "palace.grpc.ingestion_servicer.smart_ingestion_service.get_supersessions",
        new=AsyncMock(return_value=rows),
    ):
        req = palace_pb2.GetSupersessionsRequest(memory_id="new1")
        ctx = MagicMock()
        resp = await svc.GetSupersessions(req, ctx)
        assert len(resp.supersessions) == 1
        assert resp.supersessions[0].similarity_score == pytest.approx(0.91)
        assert resp.supersessions[0].has_similarity_score is True
