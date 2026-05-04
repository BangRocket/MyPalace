"""Async FalkorDB client wrapper.

FalkorDB is a Cypher engine that speaks the Redis protocol. We use the
official `falkordb` Python library (sync) and wrap each call in
`asyncio.to_thread` to avoid blocking the event loop. Graph names are
per-tenant: `palace_<tenant_id>`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class FalkorClient:
    """Lazily-initialized async wrapper around FalkorDB.

    The underlying library is synchronous; every call is shipped to a
    thread via `asyncio.to_thread`. For Palace's enrichment-only graph
    workload, that's plenty.

    If `url` is None, every operation is a no-op.
    """

    def __init__(self, url: str | None) -> None:
        self.url = url
        self._db: Any = None

    @property
    def enabled(self) -> bool:
        return self.url is not None

    def _connect(self) -> Any:
        if self._db is None:
            try:
                from falkordb import FalkorDB
            except ImportError as e:
                raise RuntimeError(
                    "falkordb package not installed; cannot use graph layer",
                ) from e
            # FalkorDB.from_url accepts redis:// URLs.
            self._db = FalkorDB.from_url(self.url)
        return self._db

    def _graph(self, tenant_id: str) -> Any:
        db = self._connect()
        return db.select_graph(f"palace_{tenant_id}")

    async def query(
        self,
        tenant_id: str,
        cypher: str,
        params: dict | None = None,
    ) -> Any:
        """Run a Cypher query inside the tenant's graph.

        Returns the raw FalkorDB QueryResult so callers can inspect
        nodes/edges/columns directly. Logs and returns None on failure
        (so write-path callers can fire-and-forget without crashing).
        """
        if not self.enabled:
            return None

        def _run() -> Any:
            graph = self._graph(tenant_id)
            return graph.query(cypher, params or {})

        try:
            return await asyncio.to_thread(_run)
        except Exception:
            logger.exception(
                "FalkorDB query failed (tenant=%s, cypher=%s)",
                tenant_id, cypher[:80],
            )
            return None

    async def drop(self, tenant_id: str) -> bool:
        """Drop a tenant's graph entirely. Used by tenant deletion."""
        if not self.enabled:
            return False

        def _run() -> bool:
            graph = self._graph(tenant_id)
            try:
                graph.delete()
                return True
            except Exception:
                logger.exception("FalkorDB drop failed for tenant=%s", tenant_id)
                return False

        return await asyncio.to_thread(_run)
