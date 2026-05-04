"""gRPC servicer that delegates to layered_retrieval_service."""

# ruff: noqa: N802  # gRPC servicer methods must match proto (PascalCase)

from __future__ import annotations

import json

import grpc

from mypalace.grpc._generated import mypalace_pb2, mypalace_pb2_grpc
from mypalace.grpc.auth_interceptor import current_auth
from mypalace.retrieval.layered import layered_retrieval_service


def _dumps(obj) -> str:
    return json.dumps(obj or [])


class RetrievalServicer(mypalace_pb2_grpc.RetrievalServiceServicer):
    async def AssembleLayered(
        self,
        request: mypalace_pb2.AssembleLayeredRequest,
        context: grpc.aio.ServicerContext,
    ) -> mypalace_pb2.LayeredContextResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        result = await layered_retrieval_service.assemble(
            user_id=request.user_id,
            query=request.query,
            agent_id=request.agent_id or None,
            session_id=request.session_id or None,
            max_l1_chars=request.max_l1_chars or 3200,
            max_l2_chars=request.max_l2_chars or 12000,
            max_recent_messages=request.max_recent_messages or 20,
            use_fsrs=bool(request.use_fsrs),
            memory_limit=request.memory_limit or 10,
            episode_limit=request.episode_limit or 5,
            min_episode_significance=float(request.min_episode_significance),
            tenant_id=tenant_id,
            include_graph=bool(request.include_graph),
            graph_depth=request.graph_depth or 1,
            graph_max_neighbors=request.graph_max_neighbors or 50,
        )

        l1 = result.get("l1_user_profile", {})
        l2 = result.get("l2_relevant_context", {})
        chars = result.get("char_counts", {})
        l3 = result.get("l3_graph_context")
        recent = result.get("recent_messages")

        ctx_msg = mypalace_pb2.LayeredContext(
            l1_user_profile=mypalace_pb2.LayeredL1(
                memories_json=_dumps(l1.get("memories")),
                recent_episodes_json=_dumps(l1.get("recent_episodes")),
                active_arcs_json=_dumps(l1.get("active_arcs")),
            ),
            l2_relevant_context=mypalace_pb2.LayeredL2(
                memories_json=_dumps(l2.get("memories")),
                episodes_json=_dumps(l2.get("episodes")),
            ),
            recent_messages_json=json.dumps(recent) if recent is not None else "",
            summary=result.get("summary") or "",
            char_counts=mypalace_pb2.LayeredCharCounts(
                l1=int(chars.get("l1", 0)),
                l2=int(chars.get("l2", 0)),
            ),
            has_l3_graph_context=l3 is not None,
        )
        if l3 is not None:
            ctx_msg.l3_graph_context.CopyFrom(mypalace_pb2.LayeredL3Graph(
                related_memories_json=_dumps(l3.get("related_memories")),
                edges_json=_dumps(l3.get("edges")),
            ))
        return mypalace_pb2.LayeredContextResponse(context=ctx_msg)
