"""Tests for the per-request tenant contextvar (phase 12 slice 1).

Covers the contextvar primitives, AuthMiddleware integration, and
AuthContext.resolve_tenant updating the contextvar. The actual
``SET LOCAL search_path`` SQL behavior is exercised in integration
tests against a real Postgres — here we only verify the wiring up to
the SQLAlchemy event boundary.
"""

from __future__ import annotations

import asyncio

import pytest

from mypalace.auth.context import AuthContext
from mypalace.tenancy import (
    current_tenant,
    is_valid_schema_name,
    set_current_tenant,
    tenant_scope,
)


class TestContextVarPrimitives:
    def test_default_is_none(self):
        # Each test starts in a fresh contextvar (pytest's asyncio mode
        # gives each test its own task / context).
        assert current_tenant() is None

    def test_set_and_read(self):
        token = set_current_tenant("acme")
        try:
            assert current_tenant() == "acme"
        finally:
            # Reset so other tests in this run don't see it.
            from mypalace.tenancy import _current_tenant
            _current_tenant.reset(token)

    def test_tenant_scope_restores_previous(self):
        token = set_current_tenant("outer")
        try:
            assert current_tenant() == "outer"
            with tenant_scope("inner"):
                assert current_tenant() == "inner"
            assert current_tenant() == "outer"
        finally:
            from mypalace.tenancy import _current_tenant
            _current_tenant.reset(token)

    @pytest.mark.asyncio
    async def test_does_not_leak_across_tasks(self):
        """contextvars are per-task — sibling asyncio tasks must not see
        each other's tenant."""
        seen: dict[str, str | None] = {}

        async def task_a():
            with tenant_scope("acme"):
                await asyncio.sleep(0)
                seen["a"] = current_tenant()

        async def task_b():
            with tenant_scope("globex"):
                await asyncio.sleep(0)
                seen["b"] = current_tenant()

        await asyncio.gather(task_a(), task_b())
        assert seen == {"a": "acme", "b": "globex"}


class TestSchemaNameValidation:
    @pytest.mark.parametrize("ok", ["acme", "default", "tenant_1", "abc-123", "a"])
    def test_valid(self, ok):
        assert is_valid_schema_name(ok)

    @pytest.mark.parametrize(
        "bad",
        [
            "Acme",                     # uppercase
            "tenant'; DROP TABLE--",    # injection attempt
            "tenant.public",            # dot
            "",                         # empty
            "x" * 33,                   # too long (limit 32)
            "tenant id",                # space
            "tenant\"id",               # quote
        ],
    )
    def test_rejects(self, bad):
        assert not is_valid_schema_name(bad)


class TestAuthContextResolveTenantSetsContextvar:
    def test_tenant_bound_key_seats_contextvar(self):
        ctx = AuthContext(
            key_id="k1", label="bound", scopes=frozenset({"read"}),
            tenant_id="acme",
        )
        # Pre-condition: contextvar is None for this test.
        token = set_current_tenant(None)
        try:
            resolved = ctx.resolve_tenant()
            assert resolved == "acme"
            assert current_tenant() == "acme"
        finally:
            from mypalace.tenancy import _current_tenant
            _current_tenant.reset(token)

    def test_cross_tenant_with_request_seats_contextvar(self):
        ctx = AuthContext(
            key_id="k2", label="cross", scopes=frozenset({"admin"}),
            tenant_id=None,
        )
        token = set_current_tenant(None)
        try:
            resolved = ctx.resolve_tenant(request_tenant="globex")
            assert resolved == "globex"
            assert current_tenant() == "globex"
        finally:
            from mypalace.tenancy import _current_tenant
            _current_tenant.reset(token)

    def test_cross_tenant_no_request_falls_back_to_default(self):
        ctx = AuthContext(
            key_id="k3", label="cross", scopes=frozenset({"admin"}),
            tenant_id=None,
        )
        token = set_current_tenant(None)
        try:
            resolved = ctx.resolve_tenant()
            assert resolved == "test"  # conftest sets PALACE_DEFAULT_TENANT_ID=test
            assert current_tenant() == "test"
        finally:
            from mypalace.tenancy import _current_tenant
            _current_tenant.reset(token)

    def test_conflict_still_403(self):
        from fastapi import HTTPException
        ctx = AuthContext(
            key_id="k4", label="bound", scopes=frozenset({"read"}),
            tenant_id="acme",
        )
        with pytest.raises(HTTPException) as exc:
            ctx.resolve_tenant(request_tenant="globex")
        assert exc.value.status_code == 403


