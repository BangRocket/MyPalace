"""Tests for SQLAlchemy event hooks (phase 8 slice 2)."""

from __future__ import annotations

import logging

import pytest
from prometheus_client.parser import text_string_to_metric_families

from mypalace.observability.db import (
    _classify,
    install,
    reset_for_tests,
)
from mypalace.observability.metrics import (
    db_queries_total,
    db_query_duration,
    db_slow_queries_total,
    metrics_response,
)


class TestClassify:
    def test_select(self):
        assert _classify("SELECT 1") == "SELECT"
        assert _classify("  select * from t") == "SELECT"

    def test_insert(self):
        assert _classify("INSERT INTO t VALUES (1)") == "INSERT"

    def test_update(self):
        assert _classify("UPDATE t SET x = 1") == "UPDATE"

    def test_delete(self):
        assert _classify("DELETE FROM t") == "DELETE"

    def test_with_cte(self):
        assert _classify("WITH x AS (SELECT 1) SELECT * FROM x") == "WITH"

    def test_transaction_control(self):
        assert _classify("BEGIN") == "BEGIN"
        assert _classify("COMMIT") == "COMMIT"

    def test_unknown_falls_to_other(self):
        assert _classify("VACUUM") == "OTHER"
        assert _classify("") == "OTHER"
        assert _classify("   ") == "OTHER"


class TestInstall:
    def test_install_attaches_listeners(self):
        reset_for_tests()
        # Use a real async engine instance — we just need the event-listener
        # wiring to register; we don't execute anything. install() raising
        # would be the failure mode here.
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        install(engine)
        install(engine)  # second call must be a no-op (idempotent set)

    def test_install_is_idempotent(self):
        reset_for_tests()
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        install(engine)
        install(engine)
        install(engine)
        # No exceptions = success.


class TestSlowQueryHook:
    """Drive the install + emit a slow query through a real-ish path."""

    @pytest.mark.asyncio
    async def test_slow_query_logged_and_counted(self, monkeypatch, caplog):
        from sqlalchemy.ext.asyncio import create_async_engine

        # Use a tiny threshold so any query qualifies as slow.
        from mypalace.config import settings
        monkeypatch.setattr(settings, "db_slow_query_threshold_ms", 0)

        # Snapshot counter before.
        before = db_slow_queries_total.labels(operation="SELECT")._value.get()

        reset_for_tests()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        install(engine)

        with caplog.at_level(logging.WARNING, logger="mypalace.db"):
            async with engine.connect() as conn:
                from sqlalchemy import text
                await conn.execute(text("SELECT 1"))
        await engine.dispose()

        after = db_slow_queries_total.labels(operation="SELECT")._value.get()
        assert after > before

        slow_records = [r for r in caplog.records if "slow query" in r.message]
        assert slow_records, "expected at least one slow-query log line"

    @pytest.mark.asyncio
    async def test_fast_query_not_logged_as_slow(self, monkeypatch, caplog):
        from sqlalchemy.ext.asyncio import create_async_engine

        from mypalace.config import settings
        # 60s threshold — no query under test will qualify
        monkeypatch.setattr(settings, "db_slow_query_threshold_ms", 60_000)

        before = db_slow_queries_total.labels(operation="SELECT")._value.get()
        before_total = db_queries_total.labels(operation="SELECT")._value.get()

        reset_for_tests()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        install(engine)

        with caplog.at_level(logging.WARNING, logger="mypalace.db"):
            async with engine.connect() as conn:
                from sqlalchemy import text
                await conn.execute(text("SELECT 1"))
        await engine.dispose()

        after_slow = db_slow_queries_total.labels(operation="SELECT")._value.get()
        after_total = db_queries_total.labels(operation="SELECT")._value.get()
        # Slow counter unchanged
        assert after_slow == before
        # Total counter incremented
        assert after_total > before_total
        # No slow-query log line
        assert not [r for r in caplog.records if "slow query" in r.message]


class TestMetricsExposed:
    def test_db_metrics_in_prometheus_output(self):
        # Force at least one increment so the metric appears in scrape.
        db_queries_total.labels(operation="SELECT").inc()
        db_query_duration.labels(operation="SELECT").observe(0.001)

        body = metrics_response().body.decode("utf-8")
        names = {f.name for f in text_string_to_metric_families(body)}
        assert "palace_db_queries" in names
        assert "palace_db_query_duration_seconds" in names
        assert "palace_db_slow_queries" in names
