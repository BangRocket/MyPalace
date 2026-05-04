"""Palace Memory Service — FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from palace.api import (
    admin,
    arcs,
    context,
    episodes,
    jobs,
    memories,
    portability,
    sessions,
    stats,
    tenants,
)
from palace.api import dynamics as dynamics_api
from palace.api import events as events_api
from palace.api import graph as graph_api
from palace.api import intentions as intentions_api
from palace.api import maintenance as maintenance_api
from palace.api import retrieval as retrieval_api
from palace.auth.key_service import key_service
from palace.auth.middleware import AuthMiddleware
from palace.config import settings
from palace.database import async_session, init_db
from palace.episode_service import episode_service
from palace.memory_service import memory_service
from palace.models import Tenant
from palace.observability.logging import configure_logging
from palace.observability.metrics import metrics_response
from palace.observability.middleware import ObservabilityMiddleware
from palace.observability.tracing import configure_tracing
from palace.ratelimit.middleware import RateLimitMiddleware


async def _ensure_default_tenant() -> None:
    """Idempotent INSERT of the default tenant row."""
    async with async_session() as db:
        existing = await db.execute(
            select(Tenant).where(Tenant.id == settings.default_tenant_id),
        )
        if existing.scalar_one_or_none() is None:
            stmt = pg_insert(Tenant).values(
                id=settings.default_tenant_id,
                label="Default Tenant",
            ).on_conflict_do_nothing(index_elements=["id"])
            await db.execute(stmt)
            await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables and init vector collections."""
    configure_logging()
    configure_tracing(app)
    await init_db()
    await _ensure_default_tenant()
    await memory_service.init(tenant_id=settings.default_tenant_id)
    await episode_service.init(tenant_id=settings.default_tenant_id)
    await key_service.bootstrap_if_needed(settings.bootstrap_admin_key)

    # Optional gRPC server alongside FastAPI (slice 5).
    grpc_server = None
    if settings.grpc_port is not None:
        from palace.grpc.server import serve as serve_grpc
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
#   RateLimitMiddleware (innermost)      — needs auth context to bucket
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(ObservabilityMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "palace-memory"}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus exposition endpoint. Public — k8s scrapers need it."""
    return metrics_response()


app.include_router(admin.router, prefix="/v1/admin", tags=["admin"])
app.include_router(tenants.router, prefix="/v1/admin", tags=["admin"])
app.include_router(stats.router, prefix="/v1/admin", tags=["admin"])
app.include_router(portability.router, prefix="/v1/admin", tags=["admin"])
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
