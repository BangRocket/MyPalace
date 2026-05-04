"""Middleware integration tests using the FastAPI test client.

These run with PALACE_AUTH_DISABLED=true (set in conftest) so the bypass
path is exercised by the regular `client` fixture. Per-flow auth checks
(real lookup, scope enforcement, 401/403) live here using a dedicated
`auth_client` fixture that turns auth back on and patches key_service.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from palace.auth.context import AuthContext


@pytest.fixture
def auth_client(
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
) -> Iterator[TestClient]:
    """Like `client` but with auth ENABLED. Tests must inject lookups
    via `mock_key_service.lookup.return_value = AuthContext(...)`."""
    from contextlib import ExitStack

    from palace.config import settings

    patches = [
        patch.dict(os.environ, {"PALACE_AUTH_DISABLED": "false"}, clear=False),
        patch.object(settings, "auth_disabled", False),
        patch.object(settings, "bootstrap_admin_key", None),
        patch("palace.api.memories.memory_service", mock_memory_service),
        patch("palace.api.sessions.session_service", mock_session_service),
        patch("palace.api.context.context_service", mock_context_service),
        patch("palace.api.episodes.episode_service", mock_episode_service),
        patch("palace.api.episodes.job_service", mock_job_service),
        patch("palace.api.arcs.arc_service", mock_arc_service),
        patch("palace.api.arcs.job_service", mock_job_service),
        patch("palace.api.jobs.job_service", mock_job_service),
        patch("palace.api.dynamics.dynamics_service", mock_dynamics_service),
        patch("palace.api.maintenance.dynamics_service", mock_dynamics_service),
        patch("palace.api.intentions.intention_service", mock_intention_service),
        patch("palace.api.maintenance.intention_service", mock_intention_service),
        patch("palace.api.retrieval.layered_retrieval_service", mock_layered_service),
        patch("palace.api.memories.smart_ingestion_service", mock_ingestion_service),
        patch("palace.api.admin.key_service", mock_key_service),
        patch("palace.auth.middleware.key_service", mock_key_service),
        patch("palace.main.key_service", mock_key_service),
        patch("palace.database.init_db", AsyncMock()),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        from palace.main import app

        @asynccontextmanager
        async def dummy_lifespan(app):
            yield

        app.router.lifespan_context = dummy_lifespan
        with TestClient(app) as c:
            yield c


def _ctx(scopes: set[str]) -> AuthContext:
    return AuthContext(key_id="k1", label="test", scopes=frozenset(scopes))


class TestPublicPaths:
    def test_health_no_auth_required(self, auth_client):
        r = auth_client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "service": "palace-memory"}

    def test_openapi_no_auth_required(self, auth_client):
        r = auth_client.get("/openapi.json")
        assert r.status_code == 200


class TestUnauthenticated:
    def test_missing_header_returns_401(self, auth_client):
        r = auth_client.post("/v1/memories", json={"user_id": "u1", "content": "x"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthenticated"

    def test_invalid_key_returns_401(self, auth_client, mock_key_service):
        mock_key_service.lookup.return_value = None
        r = auth_client.post(
            "/v1/memories",
            json={"user_id": "u1", "content": "x"},
            headers={"X-Palace-Key": "pk_live_bogus"},
        )
        assert r.status_code == 401

    def test_revoked_key_returns_401(self, auth_client, mock_key_service):
        # lookup returns None for revoked keys (key_service handles this)
        mock_key_service.lookup.return_value = None
        r = auth_client.get(
            "/v1/users/u1/memories",
            headers={"X-Palace-Key": "pk_live_revoked"},
        )
        assert r.status_code == 401


class TestScopeEnforcement:
    def test_read_key_can_search(self, auth_client, mock_key_service, mock_memory_service):
        mock_key_service.lookup.return_value = _ctx({"read"})
        mock_memory_service.search.return_value = []
        r = auth_client.post(
            "/v1/memories/search",
            json={"query": "x"},
            headers={"X-Palace-Key": "pk_live_x"},
        )
        assert r.status_code == 200

    def test_read_key_cannot_create(self, auth_client, mock_key_service):
        mock_key_service.lookup.return_value = _ctx({"read"})
        r = auth_client.post(
            "/v1/memories",
            json={"user_id": "u1", "content": "x"},
            headers={"X-Palace-Key": "pk_live_x"},
        )
        assert r.status_code == 403
        assert "write" in r.json()["error"]["message"]

    def test_write_key_cannot_admin(self, auth_client, mock_key_service):
        mock_key_service.lookup.return_value = _ctx({"read", "write"})
        r = auth_client.get(
            "/v1/admin/keys",
            headers={"X-Palace-Key": "pk_live_x"},
        )
        assert r.status_code == 403
        assert "admin" in r.json()["error"]["message"]

    def test_admin_key_can_admin(self, auth_client, mock_key_service):
        mock_key_service.lookup.return_value = _ctx({"admin"})
        mock_key_service.list_keys.return_value = []
        r = auth_client.get(
            "/v1/admin/keys",
            headers={"X-Palace-Key": "pk_live_x"},
        )
        assert r.status_code == 200

    def test_admin_doesnt_auto_grant_write(self, auth_client, mock_key_service):
        # Spec D1.10: admin doesn't auto-include write
        mock_key_service.lookup.return_value = _ctx({"admin"})
        r = auth_client.post(
            "/v1/memories",
            json={"user_id": "u1", "content": "x"},
            headers={"X-Palace-Key": "pk_live_x"},
        )
        assert r.status_code == 403


class TestAuthDisabledBypass:
    def test_bypass_grants_all_scopes(self, client, mock_memory_service):
        """Default `client` fixture has auth disabled — every request passes."""
        mock_memory_service.search.return_value = []
        r = client.post("/v1/memories/search", json={"query": "x"})
        assert r.status_code == 200

    def test_bypass_lets_admin_routes_through(self, client, mock_key_service):
        mock_key_service.list_keys.return_value = []
        r = client.get("/v1/admin/keys")
        assert r.status_code == 200
