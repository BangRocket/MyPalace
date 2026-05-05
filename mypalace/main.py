"""Palace Memory Service — FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mypalace.api import (
    admin,
    arcs,
    audit,
    context,
    entities,
    episodes,
    jobs,
    memories,
    portability,
    reembed,
    sessions,
    stats,
    tenants,
)
from mypalace.api import dynamics as dynamics_api
from mypalace.api import events as events_api
from mypalace.api import graph as graph_api
from mypalace.api import intentions as intentions_api
from mypalace.api import maintenance as maintenance_api
from mypalace.api import retrieval as retrieval_api
from mypalace.audit.middleware import AuditMiddleware
from mypalace.auth.key_service import key_service
from mypalace.auth.middleware import AuthMiddleware
from mypalace.config import settings
from mypalace.database import async_session, init_db
from mypalace.episode_service import episode_service
from mypalace.memory_service import memory_service
from mypalace.models import Tenant
from mypalace.observability.db import install as install_db_metrics
from mypalace.observability.logging import configure_logging
from mypalace.observability.metrics import metrics_response
from mypalace.observability.middleware import ObservabilityMiddleware
from mypalace.observability.tracing import configure_tracing
from mypalace.ratelimit.middleware import RateLimitMiddleware


async def _ensure_default_tenant() -> None:
    """Idempotent INSERT of the default tenant row.

    pg_insert builds a raw SQL INSERT and does NOT apply SQLModel's
    default_factory=utcnow on `created_at`, so we have to set it
    explicitly. (The ORM Tenant(...) constructor would apply it, but
    we want ON CONFLICT DO NOTHING semantics that the ORM doesn't
    expose cleanly.)
    """
    from mypalace.models import utcnow

    async with async_session() as db:
        existing = await db.execute(
            select(Tenant).where(Tenant.id == settings.default_tenant_id),
        )
        if existing.scalar_one_or_none() is None:
            stmt = pg_insert(Tenant).values(
                id=settings.default_tenant_id,
                label="Default Tenant",
                created_at=utcnow(),
            ).on_conflict_do_nothing(index_elements=["id"])
            await db.execute(stmt)
            await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: validate config, create tables, init vector collections."""
    configure_logging()

    # Phase 8 slice 1: validate env-var config BEFORE anything else.
    # ConfigError propagates and kills startup with a clean message
    # rather than crashing on the first request.
    import logging as _logging

    from mypalace.health.config_validator import validate_config
    _log = _logging.getLogger("mypalace.startup")
    for warning in validate_config():
        _log.warning(warning)

    configure_tracing(app)
    # Phase 8 slice 2: install per-query timing + slow-query log on the
    # async engine. Idempotent — re-installation on the same engine is a
    # no-op.
    from mypalace.database import engine as _engine
    install_db_metrics(_engine)
    await init_db()
    await _ensure_default_tenant()
    await memory_service.init(tenant_id=settings.default_tenant_id)
    await episode_service.init(tenant_id=settings.default_tenant_id)
    await key_service.bootstrap_if_needed(settings.bootstrap_admin_key)

    # Optional gRPC server alongside FastAPI (slice 5).
    grpc_server = None
    if settings.grpc_port is not None:
        from mypalace.grpc.server import serve as serve_grpc
        grpc_server = await serve_grpc(settings.grpc_port)

    yield

    if grpc_server is not None:
        await grpc_server.stop(grace=2.0)


app = FastAPI(
    title="Palace Memory Service",
    description="Standalone memory service for AI assistants",
    version="0.1.0",
    lifespan=lifespan,
)

# Order matters (Starlette is inside-out: last added = outermost):
#   ObservabilityMiddleware (outermost) — counts/timing/request_id even on 401/429
#   AuthMiddleware                       — populates request.state.auth
#   RateLimitMiddleware                  — needs auth context to bucket
#   AuditMiddleware (innermost)          — needs auth + final response status
app.add_middleware(AuditMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(ObservabilityMiddleware)


@app.get("/health")
async def health():
    """Backwards-compat alias for /live. Cheap process-up probe."""
    return {"status": "ok", "service": "mypalace"}


@app.get("/live")
async def live():
    """Liveness probe (k8s livenessProbe). Returns 200 iff the process is
    running and the event loop responds. Does NOT touch backends — a
    backend outage must NOT cause k8s to restart the pod, only stop
    sending traffic."""
    return {"status": "ok", "service": "mypalace"}


@app.get("/ready")
async def ready():
    """Readiness probe (k8s readinessProbe). 200 when every configured
    backend responds; 503 when any configured backend is down. Pull the
    pod out of the load balancer until backends recover."""
    from fastapi.responses import JSONResponse

    from mypalace.health.checks import check_all_backends, to_dict

    overall_ok, results = await check_all_backends()
    body = {
        "status": "ok" if overall_ok else "degraded",
        "service": "mypalace",
        "backends": [to_dict(r) for r in results],
    }
    return JSONResponse(content=body, status_code=200 if overall_ok else 503)


@app.get("/health/deep")
async def health_deep():
    """Backwards-compat alias for /ready."""
    return await ready()


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus exposition endpoint. Public — k8s scrapers need it."""
    return metrics_response()


app.include_router(admin.router, prefix="/v1/admin", tags=["admin"])
app.include_router(tenants.router, prefix="/v1/admin", tags=["admin"])
app.include_router(stats.router, prefix="/v1/admin", tags=["admin"])
app.include_router(portability.router, prefix="/v1/admin", tags=["admin"])
app.include_router(reembed.router, prefix="/v1/admin", tags=["admin"])
app.include_router(audit.router, prefix="/v1/admin", tags=["admin"])
app.include_router(entities.router, prefix="/v1/admin", tags=["admin"])
app.include_router(memories.router, prefix="/v1/memories", tags=["memories"])
app.include_router(memories.users_router, prefix="/v1/users", tags=["memories"])
app.include_router(sessions.router, prefix="/v1/sessions", tags=["sessions"])
app.include_router(context.router, prefix="/v1/context", tags=["context"])
app.include_router(episodes.router, prefix="/v1/episodes", tags=["episodes"])
app.include_router(episodes.reflection_router, prefix="/v1/reflection", tags=["episodes"])
app.include_router(episodes.users_episodes_router, prefix="/v1/users", tags=["episodes"])
app.include_router(arcs.synthesis_router, prefix="/v1/synthesis", tags=["arcs"])
app.include_router(arcs.users_arcs_router, prefix="/v1/users", tags=["arcs"])
app.include_router(jobs.router, prefix="/v1/jobs", tags=["jobs"])
app.include_router(dynamics_api.router, prefix="/v1/memories", tags=["dynamics"])
app.include_router(intentions_api.router, prefix="/v1/intentions", tags=["intentions"])
app.include_router(intentions_api.users_router, prefix="/v1/users", tags=["intentions"])
app.include_router(maintenance_api.router, prefix="/v1/maintenance", tags=["maintenance"])
app.include_router(retrieval_api.router, prefix="/v1/context", tags=["retrieval"])
app.include_router(graph_api.router, prefix="/v1/graph", tags=["graph"])
app.include_router(events_api.router, prefix="/v1", tags=["events"])
