"""Narrative arc + synthesis routes."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from palace.api.common import (
    ApiResponse,
    JobPendingOut,
    Meta,
    NarrativeArcOut,
    SynthesizeRequest,
)
from palace.arc_service import arc_service
from palace.job_service import job_service

synthesis_router = APIRouter()           # /v1/synthesis/...
users_arcs_router = APIRouter()          # /v1/users/{user_id}/arcs/...


@synthesis_router.post("/narratives")
async def synthesize_narratives(
    req: SynthesizeRequest,
    mode: Literal["sync", "async"] = Query(default="async"),
):
    start = time.time()

    if mode == "sync":
        arcs = await arc_service.synthesize_narratives(
            user_id=req.user_id,
            agent_id=req.agent_id,
            lookback_episodes=req.lookback_episodes,
        )
        took = int((time.time() - start) * 1000)
        return ApiResponse(
            data=[NarrativeArcOut.from_arc(a) for a in arcs],
            meta=Meta(count=len(arcs), took_ms=took),
        )

    async def coro():
        return await arc_service.synthesize_narratives(
            user_id=req.user_id,
            agent_id=req.agent_id,
            lookback_episodes=req.lookback_episodes,
        )

    job = await job_service.run_async(kind="synthesis", user_id=req.user_id, coro_factory=coro)
    took = int((time.time() - start) * 1000)
    response = ApiResponse(
        data=JobPendingOut(job_id=job.id),
        meta=Meta(count=1, took_ms=took),
    )
    return JSONResponse(content=response.model_dump(), status_code=202)


@users_arcs_router.get("/{user_id}/arcs/active", response_model=ApiResponse[list[NarrativeArcOut]])
async def active_arcs(user_id: str, limit: int = 10):
    start = time.time()
    arcs = await arc_service.get_active(user_id=user_id, limit=limit)
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[NarrativeArcOut.from_arc(a) for a in arcs],
        meta=Meta(count=len(arcs), took_ms=took),
    )
