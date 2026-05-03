"""Memory route handlers."""

import time

from fastapi import APIRouter, HTTPException

from palace.api.common import (
    ApiResponse,
    CreateMemoryRequest,
    MemoryOut,
    Meta,
    SearchedMemoryOut,
    SearchMemoriesRequest,
    UpdateMemoryRequest,
)
from palace.memory_service import memory_service

router = APIRouter()
users_router = APIRouter()


@router.post("", response_model=ApiResponse[MemoryOut])
async def create_memory(req: CreateMemoryRequest):
    start = time.time()
    memory = await memory_service.create(
        user_id=req.user_id,
        content=req.content,
        memory_type=req.memory_type,
        agent_id=req.agent_id,
        source=req.source,
        importance=req.importance,
        metadata=req.metadata,
    )
    took = int((time.time() - start) * 1000)
    return ApiResponse(data=MemoryOut.from_memory(memory), meta=Meta(count=1, took_ms=took))


@router.post("/search", response_model=ApiResponse[list[SearchedMemoryOut]])
async def search_memories(req: SearchMemoriesRequest):
    start = time.time()
    results = await memory_service.search(
        query=req.query,
        user_id=req.user_id,
        agent_id=req.agent_id,
        memory_type=req.memory_type,
        limit=req.limit,
        min_score=req.min_score,
    )
    took = int((time.time() - start) * 1000)
    memories = [
        SearchedMemoryOut(
            id=m.id,
            content=m.content,
            memory_type=m.memory_type,
            importance=m.importance,
            score=round(score, 4),
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m, score in results
    ]
    return ApiResponse(data=memories, meta=Meta(count=len(memories), took_ms=took))


@router.get("/{memory_id}", response_model=ApiResponse[MemoryOut])
async def get_memory(memory_id: str):
    memory = await memory_service.get(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data=MemoryOut.from_memory(memory), meta=Meta(count=1))


@router.patch("/{memory_id}", response_model=ApiResponse[MemoryOut])
async def update_memory(memory_id: str, req: UpdateMemoryRequest):
    memory = await memory_service.update(
        memory_id,
        content=req.content,
        memory_type=req.memory_type,
        importance=req.importance,
        metadata=req.metadata,
    )
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data=MemoryOut.from_memory(memory), meta=Meta(count=1))


@router.delete("/{memory_id}", response_model=ApiResponse[dict])
async def delete_memory(memory_id: str):
    ok = await memory_service.delete(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data={"deleted": True}, meta=Meta(count=1))


@users_router.get("/{user_id}/memories", response_model=ApiResponse[list[MemoryOut]])
async def list_user_memories(user_id: str, limit: int = 50):
    memories = await memory_service.list_for_user(user_id, limit=limit)
    data = [MemoryOut.from_memory(m) for m in memories]
    return ApiResponse(data=data, meta=Meta(count=len(data)))
