"""Prometheus metrics + a /metrics endpoint helper.

Counter naming convention: ``palace_<noun>_total{<labels>}``. Histograms use
``palace_<noun>_seconds`` (or ``_bytes`` etc). Labels stay low-cardinality:
no user_id, no key_id, no full path — only normalized route templates and
small enums (status code class, namespace, etc).
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.responses import Response

# Single registry per process. Tests can construct their own if needed.
registry = CollectorRegistry()


http_requests = Counter(
    "palace_http_requests_total",
    "HTTP requests handled, by route template and status class.",
    ["method", "route", "status_class"],
    registry=registry,
)

http_request_duration = Histogram(
    "palace_http_request_duration_seconds",
    "HTTP request duration in seconds, by route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry,
)

cache_hits = Counter(
    "palace_cache_hits_total",
    "Cache hits, by namespace.",
    ["namespace"],
    registry=registry,
)

cache_misses = Counter(
    "palace_cache_misses_total",
    "Cache misses (or no-ops when cache disabled), by namespace.",
    ["namespace"],
    registry=registry,
)

graph_writes = Counter(
    "palace_graph_writes_total",
    "Graph node/edge writes scheduled, by kind.",
    ["kind"],
    registry=registry,
)

graph_failures = Counter(
    "palace_graph_failures_total",
    "Graph operations that raised (logged + counted).",
    registry=registry,
)

job_total = Counter(
    "palace_jobs_total",
    "Background job lifecycle events, by kind and outcome.",
    ["kind", "outcome"],
    registry=registry,
)


def metrics_response() -> Response:
    """FastAPI/Starlette response carrying the Prometheus exposition payload."""
    return Response(
        content=generate_latest(registry),
        media_type=CONTENT_TYPE_LATEST,
    )


def status_class(code: int) -> str:
    """Map an HTTP status code to its class string for low-cardinality labels."""
    return f"{code // 100}xx"


def normalize_route(path: str) -> str:
    """Reduce path-with-IDs to a route template so Prometheus labels stay
    low-cardinality. Heuristic: anything that looks like a UUID or has length
    >= 16 with mixed alphanumerics is treated as an ID.

    Examples:
      /v1/memories/abc-123-uuid → /v1/memories/{id}
      /v1/users/u_42/memories   → /v1/users/{id}/memories
    """
    parts = path.split("/")
    out: list[str] = []
    for part in parts:
        if _looks_like_id(part):
            out.append("{id}")
        else:
            out.append(part)
    return "/".join(out)


def _looks_like_id(part: str) -> bool:
    if not part:
        return False
    if len(part) >= 16 and any(c.isdigit() for c in part):
        return True
    # UUID-like
    return part.count("-") >= 4 and len(part) >= 32
