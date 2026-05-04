"""Slice 3 models register on SQLModel.metadata.

JSONB is Postgres-only so we don't try to create the schema here — the live
integration tests (commit 4) cover real schema creation. This is just a
regression check that the table classes import cleanly and attach to the
metadata registry.
"""

from __future__ import annotations

from sqlmodel import SQLModel

import palace.models  # noqa: F401 — ensure tables are registered


def test_memory_dynamics_table_registered():
    assert "memory_dynamics" in SQLModel.metadata.tables
    table = SQLModel.metadata.tables["memory_dynamics"]
    cols = {c.name for c in table.columns}
    expected = {
        "memory_id", "user_id", "stability", "difficulty",
        "retrieval_strength", "storage_strength", "is_key",
        "importance_weight", "category", "tags",
        "last_accessed_at", "access_count", "created_at", "updated_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_memory_access_logs_table_registered():
    assert "memory_access_logs" in SQLModel.metadata.tables
    table = SQLModel.metadata.tables["memory_access_logs"]
    cols = {c.name for c in table.columns}
    expected = {
        "id", "memory_id", "user_id", "grade", "signal_type",
        "retrievability_at_access", "context", "accessed_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_memory_access_logs_has_fk_cascade_to_memory_dynamics():
    table = SQLModel.metadata.tables["memory_access_logs"]
    fks = list(table.columns["memory_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "memory_dynamics"
    assert fks[0].column.name == "memory_id"
    assert fks[0].ondelete == "CASCADE"
