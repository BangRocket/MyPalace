"""Mock-level tests for the shadow-copy migration (phase 12.3a).

Runtime correctness of the migration is exercised in integration tests
against a live Postgres. Here we verify the migration's helper
functions emit the right SQL shape — enough to catch refactor breakage
without standing up a database.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MIGRATION_PATH = (
    Path(__file__).parent.parent
    / "alembic" / "versions" / "2026_05_05_0010_per_tenant_shadow_copy.py"
)


@pytest.fixture
def migration():
    """Load the migration module by file path.

    `alembic/versions/` isn't a Python package and the filename starts
    with a digit, so plain ``importlib.import_module`` doesn't work.
    """
    spec = importlib.util.spec_from_file_location(
        "_alembic_0010_shadow_copy", _MIGRATION_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRevisionWiring:
    def test_revision_id(self, migration):
        assert migration.revision == "2026_05_05_0010_per_tenant_shadow_copy"

    def test_down_revision(self, migration):
        # Tripwire: chain must include 0009 immediately before us.
        assert migration.down_revision == "2026_05_05_0009_messages_fts"

    # LATEST_ALEMBIC_REVISION head-tracking is asserted dynamically in
    # tests/test_alembic_revision_guard.py (no hardcoded revision id).


class TestPerTenantTableEnumeration:
    def test_lists_match_live_classification(self, migration):
        from mypalace.tenancy import PER_TENANT_TABLES
        # The migration's _per_tenant_tables() must mirror the live
        # constant. If they diverge, a 12.4+ refactor that adds a
        # per-tenant table would silently skip it during shadow-copy.
        assert set(migration._per_tenant_tables()) == set(PER_TENANT_TABLES)


class TestListTenantIds:
    def test_queries_public_tenants(self, migration):
        conn = MagicMock()
        conn.execute.return_value = iter([("acme",), ("globex",), ("default",)])
        ids = migration._list_tenant_ids(conn)
        assert ids == ["acme", "globex", "default"]

        sql = str(conn.execute.call_args[0][0])
        assert "FROM public.tenants" in sql
        assert "ORDER BY id" in sql


class TestReplicateDdl:
    def test_delegates_to_tenancy_helper(self, migration, monkeypatch):
        called = {}

        def fake(tid, conn):
            called["tid"] = tid
            called["conn"] = conn

        # Patch the live function so we don't need a real connection.
        from mypalace import tenancy
        monkeypatch.setattr(tenancy, "replicate_per_tenant_schema", fake)

        conn = MagicMock()
        migration._replicate_ddl(conn, "acme")
        assert called["tid"] == "acme"
        assert called["conn"] is conn


class TestShadowCopyTenant:
    def test_skips_table_when_columns_empty(self, migration):
        """If a per-tenant table doesn't exist in public (fresh DB), skip
        the INSERT. Otherwise we'd error inserting from a non-existent
        source."""
        conn = MagicMock()
        # No columns returned for any table — every iteration becomes a no-op.
        conn.execute.return_value = iter([])
        migration._shadow_copy_tenant(conn, "acme")
        # Only the column-discovery SELECTs ran; no INSERTs.
        # Each table triggers a SELECT, then is skipped.
        from mypalace.tenancy import PER_TENANT_TABLES
        assert conn.execute.call_count == len(PER_TENANT_TABLES)

    def test_emits_insert_select_with_tenant_filter(self, migration):
        conn = MagicMock()

        # First call: column discovery returns ["id", "user_id", "content"].
        # Second call: the INSERT ... SELECT.
        # We only test one table to keep this readable.
        cols_iter = iter([("id",), ("user_id",), ("content",)])
        empty_iter = iter([])

        def fake_execute(stmt, params=None):
            sql = str(stmt)
            if "information_schema" in sql.lower():
                return cols_iter
            return empty_iter  # the INSERT returns no useful result

        conn.execute = MagicMock(side_effect=fake_execute)

        # Patch the table list down to one entry so the test is
        # focused on the per-table behavior.
        from mypalace.tenancy import PER_TENANT_TABLES
        first_table = sorted(PER_TENANT_TABLES)[0]
        original = migration._per_tenant_tables
        migration._per_tenant_tables = lambda: [first_table]
        try:
            migration._shadow_copy_tenant(conn, "acme")
        finally:
            migration._per_tenant_tables = original

        # Two execute calls: column discovery, then INSERT ... SELECT.
        assert conn.execute.call_count == 2
        insert_sql = str(conn.execute.call_args_list[1][0][0])
        assert insert_sql.startswith("INSERT INTO")
        assert f'"acme".{first_table}' in insert_sql
        assert f"FROM public.{first_table}" in insert_sql
        assert "WHERE tenant_id = :tid" in insert_sql
        assert "ON CONFLICT DO NOTHING" in insert_sql
        # tenant_id column itself is excluded (the column-list query filtered it).
        assert ":tid" in insert_sql

    def test_excludes_tenant_id_in_column_query(self, migration):
        conn = MagicMock()
        conn.execute.return_value = iter([])
        migration._shadow_copy_tenant(conn, "acme")
        # First execute is the information_schema query; check the WHERE.
        first_sql = str(conn.execute.call_args_list[0][0][0])
        assert "column_name <> 'tenant_id'" in first_sql


class TestUpgradeIsIdempotent:
    """Tripwire: re-running the migration should be safe.

    Idempotency rests on two patterns documented in the migration
    header — CREATE ... IF NOT EXISTS (DDL) and ON CONFLICT DO NOTHING
    (data). The runtime check is in integration tests; here we just
    confirm both patterns appear in the helpers.
    """

    def test_replicate_uses_if_not_exists(self, migration):
        # Inspect the source for the IF NOT EXISTS pattern. Cheap
        # tripwire: a refactor that drops it would break re-run safety.
        import inspect

        from mypalace import tenancy
        src = inspect.getsource(tenancy.replicate_per_tenant_schema)
        assert "IF NOT EXISTS" in src

    def test_shadow_copy_uses_on_conflict_do_nothing(self, migration):
        import inspect
        src = inspect.getsource(migration._shadow_copy_tenant)
        assert "ON CONFLICT DO NOTHING" in src
