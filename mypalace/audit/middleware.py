"""Starlette middleware that records every admin/maintenance request.

Behavior:
  - Only fires for paths starting with /v1/admin/ or /v1/maintenance/
  - Runs AFTER AuthMiddleware so request.state.auth is populated
  - Insert is fire-and-forget via asyncio.create_task so audit failures
    never delay or break the actual request
  - Body is hashed (SHA256), not stored — answers "did this happen"
    without leaking secrets like bootstrap key plaintext
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)


def _audit_path(path: str) -> bool:
    return path.startswith("/v1/admin/") or path.startswith("/v1/maintenance/")


def _status_class(code: int) -> str:
    return f"{code // 100}xx"


def _hash_body(body: bytes) -> str | None:
    if not body:
        return None
    return hashlib.sha256(body).hexdigest()


async def _persist(
    *,
    key_id: str,
    tenant_id: str | None,
    method: str,
    path: str,
    status_class: str,
    body_hash: str | None,
    response_ms: int,
) -> None:
    """Best-effort insert. Logged + swallowed on any exception."""
    try:
        from mypalace.database import async_session
        from mypalace.models import AuditLog

        row = AuditLog(
            key_id=key_id,
            tenant_id=tenant_id,
            method=method[:10],
            path=path[:500],
            status_class=status_class,
            request_body_hash=body_hash,
            response_ms=response_ms,
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()
    except Exception:
        logger.warning(
            "audit log insert failed (path=%s)", path, exc_info=True,
        )


_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not _audit_path(path):
            return await call_next(request)

        # Only hash bodies for methods that carry one. Reading the body for
        # GET/DELETE/HEAD wastes time and (worse) breaks downstream
        # StreamingResponse handlers that expect a fresh ASGI receive.
        body: bytes | None = None
        if request.method in _BODY_METHODS:
            body = await request.body()

            # Replay the body downstream so the route handler can read it
            # again — BaseHTTPMiddleware exposes the underlying ASGI
            # receive on request._receive.
            async def replay():
                return {"type": "http.request", "body": body, "more_body": False}

            request._receive = replay  # type: ignore[attr-defined]

        start = time.perf_counter()
        response = await call_next(request)
        elapsed = int((time.perf_counter() - start) * 1000)

        auth = getattr(request.state, "auth", None)
        if auth is None:
            return response  # 401 path; no audit row (no key to attribute it to)

        asyncio.create_task(_persist(
            key_id=auth.key_id,
            tenant_id=auth.tenant_id,
            method=request.method,
            path=path,
            status_class=_status_class(response.status_code),
            body_hash=_hash_body(body) if body else None,
            response_ms=elapsed,
        ))
        return response
