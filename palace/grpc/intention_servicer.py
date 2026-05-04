"""gRPC servicer that delegates to intention_service."""

# ruff: noqa: N802  # gRPC servicer methods must match proto (PascalCase)

from __future__ import annotations

import json
from datetime import datetime

import grpc

from palace.grpc._generated import palace_pb2, palace_pb2_grpc
from palace.grpc.auth_interceptor import current_auth
from palace.intentions.service import intention_service


def _intention_to_proto(i) -> palace_pb2.Intention:
    return palace_pb2.Intention(
        id=i.id,
        user_id=i.user_id,
        agent_id=i.agent_id,
        content=i.content,
        source_memory_id=i.source_memory_id or "",
        trigger_conditions_json=json.dumps(i.trigger_conditions or {}),
        priority=int(i.priority),
        fired=bool(i.fired),
        fire_once=bool(i.fire_once),
        created_at=i.created_at.isoformat() if i.created_at else "",
        expires_at=i.expires_at.isoformat() if i.expires_at else "",
        fired_at=i.fired_at.isoformat() if i.fired_at else "",
    )


def _fired_to_proto(f: dict) -> palace_pb2.FiredIntention:
    return palace_pb2.FiredIntention(
        id=f.get("id", "") or "",
        content=f.get("content", "") or "",
        trigger_type=f.get("trigger_type", "") or "",
        priority=int(f.get("priority") or 0),
        match_details_json=json.dumps(f.get("match_details") or {}),
        source_memory_id=f.get("source_memory_id") or "",
    )


def _parse_json(raw: str, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class IntentionServicer(palace_pb2_grpc.IntentionServiceServicer):
    async def SetIntention(
        self, request: palace_pb2.SetIntentionRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.IntentionResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        trigger = _parse_json(request.trigger_conditions_json, None)
        if trigger is None or not isinstance(trigger, dict):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "trigger_conditions_json must be a JSON object",
            )
        expires_at: datetime | None = None
        if request.expires_at:
            try:
                expires_at = datetime.fromisoformat(request.expires_at)
            except ValueError:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, "expires_at must be ISO-8601",
                )
        intention = await intention_service.set(
            user_id=request.user_id,
            content=request.content,
            trigger_conditions=trigger,
            agent_id=request.agent_id or "clara",
            expires_at=expires_at,
            source_memory_id=request.source_memory_id or None,
            priority=int(request.priority),
            fire_once=bool(request.fire_once),
            tenant_id=tenant_id,
        )
        return palace_pb2.IntentionResponse(intention=_intention_to_proto(intention))

    async def CheckIntentions(
        self, request: palace_pb2.CheckIntentionsRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.FiredIntentionsResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        ctx = _parse_json(request.context_json, None)
        fired = await intention_service.check(
            user_id=request.user_id,
            message=request.message,
            context=ctx,
            agent_id=request.agent_id or "clara",
            tenant_id=tenant_id,
        )
        return palace_pb2.FiredIntentionsResponse(
            fired=[_fired_to_proto(f) for f in fired],
        )

    async def FormatIntentions(
        self, request: palace_pb2.FormatIntentionsRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.FormattedIntentionsResponse:
        intentions = _parse_json(request.intentions_json, [])
        if not isinstance(intentions, list):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "intentions_json must be a JSON list",
            )
        text = intention_service.format_for_prompt(intentions, max_intentions=request.max or 3)
        return palace_pb2.FormattedIntentionsResponse(text=text)

    async def ListIntentions(
        self, request: palace_pb2.ListIntentionsRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.IntentionsResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        fired_filter = request.fired or "all"
        if fired_filter not in ("true", "false", "all"):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "fired must be true|false|all",
            )
        intentions = await intention_service.list_for_user(
            user_id=request.user_id,
            fired_filter=fired_filter,
            limit=request.limit or 50,
            agent_id=request.agent_id or "clara",
            tenant_id=tenant_id,
        )
        return palace_pb2.IntentionsResponse(
            intentions=[_intention_to_proto(i) for i in intentions],
        )

    async def DeleteIntention(
        self, request: palace_pb2.DeleteIntentionRequest, context: grpc.aio.ServicerContext,
    ) -> palace_pb2.DeleteResponse:
        auth = current_auth()
        tenant_id = auth.resolve_tenant()
        ok = await intention_service.delete(request.intention_id, tenant_id=tenant_id)
        if not ok:
            await context.abort(grpc.StatusCode.NOT_FOUND, "intention not found")
        return palace_pb2.DeleteResponse(deleted=True)
