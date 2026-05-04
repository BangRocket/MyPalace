"""gRPC servicer that delegates to arc_service."""

# ruff: noqa: N802  # gRPC servicer methods must match proto (PascalCase)

from __future__ import annotations

import grpc

from mypalace.arc_service import arc_service
from mypalace.config import settings
from mypalace.grpc._generated import mypalace_pb2, mypalace_pb2_grpc
from mypalace.grpc.auth_interceptor import current_auth
from mypalace.job_service import job_service
from mypalace.workers.queue import enqueue as enqueue_job


def _arc_to_proto(a) -> mypalace_pb2.NarrativeArc:
    return mypalace_pb2.NarrativeArc(
        id=a.id,
        user_id=a.user_id,
        agent_id=a.agent_id or "",
        title=a.title,
        summary=a.summary,
        status=a.status,
        key_episode_ids=list(a.key_episode_ids or []),
        emotional_trajectory=a.emotional_trajectory or "",
        created_at=a.created_at.isoformat() if a.created_at else "",
        updated_at=a.updated_at.isoformat() if a.updated_at else "",
    )


class ArcServicer(mypalace_pb2_grpc.ArcServiceServicer):
    async def SynthesizeNarratives(
        self,
        request: mypalace_pb2.SynthesizeNarrativesRequest,
        context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.SynthesizeNarrativesResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        mode = request.mode or "async"
        if mode not in ("sync", "async"):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "mode must be 'sync' or 'async'",
            )

        if mode == "sync":
            arcs = await arc_service.synthesize_narratives(
                user_id=request.user_id,
                agent_id=request.agent_id or None,
                lookback_episodes=request.lookback_episodes or 20,
                tenant_id=tenant_id,
            )
            return mypalace_pb2.SynthesizeNarrativesResponse(
                arcs=mypalace_pb2.ArcsResponse(arcs=[_arc_to_proto(a) for a in arcs]),
            )

        if settings.worker_queue_enabled:
            job = await enqueue_job(
                kind="synthesis",
                user_id=request.user_id,
                payload={
                    "user_id": request.user_id,
                    "agent_id": request.agent_id or None,
                    "lookback_episodes": request.lookback_episodes or 20,
                },
                tenant_id=tenant_id,
            )
        else:
            async def coro():
                return await arc_service.synthesize_narratives(
                    user_id=request.user_id,
                    agent_id=request.agent_id or None,
                    lookback_episodes=request.lookback_episodes or 20,
                    tenant_id=tenant_id,
                )

            job = await job_service.run_async(
                kind="synthesis",
                user_id=request.user_id,
                coro_factory=coro,
                tenant_id=tenant_id,
            )
        return mypalace_pb2.SynthesizeNarrativesResponse(
            pending=mypalace_pb2.JobPending(job_id=job.id, status="pending"),
        )

    async def GetActiveArcs(
        self, request: mypalace_pb2.GetActiveArcsRequest, context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.ArcsResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        arcs = await arc_service.get_active(
            user_id=request.user_id,
            limit=request.limit or 10,
            tenant_id=tenant_id,
        )
        return mypalace_pb2.ArcsResponse(arcs=[_arc_to_proto(a) for a in arcs])
