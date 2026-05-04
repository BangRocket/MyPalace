"""gRPC servicer that delegates to the existing memory_service."""

from __future__ import annotations

import json

import grpc

from mypalace.grpc._generated import mypalace_pb2, mypalace_pb2_grpc
from mypalace.grpc.auth_interceptor import current_auth
from mypalace.memory_service import memory_service
from mypalace.models import Memory


def _memory_to_proto(m: Memory) -> mypalace_pb2.Memory:
    return mypalace_pb2.Memory(
        id=m.id,
        user_id=m.user_id,
        agent_id=m.agent_id or "",
        content=m.content,
        memory_type=m.memory_type,
        source=m.source or "",
        importance=float(m.importance),
        created_at=m.created_at.isoformat() if m.created_at else "",
        updated_at=m.updated_at.isoformat() if m.updated_at else "",
        accessed_at=m.accessed_at.isoformat() if m.accessed_at else "",
        access_count=int(m.access_count),
        metadata_json=json.dumps(m.metadata_json) if m.metadata_json else "",
    )


def _parse_metadata(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


class MemoryServicer(mypalace_pb2_grpc.MemoryServiceServicer):
    async def CreateMemory(
        self, request: mypalace_pb2.CreateMemoryRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.MemoryResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        memory = await memory_service.create(
            user_id=request.user_id,
            content=request.content,
            memory_type=request.memory_type or "semantic",
            agent_id=request.agent_id or None,
            source=request.source or None,
            importance=float(request.importance) if request.importance else 1.0,
            metadata=_parse_metadata(request.metadata_json),
            tenant_id=tenant_id,
        )
        return mypalace_pb2.MemoryResponse(memory=_memory_to_proto(memory))

    async def GetMemory(
        self, request: mypalace_pb2.GetMemoryRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.MemoryResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        memory = await memory_service.get(request.memory_id, tenant_id=tenant_id)
        if memory is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "memory not found")
        return mypalace_pb2.MemoryResponse(memory=_memory_to_proto(memory))

    async def DeleteMemory(
        self, request: mypalace_pb2.DeleteMemoryRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.DeleteResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        ok = await memory_service.delete(request.memory_id, tenant_id=tenant_id)
        if not ok:
            await context.abort(grpc.StatusCode.NOT_FOUND, "memory not found")
        return mypalace_pb2.DeleteResponse(deleted=True)

    async def SearchMemories(
        self, request: mypalace_pb2.SearchMemoriesRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.SearchMemoriesResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        results = await memory_service.search(
            query=request.query,
            user_id=request.user_id or None,
            agent_id=request.agent_id or None,
            memory_type=request.memory_type or None,
            limit=request.limit or 10,
            min_score=float(request.min_score),
            tenant_id=tenant_id,
        )
        return mypalace_pb2.SearchMemoriesResponse(
            results=[
                mypalace_pb2.ScoredMemory(memory=_memory_to_proto(m), score=float(score))
                for m, score in results
            ],
        )

    async def ListMemories(
        self, request: mypalace_pb2.ListMemoriesRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.ListMemoriesResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        memories = await memory_service.list_filtered(
            user_id=request.user_id or None,
            agent_id=request.agent_id or None,
            memory_type=request.memory_type or None,
            limit=request.limit or 50,
            offset=request.offset or 0,
            tenant_id=tenant_id,
        )
        return mypalace_pb2.ListMemoriesResponse(
            memories=[_memory_to_proto(m) for m in memories],
        )
