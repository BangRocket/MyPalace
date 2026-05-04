"""gRPC server interceptor enforcing X-Palace-Key auth + scope."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import grpc

from mypalace.auth.context import AuthContext
from mypalace.auth.key_service import key_service
from mypalace.config import settings

# Method name → required scope. Keep in sync with palace.auth.scopes.
# Rule (mirrors HTTP scope map): list/get/search/check/format/score-of-context →
# read; everything mutating → write; admin/maintenance → admin.
RPC_SCOPE: dict[str, str] = {
    # MemoryService (phase 3 slice 5)
    "/palace.v1.MemoryService/CreateMemory":  "write",
    "/palace.v1.MemoryService/GetMemory":     "read",
    "/palace.v1.MemoryService/DeleteMemory":  "write",
    "/palace.v1.MemoryService/SearchMemories": "read",
    "/palace.v1.MemoryService/ListMemories":  "read",
    # SessionService
    "/palace.v1.SessionService/CreateSession": "write",
    "/palace.v1.SessionService/GetSession":    "read",
    "/palace.v1.SessionService/AddMessage":    "write",
    "/palace.v1.SessionService/UpdateSession": "write",
    "/palace.v1.SessionService/DeleteSession": "write",
    # EpisodeService
    "/palace.v1.EpisodeService/ReflectSession":    "write",
    "/palace.v1.EpisodeService/SearchEpisodes":    "read",
    "/palace.v1.EpisodeService/GetRecentEpisodes": "read",
    # ArcService
    "/palace.v1.ArcService/SynthesizeNarratives": "write",
    "/palace.v1.ArcService/GetActiveArcs":        "read",
    # IntentionService
    "/palace.v1.IntentionService/SetIntention":     "write",
    "/palace.v1.IntentionService/CheckIntentions":  "read",
    "/palace.v1.IntentionService/FormatIntentions": "read",
    "/palace.v1.IntentionService/ListIntentions":   "read",
    "/palace.v1.IntentionService/DeleteIntention":  "write",
    # DynamicsService
    "/palace.v1.DynamicsService/PromoteMemory": "write",
    "/palace.v1.DynamicsService/DemoteMemory":  "write",
    "/palace.v1.DynamicsService/GetDynamics":   "read",
    "/palace.v1.DynamicsService/ScoreMemory":   "write",
    # RetrievalService
    "/palace.v1.RetrievalService/AssembleLayered": "read",
    # IngestionService
    "/palace.v1.IngestionService/SupersedeMemory":  "write",
    "/palace.v1.IngestionService/GetSupersessions": "read",
    # JobService
    "/palace.v1.JobService/GetJob": "read",
}


class AuthInterceptor(grpc.aio.ServerInterceptor):
    """Reads x-palace-key from metadata, looks up the key, attaches the
    AuthContext to the servicer context (`context.auth = ctx`)."""

    async def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Awaitable[Any]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> Any:
        method = handler_call_details.method

        if settings.auth_disabled:
            return await continuation(handler_call_details)

        metadata = dict(handler_call_details.invocation_metadata or [])
        plaintext = metadata.get("x-palace-key")

        async def deny(reason: str, code: grpc.StatusCode):
            async def _abort(req, ctx):
                await ctx.abort(code, reason)
            return grpc.unary_unary_rpc_method_handler(_abort)

        if not plaintext:
            return await deny("missing x-palace-key", grpc.StatusCode.UNAUTHENTICATED)

        ctx = await key_service.lookup(plaintext)
        if ctx is None:
            return await deny("invalid api key", grpc.StatusCode.UNAUTHENTICATED)

        required = RPC_SCOPE.get(method, "write")
        if not ctx.has_scope(required):
            return await deny(
                f"requires scope '{required}'",
                grpc.StatusCode.PERMISSION_DENIED,
            )

        # Stash the auth context on a thread-local so the servicer can read it.
        # gRPC's invocation context isn't directly mutable from an interceptor
        # in a portable way; we pass through a contextvar.
        _AUTH_VAR.set(ctx)
        return await continuation(handler_call_details)


# Per-request auth context. Servicer reads via current_auth().
import contextvars  # noqa: E402

_AUTH_VAR: contextvars.ContextVar[AuthContext | None] = contextvars.ContextVar(
    "palace_grpc_auth", default=None,
)


def current_auth() -> AuthContext:
    """Return the AuthContext for the current RPC, or all-scopes if disabled."""
    ctx = _AUTH_VAR.get()
    if ctx is not None:
        return ctx
    if settings.auth_disabled:
        return AuthContext.all_scopes()
    # Should be unreachable — interceptor would have rejected.
    return AuthContext.all_scopes()
