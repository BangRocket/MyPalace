"""Tests for per-tenant schema lifecycle (phase 12 slice 2).

Real DDL is exercised by integration tests against a live Postgres.
Here we mock the SQLAlchemy connection and verify:

- replicate_per_tenant_schema emits CREATE SCHEMA + CREATE TABLE for
  the right table set
- drop_tenant_schema emits DROP SCHEMA CASCADE
- both helpers refuse invalid tenant ids
- POST /v1/admin/tenants triggers replicate when mode=schema
- DELETE /v1/admin/tenants/{id} requires confirm=<id> when destructive
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from mypalace.tenancy import (
    PER_TENANT_TABLES,
    PUBLIC_TABLES,
    drop_tenant_schema,
    replicate_per_tenant_schema,
)


class TestTableClassification:
    def test_per_tenant_set_is_complete(self):
        # Every domain-data table must land in PER_TENANT_TABLES; every
        # catalog table must land in PUBLIC_TABLES. Disjoint, no overlap.
        assert PER_TENANT_TABLES.isdisjoint(PUBLIC_TABLES)

    def test_no_unclassified_tables(self):
        """Every SQLModel table in the codebase must be in exactly one
        bucket. Catches new tables added without choosing a tier."""
        from sqlmodel import SQLModel
        all_tables = set(SQLModel.metadata.tables.keys())
        unclassified = all_tables - PER_TENANT_TABLES - PUBLIC_TABLES
        assert not unclassified, (
            f"new tables added without classification: {unclassified}. "
            "Add to mypalace/tenancy.py PER_TENANT_TABLES or PUBLIC_TABLES."
        )


class TestReplicateSchema:
    def test_emits_create_schema_then_create_tables(self):
        sync_conn = MagicMock()
        replicate_per_tenant_schema("acme", sync_conn)

        executes = sync_conn.execute.call_args_list
        # First call must be CREATE SCHEMA — order matters because the
        # tables can't be created until the schema exists.
        first_sql = str(executes[0][0][0])
        assert "CREATE SCHEMA" in first_sql.upper()
        assert "acme" in first_sql

        # Subsequent calls cover CREATE TABLE for each per-tenant table
        # plus CREATE INDEX for each table's indexes.
        all_sql = " ".join(str(c[0][0]).upper() for c in executes[1:])
        for tn in PER_TENANT_TABLES:
            assert f"CREATE TABLE IF NOT EXISTS ACME.{tn.upper()}" in all_sql.upper(), (
                f"missing CREATE TABLE for {tn}"
            )

    def test_rejects_invalid_tenant_id(self):
        import pytest
        sync_conn = MagicMock()
        with pytest.raises(ValueError, match="invalid tenant_id"):
            replicate_per_tenant_schema("bad'; DROP--", sync_conn)
        # No DDL should have run.
        assert sync_conn.execute.call_count == 0


class TestDropSchema:
    def test_emits_drop_schema_cascade(self):
        sync_conn = MagicMock()
        drop_tenant_schema("acme", sync_conn)
        assert sync_conn.execute.call_count == 1
        sql = str(sync_conn.execute.call_args[0][0]).upper()
        assert "DROP SCHEMA" in sql
        assert "CASCADE" in sql

    def test_rejects_invalid_tenant_id(self):
        import pytest
        sync_conn = MagicMock()
        with pytest.raises(ValueError, match="invalid tenant_id"):
            drop_tenant_schema("bad space", sync_conn)
        assert sync_conn.execute.call_count == 0


class TestCreateTenantWiring:
    def test_create_in_table_mode_skips_schema_provisioning(
        self, client, monkeypatch,
    ):
        from mypalace.api import tenants as api
        from mypalace.config import settings

        monkeypatch.setattr(settings, "tenant_schema_mode", "table")

        # Stub the DB session so the tenant insert "succeeds".
        scalar = MagicMock()
        scalar.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(api, "async_session", MagicMock(return_value=cm))

        replicate_called = []
        monkeypatch.setattr(
            api, "replicate_per_tenant_schema",
            lambda *a, **k: replicate_called.append(a),
        )

        r = client.post(
            "/v1/admin/tenants",
            json={"id": "acme", "label": "Acme Corp"},
        )
        assert r.status_code == 200
        assert replicate_called == []  # never called in table mode

    def test_create_in_schema_mode_calls_replicate(
        self, client, monkeypatch,
    ):
        from mypalace.api import tenants as api
        from mypalace.config import settings

        monkeypatch.setattr(settings, "tenant_schema_mode", "schema")

        scalar = MagicMock()
        scalar.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(api, "async_session", MagicMock(return_value=cm))

        # Mock engine.begin() → conn.run_sync(callable) — just record that
        # the callable received the right tenant id.
        called_with: list = []

        class _FakeConn:
            async def run_sync(self, fn):
                # Invoke the callback with a stub sync connection so the
                # closure-captured tenant id flows in.
                fn(MagicMock())

        @patch.object(api, "engine")
        def run(mock_engine):
            mock_engine.begin = MagicMock()
            mock_engine.begin.return_value.__aenter__ = AsyncMock(
                return_value=_FakeConn(),
            )
            mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

            def fake_replicate(tid, _sc):
                called_with.append(tid)

            with patch.object(api, "replicate_per_tenant_schema", fake_replicate):
                return client.post(
                    "/v1/admin/tenants",
                    json={"id": "acme", "label": "Acme Corp"},
                )

        r = run()
        assert r.status_code == 200, r.text
        assert called_with == ["acme"]


class TestDeleteTenantConfirmGuard:
    def _stub_db(self, monkeypatch, has_data: bool = False):
        from datetime import UTC, datetime

        from mypalace.api import tenants as api
        from mypalace.models import Tenant

        tenant_row = Tenant(
            id="acme", label="Acme",
            created_at=datetime(2026, 5, 5, tzinfo=UTC),
        )

        responses = [tenant_row, *(([None] * 5) if not has_data else [tenant_row] * 5)]
        scalars = []
        for resp in responses:
            s = MagicMock()
            s.scalar_one_or_none.return_value = resp
            scalars.append(s)

        db = MagicMock()
        db.execute = AsyncMock(side_effect=scalars)
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(api, "async_session", MagicMock(return_value=cm))
        return db

    def test_table_mode_no_force_no_data_succeeds(self, client, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "tenant_schema_mode", "table")
        self._stub_db(monkeypatch, has_data=False)

        r = client.delete("/v1/admin/tenants/acme")
        assert r.status_code == 200

    def test_table_mode_with_data_returns_409(self, client, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "tenant_schema_mode", "table")
        self._stub_db(monkeypatch, has_data=True)

        r = client.delete("/v1/admin/tenants/acme")
        assert r.status_code == 409
        assert "force=true" in r.json()["detail"]

    def test_schema_mode_requires_confirm(self, client, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "tenant_schema_mode", "schema")
        self._stub_db(monkeypatch, has_data=False)

        # No confirm → 400 destructive guard.
        r = client.delete("/v1/admin/tenants/acme")
        assert r.status_code == 400
        assert "confirm=acme" in r.json()["detail"]

    def test_force_requires_confirm(self, client, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "tenant_schema_mode", "table")
        self._stub_db(monkeypatch, has_data=True)

        r = client.delete("/v1/admin/tenants/acme?force=true")
        assert r.status_code == 400
        assert "confirm=acme" in r.json()["detail"]

    def test_confirm_mismatch_rejected(self, client, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "tenant_schema_mode", "schema")
        self._stub_db(monkeypatch, has_data=False)

        r = client.delete("/v1/admin/tenants/acme?confirm=globex")
        assert r.status_code == 400
