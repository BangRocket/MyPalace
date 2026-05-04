"""gRPC servicer that delegates to job_service."""

# ruff: noqa: N802  # gRPC servicer methods must match proto (PascalCase)

from __future__ import annotations

import json

import grpc

from palace.grpc._generated import palace_pb2, palace_pb2_grpc
from palace.grpc.auth_interceptor import current_auth
from palace.job_service import job_service


def _job_to_proto(j) -> palace_pb2.Job:
    return palace_pb2.Job(
        id=j.id,
        kind=j.kind,
        user_id=j.user_id,
        status=j.status,
        created_at=j.created_at.isoformat() if j.created_at else "",
        completed_at=j.completed_at.isoformat() if j.completed_at else "",
        result_json=json.dumps(j.result_json) if j.result_json is not None else "",
        error=j.error or "",
    )


class JobServicer(palace_pb2_grpc.JobServiceServicer):
    async def GetJob(
        self, request: palace_pb2.GetJobRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.JobResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        job = await job_service.get(request.job_id, tenant_id=tenant_id)
        if not job:
            await context.abort(grpc.StatusCode.NOT_FOUND, "job not found")
        return palace_pb2.JobResponse(job=_job_to_proto(job))
