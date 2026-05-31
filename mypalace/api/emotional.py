"""Emotional-context routes — record (sync) + per-user recent fetch."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from mypalace.api.common import (
    ApiResponse,
    EmotionalContextOut,
    Meta,
    RecordEmotionalRequest,
)
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.emotional_service import DEFAULT_AGENT_ID, emotional_service

router = APIRouter()  # /v1/emotional/...
users_router = APIRouter()  # /v1/users/{user_id}/emotional-context


@router.post("/record", response_model=ApiResponse[EmotionalContextOut])
async def record_emotional(
    req: RecordEmotionalRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    tenant_id = auth.resolve_tenant()
    start = time.time()
    row = await emotional_service.record(
        user_id=req.user_id,
        messages=req.messages,
        agent_id=req.agent_id,
        channel_id=req.channel_id,
        channel_name=req.channel_name,
        is_dm=req.is_dm,
        energy=req.energy,
        summary=req.summary,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(data=EmotionalContextOut.from_row(row), meta=Meta(count=1, took_ms=took))


@users_router.get(
    "/{user_id}/emotional-context",
    response_model=ApiResponse[list[EmotionalContextOut]],
)
async def emotional_context(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    limit: int = 3,
    max_age_days: int = 7,
    agent_id: str = DEFAULT_AGENT_ID,
) -> Any:
    tenant_id = auth.resolve_tenant()
    start = time.time()
    rows = await emotional_service.get_recent(
        user_id=user_id,
        agent_id=agent_id,
        limit=limit,
        max_age_days=max_age_days,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[EmotionalContextOut.from_row(r) for r in rows],
        meta=Meta(count=len(rows), took_ms=took),
    )
