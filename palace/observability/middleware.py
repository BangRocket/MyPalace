"""Request middleware: timing metrics + request_id binding for structlog."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from palace.observability.logging import bind_request_context, clear_request_context
from palace.observability.metrics import (
    http_request_duration,
    http_requests,
    normalize_route,
    status_class,
)

REQUEST_ID_HEADER = "X-Request-ID"


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Records request count + duration metrics and binds a request_id
    for structlog. Runs before AuthMiddleware so the request_id is
    available even on 401 responses."""

    async def dispatch(self, request: Request, call_next):
        request_id = (
            request.headers.get(REQUEST_ID_HEADER)
            or uuid.uuid4().hex
        )
        method = request.method
        route = normalize_route(request.url.path)

        bind_request_context(request_id=request_id, method=method, route=route)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            elapsed = time.perf_counter() - start
            http_request_duration.labels(method=method, route=route).observe(elapsed)
            http_requests.labels(
                method=method,
                route=route,
                status_class=status_class(response.status_code),
            ).inc()
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception:
            elapsed = time.perf_counter() - start
            http_request_duration.labels(method=method, route=route).observe(elapsed)
            http_requests.labels(
                method=method, route=route, status_class="5xx",
            ).inc()
            raise
        finally:
            clear_request_context()
