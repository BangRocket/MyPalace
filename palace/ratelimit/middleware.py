"""Starlette middleware enforcing rate limits per (tenant, key, user)."""

from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from palace.auth.scopes import is_public
from palace.config import settings
from palace.ratelimit.limiter import rate_limiter

# Search/context paths get the tighter bucket; everything else uses default.
SEARCH_PATHS = (
    "/v1/memories/search",
    "/v1/episodes/search",
    "/v1/context",
    "/v1/context/layered",
)


def _bucket_for(path: str) -> tuple[str, int]:
    """Return (bucket_name, per_minute_limit) for the given path."""
    for prefix in SEARCH_PATHS:
        if path == prefix or path.startswith(prefix + "/"):
            return ("search", settings.rate_limit_search_per_min)
    return ("default", settings.rate_limit_default_per_min)


def _user_id_from_request(request: Request) -> str:
    """Best-effort: pull user_id from auth context if it tracks one;
    else fall back to a per-key bucket using key_id."""
    auth = getattr(request.state, "auth", None)
    if auth is None:
        return "anon"
    # Phase 4 doesn't add a user_id to AuthContext (would require body
    # parsing for every request). For now, key_id is the partition key —
    # one bucket per key. This is the right granularity for server-to-server
    # API keys; per-end-user rate limiting can layer on later by inspecting
    # request bodies.
    return auth.key_id


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not rate_limiter.enabled or is_public(request.url.path):
            return await call_next(request)

        auth = getattr(request.state, "auth", None)
        if auth is None:
            # AuthMiddleware would have already 401'd; but defensively skip.
            return await call_next(request)

        # `unlimited` scope opt-out for trusted callers.
        if "unlimited" in auth.scopes:
            return await call_next(request)

        tenant_id = auth.tenant_id or settings.default_tenant_id
        bucket, limit = _bucket_for(request.url.path)
        decision = await rate_limiter.check(
            tenant_id=tenant_id,
            key_id=auth.key_id,
            user_id=_user_id_from_request(request),
            bucket=bucket,
            limit=limit,
        )
        if not decision.allowed:
            body = json.dumps({"error": {
                "code": "rate_limited",
                "message": (
                    f"Too many requests in {rate_limiter.WINDOW_SECONDS}s "
                    f"window: {decision.current}/{decision.limit}"
                ),
                "retry_after_seconds": decision.retry_after_seconds,
            }})
            return Response(
                content=body,
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        return await call_next(request)
