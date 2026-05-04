"""gRPC servicer that delegates to episode_service."""

# ruff: noqa: N802  # gRPC servicer methods must match proto (PascalCase)

from __future__ import annotations

import grpc

from palace.config import settings
from palace.episode_service import episode_service
from palace.grpc._generated import palace_pb2, palace_pb2_grpc
from palace.grpc.auth_interceptor import current_auth
from palace.job_service import job_service
from palace.workers.queue import enqueue as enqueue_job


def _episode_dict_to_proto(d: dict) -> palace_pb2.Episode:
    return palace_pb2.Episode(
        id=str(d.get("id", "")),
        user_id=d.get("user_id", "") or "",
        agent_id=d.get("agent_id") or "",
        content=d.get("content", "") or "",
        summary=d.get("summary", "") or "",
        participants=list(d.get("participants") or []),
        topics=list(d.get("topics") or []),
        emotional_tone=d.get("emotional_tone", "") or "",
        significance=float(d.get("significance") or 0.0),
        timestamp=d.get("timestamp") or "",
        session_id=d.get("session_id") or "",
        message_count=int(d.get("message_count") or 0),
        score=float(d.get("score") or 0.0),
    )


class EpisodeServicer(palace_pb2_grpc.EpisodeServiceServicer):
    async def ReflectSession(
        self, request: palace_pb2.ReflectSessionRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.ReflectSessionResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        mode = request.mode or "async"

        if mode not in ("sync", "async"):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "mode must be 'sync' or 'async'",
            )

        if mode == "sync":
            episodes = await episode_service.reflect_session(
                messages=messages,
                user_id=request.user_id,
                agent_id=request.agent_id or None,
                session_id=request.session_id or None,
                tenant_id=tenant_id,
            )
            return palace_pb2.ReflectSessionResponse(
                episodes=palace_pb2.EpisodesResponse(
                    episodes=[_episode_dict_to_proto(e) for e in episodes],
                ),
            )

        # async mode — queue or in-process
        if settings.worker_queue_enabled:
            job = await enqueue_job(
                kind="reflection",
                user_id=request.user_id,
                payload={
                    "messages": messages,
                    "user_id": request.user_id,
                    "agent_id": request.agent_id or None,
                    "session_id": request.session_id or None,
                },
                tenant_id=tenant_id,
            )
        else:
            async def coro():
                return await episode_service.reflect_session(
                    messages=messages,
                    user_id=request.user_id,
                    agent_id=request.agent_id or None,
                    session_id=request.session_id or None,
                    tenant_id=tenant_id,
                )

            job = await job_service.run_async(
                kind="reflection",
                user_id=request.user_id,
                coro_factory=coro,
                tenant_id=tenant_id,
            )
        return palace_pb2.ReflectSessionResponse(
            pending=palace_pb2.JobPending(job_id=job.id, status="pending"),
        )

    async def SearchEpisodes(
        self, request: palace_pb2.SearchEpisodesRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.EpisodesResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        results = await episode_service.search(
            query=request.query,
            user_id=request.user_id,
            limit=request.limit or 5,
            min_significance=float(request.min_significance),
            tenant_id=tenant_id,
        )
        return palace_pb2.EpisodesResponse(
            episodes=[_episode_dict_to_proto(r) for r in results],
        )

    async def GetRecentEpisodes(
        self, request: palace_pb2.GetRecentEpisodesRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.EpisodesResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        items = await episode_service.get_recent(
            user_id=request.user_id, limit=request.limit or 5, tenant_id=tenant_id,
        )
        return palace_pb2.EpisodesResponse(
            episodes=[_episode_dict_to_proto(i) for i in items],
        )
