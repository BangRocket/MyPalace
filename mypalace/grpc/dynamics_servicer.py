"""gRPC servicer that delegates to dynamics_service."""

# ruff: noqa: N802  # gRPC servicer methods must match proto (PascalCase)

from __future__ import annotations

import json

import grpc

from mypalace.dynamics.service import dynamics_service
from mypalace.grpc._generated import mypalace_pb2, mypalace_pb2_grpc
from mypalace.grpc.auth_interceptor import current_auth


def _dynamics_to_proto(d) -> mypalace_pb2.MemoryDynamics:
    return mypalace_pb2.MemoryDynamics(
        memory_id=d.memory_id,
        user_id=d.user_id,
        stability=float(d.stability),
        difficulty=float(d.difficulty),
        retrieval_strength=float(d.retrieval_strength),
        storage_strength=float(d.storage_strength),
        is_key=bool(d.is_key),
        importance_weight=float(d.importance_weight),
        category=d.category or "",
        tags_json=json.dumps(d.tags) if d.tags else "",
        last_accessed_at=d.last_accessed_at.isoformat() if d.last_accessed_at else "",
        access_count=int(d.access_count),
        created_at=d.created_at.isoformat() if d.created_at else "",
        updated_at=d.updated_at.isoformat() if d.updated_at else "",
    )


class DynamicsServicer(mypalace_pb2_grpc.DynamicsServiceServicer):
    async def PromoteMemory(
        self, request: mypalace_pb2.PromoteMemoryRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.DynamicsResponse:
        grade = int(request.grade) or 3
        if grade not in (1, 2, 3, 4):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "grade must be 1-4")
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        dyn = await dynamics_service.promote(
            memory_id=request.memory_id,
            user_id=request.user_id,
            grade=grade,
            signal_type=request.signal_type or "used_in_response",
            tenant_id=tenant_id,
        )
        return mypalace_pb2.DynamicsResponse(dynamics=_dynamics_to_proto(dyn))

    async def DemoteMemory(
        self, request: mypalace_pb2.DemoteMemoryRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.DynamicsResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        dyn = await dynamics_service.demote(
            memory_id=request.memory_id,
            user_id=request.user_id,
            reason=request.reason or "user_correction",
            tenant_id=tenant_id,
        )
        return mypalace_pb2.DynamicsResponse(dynamics=_dynamics_to_proto(dyn))

    async def GetDynamics(
        self, request: mypalace_pb2.GetDynamicsRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.DynamicsResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        dyn = await dynamics_service.get_dynamics(
            request.memory_id, request.user_id, tenant_id=tenant_id,
        )
        if dyn is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "dynamics not found")
        return mypalace_pb2.DynamicsResponse(dynamics=_dynamics_to_proto(dyn))

    async def ScoreMemory(
        self, request: mypalace_pb2.ScoreMemoryRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.ScoreBreakdownResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        breakdown = await dynamics_service.score(
            memory_id=request.memory_id,
            user_id=request.user_id,
            semantic_score=float(request.semantic_score),
            tenant_id=tenant_id,
        )
        return mypalace_pb2.ScoreBreakdownResponse(
            breakdown=mypalace_pb2.ScoreBreakdown(
                composite_score=float(breakdown["composite_score"]),
                fsrs_score=float(breakdown["fsrs_score"]),
                retrievability=float(breakdown["retrievability"]),
                storage_strength=float(breakdown["storage_strength"]),
            ),
        )
