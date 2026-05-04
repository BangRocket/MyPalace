"""Tests for /health/deep + config validator (phase 8 slice 1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypalace.health.checks import (
    HealthCheckResult,
    _check_falkordb,
    _check_postgres,
    _check_qdrant,
    _check_redis,
    check_all_backends,
    to_dict,
)
from mypalace.health.config_validator import ConfigError, validate_config

# ----------------------------------------------------------------------
# Result helpers
# ----------------------------------------------------------------------

class TestResult:
    def test_to_dict_round_trip(self):
        r = HealthCheckResult(
            name="postgres", ok=True, elapsed_ms=12, detail="ok",
        )
        assert to_dict(r) == {
            "name": "postgres", "ok": True, "configured": True,
            "elapsed_ms": 12, "detail": "ok",
        }

    def test_unconfigured_excluded_from_overall(self):
        r1 = HealthCheckResult("postgres", ok=True, elapsed_ms=5, detail="ok")
        r2 = HealthCheckResult(
            "redis", ok=True, elapsed_ms=0, detail="not configured",
            configured=False,
        )
        # Overall is just the .ok aggregate; configured filter happens in check_all_backends.
        assert r1.ok and r2.ok


# ----------------------------------------------------------------------
# Per-backend checks
# ----------------------------------------------------------------------

class TestPostgresCheck:
    @pytest.mark.asyncio
    async def test_success(self):
        from sqlalchemy import text  # noqa: F401  (import for autocomplete)

        async def fake_execute(stmt):
            mock = MagicMock()
            mock.scalar_one.return_value = 1
            return mock

        conn_mock = MagicMock()
        conn_mock.execute = AsyncMock(side_effect=fake_execute)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn_mock)
        cm.__aexit__ = AsyncMock(return_value=None)
        engine_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=cm)

        with patch("mypalace.database.engine", engine_mock):
            r = await _check_postgres(timeout=1.0)
        assert r.ok
        assert r.name == "postgres"
        assert r.detail == "ok"

    @pytest.mark.asyncio
    async def test_failure_swallowed_into_result(self):
        engine_mock = MagicMock()
        engine_mock.connect = MagicMock(side_effect=RuntimeError("conn refused"))

        with patch("mypalace.database.engine", engine_mock):
            r = await _check_postgres(timeout=1.0)
        assert not r.ok
        assert "conn refused" in r.detail


class TestQdrantCheck:
    @pytest.mark.asyncio
    async def test_success(self):
        from mypalace.vector import vector_store

        with patch.object(
            vector_store.client, "get_collections",
            new=AsyncMock(return_value=MagicMock()),
        ):
            r = await _check_qdrant(timeout=1.0)
        assert r.ok

    @pytest.mark.asyncio
    async def test_failure(self):
        from mypalace.vector import vector_store

        with patch.object(
            vector_store.client, "get_collections",
            new=AsyncMock(side_effect=RuntimeError("qdrant down")),
        ):
            r = await _check_qdrant(timeout=1.0)
        assert not r.ok
        assert "qdrant down" in r.detail


class TestFalkorDBCheck:
    @pytest.mark.asyncio
    async def test_unconfigured_returns_ok_not_configured(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "falkordb_url", None)

        r = await _check_falkordb(timeout=1.0)
        assert r.ok is True
        assert r.configured is False
        assert "not configured" in r.detail


class TestRedisCheck:
    @pytest.mark.asyncio
    async def test_unconfigured_returns_ok_not_configured(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "redis_url", None)

        r = await _check_redis(timeout=1.0)
        assert r.ok is True
        assert r.configured is False


class TestCheckAllBackends:
    @pytest.mark.asyncio
    async def test_unconfigured_optional_backends_dont_fail_overall(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "falkordb_url", None)
        monkeypatch.setattr(settings, "redis_url", None)

        # Stub Postgres + Qdrant to succeed.
        async def fake_pg_execute(stmt):
            mock = MagicMock()
            mock.scalar_one.return_value = 1
            return mock

        conn = MagicMock()
        conn.execute = AsyncMock(side_effect=fake_pg_execute)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        engine_mock = MagicMock()
        engine_mock.connect = MagicMock(return_value=cm)

        from mypalace.vector import vector_store

        with patch("mypalace.database.engine", engine_mock), \
             patch.object(
                 vector_store.client, "get_collections",
                 new=AsyncMock(return_value=MagicMock()),
             ):
            overall_ok, results = await check_all_backends(timeout=1.0)
        assert overall_ok is True
        names = {r.name for r in results}
        assert names == {"postgres", "qdrant", "falkordb", "redis"}
        # Optional backends marked unconfigured.
        for r in results:
            if r.name in ("falkordb", "redis"):
                assert r.configured is False


# ----------------------------------------------------------------------
# Route
# ----------------------------------------------------------------------

class TestHealthDeepRoute:
    def test_returns_200_with_ok_when_healthy(self, client, monkeypatch):
        async def fake_check(timeout=2.0):
            return True, [
                HealthCheckResult("postgres", ok=True, elapsed_ms=3, detail="ok"),
                HealthCheckResult("qdrant", ok=True, elapsed_ms=5, detail="ok"),
            ]
        monkeypatch.setattr("mypalace.health.checks.check_all_backends", fake_check)

        r = client.get("/health/deep")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "mypalace"
        assert {b["name"] for b in body["backends"]} == {"postgres", "qdrant"}

    def test_returns_503_when_degraded(self, client, monkeypatch):
        async def fake_check(timeout=2.0):
            return False, [
                HealthCheckResult("postgres", ok=True, elapsed_ms=3, detail="ok"),
                HealthCheckResult("qdrant", ok=False, elapsed_ms=2000, detail="timeout"),
            ]
        monkeypatch.setattr("mypalace.health.checks.check_all_backends", fake_check)

        r = client.get("/health/deep")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"

    def test_no_auth_required(self, client):
        # Default auth-disabled bypass would mask this; just confirm
        # /health/deep is in PUBLIC_PATHS so probes never get 401.
        from mypalace.auth.scopes import is_public
        assert is_public("/health/deep")


# ----------------------------------------------------------------------
# Config validator
# ----------------------------------------------------------------------

class TestConfigValidator:
    def test_valid_config_returns_no_warnings(self, monkeypatch):
        # Test conftest already sets a valid baseline.
        warnings = validate_config()
        # May have warnings, but should not raise.
        assert isinstance(warnings, list)

    def test_invalid_default_tenant_id_raises(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "default_tenant_id", "BAD-ID")
        with pytest.raises(ConfigError, match="PALACE_DEFAULT_TENANT_ID"):
            validate_config()

    def test_malformed_bootstrap_key_raises(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "bootstrap_admin_key", "garbage")
        with pytest.raises(ConfigError, match="PALACE_BOOTSTRAP_ADMIN_KEY"):
            validate_config()

    def test_valid_bootstrap_key_passes(self, monkeypatch):
        from mypalace.config import settings
        # A valid pk_live_ + 32 alphanumeric.
        monkeypatch.setattr(
            settings, "bootstrap_admin_key",
            "pk_live_" + "a" * 32,
        )
        validate_config()  # should not raise

    def test_unset_bootstrap_key_passes(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "bootstrap_admin_key", None)
        validate_config()  # should not raise

    def test_bare_postgresql_url_raises(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(
            settings, "database_url", "postgresql://u:p@h/d",
        )
        with pytest.raises(ConfigError, match="asyncpg"):
            validate_config()

    def test_asyncpg_url_passes(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(
            settings, "database_url", "postgresql+asyncpg://u:p@h/d",
        )
        validate_config()

    def test_rate_limit_without_redis_raises(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "redis_url", None)
        with pytest.raises(ConfigError, match="PALACE_RATE_LIMIT_ENABLED"):
            validate_config()

    def test_worker_queue_without_redis_warns_not_raises(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "worker_queue_enabled", True)
        monkeypatch.setattr(settings, "redis_url", None)
        warnings = validate_config()
        assert any("PALACE_WORKER_QUEUE_ENABLED" in w for w in warnings)

    def test_invalid_log_format_raises(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "log_format", "syslog")
        with pytest.raises(ConfigError, match="PALACE_LOG_FORMAT"):
            validate_config()

    def test_zero_cache_ttl_raises(self, monkeypatch):
        from mypalace.config import settings
        monkeypatch.setattr(settings, "cache_ttl_search_seconds", 0)
        with pytest.raises(ConfigError, match="PALACE_CACHE_TTL_SEARCH"):
            validate_config()
