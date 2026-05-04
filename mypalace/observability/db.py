"""SQLAlchemy event hooks for per-query timing + slow-query log.

Wired in lifespan startup. Idempotent — re-installing on the same
engine is a no-op so tests can stand it up multiple times.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from mypalace.config import settings
from mypalace.observability.metrics import (
    db_queries_total,
    db_query_duration,
    db_slow_queries_total,
)

logger = logging.getLogger("mypalace.db")

_INSTRUMENTED: set[int] = set()


def _classify(stmt: str) -> str:
    """Map a SQL statement to a low-cardinality operation label.

    Looks at the first non-whitespace word. Anything not in the standard
    set lands in OTHER so labels stay bounded.
    """
    if not stmt or not stmt.strip():
        return "OTHER"
    head = stmt.lstrip().split(None, 1)[0].upper()
    if head in {"SELECT", "INSERT", "UPDATE", "DELETE"}:
        return head
    if head in {"WITH", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"}:
        return head
    return "OTHER"


def install(async_engine: AsyncEngine) -> None:
    """Attach before/after_cursor_execute listeners to the underlying sync
    engine. Async engines wrap a sync one — `engine.sync_engine` exposes it.
    """
    sync = async_engine.sync_engine
    if id(sync) in _INSTRUMENTED:
        return
    _INSTRUMENTED.add(id(sync))

    @event.listens_for(sync, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        context._mypalace_start = time.perf_counter()

    @event.listens_for(sync, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        start = getattr(context, "_mypalace_start", None)
        if start is None:
            return
        elapsed = time.perf_counter() - start
        op = _classify(statement)
        db_query_duration.labels(operation=op).observe(elapsed)
        db_queries_total.labels(operation=op).inc()

        threshold_s = settings.db_slow_query_threshold_ms / 1000.0
        if elapsed >= threshold_s:
            db_slow_queries_total.labels(operation=op).inc()
            # Truncate statement for logging (some can be very long).
            snippet = statement.replace("\n", " ").strip()
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            logger.warning(
                "slow query: op=%s elapsed_ms=%d statement=%s",
                op, int(elapsed * 1000), snippet,
            )


def reset_for_tests() -> None:
    """Test helper: forget the instrumented set so a fresh engine wires up."""
    _INSTRUMENTED.clear()
