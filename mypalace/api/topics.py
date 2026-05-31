"""Topic routes — async extraction (worker) + per-user recurrence fetch."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from mypalace.api.common import (
    ApiResponse,
    ExtractTopicsRequest,
    JobPendingOut,
    Meta,
    TopicRecurrenceOut,
)
from mypalace.auth.context import AuthContext, get_auth_context
from mypalace.config import settings
from mypalace.job_service import job_service
from mypalace.topic_service import DEFAULT_AGENT_ID, topic_service
from mypalace.workers.queue import enqueue as enqueue_job

router = APIRouter()  # /v1/topics/...
users_router = APIRouter()  # /v1/users/{user_id}/topic-recurrence


@router.post("/extract")
async def extract_topics(
    req: ExtractTopicsRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    tenant_id = auth.resolve_tenant()
    start = time.time()
    payload = {
        "user_id": req.user_id,
        "conversation_text": req.conversation_text,
        "conversation_sentiment": req.conversation_sentiment,
        "agent_id": req.agent_id,
        "channel_id": req.channel_id,
        "channel_name": req.channel_name,
        "is_dm": req.is_dm,
    }
    if settings.worker_queue_enabled:
        job = await enqueue_job(
            kind="topic_extract",
            user_id=req.user_id,
            payload=payload,
            tenant_id=tenant_id,
        )
    else:

        async def coro():
            return await topic_service.extract_and_store(
                user_id=req.user_id,
                conversation_text=req.conversation_text,
                conversation_sentiment=req.conversation_sentiment,
                agent_id=req.agent_id,
                channel_id=req.channel_id,
                channel_name=req.channel_name,
                is_dm=req.is_dm,
                tenant_id=tenant_id,
            )

        job = await job_service.run_async(
            kind="topic_extract",
            user_id=req.user_id,
            coro_factory=coro,
            tenant_id=tenant_id,
        )
    took = int((time.time() - start) * 1000)
    response = ApiResponse(data=JobPendingOut(job_id=job.id), meta=Meta(count=1, took_ms=took))
    return JSONResponse(content=response.model_dump(), status_code=202)


@users_router.get(
    "/{user_id}/topic-recurrence",
    response_model=ApiResponse[list[TopicRecurrenceOut]],
)
async def topic_recurrence(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    lookback_days: int = 14,
    min_mentions: int = 2,
    agent_id: str = DEFAULT_AGENT_ID,
) -> Any:
    tenant_id = auth.resolve_tenant()
    start = time.time()
    items = await topic_service.get_recurrence(
        user_id=user_id,
        agent_id=agent_id,
        lookback_days=lookback_days,
        min_mentions=min_mentions,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data=[TopicRecurrenceOut(**i) for i in items],
        meta=Meta(count=len(items), took_ms=took),
    )
