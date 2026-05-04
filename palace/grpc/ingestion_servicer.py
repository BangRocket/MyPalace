"""gRPC servicer that delegates to smart_ingestion_service."""

# ruff: noqa: N802  # gRPC servicer methods must match proto (PascalCase)

from __future__ import annotations

import json

import grpc

from palace.grpc._generated import palace_pb2, palace_pb2_grpc
from palace.grpc.auth_interceptor import current_auth
from palace.retrieval.ingestion import smart_ingestion_service


def _supersession_to_proto(d: dict) -> palace_pb2.Supersession:
    sim = d.get("similarity_score")
    return palace_pb2.Supersession(
        superseded_id=d.get("superseded_id", "") or "",
        new_id=d.get("new_id", "") or "",
        reason=d.get("reason", "") or "",
        similarity_score=float(sim) if sim is not None else 0.0,
        has_similarity_score=sim is not None,
        created_at=d.get("created_at") or "",
    )


def _parse_metadata(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


class IngestionServicer(palace_pb2_grpc.IngestionServiceServicer):
    async def SupersedeMemory(
        self,
        request: palace_pb2.SupersedeMemoryRequest,
        context: grpc.aio.ServicerContext,
    ) -> palace_pb2.SupersessionResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        result = await smart_ingestion_service.supersede_memory(
            old_memory_id=request.memory_id,
            new_content=request.new_content,
            user_id=request.user_id,
            reason=request.reason or "manual_correction",
            metadata=_parse_metadata(request.metadata_json),
            tenant_id=tenant_id,
        )
        if result is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "memory not found")
        return palace_pb2.SupersessionResponse(
            supersession=_supersession_to_proto(result),
        )

    async def GetSupersessions(
        self,
        request: palace_pb2.GetSupersessionsRequest,
        context: grpc.aio.ServicerContext,
    ) -> palace_pb2.SupersessionsResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        rows = await smart_ingestion_service.get_supersessions(
            request.memory_id, tenant_id=tenant_id,
        )
        return palace_pb2.SupersessionsResponse(
            supersessions=[_supersession_to_proto(r) for r in rows],
        )
