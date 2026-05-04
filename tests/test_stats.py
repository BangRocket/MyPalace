"""Tests for /v1/admin/stats — per-tenant snapshot + ALL rollup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------- helpers ----------

def _patch_stats_for(monkeypatch, mapping: dict[str, dict]):
    """Patch the four stats helpers so each tenant returns deterministic
    fixtures. ``mapping`` is {tenant_id: {row_counts: {...}, ...}}."""
    from palace.api import stats as stats_mod

    async def fake_row_counts(tenant_id):
        return stats_mod.RowCounts(**mapping[tenant_id]["row_counts"])

    async def fake_activity(tenant_id):
        return stats_mod.Activity7d(**mapping[tenant_id]["activity"])

    async def fake_top(tenant_id):
        return [
            stats_mod.TopUser(**u)
            for u in mapping[tenant_id]["top_users"]
        ]

    async def fake_fsrs(tenant_id):
        return stats_mod.FsrsHealth(**mapping[tenant_id]["fsrs"])

    monkeypatch.setattr(stats_mod, "_row_counts", fake_row_counts)
    monkeypatch.setattr(stats_mod, "_activity_7d", fake_activity)
    monkeypatch.setattr(stats_mod, "_top_users_by_access_7d", fake_top)
    monkeypatch.setattr(stats_mod, "_fsrs_health", fake_fsrs)


_DEFAULT_FIXTURE = {
    "row_counts": {
        "memories": 100, "sessions": 5, "episodes": 20,
        "narrative_arcs": 3, "intentions": 2, "memory_supersessions": 1,
    },
    "activity": {
        "memories_created": 12, "memories_accessed": 88,
        "episodes_reflected": 4, "intentions_fired": 1,
    },
    "top_users": [
        {"user_id": "u1", "access_count": 50},
        {"user_id": "u2", "access_count": 38},
    ],
    "fsrs": {
        "tracked_memories": 95, "key_memories": 7,
        "mean_stability": 4.21, "mean_retrieval_strength": 0.83,
    },
}


# ---------- tenant_id validation ----------

class TestTenantIdValidation:
    def test_invalid_tenant_id_returns_400(self, client):
        r = client.get("/v1/admin/stats?tenant_id=BAD-ID")
        assert r.status_code == 400

    def test_missing_tenant_id_returns_422(self, client):
        r = client.get("/v1/admin/stats")
        assert r.status_code == 422

    def test_too_long_tenant_id_returns_422(self, client):
        # Pydantic Query max_length catches this before our custom validation
        r = client.get(f"/v1/admin/stats?tenant_id={'a' * 33}")
        assert r.status_code == 422


# ---------- per-tenant snapshot ----------

class TestPerTenantSnapshot:
    def test_returns_full_shape(self, client, monkeypatch):
        _patch_stats_for(monkeypatch, {"test": _DEFAULT_FIXTURE})

        r = client.get("/v1/admin/stats?tenant_id=test")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["tenant_id"] == "test"
        assert data["row_counts"]["memories"] == 100
        assert data["activity_7d"]["memories_accessed"] == 88
        assert len(data["top_users_by_access_7d"]) == 2
        assert data["fsrs_health"]["mean_stability"] == 4.21


# ---------- ALL rollup ----------

class TestAllTenantsRollup:
    """ALL rollup needs a cross-tenant admin (key.tenant_id is None).
    The default `client` fixture runs in auth-disabled mode whose synthetic
    AuthContext.all_scopes carries the default_tenant_id (i.e. 'test'),
    not None. So we re-enable auth and use the mocked key_service.lookup."""

    def test_all_works_with_cross_tenant_admin(
        self, client, mock_key_service, monkeypatch,
    ):
        from palace.auth.context import AuthContext
        from palace.config import settings

        mock_key_service.lookup = AsyncMock(return_value=AuthContext(
            key_id="admin-x", label="cross",
            scopes=frozenset({"read", "write", "admin"}),
            tenant_id=None,
        ))
        _patch_stats_for(monkeypatch, {
            "alpha": _DEFAULT_FIXTURE,
            "beta": _DEFAULT_FIXTURE,
        })
        from palace.api import stats as stats_mod
        monkeypatch.setattr(
            stats_mod, "_all_tenant_ids",
            AsyncMock(return_value=["alpha", "beta"]),
        )
        with patch.object(settings, "auth_disabled", False):
            r = client.get(
                "/v1/admin/stats?tenant_id=ALL",
                headers={"X-Palace-Key": "pk_live_anything"},
            )

        assert r.status_code == 200
        body = r.json()["data"]
        assert "tenants" in body
        assert len(body["tenants"]) == 2
        assert {t["tenant_id"] for t in body["tenants"]} == {"alpha", "beta"}

    def test_all_denied_with_tenant_bound_key(
        self, client, mock_key_service, monkeypatch,
    ):
        from palace.auth.context import AuthContext
        from palace.config import settings

        mock_key_service.lookup = AsyncMock(return_value=AuthContext(
            key_id="k1", label="bound",
            scopes=frozenset({"read", "write", "admin"}),
            tenant_id="acme",
        ))
        with patch.object(settings, "auth_disabled", False):
            r = client.get(
                "/v1/admin/stats?tenant_id=ALL",
                headers={"X-Palace-Key": "pk_live_anything"},
            )
        assert r.status_code == 403


# ---------- helpers (mocked-DB unit tests) ----------

class TestRowCountsHelper:
    @pytest.mark.asyncio
    async def test_row_counts_filters_by_tenant(self, monkeypatch):
        from palace.api import stats as stats_mod

        # Build a stub async_session whose execute returns counts in order:
        # memories, sessions, episodes, narrative_arcs, intentions, supersessions.
        seq = [42, 7, 11, 3, 2, 1]
        idx = {"i": 0}

        async def fake_execute(stmt):
            mock = MagicMock()
            mock.scalar_one.return_value = seq[idx["i"]]
            idx["i"] += 1
            return mock

        db_mock = MagicMock()
        db_mock.execute = AsyncMock(side_effect=fake_execute)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            stats_mod, "async_session", MagicMock(return_value=cm),
        )

        result = await stats_mod._row_counts("acme")
        assert result.memories == 42
        assert result.sessions == 7
        assert result.episodes == 11
        assert result.narrative_arcs == 3
        assert result.intentions == 2
        assert result.memory_supersessions == 1
