"""Layered retrieval route handler (slice 5)."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends

from palace.api.common import (
    ApiResponse,
    LayeredCharCounts,
    LayeredContextOut,
    LayeredContextRequest,
    LayeredL1Out,
    LayeredL2Out,
    LayeredL3GraphOut,
    Meta,
)
from palace.auth.context import AuthContext, get_auth_context
from palace.cache.decorator import cached_call
from palace.config import settings
from palace.retrieval.layered import layered_retrieval_service

router = APIRouter()


@router.post("/layered", response_model=ApiResponse[LayeredContextOut])
async def assemble_layered_context(
    req: LayeredContextRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()

    async def _load():
        return await layered_retrieval_service.assemble(
            user_id=req.user_id,
            query=req.query,
            agent_id=req.agent_id,
            session_id=req.session_id,
            max_l1_chars=req.max_l1_chars,
            max_l2_chars=req.max_l2_chars,
            max_recent_messages=req.max_recent_messages,
            use_fsrs=req.use_fsrs,
            memory_limit=req.memory_limit,
            episode_limit=req.episode_limit,
            min_episode_significance=req.min_episode_significance,
            tenant_id=tenant_id,
            include_graph=req.include_graph,
            graph_depth=req.graph_depth,
            graph_max_neighbors=req.graph_max_neighbors,
        )

    result = await cached_call(
        namespace="context_layered",
        key_parts={
            "tenant_id": tenant_id,
            "user_id": req.user_id,
            "query": req.query,
            "agent_id": req.agent_id,
            "session_id": req.session_id,
            "max_l1_chars": req.max_l1_chars,
            "max_l2_chars": req.max_l2_chars,
            "max_recent_messages": req.max_recent_messages,
            "use_fsrs": req.use_fsrs,
            "memory_limit": req.memory_limit,
            "episode_limit": req.episode_limit,
            "min_episode_significance": req.min_episode_significance,
            "include_graph": req.include_graph,
            "graph_depth": req.graph_depth,
            "graph_max_neighbors": req.graph_max_neighbors,
        },
        ttl=settings.cache_ttl_search_seconds,
        loader=_load,
    )
    took = int((time.time() - start) * 1000)
    raw_l3 = result.get("l3_graph_context")
    l3_out = LayeredL3GraphOut(**raw_l3) if raw_l3 is not None else None
    out = LayeredContextOut(
        l1_user_profile=LayeredL1Out(**result["l1_user_profile"]),
        l2_relevant_context=LayeredL2Out(**result["l2_relevant_context"]),
        l3_graph_context=l3_out,
        recent_messages=result.get("recent_messages"),
        summary=result.get("summary"),
        char_counts=LayeredCharCounts(**result["char_counts"]),
    )
    count = (
        len(result["l1_user_profile"]["memories"])
        + len(result["l2_relevant_context"]["memories"])
    )
    return ApiResponse(data=out, meta=Meta(count=count, took_ms=took))
