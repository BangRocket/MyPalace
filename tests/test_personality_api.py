"""Tests for /v1/admin/personality/* endpoints (phase 10 slice 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from mypalace.models import PersonalityTrait


def _trait(id: str = "t1", category: str = "interests") -> PersonalityTrait:
    now = datetime(2026, 5, 5, tzinfo=UTC)
    return PersonalityTrait(
        id=id, tenant_id="test", agent_id="default",
        category=category, trait_key="key", content="content",
        source="manual", reason=None, active=True,
        created_at=now, updated_at=now,
    )


class TestListEndpoint:
    def test_returns_active_traits(self, client, monkeypatch):
        from mypalace.api import personality as api

        async def fake_list(agent_id="default", tenant_id="default"):
            return [_trait("t1"), _trait("t2", category="values")]

        monkeypatch.setattr(api.personality_service, "list_active", fake_list)

        r = client.get("/v1/admin/personality/traits?tenant_id=test")
        assert r.status_code == 200
        data = r.json()["data"]
        assert {row["id"] for row in data} == {"t1", "t2"}


class TestCreateEndpoint:
    def test_post_returns_trait(self, client, monkeypatch):
        from mypalace.api import personality as api

        async def fake_add(**kwargs):
            return _trait()

        monkeypatch.setattr(api.personality_service, "add", fake_add)

        r = client.post(
            "/v1/admin/personality/traits?tenant_id=test",
            json={
                "category": "interests",
                "trait_key": "music",
                "content": "loves jazz",
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["category"] == "interests"


class TestUpdateEndpoint:
    def test_patch_returns_updated(self, client, monkeypatch):
        from mypalace.api import personality as api

        async def fake_update(**kwargs):
            return _trait()

        monkeypatch.setattr(api.personality_service, "update", fake_update)

        r = client.patch(
            "/v1/admin/personality/traits/t1",
            json={"content": "new content"},
        )
        assert r.status_code == 200

    def test_patch_missing_returns_404(self, client, monkeypatch):
        from mypalace.api import personality as api

        async def fake_update(**kwargs):
            raise ValueError("trait not found: tx")

        monkeypatch.setattr(api.personality_service, "update", fake_update)

        r = client.patch(
            "/v1/admin/personality/traits/tx",
            json={"content": "anything"},
        )
        assert r.status_code == 404


class TestDeleteEndpoint:
    def test_delete_active_returns_204(self, client, monkeypatch):
        from mypalace.api import personality as api
        monkeypatch.setattr(
            api.personality_service, "remove", AsyncMock(return_value=True),
        )
        r = client.delete("/v1/admin/personality/traits/t1")
        assert r.status_code == 204

    def test_delete_missing_returns_404(self, client, monkeypatch):
        from mypalace.api import personality as api
        monkeypatch.setattr(
            api.personality_service, "remove", AsyncMock(return_value=False),
        )
        r = client.delete("/v1/admin/personality/traits/tx")
        assert r.status_code == 404


class TestRouteIsAdmin:
    def test_routes_require_admin_scope(self):
        from mypalace.auth.scopes import required_scope
        assert required_scope("GET", "/v1/admin/personality/traits") == "admin"
        assert required_scope("POST", "/v1/admin/personality/traits") == "admin"


class TestWorkerHandlerWired:
    def test_personality_evolve_in_handler_registry(self):
        from mypalace.workers.handlers import HANDLER_REGISTRY
        assert "personality_evolve" in HANDLER_REGISTRY
