"""Tests for /v1/admin/export and /v1/admin/import."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mypalace.api.portability import EXPORTABLE, _coerce_timestamps, _row_to_dict


class TestRowToDict:
    def test_isoformats_datetimes(self):
        # Use a real SQLModel row (Tenant) to avoid __table__ mocking gymnastics.
        from mypalace.models import Tenant
        row = Tenant(id="t1", label="Test", created_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC))
        out = _row_to_dict(row)
        assert out["id"] == "t1"
        assert out["label"] == "Test"
        assert out["created_at"] == "2026-05-04T12:00:00+00:00"


class TestCoerceTimestamps:
    def test_iso_strings_become_datetimes(self):
        from mypalace.models import Memory
        rec = {
            "id": "m1",
            "tenant_id": "t1",
            "user_id": "u1",
            "created_at": "2026-05-04T12:00:00+00:00",
            "content": "hello",
        }
        out = _coerce_timestamps(rec, Memory)
        assert isinstance(out["created_at"], datetime)
        assert out["content"] == "hello"  # unchanged

    def test_non_iso_strings_kept_as_string(self):
        from mypalace.models import Memory
        out = _coerce_timestamps({"content": "hello"}, Memory)
        assert out["content"] == "hello"


class TestExportableOrder:
    def test_tenants_first(self):
        # First entry must be tenant — import depends on that for FK reasons.
        assert EXPORTABLE[0][0] == "tenant"

    def test_supersessions_last(self):
        # Supersessions reference memories, so they're last.
        assert EXPORTABLE[-1][0] == "memory_supersession"


# ---------- route smoke tests with a mocked DB ----------

class TestExportRoute:
    def test_export_invalid_tenant_id_returns_400(self, client):
        r = client.get("/v1/admin/export?tenant_id=BAD-ID")
        assert r.status_code == 400

    def test_export_missing_tenant_id_returns_422(self, client):
        r = client.get("/v1/admin/export")
        assert r.status_code == 422

    def test_export_streams_ndjson_for_empty_tenant(self, client, monkeypatch):
        from mypalace.api import portability as port_mod

        async def fake_stream(tenant_id):
            yield (json.dumps(
                {"_type": "tenant", "id": tenant_id, "label": "Empty"},
            ) + "\n").encode()

        monkeypatch.setattr(port_mod, "_stream_export", fake_stream)

        r = client.get("/v1/admin/export?tenant_id=test")
        assert r.status_code == 200
        assert "application/x-ndjson" in r.headers["content-type"]
        body = r.text.strip().splitlines()
        assert len(body) == 1
        record = json.loads(body[0])
        assert record["_type"] == "tenant"
        assert record["id"] == "test"


# ---------- import path ----------

class TestImportRoute:
    def test_import_invalid_tenant_id_returns_400(self, client):
        r = client.post("/v1/admin/import?tenant_id=BAD-ID", content=b"")
        assert r.status_code == 400

    def test_import_missing_tenant_id_returns_422(self, client):
        r = client.post("/v1/admin/import", content=b"")
        assert r.status_code == 422

    def test_import_calls_ingest_with_target(self, client, monkeypatch):
        from mypalace.api import portability as port_mod

        captured: dict = {}

        async def fake_ingest(target_tenant, lines, reembed_memories):
            captured["target"] = target_tenant
            captured["lines"] = lines
            captured["reembed"] = reembed_memories
            return port_mod.ImportSummary(
                target_tenant=target_tenant,
                memories_imported=2,
            )

        monkeypatch.setattr(port_mod, "_ingest_records", fake_ingest)

        body = (
            json.dumps({"_type": "memory", "id": "m1", "tenant_id": "wrong",
                        "user_id": "u1", "content": "hi"}) + "\n" +
            json.dumps({"_type": "memory", "id": "m2", "tenant_id": "wrong",
                        "user_id": "u1", "content": "ho"}) + "\n"
        )
        r = client.post("/v1/admin/import?tenant_id=test", content=body)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["memories_imported"] == 2
        assert data["target_tenant"] == "test"
        assert captured["target"] == "test"
        assert captured["reembed"] is True
        assert len(captured["lines"]) == 2


# ---------- ingest unit ----------

class TestIngestRecords:
    @pytest.mark.asyncio
    async def test_unknown_type_skipped(self, monkeypatch):
        from mypalace.api import portability as port_mod

        # Stub session — no real Tenant lookup.
        existing = MagicMock()
        existing.scalar_one_or_none.return_value = MagicMock()  # tenant exists
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=existing)
        db_mock.merge = AsyncMock()
        db_mock.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            port_mod, "async_session", MagicMock(return_value=cm),
        )

        lines = [
            json.dumps({"_type": "tenant", "id": "any", "label": "x"}),
            json.dumps({"_type": "bogus", "id": "x"}),
            "",
        ]
        summary = await port_mod._ingest_records(
            target_tenant="test", lines=lines, reembed_memories=False,
        )
        assert summary.tenants_seen == 1
        assert summary.skipped == 1
        assert any("unknown _type" in r for r in summary.skipped_reasons)

    @pytest.mark.asyncio
    async def test_target_tenant_overrides_source(self, monkeypatch):
        """A record with tenant_id='wrong' must end up under target_tenant."""
        from mypalace.api import portability as port_mod

        merged: list[Any] = []

        async def fake_merge(obj):
            merged.append(obj)

        existing = MagicMock()
        existing.scalar_one_or_none.return_value = MagicMock()  # tenant exists
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=existing)
        db_mock.merge = AsyncMock(side_effect=fake_merge)
        db_mock.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            port_mod, "async_session", MagicMock(return_value=cm),
        )

        lines = [
            json.dumps({
                "_type": "memory", "id": "m1",
                "tenant_id": "MALICIOUS_TENANT",  # should be overridden
                "user_id": "u1", "content": "hi",
                "memory_type": "semantic", "importance": 1.0,
                "access_count": 0,
            }),
        ]
        summary = await port_mod._ingest_records(
            target_tenant="test", lines=lines, reembed_memories=False,
        )
        assert summary.memories_imported == 1
        assert merged[0].tenant_id == "test"

    @pytest.mark.asyncio
    async def test_malformed_json_counted_as_skipped(self, monkeypatch):
        from mypalace.api import portability as port_mod

        existing = MagicMock()
        existing.scalar_one_or_none.return_value = MagicMock()
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=existing)
        db_mock.commit = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            port_mod, "async_session", MagicMock(return_value=cm),
        )

        summary = await port_mod._ingest_records(
            target_tenant="test",
            lines=["not json {{{", "{\"valid_partial\":true}", ""],
            reembed_memories=False,
        )
        assert summary.skipped >= 1
        assert any("malformed json" in r for r in summary.skipped_reasons)


# Avoid Annotated import issue
from typing import Any  # noqa: E402
