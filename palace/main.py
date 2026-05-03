"""Palace Memory Service — FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from palace.api import context, memories, sessions
from palace.database import init_db
from palace.memory_service import memory_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables and init vector collection."""
    await init_db()
    await memory_service.init()
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
