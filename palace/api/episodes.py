"""Episode + reflection routes."""

from __future__ import annotations

import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from palace.api.common import (
    ApiResponse,
    EpisodeOut,
    JobPendingOut,
    Meta,
    ReflectSessionRequest,
    SearchEpisodesRequest,
)
from palace.auth.context import AuthContext, get_auth_context
from palace.config import settings
from palace.episode_service import episode_service
from palace.job_service import job_service
from palace.workers.queue import enqueue as enqueue_job

router = APIRouter()              # /v1/episodes/...
reflection_router = APIRouter()   # /v1/reflection/...
users_episodes_router = APIRouter()  # /v1/users/{user_id}/episodes/...


@reflection_router.post("/session")
async def reflect_session(
    req: ReflectSessionRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    mode: Literal["sync", "async"] = Query(default="async"),
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    messages = [m.model_dump() for m in req.messages]

    if mode == "sync":
        episodes = await episode_service.reflect_session(
            messages=messages,
            user_id=req.user_id,
            agent_id=req.agent_id,
            session_id=req.session_id,
            tenant_id=tenant_id,
        )
        took = int((time.time() - start) * 1000)
        return ApiResponse(
            data=[EpisodeOut(**e) for e in episodes],
            meta=Meta(count=len(episodes), took_ms=took),
        )

    # async mode — route through the worker queue when configured, otherwise
    # the in-process asyncio.create_task path. Both end up writing the same
    # ReflectionJob row; only the executor differs.
    if settings.worker_queue_enabled:
        job = await enqueue_job(
            kind="reflection",
            user_id=req.user_id,
            payload={
                "messages": messages,
                "user_id": req.user_id,
                "agent_id": req.agent_id,
                "session_id": req.session_id,
            },
            tenant_id=tenant_id,
        )
    else:
        async def coro():
            return await episode_service.reflect_session(
                messages=messages,
                user_id=req.user_id,
                agent_id=req.agent_id,
                session_id=req.session_id,
                tenant_id=tenant_id,
            )

        job = await job_service.run_async(
            kind="reflection",
            user_id=req.user_id,
            coro_factory=coro,
            tenant_id=tenant_id,
        )
    took = int((time.time() - start) * 1000)
    response = ApiResponse(
        data=JobPendingOut(job_id=job.id),
        meta=Meta(count=1, took_ms=took),
    )
    # Return 202 for async
    return JSONResponse(content=response.model_dump(), status_code=202)


@router.post("/search", response_model=ApiResponse[list[EpisodeOut]])
async def search_episodes(
    req: SearchEpisodesRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    results = await episode_service.search(
        query=req.query,
        user_id=req.user_id,
        limit=req.limit,
        min_significance=req.min_significance,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[EpisodeOut(**r) for r in results],
        meta=Meta(count=len(results), took_ms=took),
    )


@users_episodes_router.get(
    "/{user_id}/episodes/recent",
    response_model=ApiResponse[list[EpisodeOut]],
)
async def recent_episodes(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    limit: int = 5,
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    items = await episode_service.get_recent(
        user_id=user_id, limit=limit, tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[EpisodeOut(**i) for i in items],
        meta=Meta(count=len(items), took_ms=took),
    )
