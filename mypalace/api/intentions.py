"""Intention routes — set, check, format, list, delete (slice 4).

Two routers exported:
    router         → mounted at /v1/intentions
    users_router   → mounted at /v1/users (so GET /v1/users/{user_id}/intentions
                     follows the slice-1 memories convention)
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from mypalace.api.common import (
    ApiResponse,
    CheckIntentionsRequest,
    FiredIntentionOut,
    FormatIntentionsRequest,
    IntentionFormatOut,
    IntentionOut,
    Meta,
    SetIntentionRequest,
)
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.intentions.service import intention_service

router = APIRouter()
users_router = APIRouter()


@router.post("", response_model=ApiResponse[IntentionOut])
async def set_intention(
    req: SetIntentionRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    intention = await intention_service.set(
        user_id=req.user_id,
        content=req.content,
        trigger_conditions=req.trigger_conditions,
        agent_id=req.agent_id,
        expires_at=req.expires_at,
        source_memory_id=req.source_memory_id,
        priority=req.priority,
        fire_once=req.fire_once,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=IntentionOut.from_intention(intention),
        meta=Meta(count=1, took_ms=took),
    )


@router.post("/check", response_model=ApiResponse[list[FiredIntentionOut]])
async def check_intentions(
    req: CheckIntentionsRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    fired = await intention_service.check(
        user_id=req.user_id,
        message=req.message,
        context=req.context,
        agent_id=req.agent_id,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    data = [FiredIntentionOut(**f) for f in fired]
    return ApiResponse(data=data, meta=Meta(count=len(data), took_ms=took))


@router.post("/format", response_model=ApiResponse[IntentionFormatOut])
async def format_intentions(req: FormatIntentionsRequest):
    text = intention_service.format_for_prompt(req.intentions, max_intentions=req.max)
    return ApiResponse(
        data=IntentionFormatOut(text=text),
        meta=Meta(count=min(len(req.intentions), req.max)),
    )


@router.delete("/{intention_id}", response_model=ApiResponse[dict])
async def delete_intention(
    intention_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    ok = await intention_service.delete(intention_id, tenant_id=tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Intention not found")
    return ApiResponse(data={"deleted": True}, meta=Meta(count=1))


@users_router.get(
    "/{user_id}/intentions",
    response_model=ApiResponse[list[IntentionOut]],
)
async def list_user_intentions(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    fired: str = "all",
    limit: int = 50,
):
    if fired not in ("true", "false", "all"):
        raise HTTPException(status_code=400, detail="fired must be true|false|all")
    tenant_id = auth.resolve_tenant()
    intentions = await intention_service.list_for_user(
        user_id=user_id,
        fired_filter=fired,
        limit=limit,
        tenant_id=tenant_id,
    )
    data = [IntentionOut.from_intention(i) for i in intentions]
    return ApiResponse(data=data, meta=Meta(count=len(data)))
