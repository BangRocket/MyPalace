"""ASGI middleware enforcing X-Palace-Key auth + scope on every request."""

from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from palace.auth.context import AuthContext
from palace.auth.key_service import key_service
from palace.auth.scopes import is_public, required_scope
from palace.config import settings

HEADER = "X-Palace-Key"


def _err(status: int, code: str, message: str) -> Response:
    body = json.dumps({"error": {"code": code, "message": message}})
    return Response(content=body, status_code=status, media_type="application/json")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if settings.auth_disabled:
            request.state.auth = AuthContext.all_scopes()
            return await call_next(request)

        if is_public(path):
            return await call_next(request)

        plaintext = request.headers.get(HEADER)
        if not plaintext:
            return _err(401, "unauthenticated", f"missing {HEADER} header")

        ctx = await key_service.lookup(plaintext)
        if ctx is None:
            return _err(401, "unauthenticated", "invalid or revoked API key")

        scope = required_scope(request.method, path)
        if not ctx.has_scope(scope):
            return _err(
                403,
                "forbidden",
                f"requires scope '{scope}'; key has {sorted(ctx.scopes)}",
            )

        request.state.auth = ctx
        return await call_next(request)


def install(app: ASGIApp) -> None:
    """FastAPI doesn't expose `add_middleware` on ASGIApp; use directly."""
    app.add_middleware(AuthMiddleware)
