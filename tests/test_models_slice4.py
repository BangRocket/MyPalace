"""Slice 4 models register on SQLModel.metadata.

JSONB is Postgres-only so we don't try to create the schema here — the live
integration tests (commit 4) cover real schema creation. This is just a
regression check that the table classes import cleanly and attach to the
metadata registry.
"""

from __future__ import annotations

from sqlmodel import SQLModel

import mypalace.models  # noqa: F401 — ensure tables are registered


def test_intention_table_registered():
    assert "intentions" in SQLModel.metadata.tables
    table = SQLModel.metadata.tables["intentions"]
    cols = {c.name for c in table.columns}
    expected = {
        "id", "user_id", "agent_id", "content", "source_memory_id",
        "trigger_conditions", "priority", "fired", "fire_once",
        "created_at", "expires_at", "fired_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_intention_indexes_registered():
    table = SQLModel.metadata.tables["intentions"]
    index_names = {ix.name for ix in table.indexes}
    assert "ix_intention_user_unfired" in index_names
    assert "ix_intention_expires" in index_names
