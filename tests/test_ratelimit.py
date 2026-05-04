"""Tests for the rate limiter (mocking Redis) + middleware behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from palace.ratelimit.limiter import LimitDecision, RateLimiter
from palace.ratelimit.middleware import _bucket_for


class TestBucketFor:
    def test_search_paths_use_search_bucket(self):
        from palace.config import settings
        bucket, limit = _bucket_for("/v1/memories/search")
        assert bucket == "search"
        assert limit == settings.rate_limit_search_per_min

        bucket, _ = _bucket_for("/v1/episodes/search")
        assert bucket == "search"
        bucket, _ = _bucket_for("/v1/context/layered")
        assert bucket == "search"

    def test_other_paths_use_default(self):
        from palace.config import settings
        bucket, limit = _bucket_for("/v1/memories")
        assert bucket == "default"
        assert limit == settings.rate_limit_default_per_min


class TestEnabledGate:
    def test_disabled_when_flag_false(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        monkeypatch.setattr(settings, "redis_url", "redis://x")
        assert RateLimiter().enabled is False

    def test_disabled_when_no_redis(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "redis_url", None)
        assert RateLimiter().enabled is False

    def test_enabled_with_both(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "redis_url", "redis://x")
        assert RateLimiter().enabled is True


class TestCheckBypassesWhenDisabled:
    @pytest.mark.asyncio
    async def test_disabled_always_allows(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "rate_limit_enabled", False)

        limiter = RateLimiter()
        decision = await limiter.check(
            tenant_id="t", key_id="k", user_id="u", bucket="default", limit=1,
        )
        assert decision.allowed is True
        assert decision.current == 0


class TestCheckEnforcesLimit:
    @pytest.mark.asyncio
    async def test_under_limit_allows(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "redis_url", "redis://x")

        limiter = RateLimiter()
        # ZCARD returned 5 (before our ZADD)
        pipeline = MagicMock()
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        pipeline.zremrangebyscore = MagicMock()
        pipeline.zcard = MagicMock()
        pipeline.zadd = MagicMock()
        pipeline.expire = MagicMock()
        pipeline.execute = AsyncMock(return_value=[1, 5, 1, True])

        client = MagicMock()
        client.pipeline = MagicMock(return_value=pipeline)

        with patch.object(limiter, "_connect", new=AsyncMock(return_value=client)):
            d = await limiter.check(
                tenant_id="t", key_id="k", user_id="u",
                bucket="default", limit=10,
            )
        assert d.allowed is True
        assert d.current == 6  # 5 before + our ZADD

    @pytest.mark.asyncio
    async def test_at_limit_denies(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "redis_url", "redis://x")

        limiter = RateLimiter()
        pipeline = MagicMock()
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        pipeline.zremrangebyscore = MagicMock()
        pipeline.zcard = MagicMock()
        pipeline.zadd = MagicMock()
        pipeline.expire = MagicMock()
        # Already at limit before this request — current_before_add == limit
        pipeline.execute = AsyncMock(return_value=[1, 10, 1, True])

        client = MagicMock()
        client.pipeline = MagicMock(return_value=pipeline)
        with patch.object(limiter, "_connect", new=AsyncMock(return_value=client)):
            d = await limiter.check(
                tenant_id="t", key_id="k", user_id="u",
                bucket="default", limit=10,
            )
        assert d.allowed is False
        assert d.current == 11
        assert d.retry_after_seconds == limiter.WINDOW_SECONDS

    @pytest.mark.asyncio
    async def test_redis_failure_fails_open(self, monkeypatch):
        from palace.config import settings
        monkeypatch.setattr(settings, "rate_limit_enabled", True)
        monkeypatch.setattr(settings, "redis_url", "redis://x")

        limiter = RateLimiter()
        with patch.object(limiter, "_connect",
                          new=AsyncMock(side_effect=ConnectionError("nope"))):
            d = await limiter.check(
                tenant_id="t", key_id="k", user_id="u",
                bucket="default", limit=1,
            )
        assert d.allowed is True


class TestMiddleware:
    """Test the middleware's dispatch directly so we don't have to rebuild
    the FastAPI app to swap the limiter (the singleton is captured at app
    construction time)."""

    def test_disabled_lets_request_through(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_dispatch_429_when_limit_exceeded(self, monkeypatch):
        from starlette.requests import Request

        from palace.auth.context import AuthContext
        from palace.ratelimit import middleware as mw_mod

        fake_limiter = MagicMock()
        fake_limiter.enabled = True
        fake_limiter.WINDOW_SECONDS = 60
        fake_limiter.check = AsyncMock(return_value=LimitDecision(
            allowed=False, current=121, limit=120, retry_after_seconds=60,
        ))
        monkeypatch.setattr(mw_mod, "rate_limiter", fake_limiter)

        mw = mw_mod.RateLimitMiddleware(app=None)

        # Build a minimal Request with auth context attached.
        scope = {
            "type": "http", "method": "POST", "path": "/v1/memories",
            "headers": [], "query_string": b"",
        }
        request = Request(scope)
        request._receive = AsyncMock()
        request.state.auth = AuthContext(
            key_id="k1", label="t",
            scopes=frozenset({"read", "write"}), tenant_id="t1",
        )

        async def call_next(req):
            return MagicMock(status_code=200)

        response = await mw.dispatch(request, call_next)
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"

    @pytest.mark.asyncio
    async def test_dispatch_passes_when_under_limit(self, monkeypatch):
        from starlette.requests import Request

        from palace.auth.context import AuthContext
        from palace.ratelimit import middleware as mw_mod

        fake_limiter = MagicMock()
        fake_limiter.enabled = True
        fake_limiter.check = AsyncMock(return_value=LimitDecision(
            allowed=True, current=5, limit=120, retry_after_seconds=0,
        ))
        monkeypatch.setattr(mw_mod, "rate_limiter", fake_limiter)

        mw = mw_mod.RateLimitMiddleware(app=None)
        scope = {
            "type": "http", "method": "GET", "path": "/v1/memories/abc",
            "headers": [], "query_string": b"",
        }
        request = Request(scope)
        request.state.auth = AuthContext(
            key_id="k1", label="t",
            scopes=frozenset({"read"}), tenant_id="t1",
        )

        sentinel = MagicMock(status_code=200)
        async def call_next(req):
            return sentinel

        response = await mw.dispatch(request, call_next)
        assert response is sentinel

    @pytest.mark.asyncio
    async def test_unlimited_scope_bypasses_check(self, monkeypatch):
        from starlette.requests import Request

        from palace.auth.context import AuthContext
        from palace.ratelimit import middleware as mw_mod

        fake_limiter = MagicMock()
        fake_limiter.enabled = True
        fake_limiter.check = AsyncMock()  # should not be called
        monkeypatch.setattr(mw_mod, "rate_limiter", fake_limiter)

        mw = mw_mod.RateLimitMiddleware(app=None)
        scope = {
            "type": "http", "method": "POST", "path": "/v1/memories",
            "headers": [], "query_string": b"",
        }
        request = Request(scope)
        request.state.auth = AuthContext(
            key_id="k1", label="trusted",
            scopes=frozenset({"read", "write", "unlimited"}),
            tenant_id="t1",
        )

        sentinel = MagicMock(status_code=200)
        async def call_next(req):
            return sentinel

        response = await mw.dispatch(request, call_next)
        assert response is sentinel
        fake_limiter.check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_public_paths_bypass(self, monkeypatch):
        from starlette.requests import Request

        from palace.ratelimit import middleware as mw_mod

        fake_limiter = MagicMock()
        fake_limiter.enabled = True
        fake_limiter.check = AsyncMock()
        monkeypatch.setattr(mw_mod, "rate_limiter", fake_limiter)

        mw = mw_mod.RateLimitMiddleware(app=None)
        scope = {
            "type": "http", "method": "GET", "path": "/health",
            "headers": [], "query_string": b"",
        }
        request = Request(scope)

        sentinel = MagicMock(status_code=200)
        async def call_next(req):
            return sentinel
        response = await mw.dispatch(request, call_next)
        assert response is sentinel
        fake_limiter.check.assert_not_awaited()
