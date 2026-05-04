"""Memory route handlers."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from palace.api.common import (
    ApiResponse,
    BatchCreateMemoriesRequest,
    CreateMemoryRequest,
    ListMemoriesRequest,
    MemoryOut,
    Meta,
    SearchedMemoryOut,
    SearchMemoriesRequest,
    SupersedeMemoryRequest,
    SupersessionOut,
    UpdateMemoryRequest,
)
from palace.auth.context import AuthContext, get_auth_context
from palace.cache.decorator import cached_call
from palace.config import settings
from palace.memory_service import memory_service
from palace.retrieval.ingestion import smart_ingestion_service

router = APIRouter()
users_router = APIRouter()


@router.post("", response_model=ApiResponse[MemoryOut])
async def create_memory(
    req: CreateMemoryRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    memory = await memory_service.create(
        user_id=req.user_id,
        content=req.content,
        memory_type=req.memory_type,
        agent_id=req.agent_id,
        source=req.source,
        importance=req.importance,
        metadata=req.metadata,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(data=MemoryOut.from_memory(memory), meta=Meta(count=1, took_ms=took))


@router.post("/batch", response_model=ApiResponse[list[MemoryOut]])
async def batch_create_memories(
    req: BatchCreateMemoriesRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    messages = [m.model_dump() for m in req.messages]
    result = await memory_service.create_batch(
        user_id=req.user_id,
        messages=messages,
        agent_id=req.agent_id,
        memory_type=req.memory_type,
        metadata=req.metadata,
        source=req.source,
        infer=req.infer,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    data = [MemoryOut.from_memory(m) for m in result["memories"]]
    meta = Meta(
        count=len(data),
        took_ms=took,
        supersessions=result.get("supersessions", []),
        skipped=result.get("skipped", []),
    )
    return ApiResponse(data=data, meta=meta)


MAX_LIST_LIMIT = 500


@router.post("/list", response_model=ApiResponse[list[MemoryOut]])
async def list_memories(
    req: ListMemoriesRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    limit = min(req.limit, MAX_LIST_LIMIT)
    memories = await memory_service.list_filtered(
        user_id=req.user_id,
        agent_id=req.agent_id,
        run_id=req.run_id,
        memory_type=req.memory_type,
        metadata=req.metadata,
        limit=limit,
        offset=req.offset,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    data = [MemoryOut.from_memory(m) for m in memories]
    return ApiResponse(data=data, meta=Meta(count=len(data), took_ms=took))


@router.post("/search", response_model=ApiResponse[list[SearchedMemoryOut]])
async def search_memories(
    req: SearchMemoriesRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    start = time.time()

    async def _load() -> list[dict]:
        results = await memory_service.search(
            query=req.query,
            user_id=req.user_id,
            agent_id=req.agent_id,
            memory_type=req.memory_type,
            limit=req.limit,
            min_score=req.min_score,
            tenant_id=tenant_id,
        )
        return [
            {
                "id": m.id,
                "content": m.content,
                "memory_type": m.memory_type,
                "importance": m.importance,
                "score": round(score, 4),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m, score in results
        ]

    cached_data = await cached_call(
        namespace="memories_search",
        key_parts={
            "tenant_id": tenant_id,
            "query": req.query,
            "user_id": req.user_id,
            "agent_id": req.agent_id,
            "memory_type": req.memory_type,
            "limit": req.limit,
            "min_score": req.min_score,
        },
        ttl=settings.cache_ttl_search_seconds,
        loader=_load,
    )
    took = int((time.time() - start) * 1000)
    memories = [SearchedMemoryOut(**d) for d in cached_data]
    return ApiResponse(data=memories, meta=Meta(count=len(memories), took_ms=took))


@router.get("/{memory_id}", response_model=ApiResponse[MemoryOut])
async def get_memory(
    memory_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    memory = await memory_service.get(memory_id, tenant_id=tenant_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data=MemoryOut.from_memory(memory), meta=Meta(count=1))


@router.patch("/{memory_id}", response_model=ApiResponse[MemoryOut])
async def update_memory(
    memory_id: str,
    req: UpdateMemoryRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    memory = await memory_service.update(
        memory_id,
        content=req.content,
        memory_type=req.memory_type,
        importance=req.importance,
        metadata=req.metadata,
        tenant_id=tenant_id,
    )
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data=MemoryOut.from_memory(memory), meta=Meta(count=1))


@router.delete("/{memory_id}", response_model=ApiResponse[dict])
async def delete_memory(
    memory_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    tenant_id = auth.resolve_tenant()
    ok = await memory_service.delete(memory_id, tenant_id=tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data={"deleted": True}, meta=Meta(count=1))


@router.post(
    "/{memory_id}/supersede",
    response_model=ApiResponse[SupersessionOut],
)
async def supersede_memory(
    memory_id: str,
    req: SupersedeMemoryRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    """Manually replace a memory with new content. Records a
    MemorySupersession audit row and demotes the old memory's FSRS state."""
    tenant_id = auth.resolve_tenant()
    start = time.time()
    result = await smart_ingestion_service.supersede_memory(
        old_memory_id=memory_id,
        new_content=req.new_content,
        user_id=req.user_id,
        reason=req.reason,
        metadata=req.metadata,
        tenant_id=tenant_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    took = int((time.time() - start) * 1000)
    out = SupersessionOut(
        superseded_id=result["superseded_id"],
        new_id=result["new_id"],
        reason=result["reason"],
    )
    return ApiResponse(data=out, meta=Meta(count=1, took_ms=took))


@router.get(
    "/{memory_id}/supersedes",
    response_model=ApiResponse[list[SupersessionOut]],
)
async def get_memory_supersessions(
    memory_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
):
    """Return supersession history involving this memory_id (either side)."""
    tenant_id = auth.resolve_tenant()
    rows = await smart_ingestion_service.get_supersessions(memory_id, tenant_id=tenant_id)
    data = [SupersessionOut(**r) for r in rows]
    return ApiResponse(data=data, meta=Meta(count=len(data)))


@users_router.get("/{user_id}/memories", response_model=ApiResponse[list[MemoryOut]])
async def list_user_memories(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    limit: int = 50,
):
    tenant_id = auth.resolve_tenant()
    memories = await memory_service.list_for_user(user_id, limit=limit, tenant_id=tenant_id)
    data = [MemoryOut.from_memory(m) for m in memories]
    return ApiResponse(data=data, meta=Meta(count=len(data)))


@users_router.delete("/{user_id}/memories", response_model=ApiResponse[dict])
async def delete_user_memories(
    user_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    agent_id: str | None = None,
    run_id: str | None = None,
):
    tenant_id = auth.resolve_tenant()
    start = time.time()
    deleted = await memory_service.delete_for_user(
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        tenant_id=tenant_id,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(
        data={"deleted": deleted},
        meta=Meta(count=deleted, took_ms=took),
    )
