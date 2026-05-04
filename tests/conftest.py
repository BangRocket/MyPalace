"""Shared test fixtures."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_memory_service():
    mock = MagicMock()
    mock.create = AsyncMock()
    mock.create_batch = AsyncMock()
    mock.list_filtered = AsyncMock(return_value=[])
    mock.get = AsyncMock()
    mock.update = AsyncMock()
    mock.delete = AsyncMock()
    mock.delete_for_user = AsyncMock(return_value=0)
    mock.search = AsyncMock(return_value=[])
    mock.list_for_user = AsyncMock(return_value=[])
    mock.init = AsyncMock()
    return mock


@pytest.fixture
def mock_session_service():
    mock = MagicMock()
    mock.create = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.add_message = AsyncMock()
    mock.update = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture
def mock_context_service():
    mock = MagicMock()
    mock.assemble = AsyncMock(
        return_value={"memories": [], "recent_messages": [], "summary": None},
    )
    return mock


@pytest.fixture
def mock_episode_service():
    mock = MagicMock()
    mock.reflect_session = AsyncMock(return_value=[])
    mock.search = AsyncMock(return_value=[])
    mock.get_recent = AsyncMock(return_value=[])
    mock.init = AsyncMock()
    return mock


@pytest.fixture
def mock_arc_service():
    mock = MagicMock()
    mock.synthesize_narratives = AsyncMock(return_value=[])
    mock.get_active = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_job_service():
    mock = MagicMock()
    mock.create = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.run_async = AsyncMock()
    return mock


@pytest.fixture
def client(
    mock_memory_service,
    mock_session_service,
    mock_context_service,
    mock_episode_service,
    mock_arc_service,
    mock_job_service,
):
    with (
        patch("palace.api.memories.memory_service", mock_memory_service),
        patch("palace.api.sessions.session_service", mock_session_service),
        patch("palace.api.context.context_service", mock_context_service),
        patch("palace.api.episodes.episode_service", mock_episode_service),
        patch("palace.api.episodes.job_service", mock_job_service),
        patch("palace.api.arcs.arc_service", mock_arc_service),
        patch("palace.api.arcs.job_service", mock_job_service),
        patch("palace.api.jobs.job_service", mock_job_service),
        patch("palace.memory_service.memory_service", mock_memory_service),
        patch("palace.episode_service.episode_service", mock_episode_service),
        patch("palace.database.init_db", AsyncMock()),
    ):
        from contextlib import asynccontextmanager

        from palace.main import app

        @asynccontextmanager
        async def dummy_lifespan(app):
            yield

        app.router.lifespan_context = dummy_lifespan
        with TestClient(app) as c:
            yield c
