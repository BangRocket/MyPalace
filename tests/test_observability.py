"""Tests for the observability layer: metrics, normalization, logging,
middleware behavior."""

from __future__ import annotations

from prometheus_client.parser import text_string_to_metric_families

from mypalace.observability.metrics import (
    cache_hits,
    cache_misses,
    http_requests,
    metrics_response,
    normalize_route,
    status_class,
)


class TestNormalizeRoute:
    def test_static_path_unchanged(self):
        assert normalize_route("/v1/memories") == "/v1/memories"
        assert normalize_route("/health") == "/health"
        assert normalize_route("/v1/memories/search") == "/v1/memories/search"

    def test_uuid_replaced(self):
        path = "/v1/memories/abc12345-6789-4def-9012-3456789abcde"
        assert normalize_route(path) == "/v1/memories/{id}"

    def test_long_id_replaced(self):
        path = "/v1/memories/m1234567890123456"
        assert normalize_route(path) == "/v1/memories/{id}"

    def test_short_user_id_kept(self):
        # Short usernames stay literal — that's a known cardinality risk
        # we accept (typical user_ids are ULIDs / UUIDs which the heuristic
        # catches).
        assert normalize_route("/v1/users/u1/memories") == "/v1/users/u1/memories"


class TestStatusClass:
    def test_buckets(self):
        assert status_class(200) == "2xx"
        assert status_class(204) == "2xx"
        assert status_class(301) == "3xx"
        assert status_class(404) == "4xx"
        assert status_class(503) == "5xx"


class TestMetricsEndpoint:
    def test_metrics_exposes_counters(self):
        # Simulate a request increment
        http_requests.labels(method="GET", route="/v1/test", status_class="2xx").inc()
        cache_hits.labels(namespace="search").inc(3)
        cache_misses.labels(namespace="search").inc(7)

        response = metrics_response()
        body = response.body.decode("utf-8")

        # Body is valid Prometheus text format
        families = list(text_string_to_metric_families(body))
        names = {f.name for f in families}
        assert "palace_http_requests" in names
        assert "palace_cache_hits" in names
        assert "palace_cache_misses" in names
        assert response.media_type.startswith("text/plain")


class TestObservabilityMiddleware:
    def test_request_id_response_header_set(self, client):
        # /health bypasses auth and goes through observability mw.
        r = client.get("/health")
        assert "X-Request-ID" in r.headers
        # Length depends on uuid4 hex (32 chars) — sanity check.
        assert len(r.headers["X-Request-ID"]) >= 16

    def test_request_id_header_propagated_when_provided(self, client):
        r = client.get("/health", headers={"X-Request-ID": "test-fixed-id-12345"})
        assert r.headers["X-Request-ID"] == "test-fixed-id-12345"

    def test_metrics_endpoint_public(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "palace_http_requests" in r.text


class TestStructlogConfiguration:
    def test_configure_logging_idempotent(self):
        from mypalace.observability.logging import configure_logging
        configure_logging()
        configure_logging()  # second call should not raise

    def test_bind_clear_request_context(self):
        import structlog

        from mypalace.observability.logging import (
            bind_request_context,
            clear_request_context,
        )
        bind_request_context(request_id="abc", tenant_id="t1")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("request_id") == "abc"
        assert ctx.get("tenant_id") == "t1"
        clear_request_context()
        assert structlog.contextvars.get_contextvars() == {}


class TestTracingNoop:
    def test_tracing_noop_when_endpoint_unset(self, monkeypatch):
        # Force-reset the module's _initialized flag for a clean assertion.
        import mypalace.observability.tracing as t
        from mypalace.observability.tracing import configure_tracing
        monkeypatch.setattr(t, "_initialized", False)
        monkeypatch.setattr(t.settings, "otlp_endpoint", None)

        result = configure_tracing(app=None)
        assert result is False