class TestSettingsExposed:
    def test_default_mode_is_table(self):
        from mypalace.config import settings
        # Tripwire: changing the default flips behavior for every existing
        # deployment. Must stay "table" until phase 12.3.
        assert settings.tenant_schema_mode == "table"


class TestEventListenerInstalled:
    """Smoke-test that database.py registered the after_begin hook.

    Real runtime SET LOCAL behavior needs Postgres; that lives in
    integration tests. Here we just confirm the hook function exists
    and is bound to its target so a refactor that drops the listener
    triggers a CI failure.
    """

    def test_hook_function_exists(self):
        # Triggering the import wires the listener via @event.listens_for.
        from mypalace.database import _set_search_path_after_begin
        assert callable(_set_search_path_after_begin)

    def test_hook_no_op_when_table_mode(self, monkeypatch):
        # Connection mock should be called zero times under table mode
        # regardless of contextvar state.
        from unittest.mock import MagicMock

        from mypalace.config import settings
        from mypalace.database import _set_search_path_after_begin

        monkeypatch.setattr(settings, "tenant_schema_mode", "table")
        with tenant_scope("acme"):
            connection = MagicMock()
            _set_search_path_after_begin(
                session=MagicMock(), transaction=MagicMock(), connection=connection,
            )
        assert connection.execute.call_count == 0

    def test_hook_runs_set_local_under_schema_mode(self, monkeypatch):
        from unittest.mock import MagicMock

        from mypalace.config import settings
        from mypalace.database import _set_search_path_after_begin

        monkeypatch.setattr(settings, "tenant_schema_mode", "schema")
        connection = MagicMock()
        with tenant_scope("acme"):
            _set_search_path_after_begin(
                session=MagicMock(), transaction=MagicMock(), connection=connection,
            )
        assert connection.execute.call_count == 1
        # SQL string interpolation of a validated tenant id.
        sql = str(connection.execute.call_args[0][0])
        assert "acme" in sql
        assert "search_path" in sql.lower()

    def test_hook_skips_invalid_tenant_id(self, monkeypatch):
        from unittest.mock import MagicMock

        from mypalace.config import settings
        from mypalace.database import _set_search_path_after_begin

        monkeypatch.setattr(settings, "tenant_schema_mode", "schema")
        connection = MagicMock()
        # set_current_tenant directly to bypass tenant_scope's reset hook,
        # since we're testing defence against an upstream bug that allowed
        # a malformed value into the contextvar.
        token = set_current_tenant("bad'; DROP TABLE--")
        try:
            _set_search_path_after_begin(
                session=MagicMock(), transaction=MagicMock(), connection=connection,
            )
        finally:
            from mypalace.tenancy import _current_tenant
            _current_tenant.reset(token)
        assert connection.execute.call_count == 0

    def test_hook_skips_when_no_tenant_in_context(self, monkeypatch):
        from unittest.mock import MagicMock

        from mypalace.config import settings
        from mypalace.database import _set_search_path_after_begin

        monkeypatch.setattr(settings, "tenant_schema_mode", "schema")
        connection = MagicMock()
        # Worker job that forgot to call tenant_scope; we choose to no-op
        # rather than guess. (Test isn't 100% airtight because the contextvar
        # may still hold a value from another test — set it to None first.)
        token = set_current_tenant(None)
        try:
            _set_search_path_after_begin(
                session=MagicMock(), transaction=MagicMock(), connection=connection,
            )
        finally:
            from mypalace.tenancy import _current_tenant
            _current_tenant.reset(token)
        assert connection.execute.call_count == 0
