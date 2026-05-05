"""Tests for /v1/admin/entities/* endpoints (phase 10 slice 1)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mypalace.models import EntityAlias


def _row(identifier: str = "discord-1", name: str = "Josh") -> EntityAlias:
    now = datetime(2026, 5, 5, tzinfo=UTC)
    return EntityAlias(
        id="abc", tenant_id="test",
        identifier=identifier, canonical_name=name,
        source="manual", created_at=now, updated_at=now,
    )


class TestRegisterEndpoint:
    def test_register_returns_alias(self, client, monkeypatch):
        from mypalace.api import entities as ent_api

        async def fake_register(identifier, canonical_name, tenant_id="default", source="manual"):
            return _row(identifier=identifier, name=canonical_name)

        monkeypatch.setattr(ent_api.entity_service, "register", fake_register)

        r = client.post(
            "/v1/admin/entities/aliases?tenant_id=test",
            json={"identifier": "discord-1", "canonical_name": "Josh"},
        )
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["identifier"] == "discord-1"
        assert body["canonical_name"] == "Josh"
        assert body["source"] == "manual"


class TestListEndpoint:
    def test_returns_aliases(self, client, monkeypatch):
        from mypalace.api import entities as ent_api

        rows = [_row("discord-1", "Josh"), _row("slack-2", "Anne")]
        scalars = MagicMock()
        scalars.scalars.return_value.all.return_value = rows
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalars)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ent_api, "async_session", MagicMock(return_value=cm))

        r = client.get("/v1/admin/entities/aliases?tenant_id=test")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2
        assert {row["identifier"] for row in data} == {"discord-1", "slack-2"}


class TestResolveEndpoint:
    @pytest.mark.parametrize(
        ("returned", "expect_matched"),
        [("Josh", True), ("discord-unknown", False)],
    )
    def test_matched_flag(self, client, monkeypatch, returned, expect_matched):
        from mypalace.api import entities as ent_api

        async def fake_resolve(identifier, tenant_id="default"):
            return returned

        monkeypatch.setattr(ent_api.entity_service, "resolve", fake_resolve)

        ident = "discord-1" if expect_matched else "discord-unknown"
        r = client.get(
            f"/v1/admin/entities/resolve?tenant_id=test&identifier={ident}",
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["resolved"] == returned
        assert data["matched"] == expect_matched


class TestDeleteEndpoint:
    def test_delete_returns_204(self, client, monkeypatch):
        from mypalace.api import entities as ent_api

        row = _row()
        scalar = MagicMock()
        scalar.scalar_one_or_none.return_value = row
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ent_api, "async_session", MagicMock(return_value=cm))
        # The endpoint also calls invalidate_cache; stub it to avoid touching state.
        monkeypatch.setattr(ent_api.entity_service, "invalidate_cache", lambda *a, **k: None)

        r = client.delete("/v1/admin/entities/aliases/discord-1?tenant_id=test")
        assert r.status_code == 204
        db.delete.assert_awaited_once()

    def test_delete_missing_returns_404(self, client, monkeypatch):
        from mypalace.api import entities as ent_api

        scalar = MagicMock()
        scalar.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(ent_api, "async_session", MagicMock(return_value=cm))

        r = client.delete("/v1/admin/entities/aliases/nope?tenant_id=test")
        assert r.status_code == 404


class TestRouteIsAdmin:
    def test_register_requires_admin_scope(self):
        from mypalace.auth.scopes import required_scope
        assert required_scope("POST", "/v1/admin/entities/aliases") == "admin"
