"""Integration test fixtures: live postgres + qdrant via TestContainers."""

import contextlib
import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer


# Auto-detect podman on macOS so testcontainers can find the container engine
# without forcing the user to set DOCKER_HOST manually. If DOCKER_HOST is
# already set (Docker users, CI, etc.), respect it.
def _configure_container_runtime() -> None:
    import shutil
    import subprocess

    if os.environ.get("DOCKER_HOST"):
        return  # respect user/CI override

    if not shutil.which("podman"):
        return  # no podman; assume Docker is on the default socket

    try:
        socket_path = subprocess.check_output(
            [
                "podman",
                "machine",
                "inspect",
                "--format",
                "{{.ConnectionInfo.PodmanSocket.Path}}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return

    if socket_path:
        os.environ["DOCKER_HOST"] = f"unix://{socket_path}"
        # Ryuk (testcontainers' reaper) doesn't always cooperate with rootless
        # podman on macOS; testcontainers can clean up containers without it.
        os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


_configure_container_runtime()


def _wait_for_http(url: str, timeout: float = 30.0) -> None:
    """Poll an HTTP URL until it returns 2xx or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 400:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Spin up postgres for the test session. Returns asyncpg URL."""
    with PostgresContainer("postgres:16-alpine") as pg:
        # testcontainers gives us a sync URL; rewrite to asyncpg
        sync_url = pg.get_connection_url()
        # Format: postgresql+psycopg2://user:pass@host:port/db
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        # Some versions return postgresql:// directly
        async_url = async_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        yield async_url


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    """Spin up qdrant for the test session."""
    container = DockerContainer("qdrant/qdrant:latest").with_exposed_ports(6333)
    container.start()
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6333)
        url = f"http://{host}:{port}"
        _wait_for_http(f"{url}/healthz")
        yield url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def palace_settings(postgres_url: str, qdrant_url: str) -> dict[str, str]:
    """Env vars Palace needs to point at the test containers.
    Use a small embedding model so test sessions stay fast."""
    return {
        "PALACE_DATABASE_URL": postgres_url,
        "QDRANT_URL": qdrant_url,
        "QDRANT_COLLECTION": f"palace_int_{uuid.uuid4().hex[:8]}",
        "EMBEDDING_PROVIDER": "huggingface",
        "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
        # Phase 3 slice 1: existing live tests run as if auth weren't there.
        # The dedicated auth_live tests flip this back on per-test.
        "PALACE_AUTH_DISABLED": "true",
    }


@pytest_asyncio.fixture(scope="session")
async def palace_app(palace_settings: dict[str, str]):
    """Boot the Palace ASGI app pointed at the test containers.
    Yields the FastAPI app instance.

    Module reload order matters: each downstream module captures the previous
    module's symbols at import time, so we must reload outward from config
    (settings) → database/vector/memory_service (engine + singletons) →
    api routers (closed-over singletons) → main (assembles the app).
    """
    for k, v in palace_settings.items():
        os.environ[k] = v

    import importlib

    from palace import config as palace_config
    importlib.reload(palace_config)
    from palace import database, memory_service, session_service, vector
    importlib.reload(database)
    importlib.reload(vector)
    importlib.reload(memory_service)
    importlib.reload(session_service)
    from palace import context_service
    importlib.reload(context_service)
    # API router modules close over the singletons via `from ... import`
    # — reload them so routes pick up the new memory_service / vector_store.
    from palace.api import common as api_common
    importlib.reload(api_common)
    from palace.api import context as api_context
    from palace.api import memories as api_memories
    from palace.api import sessions as api_sessions
    importlib.reload(api_memories)
    importlib.reload(api_sessions)
    importlib.reload(api_context)
    # Slice 3: dynamics + maintenance routers close over dynamics_service.
    from palace.dynamics import service as dynamics_service_mod
    importlib.reload(dynamics_service_mod)
    # Slice 4: intentions service + router close over async_session.
    from palace.intentions import service as intentions_service_mod
    importlib.reload(intentions_service_mod)
    from palace.api import dynamics as api_dynamics
    from palace.api import intentions as api_intentions
    from palace.api import maintenance as api_maintenance
    importlib.reload(api_dynamics)
    importlib.reload(api_intentions)
    importlib.reload(api_maintenance)
    # Slice 5: layered retrieval + smart ingestion routers close over services.
    from palace.retrieval import ingestion as ingestion_mod
    from palace.retrieval import layered as layered_mod
    importlib.reload(layered_mod)
    importlib.reload(ingestion_mod)
    from palace.api import retrieval as api_retrieval
    importlib.reload(api_retrieval)
    importlib.reload(api_memories)  # picks up the new smart_ingestion_service
    from palace import main as palace_main
    importlib.reload(palace_main)

    # Run lifespan startup (creates tables + Qdrant collection + default tenant)
    await palace_main.init_db()
    await palace_main._ensure_default_tenant()
    await palace_main.memory_service.init(tenant_id="test")
    yield palace_main.app


@pytest_asyncio.fixture
async def http_client(palace_app) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI in-process client (no real TCP) — fast and avoids port collisions."""
    transport = httpx.ASGITransport(app=palace_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://palace.test",
    ) as client:
        yield client


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables(palace_app):
    """Truncate tables and clear Qdrant points between tests."""
    from sqlalchemy import delete

    from palace.database import async_session
    from palace.models import (
        ApiKey,
        AuditLog,
        Intention,
        Memory,
        MemoryAccessLog,
        MemoryDynamics,
        MemorySupersession,
        Message,
        NarrativeArc,
        ReflectionJob,
        Tenant,
    )
    from palace.models import Session as SessionModel
    from palace.vector import episode_vector_store, vector_store

    async with async_session() as db:
        # Access logs first — they FK to memory_dynamics with CASCADE, but
        # being explicit keeps the order obvious.
        await db.execute(delete(MemoryAccessLog))
        await db.execute(delete(MemoryDynamics))
        await db.execute(delete(MemorySupersession))
        await db.execute(delete(Intention))
        await db.execute(delete(Message))
        await db.execute(delete(SessionModel))
        await db.execute(delete(Memory))
        await db.execute(delete(NarrativeArc))
        await db.execute(delete(ReflectionJob))
        await db.execute(delete(ApiKey))
        await db.execute(delete(AuditLog))
        # Tenants table: only delete non-default rows so per-tenant collection
        # creation in tests doesn't have to re-bootstrap the row each time.
        await db.execute(delete(Tenant).where(Tenant.id != "test"))
        await db.commit()

    # Clear all vector points by recreating the collections — phase 3 slice 2
    # has per-tenant collections, so iterate every collection whose name starts
    # with the base prefixes.
    with contextlib.suppress(Exception):
        all_collections = await vector_store.client.get_collections()
        for c in all_collections.collections:
            if c.name.startswith(vector_store.base_collection):
                with contextlib.suppress(Exception):
                    await vector_store.client.delete_collection(c.name)
            if c.name.startswith(episode_vector_store.base_collection):
                with contextlib.suppress(Exception):
                    await episode_vector_store.client.delete_collection(c.name)
    # Reset the per-store memo of "ensured" collections so the next test
    # actually re-creates them.
    vector_store._ensured.clear()
    episode_vector_store._ensured.clear()

    from palace.episode_service import episode_service
    from palace.memory_service import memory_service
    await memory_service.init(tenant_id="test")
    await episode_service.init(tenant_id="test")
    yield


@pytest_asyncio.fixture
async def stub_llm(palace_app):
    """Override palace.llm.llm.complete with a per-test stub.
    Tests set `stub_llm.next_response = "..."` before triggering reflection."""

    from unittest.mock import AsyncMock

    from palace import llm as llm_module

    holder = type("Holder", (), {"next_response": ""})()
    original = llm_module.llm.complete
    llm_module.llm.complete = AsyncMock(side_effect=lambda *a, **kw: holder.next_response)
    yield holder
    llm_module.llm.complete = original
