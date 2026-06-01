"""Guard: LATEST_ALEMBIC_REVISION must equal the single Alembic head.

init_db() create_all's every table then stamps LATEST_ALEMBIC_REVISION,
so a subsequent `alembic upgrade head` is a no-op. If the constant goes
stale (points below head), fresh deploys stamp an old revision and then
`alembic upgrade head` re-runs already-applied migrations. This test
catches that drift without needing a database.
"""
from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

from mypalace.database import LATEST_ALEMBIC_REVISION

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script_directory() -> ScriptDirectory:
    cfg = Config(os.path.join(_REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_REPO_ROOT, "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_single_alembic_head():
    heads = _script_directory().get_heads()
    assert len(heads) == 1, f"expected a single Alembic head, got {heads}"


def test_latest_revision_matches_head():
    heads = _script_directory().get_heads()
    assert heads[0] == LATEST_ALEMBIC_REVISION, (
        f"LATEST_ALEMBIC_REVISION ({LATEST_ALEMBIC_REVISION!r}) is stale; "
        f"Alembic head is {heads[0]!r}. Update mypalace/database.py."
    )
