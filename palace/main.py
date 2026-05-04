"""Palace Memory Service — FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from palace.api import arcs, context, episodes, jobs, memories, sessions
from palace.api import dynamics as dynamics_api
from palace.api import intentions as intentions_api
from palace.api import maintenance as maintenance_api
from palace.database import init_db
from palace.episode_service import episode_service
from palace.memory_service import memory_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables and init vector collections."""
    await init_db()
    await memory_service.init()
    await episode_service.init()
    yield
    # Shutdown


app = FastAPI(
    title="Palace Memory Service",
    description="Standalone memory service for AI assistants",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "palace-memory"}


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
