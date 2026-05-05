"""Tests for the scheduled backup worker (phase 9 slice 3)."""

from __future__ import annotations

import gzip
import os
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from mypalace.workers import backup as backup_mod


class TestBackupPath:
    def test_filename_shape(self, tmp_path):
        ts = datetime(2026, 5, 4, 12, 30, 45, tzinfo=UTC)
        path = backup_mod._backup_path(tmp_path, "acme", ts)
        assert path.name == "acme-20260504T123045Z.ndjson.gz"
        assert path.parent == tmp_path


class TestBackupTenant:
    @pytest.mark.asyncio
    async def test_writes_gzipped_ndjson_atomically(self, tmp_path):
        async def fake_stream(tenant_id):
            yield b'{"_type":"tenant","id":"acme"}\n'
            yield b'{"_type":"memory","id":"m1","content":"hello"}\n'

        with patch.object(backup_mod, "_stream_export", fake_stream):
            ts = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
            out = await backup_mod.backup_tenant("acme", tmp_path, ts)

        assert out.exists()
        assert out.suffix == ".gz"
        # No .tmp left behind.
        assert not out.with_suffix(out.suffix + ".tmp").exists()

        with gzip.open(out, "rt") as f:
            text = f.read()
        assert '"_type":"tenant"' in text
        assert '"_type":"memory"' in text

    @pytest.mark.asyncio
    async def test_creates_dir_if_missing(self, tmp_path):
        target = tmp_path / "nested" / "backups"
        async def fake_stream(tenant_id):
            yield b"{}\n"

        with patch.object(backup_mod, "_stream_export", fake_stream):
            ts = datetime(2026, 5, 4, tzinfo=UTC)
            out = await backup_mod.backup_tenant("t1", target, ts)

        assert target.is_dir()
        assert out.exists()


class TestPrune:
    def test_prunes_files_older_than_retain_days(self, tmp_path):
        old = tmp_path / "acme-20260101T000000Z.ndjson.gz"
        new = tmp_path / "acme-20260504T000000Z.ndjson.gz"
        old.write_bytes(b"x")
        new.write_bytes(b"x")
        # Push old's mtime back 30 days.
        thirty_days_ago = time.time() - (30 * 86400)
        os.utime(old, (thirty_days_ago, thirty_days_ago))

        pruned = backup_mod.prune_old_backups(tmp_path, retain_days=7)
        assert pruned == 1
        assert not old.exists()
        assert new.exists()

    def test_ignores_non_backup_files(self, tmp_path):
        unrelated = tmp_path / "README.md"
        unrelated.write_text("hi")
        thirty_days_ago = time.time() - (30 * 86400)
        os.utime(unrelated, (thirty_days_ago, thirty_days_ago))

        pruned = backup_mod.prune_old_backups(tmp_path, retain_days=7)
        assert pruned == 0
        assert unrelated.exists()

    def test_missing_dir_returns_zero(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        assert backup_mod.prune_old_backups(missing, retain_days=7) == 0


class TestRunOnce:
    @pytest.mark.asyncio
    async def test_iterates_every_tenant(self, tmp_path):
        async def fake_stream(tenant_id):
            yield f'{{"tenant":"{tenant_id}"}}\n'.encode()

        with patch.object(backup_mod, "_stream_export", fake_stream), \
             patch.object(
                 backup_mod, "_list_tenant_ids",
                 new=AsyncMock(return_value=["acme", "default"]),
             ):
            summary = await backup_mod.run_once(tmp_path, retain_days=7)

        assert summary["tenants_total"] == 2
        assert summary["succeeded"] == 2
        assert summary["failed"] == 0
        files = sorted(p.name for p in tmp_path.glob("*.ndjson.gz"))
        assert len(files) == 2
        assert any(f.startswith("acme-") for f in files)
        assert any(f.startswith("default-") for f in files)

    @pytest.mark.asyncio
    async def test_one_tenant_failure_doesnt_block_others(self, tmp_path):
        async def fake_stream(tenant_id):
            if tenant_id == "broken":
                raise RuntimeError("kaboom")
            yield b"{}\n"

        with patch.object(backup_mod, "_stream_export", fake_stream), \
             patch.object(
                 backup_mod, "_list_tenant_ids",
                 new=AsyncMock(return_value=["broken", "ok"]),
             ):
            summary = await backup_mod.run_once(tmp_path, retain_days=7)

        assert summary["tenants_total"] == 2
        assert summary["succeeded"] == 1
        assert summary["failed"] == 1
        # The "ok" file made it through.
        ok_files = list(tmp_path.glob("ok-*.ndjson.gz"))
        assert len(ok_files) == 1


class TestRun:
    @pytest.mark.asyncio
    async def test_disabled_exits_immediately(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "backup_enabled", False)
        # Should return without scheduling anything.
        await backup_mod.run()


class TestSettingsExposed:
    def test_backup_settings_present(self):
        from mypalace.config import settings
        assert isinstance(settings.backup_enabled, bool)
        assert isinstance(settings.backup_dir, str)
        assert isinstance(settings.backup_interval_hours, int)
        assert isinstance(settings.backup_retain_days, int)

    def test_backup_disabled_by_default(self):
        from mypalace.config import settings
        # Tripwire: opt-in by design (writes to disk on a schedule).
        assert settings.backup_enabled is False
