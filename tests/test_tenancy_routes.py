"""Tests for /v1/admin/tenants endpoints (auth bypassed via conftest)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from mypalace.models import Tenant


class TestCreateTenant:
    def test_create_tenant(self, client):
        with patch("mypalace.api.tenants.async_session") as mock_session:
            db = mock_session.return_value.__aenter__.return_value
            from unittest.mock import AsyncMock, MagicMock

            no_existing = MagicMock()
            no_existing.scalar_one_or_none.return_value = None
            db.execute = AsyncMock(return_value=no_existing)
            db.add = MagicMock()
            db.commit = AsyncMock()

            async def refresh(row):
                row.created_at = datetime(2026, 5, 4, tzinfo=UTC)

            db.refresh = AsyncMock(side_effect=refresh)

            r = client.post("/v1/admin/tenants", json={"id": "acme", "label": "Acme Corp"})
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["id"] == "acme"
            assert data["label"] == "Acme Corp"

    def test_create_tenant_invalid_id(self, client):
        r = client.post("/v1/admin/tenants", json={"id": "Acme", "label": "x"})
        assert r.status_code == 400
        assert "invalid_tenant_id" in r.json()["detail"]

    def test_create_tenant_too_long(self, client):
        r = client.post("/v1/admin/tenants", json={"id": "a" * 33, "label": "x"})
        # Pydantic catches length first → 422
        assert r.status_code in (400, 422)

    def test_create_tenant_conflict(self, client):
        with patch("mypalace.api.tenants.async_session") as mock_session:
            from unittest.mock import AsyncMock, MagicMock
            db = mock_session.return_value.__aenter__.return_value

            existing = MagicMock()
            existing.scalar_one_or_none.return_value = Tenant(id="acme", label="Existing")
            db.execute = AsyncMock(return_value=existing)

            r = client.post("/v1/admin/tenants", json={"id": "acme", "label": "Other"})
            assert r.status_code == 409


class TestListTenants:
    def test_list_tenants(self, client):
        with patch("mypalace.api.tenants.async_session") as mock_session:
            from unittest.mock import AsyncMock, MagicMock
            db = mock_session.return_value.__aenter__.return_value
            t = Tenant(id="default", label="Default Tenant")
            t.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            scalars = MagicMock()
            scalars.scalars.return_value.all.return_value = [t]
            db.execute = AsyncMock(return_value=scalars)
            r = client.get("/v1/admin/tenants")
            assert r.status_code == 200
            data = r.json()["data"]
            assert len(data) == 1
            assert data[0]["id"] == "default"


class TestDeleteTenant:
    def test_delete_missing_tenant_404(self, client):
        with patch("mypalace.api.tenants.async_session") as mock_session:
            from unittest.mock import AsyncMock, MagicMock
            db = mock_session.return_value.__aenter__.return_value
            no_row = MagicMock()
            no_row.scalar_one_or_none.return_value = None
            db.execute = AsyncMock(return_value=no_row)
            r = client.delete("/v1/admin/tenants/missing")
            assert r.status_code == 404

    def test_delete_invalid_id(self, client):
        r = client.delete("/v1/admin/tenants/BAD-ID")
        assert r.status_code == 400
