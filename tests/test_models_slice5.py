"""Slice 5 models register on SQLModel.metadata.

JSONB is Postgres-only so we don't try to create the schema here — the live
integration tests cover real schema creation. This is just a regression check
that the table classes import cleanly and attach to the metadata registry.
"""

from __future__ import annotations

from sqlmodel import SQLModel

import mypalace.models  # noqa: F401 — ensure tables are registered


def test_memory_supersession_table_registered():
    assert "memory_supersessions" in SQLModel.metadata.tables
    table = SQLModel.metadata.tables["memory_supersessions"]
    cols = {c.name for c in table.columns}
    expected = {
        "id", "superseded_id", "new_id", "user_id",
        "reason", "similarity_score", "created_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_memory_supersession_indexes_registered():
    table = SQLModel.metadata.tables["memory_supersessions"]
    index_names = {ix.name for ix in table.indexes}
    assert "ix_supersession_superseded" in index_names
    assert "ix_supersession_new" in index_names
