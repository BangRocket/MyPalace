"""Shared test fixtures."""

import os

# Disable auth before any palace.* import — settings is a module-level singleton.
os.environ.setdefault("PALACE_AUTH_DISABLED", "true")
os.environ.setdefault("PALACE_DEFAULT_TENANT_ID", "test")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def mock_memory_service():
    mock = MagicMock()
    mock.create = AsyncMock()
    mock.create_batch = AsyncMock(
        return_value={"memories": [], "supersessions": [], "skipped": []},
    )
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
def mock_dynamics_service():
    mock = MagicMock()
    mock.get_dynamics = AsyncMock(return_value=None)
    mock.ensure_dynamics = AsyncMock()
    mock.promote = AsyncMock()
    mock.demote = AsyncMock()
    mock.score = AsyncMock(return_value={
        "composite_score": 0.0,
        "fsrs_score": 0.0,
        "retrievability": 1.0,
        "storage_strength": 0.5,
    })
    mock.prune_access_logs = AsyncMock(return_value=0)
    return mock


@pytest.fixture
def mock_layered_service():
    mock = MagicMock()
    mock.assemble = AsyncMock(
        return_value={
            "l1_user_profile": {
                "memories": [],
                "recent_episodes": [],
                "active_arcs": [],
            },
            "l2_relevant_context": {
                "memories": [],
                "episodes": [],
            },
            "l3_graph_context": None,
            "recent_messages": None,
            "summary": None,
            "char_counts": {"l1": 0, "l2": 0},
        },
    )
    return mock


@pytest.fixture
def mock_ingestion_service():
    mock = MagicMock()
    mock.extract_memories = AsyncMock(return_value=[])
    mock.dedup_and_write = AsyncMock(return_value=([], [], []))
    mock.supersede_memory = AsyncMock()
    mock.get_supersessions = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_key_service():
    mock = MagicMock()
    mock.create_key = AsyncMock()
    mock.lookup = AsyncMock(return_value=None)
    mock.list_keys = AsyncMock(return_value=[])
    mock.revoke = AsyncMock(return_value=True)
    mock.bootstrap_if_needed = AsyncMock(return_value=False)
    return mock


@pytest.fixture
def mock_intention_service():
    mock = MagicMock()
    mock.set = AsyncMock()
    mock.check = AsyncMock(return_value=[])
    mock.format_for_prompt = MagicMock(return_value="")
    mock.list_for_user = AsyncMock(return_value=[])
    mock.delete = AsyncMock(return_value=True)
    mock.cleanup_expired = AsyncMock(return_value=0)
    return mock


@pytest.fixture
def mock_emotional_service():
    mock = MagicMock()
    mock.record = AsyncMock()
    mock.get_recent = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def client(
    mock_memory_service,
    mock_session_service,
    mock_context_service,
    mock_episode_service,
    mock_arc_service,
    mock_job_service,
    mock_dynamics_service,
    mock_intention_service,
    mock_layered_service,
    mock_ingestion_service,
    mock_key_service,
    mock_emotional_service,
):
    from contextlib import ExitStack, asynccontextmanager

    patches = [
        patch("mypalace.api.memories.memory_service", mock_memory_service),
        patch("mypalace.api.sessions.session_service", mock_session_service),
        patch("mypalace.api.context.context_service", mock_context_service),
        patch("mypalace.api.episodes.episode_service", mock_episode_service),
        patch("mypalace.api.episodes.job_service", mock_job_service),
        patch("mypalace.api.arcs.arc_service", mock_arc_service),
        patch("mypalace.api.arcs.job_service", mock_job_service),
        patch("mypalace.api.jobs.job_service", mock_job_service),
        patch("mypalace.api.dynamics.dynamics_service", mock_dynamics_service),
        patch("mypalace.api.maintenance.dynamics_service", mock_dynamics_service),
        patch("mypalace.api.intentions.intention_service", mock_intention_service),
        patch("mypalace.api.maintenance.intention_service", mock_intention_service),
        patch("mypalace.api.retrieval.layered_retrieval_service", mock_layered_service),
        patch("mypalace.api.memories.smart_ingestion_service", mock_ingestion_service),
        patch("mypalace.api.admin.key_service", mock_key_service),
        patch("mypalace.auth.key_service.key_service", mock_key_service),
        patch("mypalace.auth.middleware.key_service", mock_key_service),
        patch("mypalace.main.key_service", mock_key_service),
        patch("mypalace.memory_service.memory_service", mock_memory_service),
        patch("mypalace.episode_service.episode_service", mock_episode_service),
        patch("mypalace.api.emotional.emotional_service", mock_emotional_service),
        patch("mypalace.emotional_service.emotional_service", mock_emotional_service),
        patch("mypalace.database.init_db", AsyncMock()),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        from mypalace.main import app

        @asynccontextmanager
        async def dummy_lifespan(app):
            yield

        app.router.lifespan_context = dummy_lifespan
        with TestClient(app) as c:
            yield c
