"""Tests for the admin audit log (phase 7 slice 1)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from palace.audit.middleware import (
    _audit_path,
    _hash_body,
    _status_class,
)


class TestHelpers:
    def test_audit_path_admin(self):
        assert _audit_path("/v1/admin/keys")
        assert _audit_path("/v1/admin/tenants/abc")

    def test_audit_path_maintenance(self):
        assert _audit_path("/v1/maintenance/prune-access-logs")

    def test_audit_path_other_paths_excluded(self):
        assert not _audit_path("/v1/memories")
        assert not _audit_path("/health")
        assert not _audit_path("/v1/admin")  # exact match without trailing /

    def test_status_class(self):
        assert _status_class(200) == "2xx"
        assert _status_class(429) == "4xx"
        assert _status_class(503) == "5xx"

    def test_hash_body_empty(self):
        assert _hash_body(b"") is None

    def test_hash_body_deterministic(self):
        h1 = _hash_body(b'{"key": "value"}')
        h2 = _hash_body(b'{"key": "value"}')
        assert h1 == h2
        assert len(h1) == 64
        assert h1 == hashlib.sha256(b'{"key": "value"}').hexdigest()


class TestPersist:
    @pytest.mark.asyncio
    async def test_persist_inserts_audit_row(self, monkeypatch):
        from palace.audit import middleware as mw

        captured: dict = {}
        db_mock = MagicMock()
        db_mock.add = lambda obj: captured.setdefault("row", obj)
        db_mock.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch("palace.database.async_session", MagicMock(return_value=cm)):
            await mw._persist(
                key_id="k-1",
                tenant_id="acme",
                method="POST",
                path="/v1/admin/keys",
                status_class="2xx",
                body_hash="abc123",
                response_ms=42,
            )
        row = captured["row"]
        assert row.key_id == "k-1"
        assert row.tenant_id == "acme"
        assert row.method == "POST"
        assert row.path == "/v1/admin/keys"
        assert row.status_class == "2xx"
        assert row.request_body_hash == "abc123"
        assert row.response_ms == 42

    @pytest.mark.asyncio
    async def test_persist_failure_swallowed(self, monkeypatch):
        from palace.audit import middleware as mw

        with patch("palace.database.async_session",
                   MagicMock(side_effect=RuntimeError("db down"))):
            # Should not raise.
            await mw._persist(
                key_id="k-1", tenant_id=None, method="GET",
                path="/v1/admin/audit", status_class="2xx",
                body_hash=None, response_ms=10,
            )


class TestMiddlewareSkipsNonAdminPaths:
    def test_health_not_audited(self, client, monkeypatch):
        captured = []
        from palace.audit import middleware as mw

        async def fake_persist(**kw):
            captured.append(kw)
        monkeypatch.setattr(mw, "_persist", fake_persist)

        r = client.get("/health")
        assert r.status_code == 200
        # Give the create_task a moment — but since we never enter the audit
        # branch, captured stays empty.
        assert captured == []

    def test_memories_not_audited(self, client, monkeypatch, mock_memory_service):
        captured = []
        from palace.audit import middleware as mw

        async def fake_persist(**kw):
            captured.append(kw)
        monkeypatch.setattr(mw, "_persist", fake_persist)

        mock_memory_service.list_filtered.return_value = []
        r = client.post("/v1/memories/list", json={})
        assert r.status_code == 200
        assert captured == []


class TestAuditQueryRoute:
    def _row(self, **overrides):
        from palace.models import AuditLog
        defaults = {
            "id": "a-1",
            "key_id": "k-1",
            "tenant_id": "test",
            "method": "GET",
            "path": "/v1/admin/keys",
            "status_class": "2xx",
            "request_body_hash": None,
            "response_ms": 5,
            "created_at": datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
        }
        defaults.update(overrides)
        return AuditLog(**defaults)

    def test_returns_recent_first(self, client, monkeypatch):
        from palace.api import audit as audit_mod

        rows = [
            self._row(id="a-2", path="/v1/admin/keys"),
            self._row(id="a-1", path="/v1/admin/tenants"),
        ]
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = rows
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=scalars_result)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            audit_mod, "async_session", MagicMock(return_value=cm),
        )

        r = client.get("/v1/admin/audit")
        assert r.status_code == 200
        body = r.json()["data"]
        assert len(body) == 2
        assert body[0]["id"] == "a-2"

    def test_limit_too_high_rejected(self, client):
        r = client.get("/v1/admin/audit?limit=10000")
        assert r.status_code == 422

    def test_limit_too_low_rejected(self, client):
        r = client.get("/v1/admin/audit?limit=0")
        assert r.status_code == 422
