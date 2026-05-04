"""Tests for cross-tenant search (phase 7 slice 3)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_memory(mid: str, content: str = "x"):
    m = MagicMock()
    m.id = mid
    m.content = content
    m.memory_type = "semantic"
    m.importance = 1.0
    m.created_at = datetime(2026, 5, 4, tzinfo=UTC)
    return m


class TestRouteValidation:
    def test_all_denied_for_tenant_bound_key(self, client, mock_key_service):
        from mypalace.auth.context import AuthContext
        from mypalace.config import settings

        mock_key_service.lookup = AsyncMock(return_value=AuthContext(
            key_id="k1", label="bound",
            scopes=frozenset({"read", "write"}),
            tenant_id="acme",
        ))
        with patch.object(settings, "auth_disabled", False):
            r = client.post(
                "/v1/memories/search",
                json={"query": "x", "tenant_id": "ALL"},
                headers={"X-Palace-Key": "pk_live_x"},
            )
        assert r.status_code == 403
        assert "cross-tenant" in r.json()["detail"]


class TestCrossTenantFanout:
    def test_all_works_for_cross_tenant_admin(
        self, client, mock_memory_service, mock_key_service,
    ):
        from mypalace.auth.context import AuthContext
        from mypalace.config import settings

        mock_key_service.lookup = AsyncMock(return_value=AuthContext(
            key_id="admin-x", label="cross",
            scopes=frozenset({"read", "write", "admin"}),
            tenant_id=None,
        ))
        mock_memory_service.search_all_tenants = AsyncMock(return_value=[
            (_fake_memory("m1", "hello acme"), 0.9, "acme"),
            (_fake_memory("m2", "hello beta"), 0.7, "beta"),
        ])

        with patch.object(settings, "auth_disabled", False):
            r = client.post(
                "/v1/memories/search",
                json={"query": "hello", "tenant_id": "ALL"},
                headers={"X-Palace-Key": "pk_live_x"},
            )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2
        assert {d["tenant_id"] for d in data} == {"acme", "beta"}
        # Highest score first
        assert data[0]["score"] >= data[1]["score"]

    def test_single_tenant_path_unchanged(
        self, client, mock_memory_service,
    ):
        # Default path: no tenant_id field — uses bound tenant.
        mock_memory_service.search = AsyncMock(return_value=[
            (_fake_memory("m1", "hi"), 0.5),
        ])
        r = client.post("/v1/memories/search", json={"query": "hi"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        # No tenant_id field for single-tenant payloads.
        assert data[0]["tenant_id"] is None


class TestSearchAllTenantsService:
    @pytest.mark.asyncio
    async def test_no_tenants_returns_empty(self, monkeypatch):
        from mypalace import memory_service as ms
        from mypalace.memory_service import MemoryService

        # Stub embedder
        fake_embedder = MagicMock()
        fake_embedder.embed = AsyncMock(return_value=[[0.0] * 384])
        fake_embedder.dim = 384

        # Stub session yielding no tenants.
        empty = MagicMock()
        empty.all.return_value = []
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=empty)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))

        svc = MemoryService()
        svc._embedder = fake_embedder
        result = await svc.search_all_tenants(query="x", limit=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_merges_and_caps_at_limit(self, monkeypatch):
        from mypalace import memory_service as ms
        from mypalace.memory_service import MemoryService

        fake_embedder = MagicMock()
        fake_embedder.embed = AsyncMock(return_value=[[0.0] * 384])
        fake_embedder.dim = 384

        # Two tenants returned by Tenant.id select.
        tenants_call = {"i": 0}

        async def fake_execute(*args, **kwargs):
            tenants_call["i"] += 1
            if tenants_call["i"] == 1:
                # First call: list tenants
                m = MagicMock()
                m.all.return_value = [("t-a",), ("t-b",)]
                return m
            else:
                # Second call: load Memory rows by id
                m = MagicMock()
                m.scalars.return_value.all.return_value = [
                    _fake_memory("m1"), _fake_memory("m2"),
                    _fake_memory("m3"), _fake_memory("m4"),
                ]
                return m

        db_mock = MagicMock()
        db_mock.execute = AsyncMock(side_effect=fake_execute)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ms, "async_session", MagicMock(return_value=cm))

        # Per-tenant vector_store.search returns 2 rows each.
        async def fake_search(*args, tenant_id, **kwargs):
            if tenant_id == "t-a":
                return [("m1", 0.95), ("m2", 0.7)]
            return [("m3", 0.85), ("m4", 0.6)]

        monkeypatch.setattr(ms.vector_store, "search", fake_search)

        svc = MemoryService()
        svc._embedder = fake_embedder
        result = await svc.search_all_tenants(query="x", limit=3)
        # Top 3 by score: m1(0.95), m3(0.85), m2(0.7) — m4(0.6) capped
        assert len(result) == 3
        scores = [r[1] for r in result]
        assert scores == sorted(scores, reverse=True)
        # Tenant tagging preserved
        tenants = [r[2] for r in result]
        assert tenants[0] == "t-a"  # m1
        assert tenants[1] == "t-b"  # m3
