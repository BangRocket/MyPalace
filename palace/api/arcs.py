"""Narrative arc + synthesis routes."""

from __future__ import annotations

import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from palace.api.common import (
    ApiResponse,
    JobPendingOut,
    Meta,
    NarrativeArcOut,
    SynthesizeRequest,
)
from palace.arc_service import arc_service
from palace.auth.context import AuthContext, get_auth_context
from palace.config import settings
from palace.job_service import job_service
from palace.workers.queue import enqueue as enqueue_job

synthesis_router = APIRouter()           # /v1/synthesis/...
users_arcs_router = APIRouter()          # /v1/users/{user_id}/arcs/...


@synthesis_router.post("/narratives")
async def synthesize_narratives(
    req: SynthesizeRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    mode: Literal["sync", "async"] = Query(default="async"),
):
    tenant_id = auth.resolve_tenant()
    start = time.time()

    if mode == "sync":
        arcs = await arc_service.synthesize_narratives(
            user_id=req.user_id,
            agent_id=req.agent_id,
            lookback_episodes=req.lookback_episodes,
            tenant_id=tenant_id,
        )
        took = int((time.time() - start) * 1000)
        return ApiResponse(
            data=[NarrativeArcOut.from_arc(a) for a in arcs],
            meta=Meta(count=len(arcs), took_ms=took),
        )

    if settings.worker_queue_enabled:
        job = await enqueue_job(
            kind="synthesis",
            user_id=req.user_id,
            payload={
                "user_id": req.user_id,
                "agent_id": req.agent_id,
                "lookback_episodes": req.lookback_episodes,
            },
            tenant_id=tenant_id,
        )
    else:
        async def coro():
            return await arc_service.synthesize_narratives(
                user_id=req.user_id,
                agent_id=req.agent_id,
                lookback_episodes=req.lookback_episodes,
                tenant_id=tenant_id,
            )

        job = await job_service.run_async(
            kind="synthesis",
            user_id=req.user_id,
            coro_factory=coro,
            tenant_id=tenant_id,
        )
    took = int((time.time() - start) * 1000)
    response = ApiResponse(
        data=JobPendingOut(job_id=job.id),
        meta=Meta(count=1, took_ms=took),
    )
    return JSONResponse(content=response.model_dump(), status_code=202)


@users_arcs_router.get("/{user_id}/arcs/active", response_model=ApiResponse[list[NarrativeArcOut]])
async def active_arcs(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    limit: int = 10,
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    arcs = await arc_service.get_active(
        user_id=user_id, limit=limit, tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[NarrativeArcOut.from_arc(a) for a in arcs],
        meta=Meta(count=len(arcs), took_ms=took),
    )
