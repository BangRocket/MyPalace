"""gRPC servicer that delegates to session_service."""

# ruff: noqa: N802  # gRPC servicer methods must match proto (PascalCase)

from __future__ import annotations

import grpc

from palace.grpc._generated import palace_pb2, palace_pb2_grpc
from palace.grpc.auth_interceptor import current_auth
from palace.session_service import session_service


def _session_to_proto(s) -> palace_pb2.Session:
    return palace_pb2.Session(
        id=s.id,
        user_id=s.user_id,
        title=s.title or "",
        summary=s.summary or "",
        created_at=s.created_at.isoformat() if s.created_at else "",
        updated_at=s.updated_at.isoformat() if s.updated_at else "",
    )


def _session_dict_to_proto(d: dict) -> palace_pb2.Session:
    return palace_pb2.Session(
        id=d.get("id", ""),
        user_id=d.get("user_id", ""),
        title=d.get("title") or "",
        summary=d.get("summary") or "",
        created_at=d.get("created_at") or "",
        updated_at=d.get("updated_at") or "",
    )


def _message_to_proto(m) -> palace_pb2.Message:
    return palace_pb2.Message(
        id=m.id,
        user_id=m.user_id,
        role=m.role,
        content=m.content,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


def _message_dict_to_proto(d: dict) -> palace_pb2.Message:
    return palace_pb2.Message(
        id=d.get("id", ""),
        user_id=d.get("user_id", ""),
        role=d.get("role", ""),
        content=d.get("content", ""),
        created_at=d.get("created_at") or "",
    )


class SessionServicer(palace_pb2_grpc.SessionServiceServicer):
    async def CreateSession(
        self, request: palace_pb2.CreateSessionRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.SessionResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        session = await session_service.create(
            user_id=request.user_id,
            title=request.title or None,
            tenant_id=tenant_id,
        )
        return palace_pb2.SessionResponse(session=_session_to_proto(session))

    async def GetSession(
        self, request: palace_pb2.GetSessionRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.SessionWithMessagesResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        data = await session_service.get(request.session_id, tenant_id=tenant_id)
        if not data:
            await context.abort(grpc.StatusCode.NOT_FOUND, "session not found")
        return palace_pb2.SessionWithMessagesResponse(
            data=palace_pb2.SessionWithMessages(
                session=_session_dict_to_proto(data),
                messages=[_message_dict_to_proto(m) for m in data.get("messages", [])],
            ),
        )

    async def AddMessage(
        self, request: palace_pb2.AddMessageRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.MessageResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        message = await session_service.add_message(
            session_id=request.session_id,
            user_id=request.user_id,
            role=request.role,
            content=request.content,
            tenant_id=tenant_id,
        )
        return palace_pb2.MessageResponse(message=_message_to_proto(message))

    async def UpdateSession(
        self, request: palace_pb2.UpdateSessionRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.SessionResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        session = await session_service.update(
            request.session_id,
            title=request.title or None,
            summary=request.summary or None,
            tenant_id=tenant_id,
        )
        if session is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "session not found")
        return palace_pb2.SessionResponse(session=_session_to_proto(session))

    async def DeleteSession(
        self, request: palace_pb2.DeleteSessionRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.DeleteResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        ok = await session_service.delete(request.session_id, tenant_id=tenant_id)
        if not ok:
            await context.abort(grpc.StatusCode.NOT_FOUND, "session not found")
        return palace_pb2.DeleteResponse(deleted=True)
