"""Tests for /live + /ready split (phase 9 slice 2).

/live is a process-up probe — must NOT touch backends, so it stays 200
even when Postgres is down (otherwise k8s would restart pods on every
DB blip instead of just routing traffic away).

/ready aggregates backend pings — same semantics as /health/deep, which
remains as a back-compat alias.
"""

from __future__ import annotations

from unittest.mock import patch

from mypalace.health.checks import HealthCheckResult


class TestLiveEndpoint:
    def test_live_returns_200_with_ok(self, client):
        r = client.get("/live")
        assert r.status_code == 200
        body = r.json()
        assert body == {"status": "ok", "service": "mypalace"}

    def test_live_does_not_touch_backends(self, client):
        # Even with check_all_backends raising, /live must succeed —
        # liveness must NOT depend on backend availability.
        async def boom(timeout=2.0):
            raise RuntimeError("backends are on fire")

        with patch("mypalace.health.checks.check_all_backends", boom):
            r = client.get("/live")
        assert r.status_code == 200

    def test_live_is_public(self):
        from mypalace.auth.scopes import is_public
        assert is_public("/live")


class TestReadyEndpoint:
    def test_ready_returns_200_when_healthy(self, client, monkeypatch):
        async def fake(timeout=2.0):
            return True, [
                HealthCheckResult("postgres", ok=True, elapsed_ms=3, detail="ok"),
                HealthCheckResult("qdrant", ok=True, elapsed_ms=5, detail="ok"),
            ]
        monkeypatch.setattr("mypalace.health.checks.check_all_backends", fake)

        r = client.get("/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "mypalace"
        assert {b["name"] for b in body["backends"]} == {"postgres", "qdrant"}

    def test_ready_returns_503_when_degraded(self, client, monkeypatch):
        async def fake(timeout=2.0):
            return False, [
                HealthCheckResult("postgres", ok=False, elapsed_ms=2000, detail="timeout"),
            ]
        monkeypatch.setattr("mypalace.health.checks.check_all_backends", fake)

        r = client.get("/ready")
        assert r.status_code == 503
        assert r.json()["status"] == "degraded"

    def test_ready_is_public(self):
        from mypalace.auth.scopes import is_public
        assert is_public("/ready")


class TestHealthDeepBackCompat:
    def test_health_deep_still_works(self, client, monkeypatch):
        async def fake(timeout=2.0):
            return True, [
                HealthCheckResult("postgres", ok=True, elapsed_ms=3, detail="ok"),
            ]
        monkeypatch.setattr("mypalace.health.checks.check_all_backends", fake)

        r = client.get("/health/deep")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestPoolConfig:
    def test_settings_expose_pool_knobs(self):
        from mypalace.config import settings
        assert isinstance(settings.db_pool_size, int)
        assert isinstance(settings.db_max_overflow, int)
        assert isinstance(settings.db_pool_timeout, int)
        assert isinstance(settings.db_pool_recycle, int)
        assert isinstance(settings.db_pool_pre_ping, bool)

    def test_default_pool_size_is_reasonable(self):
        from mypalace.config import settings
        # SQLAlchemy default; we don't override unless asked. Keeping this
        # test as a tripwire — if someone bumps the default in code, they
        # need to update docs/deployment.md to match.
        assert 1 <= settings.db_pool_size <= 100
        assert 0 <= settings.db_max_overflow <= 200

    def test_pool_pre_ping_default_on(self):
        """We override SQLAlchemy's default (off) because stale connections
        after Postgres restarts are a common production pain. See
        docs/deployment.md."""
        from mypalace.config import settings
        assert settings.db_pool_pre_ping is True
